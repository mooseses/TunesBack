// Services: online accounts (Last.fm, ListenBrainz) and downloaded histories
// (Spotify), with how each one is doing: syncing, up to date, or in trouble.

import { call } from "../api.js";
import { render as renderApp, renderNav, saveSettings, state } from "../app.js";
import { confirmAction, h, icon, number, relativeTime, shortDate, toast } from "../util.js";
import { loadLibrary } from "./setup.js";

const NAMES = { lastfm: "Last.fm", listenbrainz: "ListenBrainz", spotify: "Spotify" };
const TINTS = { lastfm: "#d51007", listenbrainz: "#eb743b", spotify: "#1db954" };
const PROFILES = {
  lastfm: (user) => `https://www.last.fm/user/${encodeURIComponent(user)}`,
  listenbrainz: (user) => `https://listenbrainz.org/user/${encodeURIComponent(user)}/`,
};

let keyInfo = null; // how Last.fm is keyed: {source: "bundled" | "yours" | null, ends}
let editingKey = false;
let watching = null;
let progress = { running: false }; // the sync channel's latest progress

const accounts = () => state.sources.filter((s) => s.mode === "account");
const downloads = () => state.sources.filter((s) => s.mode === "export");
const date = (seconds) => (seconds ? shortDate(new Date(seconds * 1000).toISOString()) : "—");
const ago = (seconds) => (seconds ? relativeTime(new Date(seconds * 1000).toISOString()) : "—");

export const isSyncing = () => progress.running;

/** For the sidebar: "busy" while syncing, "error" if an account's last sync failed, "ok", or null. */
export function overallStatus() {
  if (progress.running) return "busy";
  const list = accounts();
  if (!list.length) return null;
  return list.some((s) => s.last_sync?.error) ? "error" : "ok";
}

/** Follow a sync's progress (started here, on start-up or anywhere else) until it ends. */
export function watchSync() {
  if (watching) return;
  watching = setInterval(async () => {
    const p = await call("progress", { channel: "sync" });
    const was = progress.running;
    progress = p.error ? { running: false } : p;
    if (state.view === "services") {
      const line = document.querySelector(`[data-live="${p.source}"]`);
      if (line && p.running) line.textContent = p.stage;
      else if (was !== p.running) renderApp();
    }
    renderNav();
    if (!p.running && was) {
      clearInterval(watching);
      watching = null;
    }
  }, 500);
}

async function syncNow(source) {
  progress = { running: true, stage: "Connecting…", source: source.id };
  renderApp();
  watchSync();
  const result = await call("sync_sources", { source_id: source.id });
  progress = { running: false };
  await loadLibrary();
  if (result.error) toast(result.error, { error: true });
  else if (result.problems?.length) toast(result.problems[0].error, { error: true, timeout: 7000 });
  else if (result.stopped) toast("Stopped. TunesBack carries on from there next time.");
  else toast(result.new ? `${number(result.new)} new listens from ${NAMES[source.kind]}` : `${NAMES[source.kind]} is up to date`);
  renderApp();
}

function openLink(event, url) {
  if (!state.info.desktop) return;
  event.preventDefault();
  call("open_url", { url });
}

export function render(root) {
  if (keyInfo === null) {
    keyInfo = {};
    call("catalog").then((r) => { keyInfo = r.lastfm_key_info || {}; if (state.view === "services") renderApp(); });
  }
  const list = accounts();
  const files = downloads();
  root.append(h("div.services",
    !list.length && !files.length && intro(),
    (list.length > 0 || files.length > 0) && h("div.services-head",
      h("h2.section-title", { style: { margin: 0 } }, "Online accounts"),
      h("div.services-actions",
        connectButton("lastfm"), connectButton("listenbrainz"))),
    list.map(accountCard),
    (list.length > 0 || files.length > 0) && h("h2.section-title", "Downloads"),
    files.map(downloadCard),
    (list.length > 0 || files.length > 0) && !files.length && h("div.card.service-empty",
      h("span", "Import the listening history Spotify lets you download."), connectButton("spotify")),
    settingsCard()));
}

/** Set-up, just for this service; afterwards, back here. */
function connect(kind) {
  state.openSetup({ only: kind, cancellable: true, finish: async () => { await loadLibrary(); renderApp(); } });
}

function connectButton(kind) {
  const label = kind === "spotify" ? "Import Spotify history" : `Connect ${NAMES[kind]}`;
  return h("button.btn", { onclick: () => connect(kind) },
    icon(kind === "spotify" ? "download" : "plus"), label);
}

function intro() {
  const option = (kind, text) => h("button.oobe-option.service-option", {
    type: "button", onclick: () => connect(kind),
  }, h("span.service-logo", { style: { background: TINTS[kind] } }, NAMES[kind][0]), h("b", NAMES[kind]), h("small", text));
  return h("div.card.services-intro",
    h("span.invite-icon", icon("cloud")),
    h("h2", "Bring in your listening history"),
    h("p.muted", "Services that log every listen give TunesBack the time you played each song: streaks, your listening clock, discoveries and more."),
    h("div.oobe-options",
      option("lastfm", "Every scrobble. Needs your user name."),
      option("listenbrainz", "Every listen. Needs your user name."),
      option("spotify", "From the history Spotify lets you download.")));
}

function status(source) {
  const syncing = progress.running && progress.source === source.id;
  if (syncing) return ["busy", "Syncing…"];
  if (source.last_sync?.error) return ["error", "Last sync failed"];
  if (!source.complete) return ["busy", "Importing history"];
  if (source.last_sync) return ["ok", "Up to date"];
  return ["", "Not synced yet"];
}

function accountCard(source) {
  const [tone, label] = status(source);
  const syncing = progress.running && progress.source === source.id;
  const otherSync = progress.running && !syncing;
  const profile = PROFILES[source.kind]?.(source.path);
  return h("div.card.service-card",
    h("div.service-top",
      h("span.service-logo", { style: { background: TINTS[source.kind] } }, NAMES[source.kind][0]),
      h("div.service-name",
        h("b", NAMES[source.kind]),
        h("a.muted", { href: profile, target: "_blank", rel: "noreferrer", onclick: (e) => openLink(e, profile) },
          `@${source.path}`, icon("external"))),
      h(`span.status-pill.${tone || "idle"}`, h("span.dot"), label),
      h("div.service-actions",
        syncing
          ? h("button.btn", { onclick: () => call("cancel", { channel: "sync" }) }, icon("stop"), "Stop")
          : h("button.btn", { disabled: otherSync, onclick: () => syncNow(source) }, icon("refresh"), "Sync now"),
        h("button.btn.btn-ghost", { disabled: syncing, onclick: () => remove(source) }, "Remove"))),
    syncing && h("div.service-live", h("span.spinner.small"), h("span", { "data-live": source.id }, progress.stage || "Connecting…")),
    source.last_sync?.error && !syncing && h("div.service-error", icon("info"), h("span", source.last_sync.error)),
    h("div.service-stats",
      stat("Listens", number(source.play_count || 0)),
      stat("Since", date(source.first_play)),
      stat("Newest listen", ago(source.last_play)),
      stat("Last checked", source.last_sync ? relativeTime(source.last_sync.at) : "never")),
    coverage(source),
    activity(source));
}

function stat(label, value) {
  return h("div.service-stat", h("span.label", label), h("b", value));
}

/** A bar from the account's first listen to today, filled where TunesBack has the history. */
function coverage(source) {
  if (!source.first_play) return null;
  const now = Date.now() / 1000;
  const start = Math.min(source.first_play, source.synced_back_to || source.first_play);
  const span = Math.max(1, now - start);
  const from = ((source.synced_back_to && !source.complete ? source.synced_back_to : start) - start) / span;
  const to = ((source.last_play || now) - start) / span;
  return h("div.coverage",
    h("div.coverage-bar", { title: `${date(start)} – ${date(source.last_play)}` },
      h("span.coverage-fill", { style: { left: `${from * 100}%`, width: `${Math.max(1, (to - from) * 100)}%` } })),
    h("div.coverage-legend",
      h("span", date(start)),
      h("span", source.complete ? "Whole history imported" : `Older listens still to come — back to ${date(source.synced_back_to)} so far`),
      h("span", "Today")));
}

function activity(source) {
  const history = source.history || [];
  if (!history.length) return null;
  return h("details.service-activity",
    h("summary", "Recent syncs"),
    h("ul", history.map((entry) => h("li",
      h("span.when", relativeTime(entry.at)),
      h(`span${entry.error ? ".bad" : ""}`, entry.error
        ? entry.error
        : entry.stopped ? `Stopped after ${number(entry.new)} new listens`
          : entry.new ? `${number(entry.new)} new listens` : "Nothing new")))));
}

function downloadCard(source) {
  return h("div.card.service-card",
    h("div.service-top",
      h("span.service-logo", { style: { background: TINTS[source.kind] } }, NAMES[source.kind][0]),
      h("div.service-name", h("b", `${NAMES[source.kind]} download`), h("span.muted", { title: source.path }, source.path)),
      h("span.status-pill.ok", h("span.dot"), "Imported"),
      h("div.service-actions",
        state.info.desktop && h("button.btn", {
          onclick: async () => {
            const picked = await call("pick_file", { kind: "spotify" });
            if (!picked.path) return;
            const result = await call("import_history", { kind: "spotify", path: picked.path });
            if (result.error) return toast(result.error, { error: true });
            toast(result.new ? `Added ${number(result.new)} new listens` : "That download has nothing new");
            await loadLibrary();
            renderApp();
          },
        }, icon("download"), "Add newer download"),
        h("button.btn.btn-ghost", { onclick: () => remove(source) }, "Remove"))),
    h("div.service-stats",
      stat("Listens", number(source.play_count || 0)),
      stat("From", date(source.first_play)),
      stat("To", date(source.last_play)),
      stat("Kind", "Download")));
}

async function remove(source) {
  const ok = await confirmAction(`Remove ${NAMES[source.kind]}?`,
    `TunesBack will forget the listens it imported from ${NAMES[source.kind]}. Nothing changes on ${NAMES[source.kind]} itself.`, "Remove");
  if (!ok) return;
  const r = await call("remove_library", { source_id: source.id });
  if (r.error) return toast(r.error, { error: true });
  await loadLibrary();
  if (!state.sources.length) state.openSetup({ start: "welcome" }); else renderApp();
}

function settingsCard() {
  const toggle = h("label.switch.setting",
    h("div", h("div", { style: { fontWeight: 600 } }, "Check for new listens on start-up"),
      h("div.desc", "Each time TunesBack opens, it fetches what's new from your online accounts.")),
    h("input", { type: "checkbox", role: "switch", checked: state.settings.sync_on_launch,
      onchange: (e) => saveSettings({ sync_on_launch: e.target.checked }) }));
  return h("div.card.services-settings",
    h("div.card-title", "Settings"),
    toggle,
    keyRow());
}

function keyRow() {
  if (keyInfo?.source === "bundled") {
    return h("div.setting", h("div", h("div", { style: { fontWeight: 600 } }, "Last.fm API key"),
      h("div.desc", "This copy of TunesBack comes with one.")));
  }
  if (editingKey) {
    const input = h("input.input", { type: "text", placeholder: "Paste your Last.fm API key", spellcheck: "false", "aria-label": "Last.fm API key" });
    const save = h("button.btn.btn-primary", {
      onclick: async () => {
        save.disabled = true;
        const r = await call("set_lastfm_key", { api_key: input.value });
        save.disabled = false;
        if (r.error) return toast(r.error, { error: true });
        keyInfo = r.lastfm_key;
        editingKey = false;
        toast("Saved the API key");
        renderApp();
      },
    }, "Save");
    return h("div.setting.key-edit",
      h("div", { style: { flex: 1 } }, h("div", { style: { fontWeight: 600, marginBottom: "6px" } }, "Last.fm API key"),
        h("div.folder-row", input, save, h("button.btn.btn-ghost", { onclick: () => { editingKey = false; renderApp(); } }, "Cancel"))));
  }
  return h("div.setting",
    h("div", h("div", { style: { fontWeight: 600 } }, "Last.fm API key"),
      h("div.desc", keyInfo?.source === "yours" ? `Yours, ending in ${keyInfo.ends}.` : "Not set yet. Last.fm needs one to read scrobbles.")),
    h("button.btn", { onclick: () => { editingKey = true; renderApp(); } }, icon("key"), keyInfo?.source ? "Change" : "Add key"));
}
