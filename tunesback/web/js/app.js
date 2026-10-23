import { call } from "./api.js";
import { h, icon, segmented, shortDate, showMessage, toast } from "./util.js";
import { initWindow } from "./window.js";
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
  if (view === state.view && content.childElementCount) return;
  state.view = view;
  render({ entering: true });
}

/**
 * Redraw the current view. Pass `entering` when switching views: that resets
 * the scroll position and plays the enter transition. Redraws within a view
 * (unit, ranking...) keep the scroll position so nothing jumps.
 */
export function render({ entering = false } = {}) {
  const view = VIEWS[state.view];
  document.getElementById("view-title").textContent = view.title;
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === state.view);
    item.setAttribute("aria-current", item.dataset.view === state.view ? "page" : "false");
    if (item.dataset.view !== "setup") item.disabled = !state.report;
  });
  renderPeriodChip();
  renderTopbarActions();

  const scrollTop = entering ? 0 : content.scrollTop;
  const focusedId = !entering && content.contains(document.activeElement) ? document.activeElement.id : null;
  const page = h("div.page");
  view.module.render(page);
  content.replaceChildren(page);
  content.scrollTop = scrollTop;
  if (focusedId) document.getElementById(focusedId)?.focus({ preventScroll: true });
  if (entering) {
    page.classList.add("entering");
    page.addEventListener("animationend", () => page.classList.remove("entering"), { once: true });
  }
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
      (unit) => { saveSettings({ unit }); render(); }, "Time unit"));
  }
  actions.append(segmented([["plays", "By plays"], ["time", "By time"]], state.settings.rank_by,
    (rank_by) => { state.cards = null; saveSettings({ rank_by }); render(); }, "Rank by"));
}

// ---------- settings ----------

// Settings take effect immediately; saving to disk happens in the background
// so the interface never waits on it.
let pendingSettings = {};
let saveTimer = null;

export function saveSettings(changes) {
  Object.assign(state.settings, changes);
  Object.assign(pendingSettings, changes);
  applyTheme();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const batch = pendingSettings;
    pendingSettings = {};
    const result = await call("update_settings", { changes: batch });
    if (result.error) toast(result.error, { error: true });
  }, 250);
}

function applyTheme() {
  const theme = state.settings.theme;
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
}

export function openSettings() {
  const dialog = document.getElementById("settings-dialog");
  const s = state.settings;
  const toggle = (key, title, desc) => h("label.switch.setting",
    h("div", h("div", { style: { fontWeight: 600 } }, title), desc && h("div.desc", desc)),
    h("input", { type: "checkbox", role: "switch", checked: s[key], onchange: (e) => { saveSettings({ [key]: e.target.checked }); if (state.view === "charts") render(); } }));

  dialog.replaceChildren(
    h("div.dialog-head", h("h2", { id: "settings-title", tabindex: "-1", autofocus: true }, "Settings"),
      h("button.btn.btn-ghost", { "aria-label": "Close", onclick: () => dialog.close() }, icon("close"))),
    h("div.dialog-body",
      h("div.setting", h("div", { style: { fontWeight: 600 } }, "Appearance"),
        segmented([["system", "System"], ["light", "Light"], ["dark", "Dark"]], s.theme, (theme) => saveSettings({ theme }), "Theme")),
      state.info.desktop && titleBarSetting(),
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

function titleBarSetting() {
  const running = state.info.window?.custom_title_bar ? "custom" : "native";
  const note = h("div.setting-note", { hidden: state.settings.title_bar === running },
    h("span", "Restart TunesBack to switch title bars."),
    h("button.btn", { onclick: () => call("restart") }, "Restart now"));
  return h("div",
    h("div.setting",
      h("div", h("div", { style: { fontWeight: 600 } }, "Title bar"),
        h("div.desc", "TunesBack's own title bar, or your system's.")),
      segmented([["custom", "TunesBack"], ["native", "System"]], state.settings.title_bar, (title_bar) => {
        saveSettings({ title_bar });
        note.hidden = title_bar === running;
      }, "Title bar")),
    note);
}

// ---------- commands (menu bar and keyboard shortcuts) ----------

export function runCommand(id) {
  const [kind, arg] = id.split(":");
  switch (kind) {
    case "open_folder":
      navigate("setup");
      if (state.info.desktop) setup.browse();
      else document.querySelector("input[aria-label='Snapshot folder']")?.focus();
      break;
    case "generate":
      if (setup.canGenerate()) runAnalysis();
      break;
    case "save_cards":
      navigate("wrapped");
      if (state.cards) wrapped.save(null);
      else toast("Generate the cards first");
      break;
    case "settings": openSettings(); break;
    case "quit": call("window_close"); break;
    case "view": navigate(arg); break;
    case "rank": state.cards = null; saveSettings({ rank_by: arg }); render(); break;
    case "unit": saveSettings({ unit: arg }); render(); break;
    case "theme": saveSettings({ theme: arg }); break;
    case "open_logs": call("open_logs").then((r) => r.error && toast(r.error, { error: true })); break;
    case "website":
      if (state.info.desktop) call("open_website");
      else window.open("https://github.com/mooseses/TunesBack", "_blank", "noreferrer");
      break;
    case "about":
      showMessage("About TunesBack", `Version ${state.info.version}. Year-in-review statistics for your music library.`);
      break;
  }
}

const commandHooks = {
  run: runCommand,
  isChecked: (item) => {
    const [, value] = item.command.split(":");
    return state.settings[item.group] === value;
  },
  isEnabled: (command) => {
    const [kind, arg] = command.split(":");
    if (kind === "view") return arg === "setup" || !!state.report;
    if (kind === "generate") return setup.canGenerate();
    if (kind === "save_cards") return !!state.report;
    return true;
  },
};

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
  state.view = "overview";
  render({ entering: true });
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
  initWindow(info.window, commandHooks);
  state.folder = info.settings.last_folder || "";
  applyTheme();
  render({ entering: true });
  if (state.folder) setup.scan(state.folder, { quiet: true });
}

init();
