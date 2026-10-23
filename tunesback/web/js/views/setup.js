import { call } from "../api.js";
import { render as renderApp, runAnalysis, state } from "../app.js";
import { fileSize, h, icon, segmented, shortDate, toast } from "../util.js";

const DATE_SOURCE = { filename: "date from file name", modified: "date from file" };

export async function scan(folder, { quiet = false } = {}) {
  folder = folder.trim();
  if (!folder) return;
  const result = await call("scan", { folder });
  if (result.error) {
    if (!quiet) toast(result.error, { error: true });
    state.snapshots = [];
  } else {
    if (result.folder !== state.folder || !state.snapshots.length) state.mode = result.snapshots.length > 1 ? "compare" : "single";
    state.folder = result.folder;
    state.snapshots = result.snapshots;
    pickDefaults();
  }
  if (state.view === "setup") renderApp();
}

export async function browse() {
  const result = await call("pick_folder");
  if (result.path) scan(result.path);
}

export function canGenerate() {
  if (state.mode === "compare") return state.snapshots.length > 1 && !!state.startId && !!state.endId && state.startId !== state.endId;
  return !!state.endId;
}

function pickDefaults() {
  const ids = state.snapshots.map((s) => s.id);
  if (!ids.includes(state.endId)) state.endId = ids.at(-1) ?? null;
  if (!ids.includes(state.startId) || state.startId === state.endId) state.startId = ids.length > 1 ? ids.at(-2) : null;
  // Default to a year-long window when one exists.
  if (ids.length > 2 && state.startId === ids.at(-2)) {
    const end = new Date(state.snapshots.at(-1).date);
    const target = new Date(end); target.setUTCFullYear(end.getUTCFullYear() - 1);
    const best = state.snapshots.slice(0, -1).reduce((a, b) =>
      Math.abs(new Date(b.date) - target) < Math.abs(new Date(a.date) - target) ? b : a);
    state.startId = best.id;
  }
}

export function render(root) {
  const desktop = state.info?.desktop;
  const pathInput = h("input.input", {
    type: "text", value: state.folder, placeholder: desktop ? "Choose a folder…" : "Paste the folder path, e.g. ~/Music/Snapshots",
    "aria-label": "Snapshot folder", spellcheck: "false",
    onkeydown: (e) => { if (e.key === "Enter") scan(e.target.value); },
  });

  const folderRow = h("div.folder-row", pathInput,
    desktop && h("button.btn", { onclick: browse }, icon("folder"), "Browse…"),
    h("button.btn", { onclick: () => scan(pathInput.value) }, icon("refresh"), "Scan"));

  root.append(h("div.setup",
    h("div.setup-intro",
      h("h2", "Your listening, recapped"),
      h("p.muted", "TunesBack reads library exports from iTunes or Apple Music. Compare two exports to see what you listened to in between.")),
    h("div.card",
      h("div.card-title", "1. Snapshot folder"),
      folderRow,
      h("p.hint", "In iTunes or Music choose File → Library → Export Library, and save it in this folder. Export again later to compare."),
      snapshotList()),
    state.snapshots.length > 0 && periodCard()));
}

function snapshotList() {
  if (!state.folder) return null;
  if (!state.snapshots.length) {
    return h("div.snapshot-list", h("div.empty", "No library exports found in this folder."));
  }
  return h("div.snapshot-list", { role: "list" }, [...state.snapshots].reverse().map((s) =>
    h("div.snapshot-row", { role: "listitem" },
      h("span.date", shortDate(s.date)),
      h("span.file", { title: s.file }, s.file, DATE_SOURCE[s.date_source] && h("span.badge", DATE_SOURCE[s.date_source])),
      h("span.meta", fileSize(s.size)))));
}

/** After one end of the period changes, keep "From" earlier than "To". */
function keepOrdered(changed) {
  const ids = state.snapshots.map((s) => s.id);
  const start = ids.indexOf(state.startId);
  const end = ids.indexOf(state.endId);
  if (start >= 0 && end >= 0 && start >= end) {
    if (changed === "startId") state.endId = ids[start + 1] ?? state.endId;
    else state.startId = ids[end - 1] ?? state.startId;
  }
}

function periodCard() {
  const snapshots = state.snapshots;
  const canCompare = snapshots.length > 1;
  if (!canCompare) state.mode = "single";
  const ready = canGenerate();

  const select = (label, key, options) => h("div.field",
    h("label", { for: `select-${key}` }, label),
    h("select.select", {
      id: `select-${key}`,
      disabled: !options.length,
      onchange: (e) => { state[key] = e.target.value; keepOrdered(key); renderApp(); },
    }, options.map((s) => h("option", { value: s.id, selected: s.id === state[key] }, `${shortDate(s.date)} · ${s.file}`))));

  const endIndex = snapshots.findIndex((s) => s.id === state.endId);
  const startIndex = snapshots.findIndex((s) => s.id === state.startId);
  const fields = state.mode === "compare"
    ? [select("From", "startId", snapshots.slice(0, Math.max(endIndex, 1))),
       select("To", "endId", snapshots.slice(startIndex + 1))]
    : [select("Snapshot", "endId", snapshots), h("p.hint", { style: { alignSelf: "end" } }, "Shows lifetime totals up to this export.")];

  const mode = segmented([["compare", "Compare two snapshots"], ["single", "Single snapshot"]], state.mode,
    (value) => { state.mode = value; renderApp(); }, "Mode");
  mode.querySelector("button").disabled = !canCompare;

  return h("div.card",
    h("div.mode-row", h("div.card-title", { style: { margin: 0 } }, "2. Period"), mode),
    !canCompare && snapshots.length === 1 && h("p.hint", "Add a second export to compare two points in time."),
    h("div.period-grid", fields),
    h("div", { style: { marginTop: "20px" } },
      h("button.btn.btn-primary.btn-large.btn-block", { disabled: !ready, onclick: runAnalysis }, "Generate recap")));
}
