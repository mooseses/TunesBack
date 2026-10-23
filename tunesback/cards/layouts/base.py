"""What every layout shares: the card's frame, artwork, and ranked rows."""
from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image

from ..canvas import Canvas
from ..data import CardData, Item
from ..fonts import FontSpec
from ..text import Block, Style, fit
from ..themes import MONO, Theme

FORMATS = {"story": (1080, 1920), "square": (1080, 1080)}
ICON = Path(__file__).resolve().parent.parent.parent / "assets" / "icon.png"


@lru_cache(maxsize=1)
def _icon() -> Image.Image:
    return Image.open(ICON).convert("RGBA")


def luminance(color: str) -> float:
    """Perceived lightness of a #RRGGBB colour, 0 to 1."""
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def initial(text: str) -> str:
    for char in text or "":
        if char.isalnum():
            return char.upper()
    return "♪"


@dataclass
class Ctx:
    """Everything a layout draws with."""

    canvas: Canvas
    theme: Theme
    data: CardData
    rng: random.Random
    fmt: str

    def __post_init__(self) -> None:
        self.W, self.H = self.canvas.width, self.canvas.height
        self.square = self.fmt == "square"
        self.m = 76 if self.square else 90  # side margin
        self.top = 84 if self.square else 150
        self.inner = self.W - 2 * self.m
        self.mark = 38 if self.square else 46  # TunesBack's icon at the bottom
        self.mark_y = self.H - (60 if self.square else 84) - self.mark
        self.bottom = self.mark_y - (28 if self.square else 40)  # content stays above this

    # --- shortcuts ---

    @property
    def c(self) -> Canvas:
        return self.canvas

    @property
    def t(self) -> Theme:
        return self.theme

    @property
    def d(self) -> CardData:
        return self.data

    def s(self, story: float, square: float) -> float:
        """Pick a size for the current format."""
        return square if self.square else story

    def background(self) -> None:
        self.theme.paint_background(self.canvas, self.rng, self.bottom + (12 if self.square else 20))
        from .. import canvas
        if canvas.GUIDES:  # the content area every layout keeps to
            self.canvas.overlay.append(
                f'<rect x="{self.m}" y="{self.top}" width="{self.inner}" height="{self.bottom - self.top}" '
                'fill="none" stroke="#00E5FF" stroke-width="2" stroke-dasharray="12 8"/>')

    # --- frame ---

    def header(self, title: str, label: Optional[str] = None, y: Optional[float] = None,
               width: Optional[float] = None, align: str = "left") -> float:
        """A small label (the period, by default) above a headline. Returns the y below it."""
        y = self.top if y is None else y
        width = width or self.inner
        x = {"left": self.m, "center": self.W / 2, "right": self.W - self.m}[align]
        label_block = self.c.text(label if label is not None else self.d.period, x, y,
                                  self.t.small(self.s(30, 26)), width, align=align)
        y += label_block.height + self.s(30, 22)
        block = self.c.text(title, x, y, self.t.headline(self.s(104, 80), max_lines=2), width, align=align)
        return y + block.height + block.descent

    def footer(self) -> float:
        """TunesBack's mark at the bottom. Returns the y content should stay above."""
        size, y = self.mark, self.mark_y
        self.c.image(_icon(), self.m, y, size, size, radius=size * 0.22)
        block = fit("TunesBack", self.t.title(self.s(30, 26)), 300)
        self.c.draw_block(block, self.m + size + 16, y + (size - block.cap_height) / 2)
        return self.bottom

    # --- artwork ---

    def art(self, item: Optional[Item], x: float, y: float, w: float, h: Optional[float] = None,
            round: bool = False, radius: Optional[float] = None, shadow: bool = True) -> None:
        """An item's artwork, or a coloured tile with its initial when there is none."""
        h = w if h is None else h
        radius = self.t.radius * (w / 400) if radius is None else radius
        radius = min(radius, w / 2, h / 2)
        if shadow:
            self.c.backdrop.shadow(x, y + h * 0.04, w, h, radius, blur=w * 0.08,
                                   alpha=0.55 if self.t.dark else 0.22, round=round)
        img = self.d.art(item)
        if img is not None:
            self.c.image(img, x, y, w, h, radius=radius, round=round)
            return
        fill = self.c.linear([(0, self.t.accent, 1), (1, self.t.accent2, 1)], 0, 0, 1, 1)
        if round:
            self.c.circle(x + w / 2, y + h / 2, min(w, h) / 2, fill=fill)
        else:
            self.c.rect(x, y, w, h, fill=fill, radius=radius)
        letter = Style(self.t.display, min(w, h) * 0.5, self.t.on_accent, opacity=0.9)
        block = fit(initial(item.title if item else ""), letter, w)
        self.c.draw_block(block, x + w / 2, y + h / 2 - block.cap_height / 2, align="center")

    def pill(self, text: str, x: float, y: float, size: float, align: str = "left",
             fill: Optional[str] = None, color: Optional[str] = None) -> float:
        """Text in a rounded capsule; returns its width."""
        style = Style(self.t.label, size, color or self.t.on_accent, upper=self.t.label_upper,
                      tracking=0.06 if self.t.label_upper else 0)
        block = fit(text, style, self.inner)
        pad_x, height = size * 0.9, size * 2.1
        width = block.width + 2 * pad_x
        left = {"left": x, "center": x - width / 2, "right": x - width}[align]
        self.c.rect(left, y, width, height, fill=fill or self.t.accent, radius=height / 2)
        self.c.draw_block(block, left + pad_x, y + (height - block.cap_height) / 2)
        return width

    # --- lists ---

    def rows(self, items: Sequence[Item], x: float, y: float, w: float, h: float, *, art: bool = True,
             start: int = 1, title_size: Optional[float] = None, round_art: bool = False,
             metric: bool = True, max_art: Optional[float] = None) -> None:
        """Numbered rows (rank, artwork, title, subtitle, metric) filling the box."""
        if not items:
            return
        row = min(h / len(items), self.s(300, 180))
        art_size = min(row * 0.78, max_art or self.s(180, 118))
        title_size = title_size or min(self.s(50, 38), row * 0.3)
        sub_size = title_size * 0.72
        num_w = title_size * 1.6
        for i, item in enumerate(items):
            top = y + i * row
            cx = x
            number = fit(str(start + i), self.t.number(title_size * 1.15), num_w)
            self.c.draw_block(number, cx, top + row / 2 - number.cap_height / 2)
            cx += num_w + 6
            if art:
                self.art(item, cx, top + (row - art_size) / 2, art_size, round=round_art, shadow=False)
                cx += art_size + self.s(30, 24)
            text_w = x + w - cx
            title = fit(item.title, self.t.title(title_size), text_w)
            lines: list[Block] = [title]
            sub_text = " · ".join(filter(None, [item.subtitle, self.d.metric(item) if metric else None]))
            if sub_text:
                lines.append(fit(sub_text, self.t.text(sub_size), text_w))
            gap = title_size * 0.42
            total = sum(b.height for b in lines) + gap * (len(lines) - 1)
            ty = top + (row - total) / 2
            for block in lines:
                self.c.draw_block(block, cx, ty)
                ty += block.height + gap


# ---------- receipts ----------

def receipt(ctx: Ctx, title: str, sections: Sequence[tuple[str, Sequence[tuple[str, str]]]],
            totals: Sequence[tuple[str, str]]) -> None:
    """A till receipt: paper in the theme's text colour, monospaced print in its background colour."""
    c, t = ctx.c, ctx.t
    paper = t.fg
    ink = t.bg[0] if abs(luminance(t.bg[0]) - luminance(paper)) > 0.5 else ("#141414" if luminance(paper) > 0.5 else "#F4F4F4")
    mono, bold = FontSpec(MONO), FontSpec(MONO, 700)
    size = ctx.s(30, 22)
    line = size * 1.62
    pad = ctx.s(56, 40)
    w = ctx.s(ctx.inner - 40, 600)
    x = (ctx.W - w) / 2
    inner_x, inner_w = x + pad, w - 2 * pad
    barcode = ctx.s(110, 60)

    # Work out how tall the receipt is, keeping only the rows that fit.
    room = ctx.bottom - ctx.s(150, 60) - ctx.s(40, 24)
    fixed = line * 3.4 + line * 2 * len(sections) + line * (1 + len(totals)) + size * 0.6 + barcode + size + line * 0.8
    budget = int(max(0, room - fixed) // line)
    kept = []
    for heading, rows in sections:
        rows = list(rows)[: max(1, budget // max(1, len(sections)))]
        kept.append((heading, rows))
    height = fixed + line * sum(len(r) for _h, r in kept) + pad
    top = ctx.s(150, 60) + max(0.0, (room - height) / 2)
    bottom = top + height

    # Paper with a torn (zig-zag) bottom edge.
    teeth = 24
    tooth = w / teeth
    edge = " ".join(f"L{x + w - tooth * (i + 0.5):.1f},{bottom + tooth * 0.5:.1f} L{x + w - tooth * (i + 1):.1f},{bottom:.1f}"
                    for i in range(teeth))
    c.backdrop.shadow(x, top + 12, w, height, 4, blur=50, alpha=0.5 if t.dark else 0.25)
    c.path(f"M{x:.1f},{top:.1f} L{x + w:.1f},{top:.1f} L{x + w:.1f},{bottom:.1f} {edge} Z", fill=paper)

    y = top + pad

    def text(value: str, x0: float, width: float, align: str = "left", font: FontSpec = mono, scale: float = 1.0) -> Block:
        return c.text(value, x0, y, Style(font, size * scale, ink, min_size=size * scale * 0.8, upper=True), width, align=align)

    def rule() -> None:
        c.line(inner_x, y + size * 0.4, inner_x + inner_w, y + size * 0.4, ink, 2, dash="10 8", cap="butt")

    text("TunesBack", inner_x + inner_w / 2, inner_w, "center", bold, 1.4)
    y += line * 1.4
    text(title, inner_x + inner_w / 2, inner_w, "center")
    y += line
    text(ctx.d.period_long, inner_x + inner_w / 2, inner_w, "center", scale=0.8)
    y += line
    for heading, rows in kept:
        rule()
        y += line
        text(heading, inner_x, inner_w, font=bold)
        y += line
        for left, right in rows:
            right_w = len(right) * size * 0.62 + size
            text(left, inner_x, inner_w - right_w)
            text(right, inner_x + inner_w, right_w, "right")
            y += line
    rule()
    y += line
    for left, right in totals:
        text(left, inner_x, inner_w * 0.6, font=bold)
        text(right, inner_x + inner_w, inner_w * 0.4, "right", bold)
        y += line
    # A barcode drawn from the period's numbers.
    y += size * 0.6
    rng = random.Random(repr(ctx.d.fingerprint()))
    bx = inner_x
    while bx < inner_x + inner_w - 8:
        bw = rng.choice((3, 3, 5, 8))
        c.rect(bx, y, bw, barcode, fill=ink)
        bx += bw + rng.choice((3, 5, 6))
    y += barcode + size
    text("Thanks for listening", inner_x + inner_w / 2, inner_w, "center", scale=0.8)


def two_lines(ctx: Ctx, title: str, subtitle: Optional[str], x: float, y: float, width: float, size: float,
              align: str = "left", lines: int = 2) -> float:
    """A big title (wrapping) and a subtitle below it. Returns the y below them."""
    block = ctx.c.text(title, x, y, ctx.t.headline(size, max_lines=lines), width, align=align)
    y += block.height + block.descent + size * 0.25
    if subtitle:
        sub = ctx.c.text(subtitle, x, y, ctx.t.text(size * 0.45, fill=ctx.t.fg, opacity=0.85), width, align=align)
        y += sub.height + sub.descent
    return y
