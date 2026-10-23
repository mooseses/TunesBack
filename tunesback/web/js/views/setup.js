// Library: the libraries TunesBack reads, the readings it has taken, and the
// period to recap.

import { call } from "../api.js";
import { render as renderApp, runAnalysis, state } from "../app.js";
import { confirmAction, h, icon, number, relativeTime, segmented, shortDate, toast } from "../util.js";

/** Reload sources and readings from the server. */
export async function loadLibrary() {
  const result = await call("library");
  if (result.error) return toast(result.error, { error: true });
  state.sources = result.sources;
  state.readings = result.readings;
  pickDefaults();
}

/** Take a new reading of every library that changed. */
export async function refresh({ quiet = false } = {}) {
  const result = await call("refresh_readings");
  if (result.error) {
    if (!quiet) toast(result.error, { error: true });
    return result;
  }
  for (const problem of result.problems) toast(problem.error, { error: true, timeout: 6000 });
  if (!quiet || result.new) toast(result.new ? `Took ${result.new} new reading${result.new === 1 ? "" : "s"}` : "Your library hasn't changed since the last reading");
  await loadLibrary();
  return result;
}

export async function importExports() {
  const picked = await call("pick_folder");
  if (!picked.path) return;
  const result = await call("import_exports", { folder: picked.path });
  if (result.error) return toast(result.error, { error: true });
  toast(`Added ${result.imported} reading${result.imported === 1 ? "" : "s"}`);
  await loadLibrary();
  if (state.view === "setup") renderApp();
}

/** Default period: the newest reading, compared with the one closest to a year before it. */
function pickDefaults() {
  const ids = state.readings.map((r) => r.id);
  if (!ids.includes(state.endId)) state.endId = ids.at(-1) ?? null;
  if (!ids.includes(state.startId) || state.startId === state.endId) {
    const end = state.readings.find((r) => r.id === state.endId);
    const earlier = end ? state.readings.filter((r) => r.date < end.date) : [];
    if (earlier.length) {
      const target = new Date(end.date);
      target.setUTCFullYear(target.getUTCFullYear() - 1);
      state.startId = earlier.reduce((a, b) =>
        Math.abs(new Date(b.date) - target) < Math.abs(new Date(a.date) - target) ? b : a).id;
    } else {
      state.startId = null;
    }
  }
  if (state.readings.length < 2) state.mode = "single";
}

export function canGenerate() {
  if (state.mode === "compare") return !!state.startId && !!state.endId && state.startId !== state.endId;
  return !!state.endId;
}

export function render(root) {
  root.append(h("div.setup",
    sourcesCard(),
    state.readings.length > 0 && periodCard(),
    state.readings.length > 0 && readingsCard()));
}

function sourcesCard() {
  return h("div.card",
    h("div.card-title", "Your libraries",
      h("div", { style: { display: "flex", gap: "8px" } },
        state.info.desktop && h("button.btn", { onclick: importExports }, icon("calendar"), "Import exports"),
        h("button.btn", { onclick: () => state.openSetup({ start: "apps", cancellable: true }) }, icon("library"), "Add library"))),
    state.sources.length
      ? h("div.source-list", state.sources.map((s) => h("div.source-row",
        h("span.source-icon", icon(s.mode === "folder" ? "folder" : "song")),
        h("div.source-text",
          h("b", s.mode === "folder" ? "Folder of exports" : "iTunes library"),
          h("small", { title: s.path }, s.path),
          h("small", `${s.reading_count} reading${s.reading_count === 1 ? "" : "s"}`,
            s.last_reading ? ` · last read ${relativeTime(s.last_reading + "Z")}` : "",
            s.location === "network" ? " · network drive" : "")),
        h("button.btn.btn-ghost", { onclick: () => refresh() }, icon("refresh"), "Read now"),
        h("button.btn.btn-ghost", {
          onclick: async () => {
            const ok = await confirmAction("Remove this library?",
              `TunesBack will stop reading ${s.path} and forget its readings. Your music and the file itself aren't touched.`, "Remove");
            if (!ok) return;
            const r = await call("remove_library", { source_id: s.id });
            if (r.error) return toast(r.error, { error: true });
            state.sources = r.sources; state.readings = r.readings; pickDefaults();
            if (!state.sources.length) state.openSetup({ start: "welcome" }); else renderApp();
          },
        }, "Remove"))))
      : h("div.empty", "No libraries yet."));
}

function periodCard() {
  const readings = state.readings;
  const canCompare = readings.length > 1;
  if (!canCompare) state.mode = "single";
  const label = (r) => `${shortDate(r.date)} · ${number(r.total_plays)} plays`;

  const select = (title, key, options) => h("div.field",
    h("label", { for: `select-${key}` }, title),
    h("select.select", {
      id: `select-${key}`, disabled: !options.length,
      onchange: (e) => { state[key] = Number(e.target.value); keepOrdered(key); renderApp(); },
    }, options.map((r) => h("option", { value: r.id, selected: r.id === state[key] }, label(r)))));

  const endIndex = readings.findIndex((r) => r.id === state.endId);
  const startIndex = readings.findIndex((r) => r.id === state.startId);
  const fields = state.mode === "compare"
    ? [select("From", "startId", readings.slice(0, Math.max(endIndex, 1))), select("To", "endId", readings.slice(startIndex + 1))]
    : [select("Up to", "endId", readings), h("p.hint", { style: { alignSelf: "end" } }, "Lifetime totals up to this reading.")];

  const mode = segmented([["compare", "Compare two readings"], ["single", "Lifetime"]], state.mode,
    (value) => { state.mode = value; renderApp(); }, "Mode");
  mode.querySelector("button").disabled = !canCompare;

  return h("div.card",
    h("div.mode-row", h("div.card-title", { style: { margin: 0 } }, "Recap"), mode),
    !canCompare && h("p.hint", "Comparisons unlock after the next reading. TunesBack reads your library each time you open it, or import older exports now."),
    h("div.period-grid", fields),
    h("div", { style: { marginTop: "20px" } },
      h("button.btn.btn-primary.btn-large.btn-block", { disabled: !canGenerate(), onclick: runAnalysis }, "Generate recap")));
}

/** After one end of the period changes, keep "From" earlier than "To". */
function keepOrdered(changed) {
  const ids = state.readings.map((r) => r.id);
  const start = ids.indexOf(state.startId);
  const end = ids.indexOf(state.endId);
  if (start >= 0 && end >= 0 && start >= end) {
    if (changed === "startId") state.endId = ids[start + 1] ?? state.endId;
    else state.startId = ids[end - 1] ?? state.startId;
  }
}

function readingsCard() {
  return h("div.card",
    h("div.card-title", "Readings", h("span.muted", "each one is your library at a point in time")),
    h("div.snapshot-list", { role: "list" }, [...state.readings].reverse().map((r) => h("div.snapshot-row", { role: "listitem" },
      h("span.date", shortDate(r.date)),
      h("span.file", `${number(r.track_count)} songs · ${number(r.total_plays)} plays`,
        h("span.badge", r.origin === "imported" ? "imported" : "automatic")),
      h("span.meta", { title: r.file_path }, r.kind === "itunes" ? "iTunes" : r.kind)))));
}
