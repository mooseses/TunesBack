import { cachedArtwork, paintArtwork, requestArtwork } from "../api.js";
import { duration, h, icon, number, unitInfo } from "../util.js";

export function ranked(entries, by, category) {
  const list = [...entries];
  if (category === "skipped") return list.sort((a, b) => b.skips - a.skips || a.title.localeCompare(b.title));
  const [first, second] = by === "time" ? ["ms", "plays"] : ["plays", "ms"];
  return list.sort((a, b) => b[first] - a[first] || b[second] - a[second] || a.title.localeCompare(b.title));
}

export function metricValue(entry, by, category) {
  if (category === "skipped") return entry.skips;
  return by === "time" ? entry.ms : entry.plays;
}

export function metricText(entry, unit, category) {
  if (category === "skipped") return [h("b", number(entry.skips)), h("span", entry.skips === 1 ? " skip" : " skips")];
  return [h("b", duration(entry.ms, unit)), h("span", ` ${unitInfo(unit).short} · ${number(entry.plays)} plays`)];
}

const observer = new IntersectionObserver((items) => {
  for (const item of items) {
    if (!item.isIntersecting) continue;
    observer.unobserve(item.target);
    requestArtwork(item.target.dataset.location, item.target);
  }
}, { root: document.getElementById("content"), rootMargin: "300px 0px" });

/** A square (or round) artwork tile that loads when it scrolls into view. */
export function artBox(location, { round = false, fallback = "album", className = "" } = {}) {
  const box = h(`div.art${round ? ".round" : ""}${className ? "." + className : ""}`, { "aria-hidden": "true" }, icon(fallback));
  if (!location) return box;
  const cached = cachedArtwork(location);
  if (cached) paintArtwork(box, cached, false);
  else if (cached === undefined) {
    box.dataset.location = location;
    observer.observe(box);
  }
  return box;
}

/** Rankings are sorted once per report, category and ranking, then reused. */
const rankCache = new WeakMap();

export function rankedCached(report, category, by) {
  if (!rankCache.has(report)) rankCache.set(report, new Map());
  const cache = rankCache.get(report);
  const key = `${category}|${by}`;
  if (!cache.has(key)) cache.set(key, ranked(report[category], by, category));
  return cache.get(key);
}
