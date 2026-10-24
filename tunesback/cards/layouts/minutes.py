"""Minutes listened."""
from __future__ import annotations

from ..registry import layout
from ..text import fit
from .base import Ctx


def _facts(ctx: Ctx) -> list[tuple[str, str]]:
    d = ctx.d
    hours = d.total_ms / 3_600_000
    facts = [(f"{hours:,.0f}", "hours")]
    if hours >= 48:
        facts.append((f"{hours / 24:,.1f}", "days"))
    if d.days:
        facts.append((f"{d.minutes / d.days:,.0f}", "minutes a day"))
    facts.append((f"{d.song_count:,}", "songs"))
    return facts[:3]


@layout("minutes", "big", "Big number")
def minutes_big(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("Minutes listened")
    bottom = ctx.footer()
    number = fit(f"{d.minutes:,}", t.number(ctx.s(400, 250), min_size=80), ctx.inner)
    facts = _facts(ctx)
    fact_h = ctx.s(150, 96)
    block_h = number.height + ctx.s(90, 50) + fact_h
    top = y + max(ctx.s(40, 20), (bottom - y - block_h) / 2)
    c.draw_block(number, ctx.m, top)
    top += number.height + ctx.s(90, 50)
    width = ctx.inner / len(facts)
    for i, (value, label) in enumerate(facts):
        x = ctx.m + i * width
        c.line(x, top, x, top + fact_h, t.fg, 2, opacity=0.2) if i else None
        pad = 24 if i else 0
        v = c.text(value, x + pad, top, t.headline(ctx.s(76, 50)), width - pad - 10)
        c.text(label, x + pad, top + v.height + ctx.s(24, 16), t.small(ctx.s(26, 19)), width - pad - 10)
    if d.estimated_time:
        c.text("Some times are estimated from song lengths.", ctx.m, bottom - 30, t.text(ctx.s(24, 18)), ctx.inner)


@layout("minutes", "tiles", "Flip clock")
def minutes_tiles(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("Minutes listened")
    bottom = ctx.footer()
    digits = f"{d.minutes:,}"
    count = sum(ch.isdigit() for ch in digits)
    commas = len(digits) - count
    gap = 14
    tile_w = min(ctx.s(160, 130), (ctx.inner - gap * (count - 1) - commas * 30) / max(count, 1))
    tile_h = tile_w * 1.45
    total_w = count * tile_w + gap * (count - 1) + commas * 30
    x = (ctx.W - total_w) / 2
    top = y + (bottom - y - tile_h - ctx.s(260, 150)) / 2
    style = t.number(tile_w * 0.95, fill=t.on_accent, tracking=0)
    for ch in digits:
        if not ch.isdigit():
            c.text(ch, x + 15, top + tile_h - tile_w * 0.25, t.number(tile_w * 0.6, fill=t.fg), 30, align="center", anchor="baseline")
            x += 30
            continue
        c.backdrop.shadow(x, top + 6, tile_w, tile_h, tile_w * 0.14, blur=20, alpha=0.4 if t.dark else 0.2)
        c.rect(x, top, tile_w, tile_h, fill=t.accent, radius=tile_w * 0.14)
        c.rect(x, top + tile_h / 2 - 1.5, tile_w, 3, fill=t.bg[0], opacity=0.35)
        block = fit(ch, style, tile_w)
        c.draw_block(block, x + tile_w / 2, top + (tile_h - block.cap_height) / 2, align="center")
        x += tile_w + gap
    top += tile_h + ctx.s(90, 50)
    facts = _facts(ctx)
    pill_y = top
    widths = []
    for value, label in facts:
        widths.append(fit(f"{value} {label}", t.small(ctx.s(28, 21)), ctx.inner).width + ctx.s(28, 21) * 1.8)
    x = (ctx.W - sum(widths) - 16 * (len(widths) - 1)) / 2
    for (value, label), w in zip(facts, widths):
        ctx.pill(f"{value} {label}", x, pill_y, ctx.s(28, 21), fill=t.surface, color=t.fg)
        x += w + 16
