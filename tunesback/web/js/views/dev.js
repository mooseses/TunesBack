// Dev space: feature flags, sync dry runs and diagnostics. Shown in the sidebar
// once "Dev space" is turned on in Settings.

import { call, cardImageUrl } from "../api.js";
import { render as renderApp, saveSettings, state } from "../app.js";
import { confirmAction, fileSize, h, icon, number, relativeTime, toast } from "../util.js";
import { isSyncing } from "./services.js";
import { loadLibrary } from "./setup.js";

const NAMES = { lastfm: "Last.fm", listenbrainz: "ListenBrainz", spotify: "Spotify", itunes: "iTunes" };

let info = null; // dev_info, loaded when the page opens
let log = null; // dev_log
let options = null; // card types, layouts and themes
const dry = { source: null, kind: "lastfm", username: "", apiKey: "", batches: 3, fresh: false, running: false, report: null, error: null };
const lab = { type: "top_songs", layout: null, theme: "midnight", format: "story", variant: "scripts", seed: 1 };

async function load() {
  const [i, l, o] = await Promise.all([call("dev_info"), call("dev_log"), options ? options : call("card_options")]);
  info = i;
  log = l;
  if (!o.error) options = o;
  if (state.view === "dev") renderApp();
}

export function render(root) {
  if (!info) {
    load();
    root.append(h("div.dev-grid", Array.from({ length: 4 }, () => h("div.card.skeleton", { style: { height: "180px" } }))));
    return;
  }
  if (info.error) {
    root.append(h("div.card.empty", info.error));
    return;
  }
  root.append(h("div.dev",
    h("p.dev-note", icon("flask"), "Tools for testing and tracking down problems. Nothing here changes your music."),
    h("div.dev-grid",
      flagsCard(),
      housekeepingCard(),
      dryRunCard(),
      accountsCard(),
      cardLab(),
      aboutCard(),
      fontsCard(),
      logCard(),
      reportCard())));
}

const section = (title, note, ...body) => h("div.card.dev-card", h("div.card-title", title, note && h("span.muted", note)), body);

// ---------- flags ----------

function flagsCard() {
  return section("Feature flags", "take effect at once",
    h("div.dev-flags",
      h("label.switch.setting",
        h("div", h("div", { style: { fontWeight: 600 } }, "Detailed logging"),
          h("div.desc", "Writes extra detail to the log file, every request included.")),
        h("input", { type: "checkbox", role: "switch", checked: !!state.settings.debug_logging,
          onchange: (e) => saveSettings({ debug_logging: e.target.checked }) })),
      info.flags.map((flag) => h("label.switch.setting",
      h("div", h("div", { style: { fontWeight: 600 } }, h("code", flag.id)), h("div.desc", flag.label)),
      h("input", {
        type: "checkbox", role: "switch", checked: flag.on,
        onchange: async (e) => {
          const flags = { ...state.settings.flags, [flag.id]: e.target.checked };
          // Saved straight away (not debounced): card images name the flags in their URLs.
          const r = await call("update_settings", { changes: { flags } });
          if (r.error) return toast(r.error, { error: true });
          saveSettings({ flags });
          flag.on = e.target.checked;
          if (flag.id === "card_guides") state.deck = null;
          if (flag.id === "show_ids" || flag.id === "card_guides") renderApp();
        },
      })))));
}

// ---------- dry run ----------

function dryRunCard() {
  const accounts = state.sources.filter((s) => s.mode === "account");
  if (dry.source === null || (dry.source && !accounts.some((s) => String(s.id) === dry.source))) {
    dry.source = accounts.length ? String(accounts[0].id) : ""; // "" is another account, typed in
  }
  const select = h("select.input", {
    "aria-label": "Account",
    onchange: (e) => { dry.source = e.target.value; renderApp(); },
  },
  accounts.map((s) => h("option", { value: s.id, selected: String(s.id) === dry.source }, `${NAMES[s.kind]} · @${s.path}`)),
  h("option", { value: "", selected: !dry.source }, "Another account…"));
  const other = !dry.source && h("div.dev-row",
    h("select.input", { "aria-label": "Service", onchange: (e) => { dry.kind = e.target.value; } },
      ["lastfm", "listenbrainz"].map((k) => h("option", { value: k, selected: dry.kind === k }, NAMES[k]))),
    h("input.input", { type: "text", placeholder: "User name", value: dry.username, spellcheck: "false", oninput: (e) => { dry.username = e.target.value; } }),
    h("input.input", { type: "text", placeholder: "API key (Last.fm, optional)", value: dry.apiKey, spellcheck: "false", oninput: (e) => { dry.apiKey = e.target.value; } }));

  const run = async () => {
    dry.running = true;
    dry.report = null;
    dry.error = null;
    renderApp();
    const poll = setInterval(async () => {
      const p = await call("progress", { channel: "sync" });
      const line = document.querySelector('[data-live="dry-run"]');
      if (line && p.running && p.stage) line.textContent = p.stage;
    }, 400);
    const args = dry.source
      ? { source_id: Number(dry.source), batches: dry.batches, fresh: dry.fresh }
      : { kind: dry.kind, username: dry.username, api_key: dry.apiKey, batches: dry.batches, fresh: true };
    const r = await call("dry_run_sync", args);
    clearInterval(poll);
    dry.running = false;
    if (r.error) dry.error = r.error; else dry.report = r;
    if (state.view === "dev") renderApp();
  };

  return section("Sync dry run", "fetches for real, stores nothing",
    h("div.dev-form",
      h("div.dev-row", select,
        h("label.dev-inline", "Batches", h("input.input.dev-number", { type: "number", min: 1, max: 50, value: dry.batches,
          oninput: (e) => { dry.batches = Math.max(1, Math.min(50, Number(e.target.value) || 1)); } }))),
      other,
      dry.source && h("label.dev-check", h("input", { type: "checkbox", checked: dry.fresh, onchange: (e) => { dry.fresh = e.target.checked; } }),
        "From scratch (as if this account had never synced)"),
      h("div.dev-row",
        dry.running
          ? h("button.btn", { onclick: () => call("cancel", { channel: "sync" }) }, icon("stop"), "Stop")
          : h("button.btn.btn-primary", { onclick: run, disabled: isSyncing() }, icon("play"), "Run"),
        dry.running && h("span.dev-live", h("span.spinner.small"), h("span", { "data-live": "dry-run" }, "Connecting…")))),
    dry.error && h("div.service-error", icon("info"), h("span", dry.error)),
    dry.report && dryReport(dry.report));
}

function dryReport(r) {
  const stat = (label, value) => h("div.service-stat", h("span.label", label), h("b", value));
  return h("div.dev-report",
    h("div.dev-outcome", h("b", `Dry run ${r.outcome}`), h("span.muted", ` · ${r.mode}`)),
    h("div.service-stats",
      stat("Listens fetched", number(r.plays)),
      stat("New", number(r.new)),
      stat("Already stored", number(r.already_stored)),
      stat("Requests", `${r.requests}${r.retries ? ` (${r.retries} retried)` : ""}`),
      stat("Network time", `${r.seconds} s`),
      stat("Without album", number(r.without_album)),
      stat("With artwork", number(r.with_artwork))),
    r.batches.length > 0 && h("table.dev-table",
      h("thead", h("tr", h("th", "#"), h("th", "Listens"), h("th", "New"), h("th", "Oldest"), h("th", "Newest"))),
      h("tbody", r.batches.map((b, i) => h("tr", h("td", i + 1), h("td", number(b.plays)), h("td", number(b.new)),
        h("td", b.oldest.replace("T", " ")), h("td", b.newest.replace("T", " ")))))),
    r.samples.length > 0 && h("details.dev-details", h("summary", `First ${r.samples.length} listens, as parsed`),
      h("pre.dev-pre", JSON.stringify(r.samples, null, 2))),
    h("details.dev-details", h("summary", "What a real sync would remember"),
      h("pre.dev-pre", JSON.stringify(r.would_save ?? null, null, 2))));
}

// ---------- accounts ----------

function accountsCard() {
  const list = state.sources.filter((s) => !s.counter);
  const act = async (action, source, title, message, label) => {
    if (!(await confirmAction(title, message, label))) return;
    const r = await call(action, { source_id: source.id });
    if (r.error) return toast(r.error, { error: true });
    toast(action === "forget_plays" ? `Forgot ${number(r.deleted)} listens` : "The next sync starts from the beginning");
    await loadLibrary();
    renderApp();
  };
  return section("Imported listens", null,
    list.length ? h("div.dev-list", list.map((s) => h("div.dev-list-row",
      h("div", h("b", NAMES[s.kind] || s.kind), h("small.muted", ` @${s.path} · #${s.id}`),
        h("div.desc", `${number(s.play_count || 0)} listens`, s.mode === "account"
          ? ` · ${s.complete ? "history complete" : `back to ${s.synced_back_to ? new Date(s.synced_back_to * 1000).toISOString().slice(0, 10) : "?"}`}` : "")),
      h("div.dev-row",
        s.mode === "account" && h("button.btn.btn-ghost", {
          onclick: () => act("reset_sync", s, "Reset sync progress?",
            "TunesBack forgets how far it got. The next sync fetches the whole history again; listens already stored aren't duplicated.", "Reset"),
        }, "Reset sync"),
        h("button.btn.btn-ghost", {
          onclick: () => act("forget_plays", s, `Forget every listen from ${NAMES[s.kind]}?`,
            "The account stays connected. Its listens are deleted here and fetched again on the next sync.", "Forget listens"),
        }, icon("trash"), "Forget listens")))))
      : h("p.muted", "No online accounts or downloads yet."));
}

// ---------- housekeeping ----------

function housekeepingCard() {
  const caches = info.caches;
  return section("Housekeeping", null,
    h("div.dev-list",
      h("div.dev-list-row",
        h("div", h("b", "Caches"), h("div.desc", `Artwork thumbnails ${fileSize(caches.thumbnails)} · downloaded covers ${fileSize(caches.covers)} · ${caches["cards in memory"]} cards in memory`)),
        h("button.btn", {
          onclick: async () => {
            const r = await call("clear_caches");
            if (r.error) return toast(r.error, { error: true });
            toast(`Cleared ${fileSize(r.freed)}`);
            state.deck = null;
            info = null;
            renderApp();
          },
        }, "Clear")),
      h("div.dev-list-row",
        h("div", h("b", "Set-up"), h("div.desc", "Run the welcome steps again, full screen.")),
        h("button.btn", { onclick: () => state.openSetup({ start: "welcome", cancellable: true }) }, "Run set-up")),
      startOver(),
      h("div.dev-list-row",
        h("div", h("b", "Logs"), h("div.desc", info.paths.Logs)),
        h("button.btn", { onclick: async () => { const r = await call("open_logs"); if (r.error) toast(r.error, { error: true }); } }, "Open folder")),
      h("div.dev-list-row",
        h("div", h("b", "Refresh"), h("div.desc", "Load this page's numbers again.")),
        h("button.btn", { onclick: () => { info = null; renderApp(); } }, icon("refresh"), "Reload"))));
}

/** Every setting back to its default, then set-up from the start (optionally forgetting the library). */
function startOver() {
  const forget = h("input", { type: "checkbox" });
  return h("div.dev-list-row.dev-danger",
    h("div", h("b", "Start over"),
      h("div.desc", "Resets every setting, including this page's, and goes back to the welcome screen."),
      h("label.dev-check", forget, "Also forget my music library and everything imported")),
    h("button.btn.btn-danger", {
      onclick: async () => {
        const all = forget.checked;
        const ok = await confirmAction("Reset all settings?",
          all ? "Every setting goes back to its default, and TunesBack forgets your sources and the listens it imported. Your music files and online accounts aren't touched."
            : "Every setting goes back to its default and set-up starts again. Your library and imported listens stay.",
          "Reset");
        if (!ok) return;
        const r = await call("reset_all", { forget_library: all });
        if (r.error) return toast(r.error, { error: true });
        window.location.reload();
      },
    }, "Reset…"));
}

// ---------- card lab ----------

function cardLab() {
  if (!options) return section("Card lab", null, h("p.muted", "Loading…"));
  const type = options.cards.find((c) => c.id === lab.type) || options.cards[0];
  if (!type.layouts.some((l) => l.id === lab.layout)) lab.layout = type.layouts[0].id;
  const themes = options.themes.filter((t) => t.id !== "mix");
  const select = (label, value, items, set) => h("label.dev-field", h("span.label", label),
    h("select.input", { onchange: (e) => { set(e.target.value); renderApp(); } },
      items.map(([id, name]) => h("option", { value: id, selected: id === value }, name))));
  const card = { type: type.id, layout: lab.layout, theme: lab.theme };
  const src = cardImageUrl(card, lab.format, "preview", lab.seed, "plays", { sample: lab.variant });
  return h("div.card.dev-card.dev-lab",
    h("div.card-title", "Card lab", h("span.muted", "made-up data, any design")),
    h("div.dev-lab-body",
      h("div.dev-lab-controls",
        select("Card", type.id, options.cards.map((c) => [c.id, c.name]), (v) => { lab.type = v; }),
        select("Layout", lab.layout, type.layouts.map((l) => [l.id, l.name]), (v) => { lab.layout = v; }),
        select("Theme", lab.theme, themes.map((t) => [t.id, t.name]), (v) => { lab.theme = v; }),
        select("Format", lab.format, options.formats.map((f) => [f.id, f.name]), (v) => { lab.format = v; }),
        select("Data", lab.variant, [["scripts", "Many scripts"], ["plain", "Plain"], ["long", "Long titles"]], (v) => { lab.variant = v; }),
        h("button.btn", { onclick: () => { lab.seed += 1; renderApp(); } }, icon("shuffle"), "New seed"),
        h("a.btn.btn-ghost", { href: cardImageUrl(card, lab.format, "full", lab.seed, "plays", { sample: lab.variant }), target: "_blank", rel: "noreferrer" },
          icon("external"), "Full size")),
      h(`div.dev-lab-frame.${lab.format}`, h("img", { src, alt: `${type.name} card`, loading: "lazy" }))));
}

// ---------- about ----------

const table = (rows) => h("table.dev-table.kv", h("tbody", rows.map(([k, v]) => h("tr", h("th", k), h("td", v)))));

function aboutCard() {
  const db = info.database;
  return section("This copy", null,
    table(Object.entries(info.versions)),
    h("div.label.dev-sub", "Library database"),
    table([
      ["Schema version", db.schema],
      ["Size", fileSize(db.size)],
      ...Object.entries(db.rows).map(([name, count]) => [name, number(count)]),
    ]),
    h("div.label.dev-sub", "Folders"),
    table(Object.entries(info.paths).map(([k, v]) => [k, h("code", { title: v }, v)])));
}

function fontsCard() {
  const fonts = info.fonts;
  return section("Fonts on cards", "which installed font draws each script",
    h("table.dev-table",
      h("thead", h("tr", h("th", "Script"), h("th", "Sample"), h("th", "Font"))),
      h("tbody", fonts.fallbacks.map((f) => h("tr", h("td", f.script), h("td.dev-sample", f.sample),
        h("td", { title: f.file }, f.font === "(none)" ? h("span.bad", "none found") : f.font))))),
    h("p.hint", `Bundled: ${fonts.bundled.join(", ")}`));
}

// ---------- logs ----------

function logCard() {
  const calls = log?.calls || [];
  const renders = log?.renders || [];
  const avg = renders.length ? Math.round(renders.reduce((a, r) => a + r.ms, 0) / renders.length) : 0;
  return section("Activity", null,
    h("div.dev-row", h("button.btn.btn-ghost", { onclick: async () => { log = await call("dev_log"); renderApp(); } }, icon("refresh"), "Refresh")),
    h("details.dev-details", { open: true }, h("summary", `Requests to the app (${calls.length})`),
      h("div.dev-scroll", h("table.dev-table",
        h("tbody", calls.slice(0, 80).map((c) => h(`tr${c.error ? ".bad" : ""}`,
          h("td.muted", relativeTime(c.at)), h("td", h("code", c.action)), h("td.num", `${c.ms} ms`),
          h("td", c.error || ""))))))),
    h("details.dev-details", h("summary", `Card renders (${renders.length}${renders.length ? `, ${avg} ms on average` : ""})`),
      h("div.dev-scroll", h("table.dev-table",
        h("tbody", renders.map((r) => h("tr", h("td", r.card), h("td", `${r.format} · ${r.size}`), h("td.num", `${r.ms} ms`))))))));
}

function reportCard() {
  const report = state.report;
  const text = report ? JSON.stringify(report, null, 2) : "";
  return section("Recap data", report ? `${fileSize(text.length)} of JSON` : null,
    report
      ? [
        h("div.dev-row",
          h("button.btn", {
            onclick: async () => {
              try {
                await navigator.clipboard.writeText(text);
                toast("Copied");
              } catch {
                toast("Couldn't reach the clipboard", { error: true });
              }
            },
          }, "Copy JSON")),
        h("details.dev-details", h("summary", "Show"), h("pre.dev-pre.tall", text)),
      ]
      : h("p.muted", "Build a recap on the Library page to see its data here."));
}
