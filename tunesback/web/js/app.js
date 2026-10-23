import { call, clearArtwork } from "./api.js";
import { h, icon, segmented, shortDate, showMessage, toast } from "./util.js";
import * as setup from "./views/setup.js";
import * as overview from "./views/overview.js";
import * as charts from "./views/charts.js";
import * as wrapped from "./views/wrapped.js";

const VIEWS = {
  setup: { module: setup, title: "Library", icon: "library", label: "Library" },
  overview: { module: overview, title: "Overview", icon: "overview", label: "Overview" },
  charts: { module: charts, title: "Top charts", icon: "charts", label: "Top charts" },
  wrapped: { module: wrapped, title: "Wrapped", icon: "wrapped", label: "Wrapped" },
};

export const state = {
  info: null,
  settings: {},
  folder: "",
  snapshots: [],
  mode: "compare",
  startId: null,
  endId: null,
  report: null,
  view: "setup",
  charts: { category: "songs", limit: 25, filter: "" },
  cards: null,
  selectedCards: new Set(),
};

const content = document.getElementById("content");

// ---------- navigation ----------

export function navigate(view) {
  if (view !== "setup" && !state.report) view = "setup";
  state.view = view;
  render();
}

export function render() {
  const view = VIEWS[state.view];
  document.getElementById("view-title").textContent = view.title;
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === state.view);
    if (item.dataset.view !== "setup") item.disabled = !state.report;
  });
  renderPeriodChip();
  renderTopbarActions();
  content.scrollTop = 0;
  content.replaceChildren();
  view.module.render(content);
}

function renderPeriodChip() {
  const chip = document.getElementById("period-chip");
  const report = state.report;
  chip.hidden = !report || state.view === "setup";
  if (!report) return;
  const text = report.mode === "compare"
    ? `${shortDate(report.start_date)} → ${shortDate(report.end_date)}`
    : `All time up to ${shortDate(report.end_date)}`;
  chip.replaceChildren(icon("calendar"), text);
}

function renderTopbarActions() {
  const actions = document.getElementById("topbar-actions");
  actions.replaceChildren();
  if (!state.report || state.view === "setup") return;
  if (state.view !== "wrapped") {
    actions.append(segmented([["hours", "Hours"], ["minutes", "Minutes"], ["days", "Days"]], state.settings.unit,
      (unit) => saveSettings({ unit }).then(render), "Time unit"));
  }
  actions.append(segmented([["plays", "By plays"], ["time", "By time"]], state.settings.rank_by,
    (rank_by) => { state.cards = null; saveSettings({ rank_by }).then(render); }, "Rank by"));
}

// ---------- settings ----------

export async function saveSettings(changes) {
  Object.assign(state.settings, changes);
  applyTheme();
  const result = await call("update_settings", { changes });
  if (result.settings) state.settings = result.settings;
  else if (result.error) toast(result.error, { error: true });
}

function applyTheme() {
  const theme = state.settings.theme;
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
}

function openSettings() {
  const dialog = document.getElementById("settings-dialog");
  const s = state.settings;
  const toggle = (key, title, desc) => h("label.switch.setting",
    h("div", h("div", { style: { fontWeight: 600 } }, title), desc && h("div.desc", desc)),
    h("input", { type: "checkbox", role: "switch", checked: s[key], onchange: (e) => saveSettings({ [key]: e.target.checked }).then(() => state.view === "charts" && render()) }));

  dialog.replaceChildren(
    h("div.dialog-head", h("h2", { id: "settings-title" }, "Settings"),
      h("button.btn.btn-ghost", { "aria-label": "Close", onclick: () => dialog.close() }, icon("close"))),
    h("div.dialog-body",
      h("div.setting", h("div", { style: { fontWeight: 600 } }, "Appearance"),
        segmented([["system", "System"], ["light", "Light"], ["dark", "Dark"]], s.theme, (theme) => saveSettings({ theme }), "Theme")),
      toggle("show_art", "Album artwork in lists", "Read from your music files. Can be slow on network drives."),
      toggle("debug_logging", "Detailed logging", "Writes extra detail to the log file to help track down problems."),
      h("div.setting", h("div", h("div", { style: { fontWeight: 600 } }, "Log files"), h("div.desc", state.info.log_dir)),
        h("button.btn", { onclick: async () => { const r = await call("open_logs"); if (r.error) toast(r.error, { error: true }); } }, "Open folder")),
      h("div.about", `TunesBack ${state.info.version} · `,
        h("a", { href: "https://github.com/mooseses/TunesBack", target: "_blank", rel: "noreferrer", style: { color: "inherit" } }, "github.com/mooseses/TunesBack")),
    ),
  );
  dialog.showModal();
}

// ---------- analysis ----------

const busy = document.getElementById("busy");
const busyText = document.getElementById("busy-text");

export function showBusy(text, onCancel) {
  busyText.textContent = text;
  const cancel = document.getElementById("busy-cancel");
  cancel.hidden = !onCancel;
  cancel.onclick = onCancel || null;
  busy.hidden = false;
}

export function hideBusy() {
  busy.hidden = true;
}

export async function runAnalysis() {
  const start = state.mode === "compare" ? state.startId : null;
  showBusy("Starting…", () => { busyText.textContent = "Cancelling…"; call("cancel"); });
  const poll = setInterval(async () => {
    const p = await call("progress");
    if (p.running && p.stage && !busy.hidden && busyText.textContent !== "Cancelling…") busyText.textContent = p.stage;
  }, 250);
  const result = await call("analyze", { end: state.endId, start });
  clearInterval(poll);
  hideBusy();

  if (result.error) return showMessage("Couldn't build your recap", result.error);
  if (result.cancelled) return toast("Cancelled");
  state.report = result.report;
  state.cards = null;
  state.selectedCards.clear();
  state.charts.filter = "";
  if (state.report.mode !== "compare" && state.charts.category === "new_finds") state.charts.category = "songs";
  clearArtwork();
  navigate("overview");
}

// ---------- start-up ----------

async function init() {
  for (const item of document.querySelectorAll(".nav-item[data-view]")) {
    const view = VIEWS[item.dataset.view];
    item.append(icon(view.icon), view.label);
    item.addEventListener("click", () => navigate(item.dataset.view));
  }
  const settingsButton = document.getElementById("open-settings");
  settingsButton.append(icon("settings"), "Settings");
  settingsButton.addEventListener("click", openSettings);
  document.getElementById("period-chip").addEventListener("click", () => navigate("setup"));

  const info = await call("state");
  if (info.error) return showMessage("TunesBack couldn't start", info.error);
  state.info = info;
  state.settings = info.settings;
  state.folder = info.settings.last_folder || "";
  applyTheme();
  render();
  if (state.folder) setup.scan(state.folder, { quiet: true });
}

init();
