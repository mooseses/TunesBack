import { artwork } from "../api.js";
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
    const box = item.target;
    artwork(box.dataset.location).then((uri) => {
      if (uri) {
        box.style.backgroundImage = `url("${uri}")`;
        box.classList.add("loaded");
      }
    });
  }
}, { rootMargin: "200px" });

/** A square (or round) artwork tile that loads when it scrolls into view. */
export function artBox(location, { round = false, fallback = "album", className = "" } = {}) {
  const box = h(`div.art${round ? ".round" : ""}${className ? "." + className : ""}`, { "aria-hidden": "true" }, icon(fallback));
  if (location) {
    box.dataset.location = location;
    observer.observe(box);
  }
  return box;
}
