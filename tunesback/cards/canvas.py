"""A drawing surface for cards: crisp SVG on top of a soft raster backdrop.

Layouts describe a card in full-size pixels (1080 wide). Text and shapes
become SVG, rendered by resvg. Pillow does what resvg is slow at: the soft
parts (colour glows, shadows, film grain) are painted on a small image that is
blurred and scaled up, and artwork is pasted in between the SVG layers, so
everything still stacks in the order it was drawn.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
from typing import Optional, Sequence
from xml.sax.saxutils import escape, quoteattr

import resvg_py
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import fonts
from .fonts import bundled_face
from .text import Block, Style, fit

_BACKDROP_SCALE = 0.25


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) in (3, 4):
        color = "".join(c * 2 for c in color[:3])
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _attrs(**values) -> str:
    out = []
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, float):
            value = _num(value)
        out.append(f"{key.rstrip('_').replace('_', '-')}={quoteattr(str(value))}")
    return " ".join(out)


# ---------- the backdrop ----------

@dataclass
class _Glow:
    cx: float
    cy: float
    r: float
    color: str
    alpha: float


@dataclass
class _Shadow:
    x: float
    y: float
    w: float
    h: float
    radius: float
    blur: float
    alpha: float
    round: bool = False


@dataclass
class Backdrop:
    """The soft background layer, painted at low resolution."""

    colors: tuple[str, ...] = ("#000000",)
    angle: float = 180.0  # direction of the gradient, in degrees (180 = top to bottom)
    glows: list[_Glow] = field(default_factory=list)
    shadows: list[_Shadow] = field(default_factory=list)
    grain: float = 0.0

    def glow(self, cx: float, cy: float, r: float, color: str, alpha: float = 0.8) -> None:
        self.glows.append(_Glow(cx, cy, r, color, alpha))

    def shadow(self, x: float, y: float, w: float, h: float, radius: float = 0, blur: float = 40,
               alpha: float = 0.45, round: bool = False) -> None:
        self.shadows.append(_Shadow(x, y, w, h, radius, blur, alpha, round))

    def render(self, width: int, height: int, size: tuple[int, int]) -> Image.Image:
        """Paint at a fraction of (width, height), then scale up to the card's pixel `size`."""
        k = _BACKDROP_SCALE
        small = (max(1, round(width * k)), max(1, round(height * k)))
        image = _gradient(small, self.colors, self.angle)
        for g in self.glows:
            mask = Image.new("L", small, 0)
            r = g.r * k
            ImageDraw.Draw(mask).ellipse((g.cx * k - r, g.cy * k - r, g.cx * k + r, g.cy * k + r), fill=round(255 * g.alpha))
            mask = mask.filter(ImageFilter.GaussianBlur(r * 0.55))
            image = Image.composite(Image.new("RGB", small, _rgb(g.color)), image, mask)
        for s in self.shadows:
            mask = Image.new("L", small, 0)
            box = (s.x * k, s.y * k, (s.x + s.w) * k, (s.y + s.h) * k)
            draw = ImageDraw.Draw(mask)
            if s.round:
                draw.ellipse(box, fill=round(255 * s.alpha))
            else:
                draw.rounded_rectangle(box, radius=s.radius * k, fill=round(255 * s.alpha))
            mask = mask.filter(ImageFilter.GaussianBlur(max(1.0, s.blur * k)))
            image = Image.composite(Image.new("RGB", small, (0, 0, 0)), image, mask)
        image = image.resize(size, Image.BICUBIC)
        if self.grain > 0:
            noise = _noise(size).convert("RGB")
            image = Image.blend(image, ImageChops.overlay(image, noise), min(1.0, self.grain))
        return image


def _gradient(size: tuple[int, int], colors: Sequence[str], angle: float) -> Image.Image:
    if len(colors) == 1:
        return Image.new("RGB", size, _rgb(colors[0]))
    # A 0-255 ramp along the gradient's direction...
    w, h = size
    diag = int(math.hypot(w, h)) + 2
    ramp = Image.linear_gradient("L").resize((diag, diag))
    ramp = ramp.rotate(180 - angle, resample=Image.BILINEAR, expand=False)
    left, top = (diag - w) // 2, (diag - h) // 2
    ramp = ramp.crop((left, top, left + w, top + h))
    # ...mapped through the colour stops.
    stops = [_rgb(c) for c in colors]
    luts: list[list[int]] = [[], [], []]
    for i in range(256):
        t = i / 255 * (len(stops) - 1)
        j = min(int(t), len(stops) - 2)
        f = t - j
        for ch in range(3):
            luts[ch].append(round(stops[j][ch] + (stops[j + 1][ch] - stops[j][ch]) * f))
    return Image.merge("RGB", [ramp.point(lut) for lut in luts])


@lru_cache(maxsize=4)
def _noise(size: tuple[int, int]) -> Image.Image:
    tile = Image.effect_noise((256, 256), 48)
    out = Image.new("L", size)
    for y in range(0, size[1], 256):
        for x in range(0, size[0], 256):
            out.paste(tile, (x, y))
    return out


# ---------- the canvas ----------

class Canvas:
    """Collects a card's drawing, then renders it to an image."""

    def __init__(self, width: int, height: int, detail: float = 1.0):
        self.width = width
        self.height = height
        self.detail = detail  # output scale; embedded images are sized for it
        self.backdrop = Backdrop()
        self._defs: list[str] = []
        self._body: list[str] = []  # the SVG layer being drawn
        self._layers: list[object] = []  # finished SVG layers (lists of elements) and artwork
        self._ids = 0
        self._font_files: set[str] = set()

    # --- helpers ---

    def _id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}{self._ids}"

    def raw(self, svg: str) -> None:
        self._body.append(svg)

    def linear(self, stops: Sequence[tuple[float, str, float]], x1=0.0, y1=0.0, x2=0.0, y2=1.0) -> str:
        """A linear gradient (stops are (offset, colour, opacity)); returns a fill value."""
        gid = self._id("lg")
        parts = "".join(f'<stop offset="{_num(o)}" stop-color="{c}" stop-opacity="{_num(a)}"/>' for o, c, a in stops)
        self._defs.append(f'<linearGradient id="{gid}" {_attrs(x1=x1, y1=y1, x2=x2, y2=y2)}>{parts}</linearGradient>')
        return f"url(#{gid})"

    def radial(self, stops: Sequence[tuple[float, str, float]], cx=0.5, cy=0.5, r=0.5) -> str:
        gid = self._id("rg")
        parts = "".join(f'<stop offset="{_num(o)}" stop-color="{c}" stop-opacity="{_num(a)}"/>' for o, c, a in stops)
        self._defs.append(f'<radialGradient id="{gid}" {_attrs(cx=cx, cy=cy, r=r)}>{parts}</radialGradient>')
        return f"url(#{gid})"

    # --- shapes ---

    def rect(self, x, y, w, h, fill="none", radius=0.0, opacity=1.0, stroke=None, stroke_width=None,
             transform=None) -> None:
        self._body.append(f"<rect {_attrs(x=float(x), y=float(y), width=float(w), height=float(h), rx=float(radius) or None, fill=fill, opacity=float(opacity) if opacity != 1 else None, stroke=stroke, stroke_width=stroke_width, transform=transform)}/>")

    def circle(self, cx, cy, r, fill="none", opacity=1.0, stroke=None, stroke_width=None) -> None:
        self._body.append(f"<circle {_attrs(cx=float(cx), cy=float(cy), r=float(r), fill=fill, opacity=float(opacity) if opacity != 1 else None, stroke=stroke, stroke_width=stroke_width)}/>")

    def line(self, x1, y1, x2, y2, stroke, width=2.0, opacity=1.0, dash=None, cap="round") -> None:
        self._body.append(f"<line {_attrs(x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2), stroke=stroke, stroke_width=float(width), opacity=float(opacity) if opacity != 1 else None, stroke_dasharray=dash, stroke_linecap=cap)}/>")

    def path(self, d: str, fill="none", stroke=None, width=None, opacity=1.0, cap=None, join=None) -> None:
        self._body.append(f"<path {_attrs(d=d, fill=fill, stroke=stroke, stroke_width=width, opacity=float(opacity) if opacity != 1 else None, stroke_linecap=cap, stroke_linejoin=join)}/>")

    def clip(self, x: float, y: float, w: float, h: float) -> None:
        """Clip what's drawn next to a rectangle, until `unclip()`."""
        cid = self._id("c")
        self._defs.append(f'<clipPath id="{cid}"><rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}"/></clipPath>')
        self._body.append(f'<g clip-path="url(#{cid})">')

    def unclip(self) -> None:
        self._body.append("</g>")

    def group(self, svg: str, opacity: float = 1.0, transform: Optional[str] = None, clip: Optional[str] = None) -> None:
        self._body.append(f"<g {_attrs(opacity=float(opacity) if opacity != 1 else None, transform=transform, clip_path=clip)}>{svg}</g>")

    # --- text ---

    def text(self, text: str, x: float, y: float, style: Style, width: float, align: str = "left",
             anchor: str = "top", max_lines: Optional[int] = None, block: Optional[Block] = None) -> Block:
        """Draw text fitted to `width`. `anchor` says what `y` is: the top of the
        capitals ("top"), the first baseline ("baseline") or the last baseline ("bottom")."""
        block = block or fit(text, style, width, max_lines)
        self.draw_block(block, x, y, align, anchor)
        return block

    def draw_block(self, block: Block, x: float, y: float, align: str = "left", anchor: str = "top") -> None:
        if not block.lines:
            return
        style = block.style
        if anchor == "top":
            baseline = y + block.cap_height
        elif anchor == "bottom":
            baseline = y - block.line_step * (len(block.lines) - 1)
        else:
            baseline = y
        face = bundled_face(style.font)
        text_anchor = {"left": "start", "center": "middle", "right": "end"}[align]
        tspans = "".join(
            f'<tspan x="{_num(x)}" y="{_num(baseline + i * block.line_step)}">{self._runs(line, face)}</tspan>'
            for i, line in enumerate(block.lines))
        attrs = _attrs(
            font_family=face.family, font_weight=face.weight, font_style="italic" if face.italic else None,
            font_size=float(block.size), fill=style.fill, fill_opacity=float(style.opacity) if style.opacity != 1 else None,
            letter_spacing=float(style.tracking * block.size) if style.tracking else None, text_anchor=text_anchor)
        self._body.append(f'<text {attrs} xml:space="preserve">{tspans}</text>')

    def _runs(self, line: str, face: fonts.Face) -> str:
        """A line's markup, naming the fallback font for characters the design's font lacks.

        Left to itself, resvg would pick any loaded font that has the glyph, which
        can be a CJK font with full-width Latin or Cyrillic letters. Naming the
        font also keeps the drawing identical to how the text was measured.
        """
        out = []
        for piece_face, piece in fonts.runs(line, face):
            if piece_face is None or piece_face is face:
                out.append(escape(piece))
                continue
            self._font_files.add(piece_face.path)
            attrs = _attrs(font_family=piece_face.family, font_weight=piece_face.weight,
                           font_style="italic" if piece_face.italic else "normal")
            out.append(f"<tspan {attrs}>{escape(piece)}</tspan>")
        return "".join(out)

    # --- images ---

    def image(self, img: Image.Image, x: float, y: float, w: float, h: float, radius: float = 0.0,
              round: bool = False, opacity: float = 1.0, shadow: float = 0.0) -> None:
        """Draw an image covering the box (cropped to fit), optionally with rounded corners or as a
        circle. `shadow` (0-1) casts a soft shadow onto whatever is already drawn below it."""
        if self._body:
            self._layers.append(self._body)
            self._body = []
        self._layers.append(_Art(img, x, y, w, h, radius, round, opacity, shadow))

    # --- output ---

    def svg(self, body: Optional[list[str]] = None) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
                f'viewBox="0 0 {self.width} {self.height}"><defs>{"".join(self._defs)}</defs>'
                f'{"".join(self._body if body is None else body)}</svg>')

    def render(self, scale: float = 1.0) -> Image.Image:
        size = (max(1, round(self.width * scale)), max(1, round(self.height * scale)))
        image = self.backdrop.render(self.width, self.height, size).convert("RGBA")
        files = sorted(fonts.bundled_files() | self._font_files)
        for layer in [*self._layers, self._body]:
            if isinstance(layer, _Art):
                layer.paste(image, scale)
            elif layer:
                png = resvg_py.svg_to_bytes(svg_string=self.svg(layer), width=size[0], height=size[1],
                                            skip_system_fonts=True, font_files=files)
                svg_layer = Image.open(BytesIO(png))
                svg_layer.load()
                image = Image.alpha_composite(image, svg_layer.convert("RGBA"))
        return image.convert("RGB")


@dataclass
class _Art:
    img: Image.Image
    x: float
    y: float
    w: float
    h: float
    radius: float
    round: bool
    opacity: float
    shadow: float = 0.0

    def paste(self, target: Image.Image, scale: float) -> None:
        x, y = round(self.x * scale), round(self.y * scale)
        w, h = max(1, round(self.w * scale)), max(1, round(self.h * scale))
        if self.shadow:
            _cast_shadow(target, x, y, w, h, round(self.radius * scale), self.round, self.shadow)
        art = _cover(self.img, w, h)
        mask = _mask(w, h, round(self.radius * scale), self.round)
        if self.opacity < 1:
            mask = mask.point(lambda v: round(v * self.opacity))
        target.paste(art, (x, y), mask)


def _cast_shadow(target: Image.Image, x: int, y: int, w: int, h: int, radius: int, circle: bool, alpha: float) -> None:
    """Darken a soft, slightly offset area under a box, blurred at a quarter of the resolution."""
    blur = max(2, round(max(w, h) * 0.05))
    pad = blur * 3
    k = 4
    small = Image.new("L", ((w + 2 * pad) // k + 1, (h + 2 * pad) // k + 1), 0)
    box = (pad // k, pad // k, (pad + w) // k, (pad + h) // k)
    draw = ImageDraw.Draw(small)
    if circle:
        draw.ellipse(box, fill=round(255 * alpha))
    else:
        draw.rounded_rectangle(box, radius=radius // k, fill=round(255 * alpha))
    mask = small.filter(ImageFilter.GaussianBlur(blur / k)).resize((w + 2 * pad, h + 2 * pad), Image.BILINEAR)
    target.paste((0, 0, 0, 255), (x - pad, y - pad + blur // 2), mask)


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """The image cropped to w:h and scaled to w×h."""
    src = img.convert("RGB")
    ratio = w / h
    sw, sh = src.size
    if sw / sh > ratio:
        nw = max(1, round(sh * ratio))
        src = src.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
    elif sw / sh < ratio:
        nh = max(1, round(sw / ratio))
        src = src.crop((0, (sh - nh) // 2, sw, (sh - nh) // 2 + nh))
    return src.resize((w, h), Image.LANCZOS) if src.size != (w, h) else src


@lru_cache(maxsize=64)
def _mask(w: int, h: int, radius: int, circle: bool) -> Image.Image:
    """An anti-aliased mask for rounded corners or a circle (drawn at 3× and scaled down)."""
    if not radius and not circle:
        return Image.new("L", (w, h), 255)
    k = 3
    big = Image.new("L", (w * k, h * k), 0)
    draw = ImageDraw.Draw(big)
    if circle:
        draw.ellipse((0, 0, w * k - 1, h * k - 1), fill=255)
    else:
        draw.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=radius * k, fill=255)
    return big.resize((w, h), Image.LANCZOS)
