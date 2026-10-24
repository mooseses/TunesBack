"""Cards from listening times: the clock, the months, streaks and discoveries."""
from __future__ import annotations

import math
from datetime import date, timedelta

from ..registry import layout
from ..text import fit
from .base import Ctx

HOUR_LABELS = {0: "12am", 6: "6am", 12: "12pm", 18: "6pm"}
WEEKDAYS = ("M", "T", "W", "T", "F", "S", "S")
WEEKDAY_NAMES = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")


def _hour_name(hour: int) -> str:
    return f"{(hour % 12) or 12}{'am' if hour < 12 else 'pm'}"


def persona(hour: int) -> tuple[str, str]:
    """A name for when someone listens most, and a line about it."""
    if 5 <= hour < 11:
        return "Early bird", f"Your music peaks at {_hour_name(hour)}."
    if 11 <= hour < 17:
        return "Daytime listener", f"Your music peaks at {_hour_name(hour)}."
    if 17 <= hour < 22:
        return "Evening listener", f"Your music peaks at {_hour_name(hour)}."
    return "Night owl", f"Your music peaks at {_hour_name(hour)}."


def _values(ctx: Ctx, key: str) -> list[int]:
    data = ctx.d.timeline[key]
    return data["ms"] if ctx.d.rank_by == "time" else data["plays"]


def _week(ctx: Ctx, x: float, y: float, w: float, h: float) -> None:
    """Seven bars, Monday to Sunday, with the busiest one in the accent colour."""
    c, t = ctx.c, ctx.t
    values = _values(ctx, "weekdays")
    top = max(values) or 1
    slot = w / 7
    bar_w = slot * 0.56
    label = ctx.s(26, 20)
    peak = values.index(max(values))
    for i, value in enumerate(values):
        bx = x + i * slot + (slot - bar_w) / 2
        bh = max(bar_w * 0.4, (h - label * 2) * value / top)
        c.rect(bx, y + h - label * 2 - bh, bar_w, bh, fill=t.accent if i == peak else t.fg,
               opacity=1 if i == peak else 0.25, radius=bar_w * 0.3)
        c.text(WEEKDAYS[i], bx + bar_w / 2, y + h - label, t.small(label, fill=t.fg if i == peak else t.muted),
               slot, align="center")


@layout("clock", "dial", "Dial")
def clock_dial(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    peak = d.timeline["peak_hour"]
    name, line = persona(peak)
    y = ctx.header(name, label="When I listen")
    bottom = ctx.footer()
    values = _values(ctx, "hours")
    top = max(values) or 1
    if ctx.square:
        r = min(300, (bottom - y) / 2 - 20)
        cx, cy = ctx.m + r + 20, y + (bottom - y) / 2
    else:
        r = 380
        cx, cy = ctx.W / 2, y + 60 + r
    inner = r * 0.36
    c.circle(cx, cy, r, fill=t.fg, opacity=0.06)
    for hour, value in enumerate(values):
        angle = (hour / 24) * math.tau - math.pi / 2
        length = inner + (r - inner) * (0.08 + 0.92 * value / top)
        width = math.tau * inner / 24 * 0.7
        x1, y1 = cx + math.cos(angle) * (inner + 8), cy + math.sin(angle) * (inner + 8)
        x2, y2 = cx + math.cos(angle) * length, cy + math.sin(angle) * length
        c.line(x1, y1, x2, y2, t.accent if hour == peak else t.fg, width, opacity=1 if hour == peak else 0.55)
    for hour, label in HOUR_LABELS.items():
        angle = (hour / 24) * math.tau - math.pi / 2
        lx, ly = cx + math.cos(angle) * (r + ctx.s(48, 34)), cy + math.sin(angle) * (r + ctx.s(48, 34))
        block = fit(label, t.small(ctx.s(26, 20)), 120)
        c.draw_block(block, lx, ly - block.cap_height / 2, align="center")
    peak_block = fit(_hour_name(peak), t.number(inner * 0.62), inner * 1.6)
    c.draw_block(peak_block, cx, cy - peak_block.cap_height / 2, align="center")
    if ctx.square:
        x = cx + r + 90
        width = ctx.W - ctx.m - x
        c.text(line, x, y + 30, t.text(30, fill=t.fg, max_lines=3, line_height=1.25), width)
        _week(ctx, x, y + 170, width, bottom - y - 190)
        return
    below = cy + r + 110
    c.text(line, ctx.m, below, t.text(40, fill=t.fg), ctx.inner)
    _week(ctx, ctx.m, below + 90, ctx.inner, bottom - below - 90)


@layout("clock", "bars", "Bars")
def clock_bars(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    peak = d.timeline["peak_hour"]
    name, line = persona(peak)
    y = ctx.header(name, label="When I listen")
    bottom = ctx.footer()
    values = _values(ctx, "hours")
    top = max(values) or 1
    chart_h = ctx.s(560, 300)
    chart_y = y + ctx.s(70, 30)
    slot = ctx.inner / 24
    for hour, value in enumerate(values):
        bh = max(6, chart_h * value / top)
        c.rect(ctx.m + hour * slot + slot * 0.15, chart_y + chart_h - bh, slot * 0.7, bh,
               fill=t.accent if hour == peak else t.fg, opacity=1 if hour == peak else 0.3, radius=slot * 0.2)
    for hour, label in HOUR_LABELS.items():
        c.text(label, ctx.m + hour * slot, chart_y + chart_h + 24, t.small(ctx.s(24, 18)), 120)
    y = chart_y + chart_h + ctx.s(110, 70)
    c.text(line, ctx.m, y, t.title(ctx.s(44, 32)), ctx.inner)
    week = _values(ctx, "weekdays")
    day = WEEKDAY_NAMES[week.index(max(week))]
    c.text(f"And {day} are your busiest days.", ctx.m, y + ctx.s(70, 48), t.text(ctx.s(34, 26)), ctx.inner)
    if not ctx.square:
        _week(ctx, ctx.m, y + 170, ctx.inner, bottom - y - 170)


def _months(ctx: Ctx) -> list[dict]:
    return ctx.d.timeline["months"][-12:]


def _month_label(month: str, short: bool = True) -> str:
    year, number = month.split("-")
    return date(int(year), int(number), 1).strftime("%b" if short else "%B")


@layout("months", "rows", "Rows")
def months_rows(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My year in months")
    bottom = ctx.footer()
    months = _months(ctx)
    if ctx.square:
        months = months[-6:]
    key = "ms" if d.rank_by == "time" else "plays"
    top = max((m[key] for m in months), default=1) or 1
    row = (bottom - y - 20) / len(months)
    size = min(ctx.s(34, 26), row * 0.42)
    label_w = size * 2.6
    bar_x = ctx.m + label_w
    peak = max(months, key=lambda m: m[key])["month"]
    for i, month in enumerate(months):
        ry = y + 20 + i * row
        c.text(_month_label(month["month"]), ctx.m, ry + (row - size * 0.7) / 2, t.small(size * 0.8), label_w)
        bar_w = max(row * 0.2, (ctx.inner - label_w) * 0.55 * month[key] / top)
        bar_h = row * 0.56
        c.rect(bar_x, ry + (row - bar_h) / 2, bar_w, bar_h, fill=t.accent if month["month"] == peak else t.fg,
               opacity=1 if month["month"] == peak else 0.22, radius=bar_h / 3)
        if month.get("top_artist"):
            c.text(month["top_artist"], bar_x + bar_w + 18, ry + (row - size * 0.72) / 2,
                   t.title(size * 0.9), ctx.W - ctx.m - (bar_x + bar_w + 18))


@layout("months", "grid", "Calendar")
def months_grid(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    ctx.background()
    y = ctx.header("My year in months")
    bottom = ctx.footer()
    months = _months(ctx)
    cols = 3 if not ctx.square else 4
    rows = math.ceil(len(months) / cols)
    gap = ctx.s(18, 14)
    cell_w = (ctx.inner - gap * (cols - 1)) / cols
    cell_h = min(cell_w * 1.15, (bottom - y - 30 - gap * (rows - 1)) / max(rows, 1))
    key = "ms" if d.rank_by == "time" else "plays"
    top = max((m[key] for m in months), default=1) or 1
    for i, month in enumerate(months):
        x = ctx.m + (i % cols) * (cell_w + gap)
        cy = y + 30 + (i // cols) * (cell_h + gap)
        share = month[key] / top
        c.rect(x, cy, cell_w, cell_h, fill=t.accent, opacity=0.12 + 0.88 * share, radius=ctx.s(22, 14))
        ink = t.on_accent if share > 0.55 else t.fg
        pad = ctx.s(22, 14)
        c.text(_month_label(month["month"]), x + pad, cy + pad, t.small(ctx.s(24, 17), fill=ink), cell_w - 2 * pad)
        if month.get("top_artist"):
            c.text(month["top_artist"], x + pad, cy + cell_h - pad - ctx.s(84, 52),
                   t.title(ctx.s(34, 22), fill=ink, max_lines=2, min_size=ctx.s(22, 15)), cell_w - 2 * pad)
            c.text(f"{month['plays']:,} plays", x + pad, cy + cell_h - pad - ctx.s(18, 12),
                   t.text(ctx.s(22, 15), fill=ink, opacity=0.8), cell_w - 2 * pad, anchor="bottom")


def _streak_facts(ctx: Ctx) -> tuple[dict, str]:
    tl = ctx.d.timeline
    streak = tl["longest_streak"]
    start, end = date.fromisoformat(streak["start"]), date.fromisoformat(streak["end"])
    span = f"{start.day} {start:%b} – {end.day} {end:%b %Y}" if start != end else f"{start.day} {start:%b %Y}"
    return streak, span


def _streak_details(ctx: Ctx, top: float, bottom: float) -> None:
    """Days with music and the busiest day, one per line."""
    c, t, tl = ctx.c, ctx.t, ctx.d.timeline
    busiest = date.fromisoformat(tl["busiest_day"]["date"])
    facts = [(f"{tl['days_active']:,}", f"of {tl['days']:,} days with music"),
             (f"{tl['busiest_day']['plays']:,}", f"plays on {busiest.day} {busiest:%b}, your busiest day")]
    for value, label in facts:
        if top > bottom - ctx.s(90, 60):
            break
        v = c.text(value, ctx.m, top, t.headline(ctx.s(64, 44), fill=t.accent), 300)
        c.text(label, ctx.m + v.width + 20, top + v.cap_height - ctx.s(26, 20) * 0.7, t.text(ctx.s(30, 22)),
               ctx.inner - v.width - 20)
        top += v.height + ctx.s(50, 30)


@layout("streak", "big", "Big number")
def streak_big(ctx: Ctx) -> None:
    c, t = ctx.c, ctx.t
    streak, span = _streak_facts(ctx)
    ctx.background()
    y = ctx.header("My longest streak")
    bottom = ctx.footer()
    number = fit(f"{streak['days']}", t.number(ctx.s(480, 300)), ctx.inner * 0.75)
    unit = fit("days in a row", t.title(ctx.s(56, 40)), ctx.inner)
    block = number.height + ctx.s(50, 30) + unit.height + ctx.s(30, 20) + ctx.s(320, 170)
    top = y + max(ctx.s(60, 20), (bottom - y - block) / 2)
    c.draw_block(number, ctx.m - number.size * 0.03, top)
    top += number.height + ctx.s(50, 30)
    c.draw_block(unit, ctx.m, top)
    top += unit.height + ctx.s(30, 20)
    c.text(span, ctx.m, top, t.text(ctx.s(34, 26)), ctx.inner)
    _streak_details(ctx, top + ctx.s(120, 70), bottom)


@layout("streak", "calendar", "Calendar")
def streak_calendar(ctx: Ctx) -> None:
    """Every day of the period as a square, filled in when there was music."""
    c, t, d = ctx.c, ctx.t, ctx.d
    tl = d.timeline
    streak, span = _streak_facts(ctx)
    ctx.background()
    y = ctx.header(f"{streak['days']} days in a row", label="My longest streak")
    bottom = ctx.footer()
    daily = tl["daily"]
    first = date.fromisoformat(min(daily))
    last = date.fromisoformat(max(daily))
    start = first - timedelta(days=first.weekday())
    weeks = (last - start).days // 7 + 1
    s_start, s_end = date.fromisoformat(streak["start"]), date.fromisoformat(streak["end"])
    peak = max(daily.values()) or 1
    # Weeks run across in bands of up to half a year, so the squares stay big enough to see.
    per_band = min(weeks, 27)
    bands = math.ceil(weeks / per_band)
    band_gap = ctx.s(50, 30)
    room_h = bottom - y - ctx.s(170, 110)
    cell = min(ctx.inner / per_band, (room_h - band_gap * (bands - 1)) / (7 * bands))
    gap = cell * 0.18
    x0 = ctx.m
    y0 = y + ctx.s(50, 24)
    day = start
    while day <= last:
        week, weekday = (day - start).days // 7, day.weekday()
        band, col = divmod(week, per_band)
        plays = daily.get(day.isoformat(), 0)
        in_streak = s_start <= day <= s_end
        opacity = 1 if in_streak else (0.12 + 0.55 * min(1, plays / peak) if plays else 0.06)
        c.rect(x0 + col * cell, y0 + band * (7 * cell + band_gap) + weekday * cell, cell - gap, cell - gap,
               fill=t.accent if in_streak else t.fg, opacity=opacity, radius=cell * 0.2)
        day += timedelta(days=1)
    below = y0 + bands * 7 * cell + (bands - 1) * band_gap + ctx.s(50, 30)
    c.text(span, ctx.m, below, t.text(ctx.s(34, 24), fill=t.fg), ctx.inner)
    if not ctx.square:
        _streak_details(ctx, below + 120, bottom)


@layout("discoveries", "list", "List")
def discoveries_list(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    found = d.timeline["discoveries"]
    ctx.background()
    y = ctx.header("New to me")
    bottom = ctx.footer()
    count = c.text(f"{found['artists']:,}", ctx.m, y + ctx.s(40, 16), t.number(ctx.s(220, 130)), ctx.inner * 0.6)
    c.text("artists I heard for the first time", ctx.m, y + ctx.s(40, 16) + count.height + ctx.s(36, 22),
           t.title(ctx.s(44, 30)), ctx.inner)
    top = y + ctx.s(40, 16) + count.height + ctx.s(150, 90)
    items = [type("Row", (), {"title": a["name"], "subtitle": None, "plays": a["plays"], "ms": 0, "art": None})()
             for a in found["top"][: ctx.s(5, 3)]]
    for i, item in enumerate(items):
        row = (bottom - top) / max(len(items), 1)
        size = min(ctx.s(56, 36), row * 0.45)
        ry = top + i * row
        c.text(f"{i + 1}", ctx.m, ry, t.small(size * 0.55, fill=t.accent), 60)
        name = c.text(item.title, ctx.m + size * 1.3, ry, t.headline(size), ctx.inner - size * 1.3)
        c.text(f"{item.plays:,} plays", ctx.m + size * 1.3, ry + name.height + size * 0.35, t.text(size * 0.48),
               ctx.inner - size * 1.3)


@layout("discoveries", "big", "Big number")
def discoveries_big(ctx: Ctx) -> None:
    c, t, d = ctx.c, ctx.t, ctx.d
    found = d.timeline["discoveries"]
    ctx.background()
    y = ctx.header("New to me")
    bottom = ctx.footer()
    top_name = found["top"][0]["name"] if found["top"] else ""
    number = fit(f"{found['artists']:,}", t.number(ctx.s(460, 300)), ctx.inner)
    block = number.height + ctx.s(260, 150)
    top = y + max(ctx.s(40, 10), (bottom - y - block) / 2)
    c.draw_block(number, ctx.m - number.size * 0.03, top)
    top += number.height + ctx.s(60, 34)
    c.text("new artists", ctx.m, top, t.title(ctx.s(56, 38)), ctx.inner)
    if top_name:
        c.text(f"The one you played most: {top_name}", ctx.m, top + ctx.s(90, 60),
               t.text(ctx.s(34, 24), fill=t.fg, max_lines=2), ctx.inner)
