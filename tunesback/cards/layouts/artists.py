"""Top artists."""
from __future__ import annotations

from ..registry import layout
from ..text import fit
from .base import Ctx


@layout("top_artists", "billboard", "Billboard")
def artists_billboard(ctx: Ctx) -> None:
    """Names in big type, getting smaller down the list, stacked closely and centred in the card."""
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My top artists")
    bottom = ctx.footer()
    artists = d.artists[:5]
    sizes = [ctx.s(150, 96) * k for k in (1, 0.8, 0.68, 0.6, 0.54)]
    indent = ctx.s(64, 52)
    width = ctx.inner - indent
    gap, under = ctx.s(34, 20), ctx.s(10, 6)
    area_top = y + ctx.s(40, 20)
    area = bottom - area_top

    def measure(scale: float) -> list[tuple]:
        rows = []
        for i, artist in enumerate(artists):
            size = sizes[i] * scale
            name = fit(artist.title, t.headline(size, fill=t.accent if i == 0 else t.fg, min_size=size * 0.5), width)
            metric = fit(d.metric(artist), t.text(ctx.s(30, 22)), width)
            rows.append((artist, name, metric, name.height + name.descent + under + metric.height + metric.descent))
        return rows

    rows = measure(1)
    total = sum(r[3] for r in rows) + gap * (len(rows) - 1)
    if total > area:  # long names wrapped: shrink everything to fit
        rows = measure(max(0.5, area / total * 0.97))
        total = sum(r[3] for r in rows) + gap * (len(rows) - 1)
    top = area_top + max(0, (area - total) / 2)
    for i, (artist, name, metric, height) in enumerate(rows):
        c.text(f"{i + 1}", ctx.m, top, t.small(ctx.s(30, 24), fill=t.accent), 80)
        c.draw_block(name, ctx.m + indent, top)
        c.draw_block(metric, ctx.m + indent, top + name.height + name.descent + under)
        top += height + gap


@layout("top_artists", "spotlight", "Spotlight")
def artists_spotlight(ctx: Ctx) -> None:
    """The #1 artist large, the next ones in a short list below, all centred in the card."""
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    first, rest = d.artists[0], d.artists[1:5]
    bottom = ctx.footer()
    if ctx.square:
        c.text("My top artist", ctx.m, ctx.top, t.small(26), ctx.inner)
        c.text(d.period, ctx.m, ctx.top + 40, t.small(26, fill=t.accent), ctx.inner)
        size, title, row = 380, 32, 84
        x = ctx.m + size + 50
        name = fit(first.title, t.headline(84, max_lines=3), ctx.W - ctx.m - x)
        hero = max(size, name.height + name.descent + 40 + 44)
        listed = rest[:3]
        total = hero + (36 + len(listed) * row if listed else 0)
        area = ctx.top + 100
        top = area + max(0, (bottom - area - total) / 2)
        ctx.art(first, ctx.m, top, size, round=True)
        text_top = top + (size - (name.height + name.descent + 40 + 44)) / 2
        c.draw_block(name, x, text_top)
        ctx.pill(d.metric(first), x, text_top + name.height + name.descent + 40, 21)
        if listed:
            ctx.rows(listed, ctx.m, top + hero + 36, ctx.inner, len(listed) * row, art=False, start=2,
                     title_size=title)
        return
    y = ctx.header("My top artist")
    size, title, row = 560, 38, 92
    name = fit(first.title, t.headline(120, max_lines=2), ctx.inner)
    pill_h = 28 * 2.1
    hero = size + 64 + name.height + name.descent + 32 + pill_h
    columns = [rest[:2], rest[2:4]]
    listed = max(len(col) for col in columns)
    total = hero + (60 + 2 + 36 + listed * row if rest else 0)
    top = y + max(48, (bottom - y - total) / 2)
    ctx.art(first, (ctx.W - size) / 2, top, size, round=True)
    top += size + 64
    c.draw_block(name, ctx.W / 2, top, align="center")
    top += name.height + name.descent + 32
    ctx.pill(d.metric(first), ctx.W / 2, top, 28, align="center")
    if rest:
        top += pill_h + 60
        c.line(ctx.m, top, ctx.W - ctx.m, top, t.fg, 2, opacity=0.18)
        top += 36
        half = (ctx.inner - 40) / 2
        for i, col in enumerate(columns):
            if col:
                ctx.rows(col, ctx.m + i * (half + 40), top, half, len(col) * row, art=False, start=2 + i * 2,
                         title_size=title, metric=False)
