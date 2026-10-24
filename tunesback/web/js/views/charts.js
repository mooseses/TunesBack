import { state } from "../app.js";
import { h, icon, segmented } from "../util.js";
import { artBox, metricText, metricValue, rankedCached } from "./shared.js";

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
  const current = () => categories.find((c) => c.key === view.category);

  const list = h("div.rows");
  const filter = h("input.input", {
    type: "search", placeholder: "Filter…", value: view.filter, "aria-label": "Filter list",
    oninput: (e) => { view.filter = e.target.value; fill(list, current()); },
  });

  const tabs = categories.map((c) => {
    const tab = h("button.tab", { role: "tab", "aria-selected": String(c.key === view.category) },
      icon(c.icon), c.label, h("span.count", report[c.key].length));
    tab.addEventListener("click", () => {
      if (view.category === c.key) return;
      view.category = c.key;
      view.filter = filter.value = "";
      tabs.forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      fill(list, c, { swap: true });
    });
    return tab;
  });

  root.append(
    h("div.toolbar",
      h("div.tabs", { role: "tablist" }, tabs),
      h("div", { style: { display: "flex", gap: "10px", alignItems: "center" } },
        filter,
        segmented([[10, "10"], [25, "25"], [50, "50"], [100, "100"]], view.limit,
          (limit) => { view.limit = limit; fill(list, current()); }, "Rows to show"))),
    h("div.card.list-card", list));
  fill(list, current());
}

function fill(list, category, { swap = false } = {}) {
  const { unit, rank_by: by, show_art: showArt } = state.settings;
  const view = state.charts;
  const all = rankedCached(state.report, category.key, by);
  const needle = view.filter.trim().toLocaleLowerCase();
  const rows = needle
    ? all.map((e, i) => [e, i]).filter(([e]) => `${e.title} ${e.subtitle || ""}`.toLocaleLowerCase().includes(needle)).slice(0, view.limit)
    : all.slice(0, view.limit).map((e, i) => [e, i]);
  const max = Math.max(1, ...all.slice(0, 1).map((e) => metricValue(e, by, category.key)));
  const withArt = showArt && category.art;

  list.classList.toggle("no-art", !withArt);
  if (swap) {
    list.classList.remove("swap");
    void list.offsetWidth; // restart the animation
    list.classList.add("swap");
  }
  if (!rows.length) {
    list.replaceChildren(h("div.empty", needle ? "Nothing matches that filter." : emptyText(category.key)));
    return;
  }
  list.replaceChildren(...rows.map(([e, index]) => h("div.row",
    h("span.rank", index + 1),
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
