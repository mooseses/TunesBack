import { call, setCardFlags } from "./api.js";
import { h, icon, number, segmented, shortDate, showMessage, toast } from "./util.js";
import { openAbout } from "./about.js";
import { initSidebar, setNativeSidebar, toggleSidebar } from "./sidebar.js";
import { initWindow } from "./window.js";
import * as setup from "./views/setup.js";
import { openOnboarding } from "./views/onboarding.js";
import * as overview from "./views/overview.js";
import * as charts from "./views/charts.js";
import * as age from "./views/age.js";
import * as wrapped from "./views/wrapped.js";
import * as services from "./views/services.js";
import * as dev from "./views/dev.js";

// The sidebar, top to bottom. Views in the "recap" group need a recap first.
const VIEWS = {
  overview: { module: overview, title: "Overview", icon: "overview", group: "recap" },
  charts: { module: charts, title: "Top charts", icon: "charts", group: "recap" },
  age: { module: age, title: "Listening age", icon: "age", group: "recap" },
  wrapped: { module: wrapped, title: "Wrapped", icon: "wrapped", group: "recap" },
  setup: { module: setup, title: "Library", icon: "library", group: "manage" },
  services: { module: services, title: "Services", icon: "cloud", group: "manage" },
  dev: { module: dev, title: "Dev space", icon: "flask", group: "manage", shown: () => !!state.settings.dev_mode },
};

export const state = {
  info: null,
  settings: {},
  sources: [],
  readings: [],
  openSetup: (options) => openSetup(options),
  mode: "compare",
  startId: null,
  endId: null,
  report: null,
  view: "setup",
  charts: { category: "songs", limit: 25, filter: "" },
  deck: null, // the Wrapped cards for the current recap
  selectedCards: new Set(), // card types picked for saving
};

const content = document.getElementById("content");

// ---------- navigation ----------

export function navigate(view) {
  if (!VIEWS[view] || (VIEWS[view].shown && !VIEWS[view].shown())) return;
  if (VIEWS[view].group === "recap" && !state.report) view = "setup";
  if (view === state.view && content.childElementCount) return;
  if (state.view === "overview" && overview.isEditing()) overview.stopEditing();
  state.view = view;
  render({ entering: true });
}

/**
 * Redraw the current view. Pass `entering` when switching views: that resets
 * the scroll position and plays the enter transition. Redraws within a view
 * (unit, ranking...) keep the scroll position so nothing jumps.
 */
export function render({ entering = false } = {}) {
  if (VIEWS[state.view].shown && !VIEWS[state.view].shown()) state.view = "setup";
  const view = VIEWS[state.view];
  document.getElementById("view-title").textContent = view.title;
  renderNav();
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


/** The sidebar's items: enabled when they can show something, with a status dot for Services. */
export function renderNav() {
  for (const [key, view] of Object.entries(VIEWS)) {
    const item = document.querySelector(`.nav-item[data-view="${key}"]`);
    if (!item) continue;
    item.hidden = !!view.shown && !view.shown();
    item.classList.toggle("active", key === state.view);
    item.setAttribute("aria-current", key === state.view ? "page" : "false");
    item.disabled = view.group === "recap" && !state.report;
  }
  const dot = document.querySelector('.nav-item[data-view="services"] .status-dot');
  const status = services.overallStatus();
  if (dot) {
    dot.className = `status-dot ${status || ""}`;
    dot.hidden = !status;
  }
  if (nativeSidebar) sendSidebarModel(status);
}

// macOS: the native sidebar mirrors this one. Send it what to show when anything changes.
let nativeSidebar = false;
let sentModel = "";

function sendSidebarModel(status) {
  const items = Object.entries(VIEWS).map(([id, view]) => ({
    id, label: view.title, group: view.group,
    hidden: !!view.shown && !view.shown(),
    enabled: view.group !== "recap" || !!state.report,
    status: id === "services" ? status : null,
  }));
  items.push({ id: "settings", label: "Settings", group: "manage", enabled: true, hidden: false, status: null });
  const model = JSON.stringify({ items, active: state.view });
  if (model === sentModel) return;
  sentModel = model;
  call("window_sidebar", { model: JSON.parse(model) });
}

function buildNav() {
  const groups = { recap: document.getElementById("nav-top"), manage: document.getElementById("nav-bottom") };
  for (const [key, view] of Object.entries(VIEWS)) {
    const item = h("button.nav-item", { type: "button", "data-view": key, title: view.title },
      icon(view.icon), h("span.nav-label", view.title), key === "services" && h("span.status-dot", { hidden: true }));
    item.addEventListener("click", () => navigate(key));
    groups[view.group].append(item);
  }
  const settingsButton = h("button.nav-item", { type: "button", id: "open-settings", title: "Settings" },
    icon("settings"), h("span.nav-label", "Settings"));
  settingsButton.addEventListener("click", openSettings);
  groups.manage.append(settingsButton);
}

function renderPeriodChip() {
  const chip = document.getElementById("period-chip");
  const report = state.report;
  chip.hidden = !report || VIEWS[state.view].group !== "recap";
  if (!report) return;
  const text = report.mode === "compare"
    ? `${shortDate(report.start_date)} → ${shortDate(report.end_date)}`
    : `All time up to ${shortDate(report.end_date)}`;
  chip.replaceChildren(icon("calendar"), text);
}

// The unit and ranking toggles persist while you stay in a view, so a change
// (from a click, the menu or a shortcut) slides their indicator instead of
// redrawing them.
let topbar = { key: null, unit: null, rank: null };

function renderTopbarActions() {
  const actions = document.getElementById("topbar-actions");
  const editing = state.view === "overview" && overview.isEditing();
  const key = `${state.view}|${!!state.report}|${editing}`;
  if (topbar.key === key) {
    topbar.unit?.setValue(state.settings.unit);
    topbar.rank?.setValue(state.settings.rank_by);
    return;
  }
  topbar = { key, unit: null, rank: null };
  actions.replaceChildren();
  if (!state.report || VIEWS[state.view].group !== "recap" || state.view === "age") return;
  if (state.view === "overview") actions.append(...overview.topbarActions());
  if (editing) return; // the unit and ranking switches come back when you're done
  if (state.view !== "wrapped") {
    topbar.unit = segmented([["hours", "Hours"], ["minutes", "Minutes"], ["days", "Days"]], state.settings.unit,
      (unit) => { saveSettings({ unit }); render(); }, "Time unit");
    actions.append(topbar.unit);
  }
  topbar.rank = segmented([["plays", "By plays"], ["time", "By time"]], state.settings.rank_by,
    (rank_by) => { saveSettings({ rank_by }); render(); }, "Rank by");
  actions.append(topbar.rank);
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
  if ("dev_mode" in changes) renderNav();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const batch = pendingSettings;
    pendingSettings = {};
    const result = await call("update_settings", { changes: batch });
    if (result.error) toast(result.error, { error: true });
  }, 250);
}

/** Save now and wait for it, for changes the server needs before the next request (e.g. what goes in the deck). */
export async function saveSettingsNow(changes) {
  Object.assign(state.settings, changes);
  const result = await call("update_settings", { changes });
  if (result.error) toast(result.error, { error: true });
  return result;
}

function applyTheme() {
  const theme = state.settings.theme;
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("reduce-motion", !!state.settings.flags?.reduced_motion);
  setCardFlags(state.settings.flags?.card_guides ? { guides: 1 } : {});
}

/** Animations are off when the system asks for less motion, or the Dev space flag says so. */
export const reducedMotion = () => !!state.settings.flags?.reduced_motion
  || window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
      state.info.desktop && materialSetting(),
      toggle("show_art", "Album artwork in lists", "Read from your music files. Can be slow on network drives."),
      toggle("sync_on_launch", "Check for new listens on start-up", "Fetches from Last.fm and ListenBrainz each time TunesBack opens."),
      h("div.setting", h("div", h("div", { style: { fontWeight: 600 } }, "Set-up"),
        h("div.desc", "Go through the welcome steps again, for example to add another source.")),
        h("button.btn", { onclick: () => { dialog.close(); openSetup({ start: "welcome", cancellable: true }); } }, "Run set-up")),
      toggle("debug_logging", "Detailed logging", "Writes extra detail to the log file to help track down problems."),
      toggle("dev_mode", "Dev space", "Adds a page with dry runs, feature flags and diagnostics to the sidebar."),
      h("div.setting", h("div", h("div", { style: { fontWeight: 600 } }, "Log files"), h("div.desc", state.info.log_dir)),
        h("button.btn", { onclick: async () => { const r = await call("open_logs"); if (r.error) toast(r.error, { error: true }); } }, "Open folder")),
      h("div.about", h("span", `TunesBack ${state.info.version}`),
        h("button.btn.btn-ghost.btn-small", { onclick: () => { dialog.close(); openAbout(); } }, "About TunesBack")),
    ),
  );
  dialog.showModal();
}

/** macOS: the native sidebar; Windows 11: Mica. Both take effect when TunesBack restarts. */
function materialSetting() {
  const platform = state.info.window?.platform;
  const [key, title, desc, running] = platform === "macos"
    ? ["native_sidebar", "Native sidebar", "The macOS sidebar, in Liquid Glass on macOS Tahoe.", state.info.window?.sidebar === "native"]
    : platform === "windows"
      ? ["mica", "Mica background", "Windows 11's tinted, translucent window background.", state.info.window?.material === "mica"]
      : [];
  if (!key) return null;
  const note = h("div.setting-note", { hidden: true },
    h("span", "Restart TunesBack to apply this."),
    h("button.btn", { onclick: () => call("restart") }, "Restart now"));
  return h("div",
    h("label.switch.setting",
      h("div", h("div", { style: { fontWeight: 600 } }, title), h("div.desc", desc)),
      h("input", {
        type: "checkbox", role: "switch", checked: state.settings[key],
        onchange: (e) => { saveSettings({ [key]: e.target.checked }); note.hidden = e.target.checked === running; },
      })),
    note);
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
    case "add_library": openSetup({ start: "apps", cancellable: true }); break;
    case "import_exports":
      if (state.info.desktop) setup.importExports();
      else toast("Importing exports needs the desktop app");
      break;
    case "refresh":
      setup.refresh().then(() => { if (state.view === "setup") render(); });
      break;
    case "generate":
      if (setup.canGenerate()) runAnalysis();
      break;
    case "save_cards":
      navigate("wrapped");
      if (state.deck?.cards) wrapped.save(null);
      else toast("The cards are still being drawn");
      break;
    case "settings": openSettings(); break;
    case "sidebar": toggleSidebar(); break;
    case "quit": call("window_close"); break;
    case "view": navigate(arg); break;
    case "rank": saveSettings({ rank_by: arg }); render(); break;
    case "unit": saveSettings({ unit: arg }); render(); break;
    case "theme": saveSettings({ theme: arg }); break;
    case "open_logs": call("open_logs").then((r) => r.error && toast(r.error, { error: true })); break;
    case "website":
      if (state.info.desktop) call("open_website");
      else window.open("https://github.com/mooseses/TunesBack", "_blank", "noreferrer");
      break;
    case "about": openAbout(); break;
  }
}

const commandHooks = {
  run: runCommand,
  windowChanged: (info) => {
    const native = info?.sidebar === "native";
    if (native === nativeSidebar) return;
    nativeSidebar = native;
    sentModel = "";
    setNativeSidebar(native);
    renderNav();
  },
  isChecked: (item) => {
    const [, value] = item.command.split(":");
    return state.settings[item.group] === value;
  },
  isEnabled: (command) => {
    const [kind, arg] = command.split(":");
    if (kind === "view") {
      const view = VIEWS[arg];
      return !!view && (!view.shown || view.shown()) && (view.group !== "recap" || !!state.report);
    }
    if (kind === "generate") return setup.canGenerate();
    if (kind === "import_exports" || kind === "refresh") return state.sources.length > 0;
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

/** Build the recap chosen on the Library page. `quiet` (at start-up): on failure, stay on the Library page. */
export async function runAnalysis({ quiet = false } = {}) {
  showBusy("Starting…", () => { busyText.textContent = "Cancelling…"; call("cancel"); });
  const poll = setInterval(async () => {
    const p = await call("progress");
    if (p.running && p.stage && !busy.hidden && busyText.textContent !== "Cancelling…") busyText.textContent = p.stage;
  }, 250);
  const result = await call("analyze", setup.analysisRequest());
  clearInterval(poll);
  hideBusy();

  if (result.error) {
    if (!quiet) return showMessage("Couldn't build your recap", result.error);
    toast(result.error, { timeout: 6000 });
    return navigate("setup");
  }
  if (result.cancelled) return toast("Cancelled");
  state.report = result.report;
  state.deck = null;
  state.selectedCards.clear();
  state.charts.filter = "";
  if (state.report.mode !== "compare" && state.charts.category === "new_finds") state.charts.category = "songs";
  state.view = "overview";
  render({ entering: true });
}

// ---------- start-up ----------

/** Show first-run set-up; when it finishes, load the library and show a recap. */
function openSetup(options = {}) {
  openOnboarding({ finish: () => showLibrary({ recap: true }), ...options });
}

async function showLibrary({ recap }) {
  await setup.loadLibrary();
  if (recap && setup.canGenerate()) await runAnalysis({ quiet: true });
  else navigate("setup");
  if (!state.report) render({ entering: true });
}

async function init() {
  buildNav();
  document.getElementById("period-chip").addEventListener("click", () => navigate("setup"));

  const info = await call("state");
  if (info.error) return showMessage("TunesBack couldn't start", info.error);
  state.info = info;
  state.settings = info.settings;
  initWindow(info.window, commandHooks);
  initSidebar(state.settings, saveSettings);
  applyTheme();

  if (!state.settings.setup_done) {
    render({ entering: true });
    openSetup();
    return;
  }
  // Every launch: read the libraries again, then go straight to the recap.
  showBusy("Reading your library…");
  await setup.refresh({ quiet: true });
  hideBusy();
  if (!state.sources.length) {
    openSetup();
    return;
  }
  await showLibrary({ recap: true });
  syncInBackground();
}

/** Fetch new listens from online accounts after start-up, without holding anything up. */
async function syncInBackground() {
  if (!state.settings.sync_on_launch || !state.sources.some((s) => s.mode === "account")) return;
  services.watchSync();
  const result = await setup.sync({ quiet: true });
  await setup.loadLibrary();
  renderNav();
  if (state.view === "services" || state.view === "setup") render();
  if (!result.new) return;
  const uses = state.report?.sources?.some((s) => state.sources.find((x) => x.id === s.id)?.mode === "account");
  toast(`${number(result.new)} new listens from your accounts`,
    uses ? { action: { label: "Update recap", run: runAnalysis } } : {});
}

init();
