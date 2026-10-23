"""Fitting text into a box: shrink, wrap, and only then cut it short with "…"."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Optional

from .fonts import FontSpec, text_width, vertical_metrics

ELLIPSIS = "…"
# Characters a line may break after even without a space (CJK and similar scripts).
_NO_SPACE_SCRIPTS = re.compile(r"[⺀-鿿가-힯豈-﫿＀-￯　-〿\U00020000-\U0002FFFF]")
_TOKENS = re.compile(r"[⺀-鿿가-힯豈-﫿＀-￯　-〿\U00020000-\U0002FFFF]|[^\s⺀-鿿가-힯豈-﫿＀-￯　-〿\U00020000-\U0002FFFF]+|\s+")


@dataclass(frozen=True)
class Style:
    """How a piece of text looks. Sizes are in pixels on the full-size card."""

    font: FontSpec
    size: float
    fill: str = "#FFFFFF"
    opacity: float = 1.0
    min_size: Optional[float] = None  # how far it may shrink to fit (default: 70% of size)
    max_lines: int = 1
    line_height: float = 1.08  # times the font size
    tracking: float = 0.0  # letter spacing, in em
    upper: bool = False

    def but(self, **changes) -> "Style":
        return replace(self, **changes)


@dataclass(frozen=True)
class Block:
    """Text laid out in a box: its lines and the size it ended up at."""

    lines: tuple[str, ...]
    size: float
    style: Style
    width: float  # widest line

    @property
    def line_step(self) -> float:
        return self.size * self.style.line_height

    @property
    def cap_height(self) -> float:
        return vertical_metrics(self.style.font)[2] * self.size

    @property
    def height(self) -> float:
        """From the top of the capitals on the first line to the baseline of the last."""
        return self.cap_height + self.line_step * (len(self.lines) - 1) if self.lines else 0.0

    @property
    def descent(self) -> float:
        return vertical_metrics(self.style.font)[1] * self.size


def _measure(text: str, style: Style, size: float) -> float:
    return text_width(text, style.font, size, style.tracking)


def _tokens(text: str) -> list[str]:
    return _TOKENS.findall(text)


def _wrap(text: str, style: Style, size: float, max_width: float) -> tuple[list[str], bool]:
    """Greedy line breaking. Returns (lines, every word fitted on its line)."""
    lines: list[str] = []
    line = ""
    clean = True
    for token in _tokens(text):
        if token.isspace():
            if line:
                line += " "
            continue
        candidate = line + token
        if not line or _measure(candidate, style, size) <= max_width:
            line = candidate
        else:
            lines.append(line.rstrip())
            line = token
        if _measure(line, style, size) > max_width:
            clean = False
    if line.strip():
        lines.append(line.rstrip())
    return lines, clean


def _cut(text: str, style: Style, size: float, max_width: float) -> str:
    """Shorten one line to fit, ending it with an ellipsis."""
    if _measure(text, style, size) <= max_width:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _measure(text[:mid].rstrip() + ELLIPSIS, style, size) <= max_width:
            low = mid
        else:
            high = mid - 1
    head = text[:low]
    # End on a whole word when that loses little; otherwise cut inside the word.
    if low < len(text) and not text[low].isspace() and not _NO_SPACE_SCRIPTS.match(text[low]):
        space = head.rfind(" ")
        if space > len(head) * 0.6:
            head = head[:space]
    # Don't leave a dangling accent, joiner or separator.
    while head and unicodedata.category(head[-1]) in ("Mn", "Me", "Cf", "Zs"):
        head = head[:-1]
    head = head.rstrip(" ,;:-–—/(")
    return (head + ELLIPSIS) if head else ELLIPSIS


def fit(text: str, style: Style, max_width: float, max_lines: Optional[int] = None) -> Block:
    """Lay out text to fit `max_width` and at most `max_lines` lines.

    Tries the design size first, then smaller sizes down to the style's
    minimum, wrapping as allowed. If it still doesn't fit, the last line ends
    with "…".
    """
    text = " ".join((text or "").split())
    if style.upper:
        text = text.upper()
    lines_allowed = max(1, max_lines or style.max_lines)
    if not text:
        return Block((), style.size, style, 0.0)

    min_size = style.min_size or style.size * 0.7
    size = style.size
    while True:
        if lines_allowed == 1:
            if _measure(text, style, size) <= max_width:
                return _block([text], size, style)
        else:
            lines, clean = _wrap(text, style, size, max_width)
            if clean and len(lines) <= lines_allowed:
                return _block(lines, size, style)
        if size <= min_size:
            break
        size = max(min_size, size * 0.94)

    # Smallest size and still too long: keep what fits and cut the rest.
    if lines_allowed == 1:
        return _block([_cut(text, style, size, max_width)], size, style)
    lines, _ = _wrap(text, style, size, max_width)
    if len(lines) <= lines_allowed:  # it's a single word that's too long
        return _block([_cut(line, style, size, max_width) for line in lines], size, style)
    kept = [_cut(line, style, size, max_width) for line in lines[: lines_allowed - 1]]
    # Greedy wrapping means two joined lines never fit, so this always ends in "…".
    rest = _cut(" ".join(lines[lines_allowed - 1:]), style, size, max_width)
    return _block(kept + [rest], size, style)


def _block(lines: list[str], size: float, style: Style) -> Block:
    width = max((_measure(line, style, size) for line in lines), default=0.0)
    return Block(tuple(lines), size, style, width)
