"""Listening age."""
from __future__ import annotations

from datetime import date

from ..registry import layout
from ..text import fit
from .base import Ctx


@layout("listening_age", "big", "Big number")
def age_big(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    age = d.listening_age
    ctx.background()
    y = ctx.header("My listening age")
    bottom = ctx.footer()
    number = fit(str(age["age"]), t.number(ctx.s(560, 360)), ctx.inner)
    title = fit(f"Into the music of the {age['era_label']}", t.title(ctx.s(56, 40), max_lines=2), ctx.inner)
    body = fit(f"You played the most music released between {age['era_start']} and {age['era_end']}. "
               "That's how old you'd be if you were 18 back then.", t.text(ctx.s(32, 24), max_lines=4, line_height=1.3),
               ctx.inner)
    block = number.height + ctx.s(70, 40) + title.height + title.descent + ctx.s(30, 20) + body.height
    top = y + max(ctx.s(30, 10), (bottom - y - block) / 2)
    c.draw_block(number, ctx.m - number.size * 0.04, top)
    top += number.height + ctx.s(70, 40)
    c.draw_block(title, ctx.m, top)
    top += title.height + title.descent + ctx.s(30, 20)
    c.draw_block(body, ctx.m, top)


@layout("listening_age", "era", "Timeline")
def age_era(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    age = d.listening_age
    ctx.background()
    y = ctx.header("My listening age")
    bottom = ctx.footer()
    era = fit(age["era_label"], t.headline(ctx.s(200, 130)), ctx.inner)
    top = y + ctx.s(80, 30)
    c.draw_block(era, ctx.m, top)
    top += era.height + era.descent + ctx.s(40, 24)
    ctx.pill(f"Listening age {age['age']}", ctx.m, top, ctx.s(30, 22))
    # A ruler of decades with the era marked on it.
    first = (min(age["era_start"], date.today().year - 40) // 10) * 10
    last = (date.today().year // 10 + 1) * 10
    ruler_y = top + ctx.s(420, 170)
    span = last - first
    x_of = lambda year: ctx.m + (year - first) / span * ctx.inner
    band_h = ctx.s(220, 100)
    c.rect(x_of(age["era_start"]), ruler_y - band_h / 2, max(12, x_of(age["era_end"] + 1) - x_of(age["era_start"])),
           band_h, fill=t.accent, radius=ctx.s(18, 12))
    c.line(ctx.m, ruler_y, ctx.W - ctx.m, ruler_y, t.fg, 3, opacity=0.5)
    for decade in range(first, last + 1, 10):
        x = x_of(decade)
        c.line(x, ruler_y - 18, x, ruler_y + 18, t.fg, 3, opacity=0.6)
        c.text(f"'{str(decade)[-2:]}", x, ruler_y + band_h / 2 + 24, t.small(ctx.s(26, 20)), 120, align="center")
    note = (f"Most of what you played came out between {age['era_start']} and {age['era_end']}.")
    if bottom - (ruler_y + band_h) > ctx.s(200, 80):
        c.text(note, ctx.m, ruler_y + band_h / 2 + ctx.s(130, 70), t.text(ctx.s(36, 24), max_lines=3, line_height=1.3), ctx.inner)
