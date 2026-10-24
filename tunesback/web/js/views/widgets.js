// The Overview's widgets. Each one draws a card from the recap and says which
// sizes it comes in and when it has something to show. The Overview arranges
// them (views/overview.js); docs/plans/overview-widgets.md has the design.

import { navigate, reducedMotion, render as renderApp, saveSettingsNow, state } from "../app.js";
import { duration, h, icon, number, plural, toast, unitInfo } from "../util.js";
import { artBox, rankedCached } from "./shared.js";

/** Tile sizes in grid cells, [columns, rows], as on the Windows Phone Start screen. */
export const TILES = { M: [2, 2], L: [4, 2], XL: [4, 4] };
export const SIZE_NAMES = { M: "Medium", L: "Wide", XL: "Large" };
export const SIZE_LABELS = { M: "M", L: "W", XL: "L" };

const timeline = (r) => !!r.timeline;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const hourName = (hour) => `${hour % 12 || 12}${hour < 12 ? "am" : "pm"}`;
const dayName = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
const value = (entry, by) => (by === "time" ? entry.ms : entry.plays);
const amount = (v, by, unit) => (by === "time" ? `${duration(v, unit)} ${unitInfo(unit).short}` : number(v));

/**
 * id -> {title, description, sizes (allowed, smallest first), size (default),
 *        available(report) -> bool, needs (when it isn't), render(report, {by, unit}) -> .card}
 */
export const WIDGETS = {
  "listening-time": {
    title: "Listening time", description: "How long you listened.", sizes: ["M", "L"], size: "M",
    render: (r, { unit }) => kpi("Listening time", `${r.estimated_time ? "≈ " : ""}${duration(r.total_ms, unit)}`, unitInfo(unit).long,
      r.estimated_time ? "partly estimated from song lengths" : r.mode === "compare" ? "in this period" : "all time"),
  },
  plays: {
    title: "Plays", description: "How many times you pressed play.", sizes: ["M", "L"], size: "M",
    render: (r) => kpi(r.mode === "compare" && !r.timeline ? "New plays" : "Plays", number(r.total_plays), null, plural(r.songs.length, "song")),
  },
  "new-finds": {
    title: "New finds", description: "Songs you played for the first time; for all-time recaps, how many artists you played.",
    sizes: ["M", "L"], size: "M",
    render: (r) => (r.mode === "compare"
      ? kpi("New finds", number(r.new_finds.length), null, r.timeline ? "songs played for the first time" : "songs added and played")
      : kpi("Artists", number(r.artists.length), null, plural(r.albums.length, "album"))),
  },
  skips: {
    title: "Skips", description: "Songs you skipped.", sizes: ["M", "L"], size: "M",
    render: (r) => kpi("Skips", number(r.total_skips), null, r.skipped.length ? `across ${plural(r.skipped.length, "song")}` : "nothing skipped"),
  },
  "top-artist": {
    title: "Top artist", description: "Your #1 artist.", sizes: ["L", "XL"], size: "L",
    render: (r, { by }) => highlight("Top artist", rankedCached(r, "artists", by)[0], { round: true, fallback: "artist" }),
  },
  "top-album": {
    title: "Top album", description: "Your #1 album.", sizes: ["L", "XL"], size: "L",
    render: (r, { by }) => highlight("Top album", rankedCached(r, "albums", by)[0], { fallback: "album" }),
  },
  "top-song": {
    title: "Top song", description: "Your #1 song.", sizes: ["L", "XL"], size: "L",
    render: (r, { by }) => highlight("Top song", rankedCached(r, "songs", by)[0], { fallback: "song" }),
  },
  "top-artists": {
    title: "Top artists", description: "Your ten most played artists, as bars.", sizes: ["L", "XL"], size: "L",
    render: (r, { by, unit }) => topList("Top artists", "artists", r, by, unit, 10),
  },
  "top-songs": {
    title: "Top songs", description: "Your five most played songs.", sizes: ["L", "XL"], size: "L",
    render: (r, { by, unit }) => rows("Top songs", "songs", rankedCached(r, "songs", by).slice(0, 5), by, unit),
  },
  "top-albums": {
    title: "Top albums", description: "Your most played albums, as a wall of covers.", sizes: ["L", "XL"], size: "L",
    render: (r, { by }) => covers(r, by),
  },
  genres: {
    title: "Genres", description: "Your listening split by genre.", sizes: ["L", "XL"], size: "L",
    available: (r) => r.genres.length > 0, needs: "Needs genres on the songs you played.",
    render: (r, { by }) => genres(r, by),
  },
  age: {
    title: "Listening age", description: "How old your taste is. Shown once you've worked it out.", sizes: ["L", "XL"], size: "L",
    render: (r) => listeningAge(r),
  },
  decades: {
    title: "Release decades", description: "When the music you played came out.", sizes: ["L", "XL"], size: "L",
    available: (r) => r.years.length > 0, needs: "Needs release years on the songs you played.",
    render: (r, { by, unit }) => decades(r, by, unit),
  },
  "most-skipped": {
    title: "Most skipped", description: "The songs you skipped most.", sizes: ["L", "XL"], size: "L",
    available: (r) => r.skipped.length > 0, needs: "Shows up once you've skipped something.",
    render: (r, { by, unit }) => rows("Most skipped", "skipped", rankedCached(r, "skipped", by).slice(0, 5), by, unit),
  },
  "listen-invite": {
    title: "See when you listen", description: "Add a source that logs every listen.", sizes: ["L", "XL"], size: "L",
    available: (r) => !r.timeline && state.sources.every((s) => s.counter), needs: "Shown until you add Last.fm, ListenBrainz or Spotify.",
    render: () => invite(),
  },
  streak: {
    title: "Longest streak", description: "The most days in a row you listened.", sizes: ["M", "L"], size: "M",
    available: timeline, needs: "Needs a source with listening dates.",
    render: (r) => {
      const s = r.timeline.longest_streak;
      return kpi("Longest streak", number(s.days), s.days === 1 ? "day" : "days", s.days > 1 ? `${dayName(s.start)} – ${dayName(s.end)}` : dayName(s.start));
    },
  },
  "days-active": {
    title: "Days with music", description: "How many days you listened at all.", sizes: ["M", "L"], size: "M",
    available: timeline, needs: "Needs a source with listening dates.",
    render: (r) => kpi("Days with music", number(r.timeline.days_active), null, `of ${plural(r.timeline.days, "day")}`),
  },
  "busiest-day": {
    title: "Busiest day", description: "The day you played the most.", sizes: ["M", "L"], size: "M",
    available: timeline, needs: "Needs a source with listening dates.",
    render: (r) => kpi("Busiest day", dayName(r.timeline.busiest_day.date), null, plural(r.timeline.busiest_day.plays, "play")),
  },
  "new-artists": {
    title: "New artists", description: "Artists you heard for the first time.", sizes: ["M", "L"], size: "M",
    available: (r) => !!r.timeline?.discoveries, needs: "Needs a long enough listening history.",
    render: (r) => {
      const found = r.timeline.discoveries;
      return kpi("New artists", number(found.artists), null, found.top[0] ? `most played: ${found.top[0].name}` : "first heard this period");
    },
  },
  "peak-time": {
    title: "Peak time", description: "The hour and day you listen most.", sizes: ["M", "L"], size: "M",
    available: timeline, needs: "Needs a source with listening dates.",
    render: (r) => kpi("Peak time", hourName(r.timeline.peak_hour), null, `busiest on ${WEEKDAYS[r.timeline.peak_weekday]}s`),
  },
  discoveries: {
    title: "Discoveries", description: "The new artists you played most.", sizes: ["L", "XL"], size: "L",
    available: (r) => !!r.timeline?.discoveries?.top?.length, needs: "Needs a long enough listening history.",
    render: (r) => discoveries(r),
  },
  "time-of-day": {
    title: "Time of day", description: "Your listening by hour.", sizes: ["L", "XL"], size: "L",
    available: timeline, needs: "Needs a source with listening dates.",
    render: (r, { by, unit }) => {
      const tl = r.timeline;
      return h("div.card",
        h("div.card-title", "Time of day", h("span.muted", `peaks at ${hourName(tl.peak_hour)}`)),
        columns(tl.hours[by === "time" ? "ms" : "plays"].map((v, hour) => ({
          value: v, tick: hour % 6 === 0 ? hourName(hour) : "", title: `${hourName(hour)}: ${amount(v, by, unit)}`, peak: hour === tl.peak_hour,
        })), { compact: true }));
    },
  },
  weekdays: {
    title: "Day of the week", description: "Your listening by weekday.", sizes: ["L", "XL"], size: "L",
    available: timeline, needs: "Needs a source with listening dates.",
    render: (r, { by, unit }) => {
      const tl = r.timeline;
      return h("div.card",
        h("div.card-title", "Day of the week"),
        columns(tl.weekdays[by === "time" ? "ms" : "plays"].map((v, day) => ({
          value: v, tick: WEEKDAYS[day], title: `${WEEKDAYS[day]}: ${amount(v, by, unit)}`, peak: day === tl.peak_weekday,
        })), { values: (v) => amount(v, by, unit) }));
    },
  },
  months: {
    title: "Month by month", description: "Each month, with the artist you played most.", sizes: ["XL"], size: "XL",
    available: (r) => (r.timeline?.months?.length ?? 0) > 1, needs: "Needs listening dates across two months or more.",
    render: (r, { by, unit }) => {
      const months = r.timeline.months;
      const metric = (m) => (by === "time" ? m.ms : m.plays);
      const most = Math.max(...months.map(metric));
      return h("div.card",
        h("div.card-title", "Month by month", h("span.muted", "with the artist you played most")),
        columns(months.map((m) => ({
          value: metric(m), tick: new Date(`${m.month}-01T00:00:00Z`).toLocaleDateString(undefined, { month: "short", timeZone: "UTC" }),
          title: `${m.month}: ${amount(metric(m), by, unit)}${m.top_artist ? ` · ${m.top_artist}` : ""}`, caption: m.top_artist,
          peak: metric(m) === most,
        })), { values: (v) => amount(v, by, unit), tall: true }));
    },
  },
};

/** Today's Overview, as tiles in order. Tiles that can't show anything for a recap are skipped. */
export const DEFAULT_LAYOUT = [
  // In four-cell groups: a Wide tile, a Large one or a pair of Medium ones each fill a group,
  // so the tiles pack without holes at 8, 12 or 16 columns.
  ["listening-time", "M"], ["plays", "M"], ["top-artist", "L"],
  ["new-finds", "M"], ["skips", "M"], ["top-song", "L"],
  ["top-artists", "XL"], ["top-album", "L"], ["genres", "L"],
  ["age", "L"], ["decades", "L"],
  ["listen-invite", "L"], ["streak", "M"], ["days-active", "M"],
  ["busiest-day", "M"], ["new-artists", "M"], ["time-of-day", "L"],
  ["weekdays", "L"], ["months", "XL"],
].map(([id, size]) => ({ id, size }));

/** Whether a widget is in the page for this recap (the age widget also follows its opt-in). */
export function shows(id, report) {
  const widget = WIDGETS[id];
  if (!widget) return false;
  if (id === "age" && state.settings.age_overview === false) return false;
  return !widget.available || widget.available(report);
}

// ---------- building blocks ----------

function kpi(label, text, unitText, sub) {
  return h("div.card.kpi",
    h("div.label", label),
    h("div.value", text, unitText && h("span.unit", unitText)),
    sub && h("div.sub", sub));
}

function highlight(label, entry, artOptions) {
  if (!entry) return h("div.card.highlight", h("div.text", h("div.label", label), h("div.title", "—")));
  const { unit, rank_by: by } = state.settings;
  const stat = by === "time" ? `${duration(entry.ms, unit)} ${unitInfo(unit).short}` : plural(entry.plays, "play");
  return h("div.card.highlight",
    artBox(entry.art, artOptions),
    h("div.text",
      h("div.label", label),
      h("div.title", { title: entry.title }, entry.title),
      entry.subtitle && h("div.subtitle", entry.subtitle),
      h("div.stat", stat)));
}

function seeAll(category) {
  return h("button.btn.btn-ghost.btn-small", { onclick: () => { state.charts.category = category; navigate("charts"); } }, "See all");
}

function topList(title, category, report, by, unit, limit) {
  const top = rankedCached(report, category, by).slice(0, limit);
  const max = Math.max(1, ...top.map((e) => value(e, by)));
  return h("div.card",
    h("div.card-title", title, seeAll(category)),
    top.length ? top.map((e, i) => h("div.hbar",
      h("span.rank", i + 1),
      h("span.name", { title: e.title }, e.title),
      h("span.track", h("span.fill", { style: { width: `${(value(e, by) / max) * 100}%`, display: "block" } })),
      h("span.num", amount(value(e, by), by, unit))))
      : h("p.muted", "No plays in this period."));
}

/** A short ranked list with artwork. */
function rows(title, category, entries, by, unit) {
  return h("div.card",
    h("div.card-title", title, seeAll(category)),
    entries.length ? h("div.mini-rows", entries.map((e, i) => h("div.mini-row",
      h("span.rank", i + 1),
      artBox(e.art, { fallback: category === "albums" ? "album" : "song", className: "mini-art" }),
      h("div.mini-text", h("b", { title: e.title }, e.title), e.subtitle && h("small", e.subtitle)),
      h("span.num", category === "skipped" ? plural(e.skips, "skip") : amount(value(e, by), by, unit)))))
      : h("p.muted", "Nothing here for this period."));
}

function covers(report, by) {
  const top = rankedCached(report, "albums", by).slice(0, 8);
  return h("div.card",
    h("div.card-title", "Top albums", seeAll("albums")),
    top.length ? h("div.cover-wall", top.map((e, i) => h("div.cover", { title: `${i + 1}. ${e.title}${e.subtitle ? ` · ${e.subtitle}` : ""}` },
      artBox(e.art, { fallback: "album" }), h("span.cover-rank", i + 1))))
      : h("p.muted", "No plays in this period."));
}

function discoveries(report) {
  const found = report.timeline.discoveries;
  return h("div.card",
    h("div.card-title", "Discoveries", h("span.muted", `${plural(found.artists, "new artist")}`)),
    h("div.mini-rows", found.top.map((a, i) => h("div.mini-row.no-art",
      h("span.rank", i + 1), h("div.mini-text", h("b", a.name)), h("span.num", plural(a.plays, "play"))))));
}

function invite() {
  return h("div.card.invite",
    h("span.invite-icon", icon("clock")),
    h("div",
      h("div.card-title", { style: { marginBottom: "4px" } }, "See when you listen"),
      h("p.muted", "Connect Last.fm or ListenBrainz, or import your Spotify history, to see your listening by hour and day, your streaks and the artists you discovered.")),
    h("button.btn", { onclick: () => state.openSetup({ start: "apps", cancellable: true }) }, icon("plus"), "Add a source"));
}

/** A column chart: items are {value, tick, title, peak, caption}. */
function columns(items, { values = null, compact = false, tall = false } = {}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return h(`div.columns${compact ? ".compact" : ""}${tall ? ".tall" : ""}`, { role: "img", "aria-label": items.map((i) => i.title).join(", ") },
    items.map((i) => h("div.column", { title: i.title },
      values && h("span.value", i.value ? values(i.value) : ""),
      h(`div.bar${i.peak ? "" : ".dim"}`, { style: { height: `${(i.value / max) * 100}%` } }),
      i.caption !== undefined && h("span.caption", i.caption || ""),
      h("span.tick", i.tick))));
}

const GENRE_COLORS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6"];

function genres(report, by) {
  const all = rankedCached(report, "genres", by);
  const total = all.reduce((sum, e) => sum + value(e, by), 0);
  const parts = all.slice(0, 6).map((e, i) => ({ title: e.title, value: value(e, by), color: `var(${GENRE_COLORS[i]})` }));
  const rest = total - parts.reduce((sum, p) => sum + p.value, 0);
  if (rest > 0) parts.push({ title: "Everything else", value: rest, color: "var(--chart-other)" });
  const pct = (v) => (total ? Math.round((v / total) * 100) : 0);
  return h("div.card",
    h("div.card-title", "Genres", h("span.muted", by === "time" ? "share of listening time" : "share of plays")),
    total ? [
      h("div.stack", { role: "img", "aria-label": parts.map((p) => `${p.title} ${pct(p.value)}%`).join(", ") },
        parts.map((p) => h("span", { title: `${p.title}: ${pct(p.value)}%`, style: { flex: `${p.value} 0 0`, background: p.color } }))),
      h("div.legend", parts.map((p) => h("div",
        h("i", { style: { background: p.color } }),
        h("span.name", { title: p.title }, p.title),
        h("span.pct", `${pct(p.value)}%`)))),
    ] : h("p.muted", "None of the songs played in this period have a genre."));
}

function decades(report, by, unit) {
  const buckets = new Map();
  for (const e of report.years) {
    const decade = Math.floor(Number(e.title) / 10) * 10;
    buckets.set(decade, (buckets.get(decade) || 0) + value(e, by));
  }
  const keys = [...buckets.keys()].sort((a, b) => a - b);
  const span = keys.length ? Array.from({ length: (keys.at(-1) - keys[0]) / 10 + 1 }, (_, i) => keys[0] + i * 10) : [];
  const max = Math.max(1, ...buckets.values());
  const peak = keys.reduce((a, b) => (buckets.get(b) > (buckets.get(a) || 0) ? b : a), keys[0]);
  return h("div.card",
    h("div.card-title", "Release decades", h("span.muted", "when the music you played came out")),
    h("div.columns", { role: "img", "aria-label": span.map((d) => `${d}s: ${amount(buckets.get(d) || 0, by, unit)}`).join(", ") },
      span.map((d) => {
        const v = buckets.get(d) || 0;
        return h("div.column",
          h("span.value", v ? amount(v, by, unit) : ""),
          h(`div.bar${d === peak ? "" : ".dim"}`, { style: { height: `${(v / max) * 100}%` }, title: `${d}s` }),
          h("span.tick", `'${String(d).slice(-2)}s`));
      })));
}

// ---------- listening age (opt-in) ----------

let ageJustShown = false; // pop the card in once after "Show it here"

/** A greyed teaser until it's been worked out on its own page, then a one-time question, then the age. */
function listeningAge(report) {
  const age = report.listening_age;
  const { age_calculated: calculated, age_overview: onOverview } = state.settings;
  if (!calculated) {
    return h("div.card.age-locked",
      h("div.card-title", "Listening age", h("span.age-lock", icon("age"), "Not worked out yet")),
      h("div.age",
        h("div.big", { "aria-hidden": "true" }, "??"),
        h("div",
          h("div", { style: { fontWeight: 700, fontSize: "17px" } }, "How old is your taste?"),
          h("p.muted", { style: { fontSize: "14px", margin: "4px 0 12px" } },
            "Find the era of music you keep coming back to, on its own page."),
          h("button.btn.btn-small", { onclick: () => navigate("age") }, "Work it out", icon("arrow")))));
  }
  if (onOverview == null) {
    const card = h("div.card.age-ask",
      h("div.card-title", "Listening age"),
      h("p", { style: { margin: "0 0 4px", fontWeight: 600 } }, "Show your listening age on the Overview?"),
      h("p.muted", { style: { fontSize: "14px", margin: "0 0 14px" } }, "You can change your mind on the Listening age page."),
      h("div.age-ask-actions",
        h("button.btn.btn-primary.btn-small", { onclick: () => chooseAge(card, true) }, "Show it here"),
        h("button.btn.btn-ghost.btn-small", { onclick: () => chooseAge(card, false) }, "Not on the Overview")));
    return card;
  }
  const pop = ageJustShown;
  ageJustShown = false;
  return h(`div.card.age-card${pop ? ".pop" : ""}`,
    h("div.card-title", "Listening age",
      h("div.age-card-actions",
        h("button.btn.btn-ghost.btn-small", { title: "Hide from the Overview", "aria-label": "Hide from the Overview",
          onclick: (e) => chooseAge(e.currentTarget.closest(".card"), false) }, icon("hidden")),
        age && h("button.btn.btn-ghost.btn-small", { onclick: () => navigate("age") }, "See how", icon("arrow")))),
    age ? h("div.age",
      h("div.big", age.age),
      h("div",
        h("div", { style: { fontWeight: 700, fontSize: "17px" } }, `Into the music of the ${age.era_label}`),
        h("p.muted", { style: { fontSize: "14px", marginTop: "4px" } },
          `You played the most music released between ${age.era_start} and ${age.era_end}. `
          + "Your listening age is how old you'd be if you were 18 in the middle of that era.")))
      : h("p.muted", "Needs release years on the songs you played."));
}

/** Keep or drop the card, letting it pop in or fold away (the tiles after it move up). */
export function chooseAge(card, show) {
  let finished = false;
  const done = () => { if (!finished) { finished = true; renderApp(); } };
  saveSettingsNow({ age_overview: show });
  ageJustShown = show;
  if (show || reducedMotion() || !card) return done();
  card.classList.add("folding");
  card.addEventListener("transitionend", done, { once: true });
  setTimeout(done, 400); // in case the transition doesn't run
  toast("Hidden from the Overview", { action: { label: "Undo", run: () => { saveSettingsNow({ age_overview: true }); renderApp(); } } });
}
