"""The summary card: a bit of everything."""
from __future__ import annotations

from ..registry import layout
from ..text import fit
from .base import Ctx, receipt


def _column(ctx: Ctx, heading: str, names: list[str], x: float, y: float, width: float, size: float) -> float:
    c, t = ctx.c, ctx.t
    head = c.text(heading, x, y, t.small(size * 0.62), width)
    y += head.height + size * 0.9
    for i, name in enumerate(names):
        number = fit(str(i + 1), t.number(size, fill=t.accent), size * 1.4)
        c.draw_block(number, x, y)
        c.text(name, x + size * 1.3, y, t.title(size), width - size * 1.3)
        y += size * 1.75
    return y


@layout("summary", "classic", "Classic")
def summary_classic(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    bottom = ctx.footer()
    hero = d.artists[0] if d.art(d.artists[0] if d.artists else None) else (d.albums[0] if d.albums else d.songs[0])
    artists = [a.title for a in d.artists[:5]]
    songs = [s.title for s in d.songs[:5]]
    top_genre = d.genres[0].title if d.genres else "—"
    if ctx.square:
        size = 330
        ctx.art(hero, ctx.m, ctx.top, size)
        x = ctx.m + size + 50
        width = ctx.W - ctx.m - x
        c.text(d.period, x, ctx.top + 4, t.small(24, fill=t.accent), width)
        y = ctx.top + 70
        c.text("Minutes listened", x, y, t.small(22), width)
        num = c.text(f"{d.minutes:,}", x, y + 42, t.headline(76), width)
        y += 42 + num.height + 44
        c.text("Top genre", x, y, t.small(22), width)
        c.text(top_genre, x, y + 42, t.headline(54), width)
        half = (ctx.inner - 40) / 2
        y = ctx.top + size + 50
        _column(ctx, "Top artists", artists, ctx.m, y, half, 30)
        _column(ctx, "Top songs", songs, ctx.m + half + 40, y, half, 30)
        return
    size = 600
    ctx.art(hero, (ctx.W - size) / 2, ctx.top, size)
    y = ctx.top + size + 80
    half = (ctx.inner - 50) / 2
    end = max(_column(ctx, "Top artists", artists, ctx.m, y, half, 42),
              _column(ctx, "Top songs", songs, ctx.m + half + 50, y, half, 42))
    y = end + 30
    c.text("Minutes listened", ctx.m, y, t.small(26), half)
    c.text("Top genre", ctx.m + half + 50, y, t.small(26), half)
    c.text(f"{d.minutes:,}", ctx.m, y + 52, t.headline(96), half)
    c.text(top_genre, ctx.m + half + 50, y + 52, t.headline(96, min_size=48, max_lines=1), half)


@layout("summary", "receipt", "Receipt")
def summary_receipt(ctx: Ctx) -> None:
    ctx.background()
    d = ctx.d
    n = 3 if ctx.square else 5
    receipt(ctx, f"My {d.period}" if not d.lifetime else "My music, all time", [
        ("Top artists", [(f"{i + 1:02d} {a.title}", d.metric(a, short=True)) for i, a in enumerate(d.artists[:n])]),
        ("Top songs", [(f"{i + 1:02d} {s.title}", d.metric(s, short=True)) for i, s in enumerate(d.songs[:n])]),
    ], [("Minutes", f"{d.minutes:,}"), ("Plays", f"{d.total_plays:,}")]
        + ([("Top genre", d.genres[0].title)] if d.genres else []))
