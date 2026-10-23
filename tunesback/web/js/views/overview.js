import { navigate, state } from "../app.js";
import { duration, h, number, plural, unitInfo } from "../util.js";
import { artBox, rankedCached } from "./shared.js";

export function render(root) {
  const report = state.report;
  const { unit, rank_by: by } = state.settings;
  const compare = report.mode === "compare";

  root.append(
    h("div.grid.kpis",
      kpi("Listening time", duration(report.total_ms, unit), unitInfo(unit).long,
        compare ? "between the two snapshots" : "all time"),
      kpi(compare ? "New plays" : "Plays", number(report.total_plays), null, plural(report.songs.length, "song")),
      compare
        ? kpi("New finds", number(report.new_finds.length), null, "songs added and played")
        : kpi("Artists", number(report.artists.length), null, plural(report.albums.length, "album")),
      kpi("Skips", number(report.total_skips), null, report.skipped.length ? `across ${plural(report.skipped.length, "song")}` : "nothing skipped")),

    h("div.grid.highlights.section",
      highlight("Top artist", rankedCached(report, "artists", by)[0], { round: true, fallback: "artist" }),
      highlight("Top album", rankedCached(report, "albums", by)[0], { fallback: "album" }),
      highlight("Top song", rankedCached(report, "songs", by)[0], { fallback: "song" })),

    h("div.grid.charts.section",
      topArtists(report, by, unit),
      h("div.grid", { style: { alignContent: "start" } }, genres(report, by), listeningAge(report))),

    h("div.section", decades(report, by)),
  );
}

function kpi(label, value, unitText, sub) {
  return h("div.card.kpi",
    h("div.label", label),
    h("div.value", value, unitText && h("span.unit", unitText)),
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

function value(entry, by) {
  return by === "time" ? entry.ms : entry.plays;
}

function topArtists(report, by, unit) {
  const top = rankedCached(report, "artists", by).slice(0, 10);
  const max = Math.max(1, ...top.map((e) => value(e, by)));
  return h("div.card",
    h("div.card-title", "Top artists",
      h("button.btn.btn-ghost", { style: { height: "28px", padding: "0 8px", fontSize: "13px" },
        onclick: () => { state.charts.category = "artists"; navigate("charts"); } }, "See all")),
    top.length ? top.map((e, i) => h("div.hbar",
      h("span.rank", i + 1),
      h("span.name", { title: e.title }, e.title),
      h("span.track", h("span.fill", { style: { width: `${(value(e, by) / max) * 100}%`, display: "block" } })),
      h("span.num", by === "time" ? `${duration(e.ms, unit)} ${unitInfo(unit).short}` : number(e.plays))))
      : h("p.muted", "No plays in this period."));
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

function decades(report, by) {
  const buckets = new Map();
  for (const e of report.years) {
    const decade = Math.floor(Number(e.title) / 10) * 10;
    buckets.set(decade, (buckets.get(decade) || 0) + value(e, by));
  }
  const keys = [...buckets.keys()].sort((a, b) => a - b);
  const span = keys.length ? Array.from({ length: (keys.at(-1) - keys[0]) / 10 + 1 }, (_, i) => keys[0] + i * 10) : [];
  const max = Math.max(1, ...buckets.values());
  const peak = keys.reduce((a, b) => (buckets.get(b) > (buckets.get(a) || 0) ? b : a), keys[0]);
  const label = (v) => (by === "time" ? `${duration(v, state.settings.unit)} ${unitInfo(state.settings.unit).short}` : number(v));

  return h("div.card",
    h("div.card-title", "Release decades", h("span.muted", "when the music you played came out")),
    span.length ? h("div.columns", { role: "img", "aria-label": span.map((d) => `${d}s: ${label(buckets.get(d) || 0)}`).join(", ") },
      span.map((d) => {
        const v = buckets.get(d) || 0;
        return h("div.column",
          h("span.value", v ? label(v) : ""),
          h(`div.bar${d === peak ? "" : ".dim"}`, { style: { height: `${(v / max) * 100}%` }, title: `${d}s` }),
          h("span.tick", `'${String(d).slice(-2)}s`));
      }))
      : h("p.muted", "None of the songs played in this period have a release year."));
}

function listeningAge(report) {
  const age = report.listening_age;
  return h("div.card",
    h("div.card-title", "Listening age"),
    age ? h("div.age",
      h("div.big", age.age),
      h("div",
        h("div", { style: { fontWeight: 700, fontSize: "17px" } }, `Into the music of the ${age.era_label}`),
        h("p.muted", { style: { fontSize: "14px", marginTop: "4px" } },
          `You played the most music released between ${age.era_start} and ${age.era_end}. `
          + "Your listening age is how old you'd be if you were 18 in the middle of that era.")))
      : h("p.muted", "Needs release years on the songs you played."));
}
