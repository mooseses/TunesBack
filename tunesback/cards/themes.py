"""Card themes: colours, fonts and background decoration.

A theme never decides where things go (that's the layout's job), only how
they look, so any layout works with any theme.
"""
from __future__ import annotations

import colorsys
import math
import random
from dataclasses import dataclass, replace
from typing import Optional

from PIL import Image

from .canvas import Canvas
from .fonts import FontSpec
from .text import Style

FIGTREE = "Figtree"
SERIF = "Instrument Serif"
MONO = "Space Mono"
CONDENSED = "Anton"


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    bg: tuple[str, ...]  # one colour, or gradient stops
    fg: str  # main text
    muted: str  # secondary text
    accent: str
    accent2: str
    on_accent: str  # text drawn on the accent colour
    surface: str  # panels and placeholders
    display: FontSpec  # headlines and big numbers
    body: FontSpec  # everything else
    label: FontSpec  # small caps-style labels
    pattern: str = "glow"
    bg_angle: float = 160
    grain: float = 0.0
    display_upper: bool = False
    display_tracking: float = -0.01
    label_upper: bool = True
    radius: float = 28  # artwork corners
    glow: float = 1.0  # strength of the "glow" decoration
    extra: tuple[str, ...] = ()  # more colours for patterns and charts

    # --- text styles layouts use ---

    def headline(self, size: float, **kw) -> Style:
        kw.setdefault("fill", self.fg)
        kw.setdefault("upper", self.display_upper)
        kw.setdefault("tracking", self.display_tracking)
        return Style(self.display, size, **kw)

    def title(self, size: float, **kw) -> Style:
        kw.setdefault("fill", self.fg)
        font = replace(self.body, weight=max(self.body.weight, 700)) if self.body.family == FIGTREE else self.body
        return Style(font, size, **kw)

    def text(self, size: float, **kw) -> Style:
        kw.setdefault("fill", self.muted)
        return Style(self.body, size, **kw)

    def small(self, size: float, **kw) -> Style:
        kw.setdefault("fill", self.muted)
        kw.setdefault("upper", self.label_upper)
        kw.setdefault("tracking", 0.08 if self.label_upper else 0)
        return Style(self.label, size, **kw)

    def number(self, size: float, **kw) -> Style:
        kw.setdefault("fill", self.accent)
        kw.setdefault("upper", self.display_upper)
        kw.setdefault("tracking", self.display_tracking)
        return Style(self.display, size, **kw)

    @property
    def palette(self) -> tuple[str, ...]:
        """Distinct colours for chart bars and such, accent first."""
        return (self.accent, self.accent2, *self.extra)

    @property
    def dark(self) -> bool:
        """Light text on a dark background?"""
        r, g, b = (int(self.bg[0].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 140

    @property
    def swatch(self) -> list[str]:
        return [self.bg[0], self.bg[-1], self.accent, self.accent2]

    # --- background ---

    def paint_background(self, canvas: Canvas, rng: random.Random, free_from: float) -> None:
        """Fill the backdrop and add this theme's decoration. Bold decoration stays
        in the strip below `free_from`, beside TunesBack's mark, where layouts draw nothing."""
        canvas.backdrop.colors = self.bg
        canvas.backdrop.angle = self.bg_angle
        canvas.backdrop.grain = self.grain
        w, h = canvas.width, canvas.height
        zone = (w * 0.5, free_from, w * 0.5, h - free_from)
        canvas.clip(*zone)
        PATTERNS.get(self.pattern, _none)(canvas, self, rng, zone)
        canvas.unclip()


# ---------- decoration ----------

def _none(canvas, theme, rng, zone):
    pass


def _glow(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    w, h = canvas.width, canvas.height
    corners = [(0, 0), (w, 0), (0, h), (w, h)]
    rng.shuffle(corners)
    for (cx, cy), color, alpha in zip(corners, (theme.accent, theme.accent2, *theme.extra), (0.85, 0.7, 0.5)):
        canvas.backdrop.glow(cx + rng.uniform(-0.15, 0.15) * w, cy + rng.uniform(-0.1, 0.1) * h,
                             rng.uniform(0.38, 0.5) * w, color, alpha * theme.glow)


def _soft(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    w, h = canvas.width, canvas.height
    for color in (theme.accent2, theme.accent, *theme.extra[:1]):
        canvas.backdrop.glow(rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.3, 0.45) * w, color, 0.35)


def _waves(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    w, h = canvas.width, canvas.height
    canvas.unclip()  # waves run the full width of the strip
    zx, zy, zw, zh = 0, zone[1] - zone[3] * 0.3, w, zone[3] * 1.3
    colors = [theme.accent, theme.accent2, *theme.extra] or [theme.accent]
    bands = 5
    phase = rng.uniform(0, math.tau)
    for i in range(bands):
        base = zy + zh * (i + 0.5) / bands
        amp = zh / bands * rng.uniform(0.35, 0.6)
        freq = rng.uniform(1.0, 1.8) * math.tau / w
        pts = [f"{x:.0f},{base + amp * math.sin(freq * x + phase + i * 0.9):.1f}" for x in range(0, w + 41, 40)]
        canvas.path(f"M0,{h} L{' L'.join(pts)} L{w},{h} Z", fill=colors[i % len(colors)], opacity=0.22 + 0.1 * i)
    canvas.clip(*zone)  # balanced by paint_background's unclip


def _rings(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    zx, zy, zw, zh = zone
    cx, cy = zx + zw, zy + zh
    colors = theme.palette
    step = zh / 4
    for i in range(12, 0, -1):
        canvas.circle(cx, cy, i * step, fill=colors[(i // 2) % len(colors)] if i % 2 == 0 else theme.bg[0])


def _dots(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    zx, zy, zw, zh = zone
    cols = 10
    gap = zw / cols
    rows = max(1, int(zh / gap))
    color = rng.choice(theme.palette)
    for r in range(rows):
        for c in range(cols):
            t = (c + 1) / cols  # dots grow towards the edge: a halftone fade
            canvas.circle(zx + gap * (c + 0.5), zy + gap * (r + 0.5), gap * 0.48 * t, fill=color)


def _stripes(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    zx, zy, zw, zh = zone
    count = 13
    colors = theme.palette
    width = zw / count
    for i in range(count):
        if i % 2 == 0:
            continue
        height = zh * rng.uniform(0.3, 1.0)
        canvas.rect(zx + i * width, zy + zh - height, width, height, fill=colors[(i // 2) % len(colors)])


def _checker(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    zx, zy, zw, zh = zone
    size = zh / 3
    color = rng.choice(theme.palette)
    for r in range(3):
        for c in range(int(zw / size) + 1):
            if (r + c) % 2 == 0:
                canvas.rect(zx + zw - (c + 1) * size, zy + r * size, size, size, fill=color)


def _grid(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    w, h = canvas.width, canvas.height
    canvas.unclip()
    _grid_lines(canvas, theme, w, h)
    canvas.clip(*zone)


def _grid_lines(canvas: Canvas, theme: Theme, w: float, h: float) -> None:
    step = 54
    for x in range(step, w, step):
        canvas.line(x, 0, x, h, theme.fg, 1, opacity=0.06, cap="butt")
    for y in range(step, h, step):
        canvas.line(0, y, w, y, theme.fg, 1, opacity=0.06, cap="butt")


def _classic(canvas: Canvas, theme: Theme, rng: random.Random, zone) -> None:
    rng.choice((_stripes, _dots, _rings, _checker))(canvas, theme, rng, zone)


PATTERNS = {
    "none": _none, "glow": _glow, "soft": _soft, "waves": _waves, "rings": _rings, "dots": _dots,
    "stripes": _stripes, "checker": _checker, "grid": _grid, "classic": _classic,
}


# ---------- the themes ----------

def _fig(weight: int) -> FontSpec:
    return FontSpec(FIGTREE, weight)


THEMES: dict[str, Theme] = {t.id: t for t in (
    Theme("midnight", "Midnight", bg=("#0A0A12", "#151036"), fg="#FFFFFF", muted="#B4AFD6", accent="#8C7BFF",
          accent2="#FF4F9A", on_accent="#FFFFFF", surface="#24203F", display=_fig(900), body=_fig(500),
          label=_fig(700), pattern="glow", grain=0.07, extra=("#36D6E7", "#FFB547")),
    Theme("sunset", "Sunset", bg=("#FF7A3D", "#FF3D7F", "#6A2BFF"), fg="#FFFFFF", muted="#FFE4EE",
          accent="#FFE14D", accent2="#2B0B3F", on_accent="#2B0B3F", surface="#FFFFFF33", display=_fig(900),
          body=_fig(600), label=_fig(800), pattern="waves", bg_angle=200, grain=0.06, extra=("#FFFFFF",)),
    Theme("paper", "Paper", bg=("#F4EFE4",), fg="#1B1A17", muted="#6F685D", accent="#E4412B", accent2="#1F4BD8",
          on_accent="#FFFFFF", surface="#E5DECF", display=FontSpec(SERIF), body=_fig(500), label=_fig(700),
          pattern="grid", grain=0.05, display_tracking=-0.02, radius=4, extra=("#E9A21B", "#2A8C55")),
    Theme("poster", "Poster", bg=("#F5E52A",), fg="#121212", muted="#3A3A2A", accent="#FF3B2F", accent2="#121212",
          on_accent="#FFFFFF", surface="#E3D21F", display=FontSpec(CONDENSED), body=_fig(700), label=_fig(800),
          pattern="stripes", display_upper=True, display_tracking=0.0, radius=0, extra=("#2F5BFF",)),
    Theme("mint", "Mint", bg=("#E2F8EC", "#B6EAD3"), fg="#0B3B2C", muted="#3B6B5A", accent="#0E9F6E",
          accent2="#FF9F1C", on_accent="#FFFFFF", surface="#CBEEDD", display=_fig(800), body=_fig(500),
          label=_fig(700), pattern="soft", bg_angle=140, grain=0.04, radius=36, extra=("#5B8CFF", "#F25F8E")),
    Theme("mono", "Mono", bg=("#FFFFFF",), fg="#0A0A0A", muted="#6B6B6B", accent="#0A0A0A", accent2="#9A9A9A",
          on_accent="#FFFFFF", surface="#EDEDED", display=FontSpec(MONO, 700), body=FontSpec(MONO), label=FontSpec(MONO, 700),
          pattern="none", display_tracking=-0.03, radius=0, extra=("#4A4A4A", "#C8C8C8")),
    Theme("neon", "Neon", bg=("#050505",), fg="#F4FFE6", muted="#9AA88A", accent="#C6FF1A", accent2="#00E1FF",
          on_accent="#050505", surface="#1A1D14", display=FontSpec(CONDENSED), body=_fig(500), label=FontSpec(MONO, 700),
          pattern="glow", display_upper=True, display_tracking=0.01, grain=0.08, radius=10, glow=0.45,
          extra=("#FF3DDB",)),
    Theme("classic", "Classic", bg=("#292929",), fg="#EFEFEB", muted="#B3B3B3", accent="#DDBA13", accent2="#FE4635",
          on_accent="#292929", surface="#3A3A3A", display=_fig(900), body=_fig(500), label=_fig(800),
          pattern="classic", radius=0, extra=("#9891FE", "#96C90D", "#F1A2BD")),
)}

# Used for a card when the deck's theme is "mix" and nothing was shuffled yet,
# so the default deck looks curated rather than random.
MIX_ROTATION = ("midnight", "cover", "sunset", "poster", "mint", "classic", "paper", "neon", "mono")


# ---------- colours from artwork ----------

def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c))) for c in rgb))


def _hls(rgb) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def _from_hls(h: float, l: float, s: float) -> str:
    return _hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, s)))


def cover_theme(art: Optional[Image.Image]) -> Theme:
    """A theme in the colours of an album cover (Midnight when there's no art)."""
    base = THEMES["midnight"]
    if art is None:
        return replace(base, id="cover", name="Cover")
    small = art.convert("RGB").resize((48, 48))
    quantized = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()[: 6 * 3]
    counts = sorted(quantized.getcolors(), reverse=True)
    colors = [tuple(palette[i * 3: i * 3 + 3]) for _count, i in counts]
    # The most vivid colours make the accents; the most common one sets the mood.
    vivid = sorted(colors, key=lambda c: _hls(c)[2] * (1 - abs(_hls(c)[1] - 0.5)), reverse=True)
    h0, _l0, s0 = _hls(colors[0])
    h1, _l1, s1 = _hls(vivid[0])
    h2, _l2, s2 = _hls(vivid[1] if len(vivid) > 1 else vivid[0])
    if abs(h2 - h1) < 0.06:
        h2 = (h1 + 0.5) % 1.0
    return replace(
        base, id="cover", name="Cover",
        bg=(_from_hls(h0, 0.07, min(0.5, s0)), _from_hls(h0, 0.16, min(0.6, s0 + 0.1))),
        accent=_from_hls(h1, 0.62, max(0.55, s1)), accent2=_from_hls(h2, 0.58, max(0.5, s2)),
        muted=_from_hls(h0, 0.78, min(0.35, s0)), surface=_from_hls(h0, 0.2, min(0.4, s0)),
        extra=(_from_hls((h1 + 0.33) % 1, 0.6, 0.6), _from_hls((h1 + 0.66) % 1, 0.6, 0.6)),
    )
