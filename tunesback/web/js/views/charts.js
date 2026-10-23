import { state } from "../app.js";
import { h, icon, segmented } from "../util.js";
import { artBox, metricText, metricValue, ranked } from "./shared.js";

const CATEGORIES = [
  { key: "songs", label: "Songs", icon: "song", art: true },
  { key: "albums", label: "Albums", icon: "album", art: true },
  { key: "artists", label: "Artists", icon: "artist", art: true, round: true },
  { key: "genres", label: "Genres", icon: "genre" },
  { key: "years", label: "Release years", icon: "year" },
  { key: "new_finds", label: "New finds", icon: "new", art: true, compareOnly: true },
  { key: "skipped", label: "Skipped", icon: "skip", art: true },
];

export function render(root) {
  const report = state.report;
  const view = state.charts;
  const categories = CATEGORIES.filter((c) => !c.compareOnly || report.mode === "compare");
  if (!categories.some((c) => c.key === view.category)) view.category = "songs";
  const category = categories.find((c) => c.key === view.category);

  const list = h("div.rows");
  const filter = h("input.input", {
    type: "search", placeholder: "Filter…", value: view.filter, "aria-label": "Filter list",
    oninput: (e) => { view.filter = e.target.value; fill(list, category); },
  });

  root.append(
    h("div.toolbar",
      h("div.tabs", { role: "tablist" }, categories.map((c) => h("button.tab", {
        role: "tab", "aria-selected": String(c.key === category.key),
        onclick: () => { view.category = c.key; view.filter = ""; root.replaceChildren(); render(root); },
      }, icon(c.icon), c.label, h("span.count", report[c.key].length)))),
      h("div", { style: { display: "flex", gap: "10px", alignItems: "center" } },
        filter,
        segmented([[10, "10"], [25, "25"], [50, "50"], [100, "100"]], view.limit,
          (limit) => { view.limit = limit; fill(list, category); }, "Rows to show"))),
    h("div.card", { style: { padding: "8px" } }, list));
  fill(list, category);
}

function fill(list, category) {
  const { unit, rank_by: by, show_art: showArt } = state.settings;
  const view = state.charts;
  const all = ranked(state.report[category.key], by, category.key);
  const needle = view.filter.trim().toLocaleLowerCase();
  const rows = (needle
    ? all.filter((e) => `${e.title} ${e.subtitle || ""}`.toLocaleLowerCase().includes(needle))
    : all).slice(0, view.limit);
  const max = Math.max(1, ...all.slice(0, 1).map((e) => metricValue(e, by, category.key)));
  const withArt = showArt && category.art;

  list.classList.toggle("no-art", !withArt);
  if (!rows.length) {
    list.replaceChildren(h("div.empty", needle ? "Nothing matches that filter." : emptyText(category.key)));
    return;
  }
  list.replaceChildren(...rows.map((e) => h("div.row",
    h("span.rank", all.indexOf(e) + 1),
    withArt && artBox(e.art, { round: category.round, fallback: category.icon }),
    h("div.text",
      h("div.title", { title: e.title }, e.title),
      e.subtitle && h("div.subtitle", { title: e.subtitle }, e.subtitle)),
    h("div.track", h("div.fill", { style: { width: `${(metricValue(e, by, category.key) / max) * 100}%` } })),
    h("div.metric", metricText(e, unit, category.key)))));
}

function emptyText(key) {
  return {
    new_finds: "No new songs were added and played in this period.",
    skipped: "Nothing was skipped in this period.",
    genres: "None of the songs played have a genre.",
    years: "None of the songs played have a release year.",
  }[key] || "No plays in this period.";
}
