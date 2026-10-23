// Library: the sources TunesBack reads, and the period to recap.
//
// Counter sources (iTunes) are compared between two readings. Sources that
// log every listen (Last.fm, ListenBrainz, Spotify) take any date range, and
// so does "All sources" when there's more than one.

import { call } from "../api.js";
import { navigate, render as renderApp, runAnalysis, saveSettings, state } from "../app.js";
import { confirmAction, h, icon, number, relativeTime, segmented, shortDate, toast } from "../util.js";

const showIds = () => !!state.settings.flags?.show_ids;
const KIND_ICONS = { itunes: "library", lastfm: "wave", listenbrainz: "wave", spotify: "download" };
const PRESETS = [
  ["this_year", "This year"], ["last_year", "Last year"], ["last_12", "Last 12 months"], ["all", "All time"], ["custom", "Custom"],
];

/** Reload sources and readings from the server. */
export async function loadLibrary() {
  const result = await call("library");
  if (result.error) return toast(result.error, { error: true });
  state.sources = result.sources;
  state.readings = result.readings;
  pickDefaults();
}

/** Read every library again and fetch new listens from online accounts. */
export async function refresh({ quiet = false } = {}) {
  const result = await call("refresh_readings");
  if (result.error) {
    if (!quiet) toast(result.error, { error: true });
    return result;
  }
  for (const problem of result.problems) toast(problem.error, { error: true, timeout: 6000 });
  if (!quiet && state.sources.some((s) => s.mode === "account")) {
    toast("Checking for new listens…");
    const synced = await sync({ quiet: true });
    if (synced.new) result.newListens = synced.new;
  }
  if (!quiet || result.new) {
    const parts = [];
    if (result.new) parts.push(`${result.new} new reading${result.new === 1 ? "" : "s"}`);
    if (result.newListens) parts.push(`${number(result.newListens)} new listens`);
    toast(parts.length ? `Got ${parts.join(" and ")}` : "Nothing new since last time");
  }
  await loadLibrary();
  return result;
}

/** Fetch new listens from Last.fm / ListenBrainz (all accounts, or one). */
export async function sync({ sourceId = null, quiet = false } = {}) {
  const result = await call("sync_sources", { source_id: sourceId, quiet });
  if (result.error) {
    toast(result.error, { error: true });
    return { new: 0 };
  }
  for (const problem of result.problems || []) toast(`${problem.source}: ${problem.error}`, { error: true, timeout: 7000 });
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

// ---------- choosing the period ----------

const recap = () => state.settings.recap || {};
const chosenSources = () => {
  const source = recap().source;
  if (source === undefined || source === "all") return state.sources;
  return state.sources.filter((s) => s.id === source);
};
/** Only counter sources picked: compare readings rather than dates. */
export const usesReadings = () => chosenSources().length > 0 && chosenSources().every((s) => s.counter);

function setRecap(changes) {
  saveSettings({ recap: { ...recap(), ...changes } });
}

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The dates a preset stands for: {start, end} as YYYY-MM-DD (start null for all time). */
export function presetRange(preset) {
  const today = new Date();
  const year = today.getFullYear();
  switch (preset) {
    case "last_year": return { start: `${year - 1}-01-01`, end: `${year - 1}-12-31` };
    case "last_12": {
      const start = new Date(today);
      start.setFullYear(year - 1);
      start.setDate(start.getDate() + 1);
      return { start: iso(start), end: iso(today) };
    }
    case "all": return { start: null, end: null };
    case "custom": return { start: recap().start || `${year}-01-01`, end: recap().end || iso(today) };
    default: return { start: `${year}-01-01`, end: `${year}-12-31` };
  }
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
  // A source that was removed falls back to all of them; early in a year, last year is the better default.
  const r = recap();
  if (r.source !== undefined && r.source !== "all" && !state.sources.some((s) => s.id === r.source)) setRecap({ source: "all" });
  if (!r.preset) setRecap({ preset: defaultPreset() });
}

/** This year once it has a couple of months in it, else last year; all time if the listens are older still. */
function defaultPreset() {
  const today = new Date();
  const early = today.getMonth() < 2;
  const lastPlays = state.sources.filter((s) => !s.counter && s.last_play).map((s) => s.last_play * 1000);
  if (!lastPlays.length) return early ? "last_year" : "this_year";
  const newest = new Date(Math.max(...lastPlays)).getFullYear();
  if (newest === today.getFullYear() && !early) return "this_year";
  return newest >= today.getFullYear() - 1 ? "last_year" : "all";
}

export function canGenerate() {
  if (!state.sources.length) return false;
  if (usesReadings()) {
    const readings = readingsFor(chosenSources());
    if (state.mode === "compare") return !!state.startId && !!state.endId && state.startId !== state.endId;
    return !!state.endId && readings.some((r) => r.id === state.endId);
  }
  return true;
}

/** What analyze() needs for the current choice. */
export function analysisRequest() {
  if (usesReadings()) return { end: state.endId, start: state.mode === "compare" ? state.startId : null };
  const r = recap();
  return {
    sources: chosenSources().map((s) => s.id),
    period: presetRange(r.preset || "this_year"),
    combine: r.combine === "separate" ? "separate" : "same",
  };
}

const readingsFor = (sources) => state.readings.filter((r) => sources.some((s) => s.id === r.source_id));

// ---------- the page ----------

export function render(root) {
  root.append(h("div.setup",
    sourcesCard(),
    state.sources.length > 0 && periodCard(),
    readingsFor(state.sources).length > 0 && readingsCard()));
}

function sourceStats(s) {
  if (s.counter) {
    return [`${s.reading_count} reading${s.reading_count === 1 ? "" : "s"}`,
      s.last_reading ? ` · last read ${relativeTime(s.last_reading + "Z")}` : "",
      s.location === "network" ? " · network drive" : ""];
  }
  const since = s.first_play ? ` since ${shortDate(new Date(s.first_play * 1000).toISOString())}` : "";
  return [`${number(s.play_count || 0)} listens${since}`,
    s.mode === "account" && !s.complete ? " · still importing older listens" : "",
    s.mode === "account" && s.last_play ? ` · newest ${relativeTime(new Date(s.last_play * 1000).toISOString())}` : ""];
}

function sourcesCard() {
  const label = (s) => s.kind === "itunes" ? (s.mode === "folder" ? "iTunes exports" : "iTunes library") : s.name;
  const detail = (s) => s.mode === "account" ? `@${s.path}` : s.path;
  return h("div.card",
    h("div.card-title", "Your music",
      h("div", { style: { display: "flex", gap: "8px" } },
        state.info.desktop && state.sources.some((s) => s.kind === "itunes") &&
          h("button.btn", { onclick: importExports }, icon("calendar"), "Import exports"),
        h("button.btn", { onclick: () => state.openSetup({ start: "apps", cancellable: true }) }, icon("plus"), "Add source"))),
    state.sources.length
      ? h("div.source-list", state.sources.map((s) => h("div.source-row",
        h(`span.source-icon.kind-${s.kind}`, icon(KIND_ICONS[s.kind] || "song")),
        h("div.source-text",
          h("b", label(s)),
          h("small", { title: s.path }, detail(s)),
          h("small", sourceStats(s), showIds() && ` · source #${s.id}`)),
        s.counter && h("button.btn.btn-ghost", { onclick: () => refresh().then(() => renderApp()) }, icon("refresh"), "Read now"),
        !s.counter && h("button.btn.btn-ghost", { onclick: () => navigate("services") }, icon("cloud"), "Manage"),
        s.counter && h("button.btn.btn-ghost", {
          onclick: async () => {
            const ok = await confirmAction(`Remove ${label(s)}?`,
              `TunesBack will stop reading ${s.path} and forget its readings. Your music and the file itself aren't touched.`, "Remove");
            if (!ok) return;
            const r = await call("remove_library", { source_id: s.id });
            if (r.error) return toast(r.error, { error: true });
            state.sources = r.sources; state.readings = r.readings; pickDefaults();
            if (!state.sources.length) state.openSetup({ start: "welcome" }); else renderApp();
          },
        }, "Remove"))))
      : h("div.empty", "Nothing here yet. Add your iTunes library, Last.fm, ListenBrainz or Spotify history."));
}

function periodCard() {
  const sources = state.sources;
  const r = recap();
  const many = sources.length > 1;
  const sourceSelect = many && h("div.field",
    h("label", { for: "select-source" }, "Source"),
    h("select.select", {
      id: "select-source",
      onchange: (e) => { setRecap({ source: e.target.value === "all" ? "all" : Number(e.target.value) }); renderApp(); },
    },
      h("option", { value: "all", selected: r.source === undefined || r.source === "all" }, "All sources"),
      sources.map((s) => h("option", { value: s.id, selected: r.source === s.id }, s.kind === "itunes" ? "iTunes" : s.name))));

  const body = usesReadings() ? readingsPeriod() : datesPeriod();
  return h("div.card",
    h("div.mode-row", h("div.card-title", { style: { margin: 0 } }, "Recap"), body.toggle),
    body.note,
    h("div.period-grid", sourceSelect, body.fields),
    !usesReadings() && chosenSources().length > 1 && combineChoice(),
    h("div", { style: { marginTop: "20px" } },
      h("button.btn.btn-primary.btn-large.btn-block", { disabled: !canGenerate(), onclick: runAnalysis }, "Generate recap")));
}

/** Period by readings (iTunes): compare two of them, or lifetime totals up to one. */
function readingsPeriod() {
  const readings = readingsFor(chosenSources());
  const canCompare = readings.length > 1;
  if (!canCompare) state.mode = "single";
  if (!readings.some((x) => x.id === state.endId)) state.endId = readings.at(-1)?.id ?? null;
  const label = (x) => `${shortDate(x.date)} · ${number(x.total_plays)} plays`;
  const select = (title, key, options) => h("div.field",
    h("label", { for: `select-${key}` }, title),
    h("select.select", {
      id: `select-${key}`, disabled: !options.length,
      onchange: (e) => { state[key] = Number(e.target.value); keepOrdered(key, readings); renderApp(); },
    }, options.map((x) => h("option", { value: x.id, selected: x.id === state[key] }, label(x)))));

  const endIndex = readings.findIndex((x) => x.id === state.endId);
  const startIndex = readings.findIndex((x) => x.id === state.startId);
  const fields = state.mode === "compare"
    ? [select("From", "startId", readings.slice(0, Math.max(endIndex, 1))), select("To", "endId", readings.slice(startIndex + 1))]
    : [select("Up to", "endId", readings), h("p.hint", { style: { alignSelf: "end" } }, "Lifetime totals up to this reading.")];
  const toggle = segmented([["compare", "Compare two readings"], ["single", "Lifetime"]], state.mode,
    (value) => { state.mode = value; renderApp(); }, "Mode");
  toggle.querySelector("button").disabled = !canCompare;
  return {
    toggle,
    fields,
    note: !canCompare && h("p.hint", "Comparisons unlock after the next reading. TunesBack reads your library each time you open it, or import older exports now."),
  };
}

/** Period by dates (sources that log every listen, or all sources together). */
function datesPeriod() {
  const r = recap();
  const preset = r.preset || "this_year";
  const range = presetRange(preset);
  const toggle = segmented(PRESETS, preset, (value) => {
    const changes = { preset: value };
    if (value === "custom") Object.assign(changes, presetRange(preset).start ? presetRange(preset) : presetRange("this_year"));
    setRecap(changes);
    renderApp();
  }, "Period");
  const dateField = (title, key) => h("div.field",
    h("label", { for: `date-${key}` }, title),
    h("input.input", {
      id: `date-${key}`, type: "date", value: range[key] || "", max: iso(new Date()),
      onchange: (e) => setRecap({ [key]: e.target.value }),
    }));
  const counterIncluded = chosenSources().some((s) => s.counter);
  return {
    toggle,
    fields: preset === "custom"
      ? [dateField("From", "start"), dateField("To", "end")]
      : h("p.hint", { style: { alignSelf: "end" } }, range.start
        ? `${shortDate(range.start)} to ${shortDate(range.end)}.`
        : "Everything TunesBack has."),
    note: counterIncluded && h("p.hint", "iTunes counts come from the readings closest to the start and end of the period."),
  };
}

function combineChoice() {
  const r = recap();
  return h("div.combine",
    h("div",
      h("div", { style: { fontWeight: 600 } }, "Do these sources record the same listening?"),
      h("p.hint", { style: { marginTop: "2px" } }, r.combine === "separate"
        ? "Separate: for example your phone and your computer. Plays add up."
        : "Same: for example iTunes scrobbling to Last.fm. Each song counts once, using the higher number.")),
    segmented([["same", "Same"], ["separate", "Separate"]], r.combine === "separate" ? "separate" : "same",
      (value) => { setRecap({ combine: value }); renderApp(); }, "Combine sources"));
}

/** After one end of the period changes, keep "From" earlier than "To". */
function keepOrdered(changed, readings) {
  const ids = readings.map((x) => x.id);
  const start = ids.indexOf(state.startId);
  const end = ids.indexOf(state.endId);
  if (start >= 0 && end >= 0 && start >= end) {
    if (changed === "startId") state.endId = ids[start + 1] ?? state.endId;
    else state.startId = ids[end - 1] ?? state.startId;
  }
}

function readingsCard() {
  const readings = readingsFor(state.sources);
  return h("div.card",
    h("div.card-title", "iTunes readings", h("span.muted", "each one is your library at a point in time")),
    h("div.snapshot-list", { role: "list" }, [...readings].reverse().map((x) => h("div.snapshot-row", { role: "listitem" },
      h("span.date", shortDate(x.date)),
      h("span.file", `${number(x.track_count)} songs · ${number(x.total_plays)} plays`,
        h("span.badge", x.origin === "imported" ? "imported" : "automatic"), showIds() && h("span.badge", `#${x.id}`)),
      h("span.meta", { title: x.file_path }, x.mode === "folder" ? "exports" : "library")))));
}
