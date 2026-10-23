"""Top artists."""
from __future__ import annotations

from ..registry import layout
from .base import Ctx


@layout("top_artists", "billboard", "Billboard")
def artists_billboard(ctx: Ctx) -> None:
    """Names in big type, getting smaller down the list."""
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My top artists")
    bottom = ctx.footer()
    artists = d.artists[:5]
    sizes = [ctx.s(150, 96) * k for k in (1, 0.8, 0.68, 0.6, 0.54)]
    row = (bottom - y - ctx.s(40, 20)) / max(1, len(artists))
    for i, artist in enumerate(artists):
        top = y + ctx.s(40, 20) + i * row
        size = min(sizes[i], row * 0.55)
        number = c.text(f"{i + 1}", ctx.m, top, t.small(ctx.s(30, 24), fill=t.accent), 80)
        name = c.text(artist.title, ctx.m + ctx.s(64, 52), top, t.headline(size, fill=t.accent if i == 0 else t.fg, min_size=size * 0.5),
                      ctx.inner - ctx.s(64, 52))
        c.text(d.metric(artist), ctx.m + ctx.s(64, 52), top + name.height + name.descent + 12,
               t.text(ctx.s(30, 22)), ctx.inner - ctx.s(64, 52))


@layout("top_artists", "spotlight", "Spotlight")
def artists_spotlight(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    first, rest = d.artists[0], d.artists[1:5]
    bottom = ctx.footer()
    if ctx.square:
        c.text("My top artist", ctx.m, ctx.top, t.small(26), ctx.inner)
        c.text(d.period, ctx.m, ctx.top + 40, t.small(26, fill=t.accent), ctx.inner)
        size = 400
        top = ctx.top + 110
        ctx.art(first, ctx.m, top, size, round=True)
        x = ctx.m + size + 50
        width = ctx.W - ctx.m - x
        name = c.text(first.title, x, top + 40, t.headline(84, max_lines=3), width)
        ctx.pill(d.metric(first), x, top + 40 + name.height + 40, 22)
        if rest:
            list_top = top + size + 40
            ctx.rows(rest[:2], ctx.m, list_top, ctx.inner, bottom - list_top, art=False, start=2, title_size=30)
        return
    y = ctx.header("My top artist")
    size = 600
    ctx.art(first, (ctx.W - size) / 2, y + 60, size, round=True)
    y += 60 + size + 70
    name = c.text(first.title, ctx.W / 2, y, t.headline(120, max_lines=2), ctx.inner, align="center")
    y += name.height + name.descent + 30
    ctx.pill(d.metric(first), ctx.W / 2, y, 28, align="center")
    y += 110
    if rest:
        c.line(ctx.m, y, ctx.W - ctx.m, y, t.fg, 2, opacity=0.18)
        half = (ctx.inner - 40) / 2
        rows_h = bottom - y - 30
        ctx.rows(rest[:2], ctx.m, y + 30, half, rows_h, art=False, start=2, title_size=36, metric=False)
        if len(rest) > 2:
            ctx.rows(rest[2:4], ctx.m + half + 40, y + 30, half, rows_h, art=False, start=4, title_size=36, metric=False)
