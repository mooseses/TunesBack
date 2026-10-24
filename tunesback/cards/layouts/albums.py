"""Top albums."""
from __future__ import annotations

from ..registry import layout
from .base import Ctx


@layout("top_albums", "grid", "Grid")
def albums_grid(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My top albums")
    bottom = ctx.footer()
    albums = d.albums
    if ctx.square:
        gap = 24
        count = min(3, len(albums))
        size = (ctx.inner - gap * 2) / 3
        top = y + 24
        for i, album in enumerate(albums[:3]):
            x = ctx.m + i * (size + gap)
            ctx.art(album, x, top, size)
            ctx.pill(str(i + 1), x + 16, top + 16, 20)
            c.text(album.title, x, top + size + 22, t.title(26), size)
            c.text(album.subtitle or "", x, top + size + 60, t.text(21), size)
        rest = albums[count:5]
        list_top = top + size + 110
        if rest and bottom - list_top > 60:
            ctx.rows(rest[: max(1, int((bottom - list_top) // 70))], ctx.m, list_top, ctx.inner, bottom - list_top,
                     art=False, start=count + 1, title_size=28)
        return
    gap = 30
    size = (ctx.inner - gap) / 2
    top = y + 50
    for i, album in enumerate(albums[:4]):
        x = ctx.m + (i % 2) * (size + gap)
        ay = top + (i // 2) * (size + gap)
        ctx.art(album, x, ay, size)
        ctx.pill(str(i + 1), x + 22, ay + 22, 26)
    rows = (len(albums[:4]) + 1) // 2
    list_top = top + rows * (size + gap) + 20
    ctx.rows(albums[:5], ctx.m, list_top, ctx.inner, bottom - list_top, art=False, title_size=36)


@layout("top_albums", "stack", "Stack")
def albums_stack(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My top albums")
    bottom = ctx.footer()
    albums = d.albums[:5]
    n = len(albums)
    if ctx.square:
        size, dx, dy = 360, 46, 34
        x0, y0 = ctx.m, y + 30
    else:
        size, dx, dy = 560, 80, 60
        x0, y0 = ctx.m + (ctx.inner - size - dx * (n - 1)) / 2, y + 60
    # Back to front: the last album is drawn first, #1 ends up on top.
    for i in range(n - 1, -1, -1):
        album = albums[i]
        ax, ay = x0 + dx * (n - 1 - i), y0 + dy * (n - 1 - i)
        img = d.art(album)
        if img is not None:
            c.image(img, ax, ay, size, size, radius=t.radius * size / 400, shadow=0.55 if t.dark else 0.3)
        else:
            ctx.art(album, ax, ay, size, shadow=False)
    if ctx.square:
        x = x0 + size + dx * (n - 1) + 40
        ctx.rows(albums, x, y + 30, ctx.W - ctx.m - x, bottom - y - 30, art=False, title_size=26)
    else:
        list_top = y0 + size + dy * (n - 1) + 50
        ctx.rows(albums, ctx.m, list_top, ctx.inner, bottom - list_top, art=False, title_size=36)
