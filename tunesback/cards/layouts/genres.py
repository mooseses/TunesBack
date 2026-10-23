"""Top genres."""
from __future__ import annotations

import math

from ..registry import layout
from ..text import fit
from .base import Ctx


def _pct(share: float) -> str:
    return f"{share * 100:.0f}%" if share >= 0.01 else "<1%"


@layout("genres", "bars", "Bars")
def genres_bars(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My top genres")
    bottom = ctx.footer()
    genres = d.genres[: ctx.s(6, 5)]
    biggest = max((g.share for g in genres), default=1) or 1
    row = (bottom - y - ctx.s(40, 20)) / max(len(genres), ctx.s(4, 3))
    colors = t.palette
    for i, genre in enumerate(genres):
        top = y + ctx.s(40, 20) + i * row
        size = min(ctx.s(52, 38), row * 0.3)
        pct = fit(_pct(genre.share), t.number(size, fill=t.fg), 200)
        c.draw_block(pct, ctx.W - ctx.m, top, align="right")
        name = c.text(genre.title, ctx.m, top, t.title(size), ctx.inner - pct.width - 30)
        bar_y = top + name.height + size * 0.55
        bar_h = size * 0.62
        c.rect(ctx.m, bar_y, ctx.inner, bar_h, fill=t.fg, radius=bar_h / 2, opacity=0.1)
        c.rect(ctx.m, bar_y, max(bar_h, ctx.inner * genre.share / biggest), bar_h, fill=colors[i % len(colors)],
               radius=bar_h / 2)


@layout("genres", "words", "Words")
def genres_words(ctx: Ctx) -> None:
    """Genre names stacked, sized by their share."""
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My top genres")
    bottom = ctx.footer()
    genres = d.genres[: ctx.s(6, 4)]
    biggest = max((g.share for g in genres), default=1) or 1
    colors = (t.fg, *t.palette)
    max_size = ctx.s(170, 110)
    sizes = [max_size * (0.45 + 0.55 * math.sqrt(g.share / biggest)) for g in genres]
    room = bottom - y - ctx.s(40, 20)
    # Fill the space: grow or shrink every word by the same factor.
    total = sum(sizes) * 1.15
    sizes = [s * min(room / total, 1.5) for s in sizes]
    top = y + ctx.s(40, 20)
    for i, (genre, size) in enumerate(zip(genres, sizes)):
        pct = fit(_pct(genre.share), t.small(max(20, size * 0.24)), 160)
        word = c.text(genre.title, ctx.m, top, t.headline(size, fill=colors[i % len(colors)], min_size=size * 0.5),
                      ctx.inner - pct.width - 24)
        c.draw_block(pct, ctx.m + word.width + 20, top)
        top += word.height + size * 0.28
