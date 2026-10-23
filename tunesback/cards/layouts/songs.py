"""Top songs, and the #1 song on its own."""
from __future__ import annotations

from ..registry import layout
from .base import Ctx, receipt, two_lines


@layout("top_songs", "list", "List")
def songs_list(ctx: Ctx) -> None:
    ctx.background()
    y = ctx.header("My top songs")
    bottom = ctx.footer()
    items = ctx.d.songs[:5]
    gap = ctx.s(50, 28)
    ctx.rows(items, ctx.m, y + gap, ctx.inner, bottom - y - gap)


@layout("top_songs", "spotlight", "Spotlight")
def songs_spotlight(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    first, rest = d.songs[0], d.songs[1:5]
    if ctx.square:
        ctx.background()
        y = ctx.header("My top songs", width=ctx.inner)
        bottom = ctx.footer()
        size = min(bottom - y - 30, 400)
        top = y + 24
        ctx.art(first, ctx.m, top, size)
        x = ctx.m + size + 44
        width = ctx.W - ctx.m - x
        ctx.pill("#1", x, top, 24)
        after = two_lines(ctx, first.title, first.subtitle, x, top + 80, width, 64, lines=3)
        c.text(d.metric(first), x, after + 10, t.small(24, fill=t.accent), width)
        if rest:
            list_top = top + size + 30
            ctx.rows(rest[:2], ctx.m, list_top, ctx.inner, bottom - list_top, art=False, start=2, title_size=30)
        return
    ctx.background()
    y = ctx.header("My top songs")
    bottom = ctx.footer()
    size = 640
    left = (ctx.W - size) / 2
    ctx.art(first, left, y + 50, size)
    ctx.pill("#1", left + 28, y + 78, 28)
    y = two_lines(ctx, first.title, first.subtitle, ctx.W / 2, y + 50 + size + 56, ctx.inner, 78, align="center")
    if rest:
        c.line(ctx.m, y + 24, ctx.W - ctx.m, y + 24, t.fg, 2, opacity=0.18)
        ctx.rows(rest, ctx.m, y + 44, ctx.inner, bottom - y - 44, art=False, start=2, title_size=36)


@layout("top_songs", "receipt", "Receipt")
def songs_receipt(ctx: Ctx) -> None:
    ctx.background()
    d = ctx.d
    count = 5 if ctx.square else 10
    rows = [(f"{i + 1:02d} {s.title}", d.metric(s, short=True)) for i, s in enumerate(d.songs[:count])]
    receipt(ctx, "My top songs", [("Song" + (" · plays" if d.rank_by == "plays" else " · minutes"), rows)],
            [("Songs played", f"{d.song_count:,}"), ("Minutes", f"{d.minutes:,}")])


@layout("top_song", "cover", "Cover")
def song_cover(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    song = d.songs[0]
    if ctx.square:
        ctx.background()
        size = 520
        top = (ctx.H - size) / 2 - 30
        ctx.art(song, ctx.m, top, size)
        x = ctx.m + size + 48
        width = ctx.W - ctx.m - x
        c.text("My top song", x, top + 6, t.small(26), width)
        c.text(d.period, x, top + 50, t.small(26, fill=t.accent), width)
        after = two_lines(ctx, song.title, song.subtitle, x, top + 120, width, 66, lines=4)
        ctx.pill(d.metric(song), x, min(after + 20, top + size - 52), 22)
        ctx.footer()
        return
    ctx.background()
    y = ctx.header("My top song")
    ctx.footer()
    size = ctx.inner
    ctx.art(song, ctx.m, y + 40, size)
    y = two_lines(ctx, song.title, song.subtitle, ctx.m, y + 40 + size + 60, ctx.inner, 92)
    ctx.pill(d.metric(song), ctx.m, y + 26, 28)


@layout("top_song", "vinyl", "Vinyl")
def song_vinyl(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    song = d.songs[0]
    ctx.background()

    def record(cx: float, cy: float, r: float) -> None:
        c.backdrop.shadow(cx - r, cy - r + r * 0.05, 2 * r, 2 * r, blur=r * 0.12, alpha=0.6, round=True)
        c.circle(cx, cy, r, fill="#0E0E10")
        for i in range(10):
            c.circle(cx, cy, r * (0.42 + i * 0.055), stroke="#FFFFFF", stroke_width=1.5, opacity=0.07)
        c.path(f"M{cx - r * 0.7:.0f},{cy - r * 0.55:.0f} A{r * 0.9:.0f},{r * 0.9:.0f} 0 0 1 {cx + r * 0.2:.0f},{cy - r * 0.88:.0f}",
               stroke="#FFFFFF", width=r * 0.05, opacity=0.08, cap="round")
        ctx.art(song, cx - r * 0.36, cy - r * 0.36, r * 0.72, round=True, shadow=False)
        c.circle(cx, cy, r * 0.035, fill=t.bg[0])

    if ctx.square:
        r = 330
        record(ctx.m + r, ctx.H / 2 - 20, r)
        x = ctx.m + 2 * r + 50
        width = ctx.W - ctx.m - x
        top = ctx.H / 2 - 200
        c.text("My top song", x, top, t.small(24), width)
        after = two_lines(ctx, song.title, song.subtitle, x, top + 56, width, 56, lines=4)
        ctx.pill(d.metric(song), x, after + 18, 20)
        ctx.footer()
        return
    y = ctx.header("My top song")
    ctx.footer()
    r = 430
    record(ctx.W / 2, y + 60 + r, r)
    y = two_lines(ctx, song.title, song.subtitle, ctx.W / 2, y + 60 + 2 * r + 70, ctx.inner, 88, align="center")
    ctx.pill(d.metric(song), ctx.W / 2, y + 26, 28, align="center")
