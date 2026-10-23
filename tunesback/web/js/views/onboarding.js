// First-run set-up: a few friendly steps that end with TunesBack knowing
// where your music lives and holding its first reading or import of it.
//
// After "Which music apps do you use?", each app you picked adds its own
// steps: iTunes looks for the library on this computer or a network drive,
// Last.fm and ListenBrainz ask for a user name, Spotify for its download.

import { call } from "../api.js";
import { state } from "../app.js";
import { h, icon, number, relativeTime, shortDate } from "../util.js";

const STEPS_FOR = {
  itunes: ["location", "find", "history"],
  lastfm: ["lastfm"],
  listenbrainz: ["listenbrainz"],
  spotify: ["spotify"],
};
const TINTS = { itunes: "#e0284f", lastfm: "#d51007", listenbrainz: "#eb743b", spotify: "#1db954" };
const OTHER_TINTS = ["#7b61ff", "#0ea5a4", "#f59e0b", "#3b82f6", "#ec4899", "#22c55e", "#8b5cf6", "#f97316"];
const LINKS = {
  spotifyPrivacy: "https://www.spotify.com/account/privacy/",
};

let root = null;
let flow = null;
let onFinish = null;

/** Show set-up. `start` skips the welcome (e.g. when adding another source). */
export function openOnboarding({ start = "welcome", finish, cancellable = false } = {}) {
  onFinish = finish;
  flow = {
    step: start, apps: new Set(["itunes"]), queue: [], location: "local", root: "", catalog: [], lastfmKey: true,
    lastfmKeyUrl: "", search: "idle", candidates: [], selected: null, reading: null, error: null, imported: null,
    accounts: {}, added: [], cancellable,
  };
  root = document.getElementById("onboarding");
  root.hidden = false;
  document.body.classList.add("onboarding-open");
  call("catalog").then((r) => {
    flow.catalog = r.sources || [];
    flow.lastfmKey = !!r.lastfm_key;
    flow.lastfmKeyUrl = r.lastfm_key_url || "";
    if (flow.step === "apps") show("none");
  });
  show();
}

function close() {
  root.hidden = true;
  root.replaceChildren();
  document.body.classList.remove("onboarding-open");
}

const order = () => ["welcome", "apps", ...flow.queue, "done"];

function go(step) {
  const steps = order();
  const forward = steps.indexOf(step) >= steps.indexOf(flow.step);
  flow.step = step;
  show(forward ? "forward" : "back");
  if (step === "find" && flow.search === "idle") search();
}

/** The step after (or before) this one, in the order the picked apps set up. */
const next = () => order()[order().indexOf(flow.step) + 1] ?? "done";
const previous = () => order()[order().indexOf(flow.step) - 1] ?? "apps";

function show(direction = "forward") {
  const body = { welcome, apps, location, find, history, lastfm: () => account("lastfm"),
    listenbrainz: () => account("listenbrainz"), spotify, done }[flow.step]();
  const page = h(`div.oobe-step.enter-${direction}`, body);
  const dots = ["apps", ...flow.queue];
  const progress = dots.includes(flow.step) && h("div.oobe-progress", { "aria-label": `Step ${dots.indexOf(flow.step) + 1} of ${dots.length}` },
    dots.map((s, i) => h(`span${i <= dots.indexOf(flow.step) ? ".on" : ""}`)));
  root.replaceChildren(...[
    flow.cancellable && h("button.oobe-close.btn.btn-ghost", { "aria-label": "Close set-up", onclick: close }, icon("close")),
    progress,
    page,
  ].filter(Boolean));
  page.querySelector("[data-autofocus]")?.focus({ preventScroll: true });
}

function footer(...buttons) {
  return h("div.oobe-footer", buttons);
}

function back() {
  return h("button.btn.btn-ghost", { onclick: () => go(previous()) }, "Back");
}

function monogram(source, i) {
  return h("span.oobe-monogram", { style: { background: TINTS[source.id] || OTHER_TINTS[i % OTHER_TINTS.length] } }, source.name[0]);
}

// ---------- steps ----------

function welcome() {
  return h("div.oobe-center",
    h("img.oobe-logo", { src: "/assets/icon.png", alt: "" }),
    h("h1.oobe-title", "Welcome to TunesBack"),
    h("p.oobe-lead", "Your year in music, from the apps you already use."),
    h("button.btn.btn-primary.btn-large.oobe-cta", { onclick: () => go("apps") },
      "Get started", icon("arrow")),
    h("p.oobe-fine", "Your listening history stays on this computer."));
}

function apps() {
  const catalog = flow.catalog.length ? flow.catalog : [{ id: "itunes", name: "iTunes / Apple Music", blurb: "", available: true }];
  const tiles = catalog.map((source, i) => {
    const picked = flow.apps.has(source.id);
    const tile = h(`button.oobe-tile${picked ? ".picked" : ""}${source.available ? "" : ".soon"}`, {
      type: "button", "aria-pressed": source.available ? String(picked) : null, disabled: !source.available,
      title: source.available ? null : `${source.name} support is coming soon`,
    },
      monogram(source, i),
      h("span.oobe-tile-text", h("b", source.name), source.blurb && h("small", source.blurb),
        !source.available && h("span.oobe-soon", "Coming Soon!")),
      source.available && h("span.oobe-check", icon("check")));
    if (source.available) {
      tile.addEventListener("click", () => {
        if (flow.apps.has(source.id)) flow.apps.delete(source.id); else flow.apps.add(source.id);
        tile.classList.toggle("picked");
        tile.setAttribute("aria-pressed", String(flow.apps.has(source.id)));
        cta.disabled = !flow.apps.size;
      });
    }
    return tile;
  });
  const cta = h("button.btn.btn-primary", {
    disabled: !flow.apps.size,
    onclick: () => {
      // Set up the picked apps in catalogue order.
      flow.queue = catalog.filter((s) => flow.apps.has(s.id)).flatMap((s) => STEPS_FOR[s.id] || []);
      go(flow.queue[0] || "done");
    },
  }, "Continue");
  return [
    h("h2.oobe-heading", "Which music apps do you use?"),
    h("p.oobe-sub", "Pick all that apply. Services that log every listen, like Last.fm, also show when you listen."),
    h("div.oobe-tiles", tiles),
    footer(back(), cta),
  ];
}

function location() {
  const option = (value, iconName, title, text) => {
    const card = h(`button.oobe-option${flow.location === value ? ".picked" : ""}`, { type: "button", "aria-pressed": String(flow.location === value) },
      h("span.oobe-option-icon", icon(iconName)), h("b", title), h("small", text));
    card.addEventListener("click", () => { flow.location = value; flow.search = "idle"; show("none"); });
    return card;
  };
  const example = state.info.platform === "Windows" ? "\\\\nas\\music or Z:\\Music"
    : state.info.platform === "Darwin" ? "/Volumes/Music" : "/run/user/1000/gvfs/… or /mnt/music";
  const rootInput = h("input.input", {
    id: "oobe-root", type: "text", value: flow.root, placeholder: `Where the drive is mounted, e.g. ${example}`, spellcheck: "false",
    oninput: (e) => { flow.root = e.target.value; cta.disabled = !flow.root.trim(); },
  });
  const browse = state.info.desktop && h("button.btn", {
    onclick: async () => {
      const r = await call("pick_folder");
      if (r.path) { flow.root = rootInput.value = r.path; cta.disabled = false; }
    },
  }, icon("folder"), "Browse…");
  const cta = h("button.btn.btn-primary", {
    disabled: flow.location === "network" && !flow.root.trim(),
    onclick: () => { flow.search = "idle"; go("find"); },
  }, "Continue");
  return [
    h("h2.oobe-heading", "Where does your iTunes library live?"),
    h("p.oobe-sub", "TunesBack will look for it there."),
    h("div.oobe-options",
      option("local", "computer", "On this computer", "In your Music folder or iTunes folder"),
      option("network", "server", "On a network drive", "A NAS or shared folder")),
    flow.location === "network" && h("div.oobe-network",
      h("label.label", { for: "oobe-root" }, "Network folder"),
      h("div.folder-row", rootInput, browse),
      h("p.hint", "Connect the drive first, then point TunesBack at it. It searches a few folders deep.")),
    footer(back(), cta),
  ];
}

async function search() {
  flow.search = "searching";
  flow.error = null;
  show("none");
  const started = performance.now();
  const result = await call("discover", flow.location === "network" ? { root: flow.root } : {});
  // Let the search animation be seen, so the result doesn't feel like a flicker.
  await new Promise((resolve) => setTimeout(resolve, Math.max(0, 900 - (performance.now() - started))));
  if (result.error) {
    flow.search = "failed";
    flow.error = result.error;
  } else {
    flow.candidates = result.candidates;
    const usable = flow.candidates.filter((c) => c.kind !== "needs_export");
    flow.selected = usable[0]?.path ?? null;
    flow.search = usable.length ? "found" : "failed";
  }
  if (flow.step === "find") show("none");
}

async function useLibrary(path) {
  flow.search = "reading";
  flow.error = null;
  show("none");
  const result = await call("add_library", { path, location: flow.location });
  if (result.error) {
    flow.search = "failed";
    flow.error = result.error;
  } else {
    flow.search = "read";
    flow.reading = result;
    flow.added.push(`${number(result.tracks)} songs from iTunes`);
  }
  show("none");
}

async function chooseManually(kind) {
  const r = await call(kind === "file" ? "pick_file" : "pick_folder");
  if (r.path) useLibrary(r.path);
}

function find() {
  const s = flow.search;
  if (s === "searching" || s === "idle") {
    return h("div.oobe-center",
      h("div.oobe-radar", h("span"), h("span"), h("span"), icon("search")),
      h("h2.oobe-heading", "Looking for your library…"),
      h("p.oobe-sub", flow.location === "network" ? `Searching ${flow.root}` : "Checking your Music folder and the usual iTunes places."));
  }
  if (s === "reading") {
    return h("div.oobe-center",
      h("div.spinner.oobe-spinner"),
      h("h2.oobe-heading", "Reading your library…"),
      h("p.oobe-sub", "This takes a moment for big libraries."));
  }
  if (s === "read") {
    const r = flow.reading;
    return [
      h("div.oobe-center",
        h("div.oobe-success", icon("check")),
        h("h2.oobe-heading", "Got it!"),
        h("p.oobe-lead", h("b", number(r.tracks)), " songs and ", h("b", number(r.plays)), " plays"),
        h("p.oobe-sub", r.source.mode === "folder"
          ? `Read ${r.readings} export${r.readings === 1 ? "" : "s"} from ${r.source.path}. New exports there are picked up automatically.`
          : `From ${r.source.path}. TunesBack will read it again each time you open the app.`),
        h("button.btn.btn-primary.btn-large.oobe-cta", { onclick: () => go("history") }, "Continue", icon("arrow"))),
    ];
  }
  if (s === "found") {
    const usable = flow.candidates.filter((c) => c.kind !== "needs_export");
    return [
      h("h2.oobe-heading", usable.length > 1 ? "We found a few libraries" : "We found your library"),
      h("p.oobe-sub", "Choose the one you listen with."),
      h("div.oobe-candidates", usable.map((c) => {
        const card = h(`button.oobe-candidate${flow.selected === c.path ? ".picked" : ""}`, { type: "button" },
          h("span.oobe-radio"),
          h("span.oobe-candidate-text",
            h("b", c.kind === "exports" ? "Folder of library exports" : "iTunes library"),
            h("small", { title: c.path }, c.path),
            h("small", c.kind === "exports"
              ? `${c.size} exports · newest ${c.date ? shortDate(c.date) : "unknown"}`
              : `Updated ${c.date ? relativeTime(c.date) : "at an unknown time"}`)));
        card.addEventListener("click", () => { flow.selected = c.path; show("none"); });
        return card;
      })),
      musicAppNote(),
      h("button.btn.btn-ghost.oobe-link", { onclick: () => { flow.search = "failed"; flow.error = null; show("none"); } },
        "Not here? Choose it yourself"),
      footer(back(), h("button.btn.btn-primary", { disabled: !flow.selected, onclick: () => useLibrary(flow.selected) }, "Use this library")),
    ];
  }
  // Nothing found or reading failed: set it up by hand.
  const pathInput = h("input.input", { type: "text", placeholder: "Path to your library file or exports folder", spellcheck: "false", "aria-label": "Library path" });
  return [
    h("h2.oobe-heading", flow.error ? "That didn't work" : "Let's find it together"),
    h("p.oobe-sub", flow.error || "TunesBack couldn't find your library automatically. Point it to the file, or to a folder of exports."),
    musicAppNote(),
    state.info.desktop
      ? h("div.oobe-options",
        h("button.oobe-option", { type: "button", onclick: () => chooseManually("file") },
          h("span.oobe-option-icon", icon("song")), h("b", "Choose library file"), h("small", "An iTunes Library.xml or an export")),
        h("button.oobe-option", { type: "button", onclick: () => chooseManually("folder") },
          h("span.oobe-option-icon", icon("folder")), h("b", "Choose a folder of exports"), h("small", "Every export in it becomes a reading")))
      : h("div.folder-row", pathInput, h("button.btn.btn-primary", { onclick: () => pathInput.value.trim() && useLibrary(pathInput.value) }, "Use this")),
    exportHelp(),
    footer(back(), h("div.oobe-footer-group",
      h("button.btn.btn-ghost", { onclick: () => go(next()) }, "Skip iTunes"),
      h("button.btn", { onclick: () => { flow.search = "idle"; search(); } }, icon("refresh"), "Search again"))),
  ];
}

function musicAppNote() {
  if (!flow.candidates.some((c) => c.kind === "needs_export")) return null;
  return h("div.oobe-note", icon("info"),
    h("span", "Using the Music app on a Mac? It doesn't share its library automatically. Export it once (below), then choose the exported file."));
}

function exportHelp() {
  return h("details.oobe-help",
    h("summary", "How do I export my library?"),
    h("ol",
      h("li", "Open iTunes, or the Music app on a Mac."),
      h("li", "Choose File → Library → Export Library…"),
      h("li", "Save it somewhere easy to find, like your Music folder."),
      h("li", "Export again now and then: each export is another point in time to compare.")),
    h("p.hint", "On Windows, iTunes can also keep a library file up to date for you: Edit → Preferences → Advanced → “Share iTunes Library XML with other applications”."));
}

function history() {
  const importFrom = async (folder) => {
    const result = await call("import_exports", { folder, source_id: flow.reading?.source?.id });
    flow.imported = result.error ? { error: result.error } : result;
    show("none");
  };
  const importChosen = async () => {
    const r = await call("pick_folder");
    if (r.path) importFrom(r.path);
  };
  // Exports discovery already spotted (other than the library just added) are one click away.
  const spotted = flow.candidates.filter((c) => c.kind === "exports" && c.path !== flow.reading?.source?.path);
  const result = flow.imported;
  return [
    h("h2.oobe-heading", "Want to look further back?"),
    h("p.oobe-sub", "TunesBack reads your library every time you open it, so comparisons appear as time goes by. If you've saved exports before, add them now to compare right away."),
    h("div.oobe-options",
      spotted.map((c) => h("button.oobe-option", { type: "button", disabled: !!result, onclick: () => importFrom(c.path) },
        h("span.oobe-option-icon", icon("calendar")), h("b", `Add the ${c.size} exports we found`), h("small", { title: c.path }, c.path))),
      state.info.desktop && h("button.oobe-option", { type: "button", onclick: importChosen },
        h("span.oobe-option-icon", icon("folder")), h("b", spotted.length ? "Choose another folder" : "Add older exports"),
        h("small", "Choose the folder you saved them in"))),
    !spotted.length && !state.info.desktop && h("p.hint", "You can import exports later from the Library page."),
    result && h(`p.oobe-result${result.error ? ".error" : ""}`, result.error
      ? result.error
      : `Added ${result.imported} reading${result.imported === 1 ? "" : "s"}${result.skipped ? ` (${result.skipped} already there)` : ""}.`),
    footer(h("span"), h("button.btn.btn-primary", { onclick: () => go(next()) }, result && !result.error ? "Continue" : "Skip for now")),
  ];
}

// ---------- Last.fm and ListenBrainz ----------

const ACCOUNTS = {
  lastfm: {
    name: "Last.fm",
    lead: "TunesBack reads your scrobbles, every song with the time you played it. It never posts anything.",
    placeholder: "Your Last.fm user name",
  },
  listenbrainz: {
    name: "ListenBrainz",
    lead: "TunesBack reads your listens, every song with the time you played it. It never posts anything.",
    placeholder: "Your ListenBrainz user name",
  },
};

function account(kind) {
  const info = ACCOUNTS[kind];
  const a = (flow.accounts[kind] ||= { status: "form", username: "", apiKey: "", error: null, result: null, stage: "" });
  if (a.status === "syncing") {
    return h("div.oobe-center",
      h("div.spinner.oobe-spinner"),
      h("h2.oobe-heading", `Importing your ${info.name} history…`),
      h("p.oobe-sub.oobe-stage", a.stage || "Connecting…"),
      h("p.oobe-fine", "Long histories take a few minutes. You can stop at any time: TunesBack keeps what it has and carries on next time."),
      h("button.btn", { onclick: () => { a.stage = "Stopping…"; call("cancel", { channel: "sync" }); show("none"); } }, "Stop for now"));
  }
  if (a.status === "done") {
    const r = a.result;
    return h("div.oobe-center",
      h("div.oobe-success", icon("check")),
      h("h2.oobe-heading", r.stopped ? "Imported so far" : "Got it!"),
      h("p.oobe-lead", h("b", number(r.source.play_count)), ` ${kind === "lastfm" ? "scrobbles" : "listens"}`,
        r.source.first_play ? [" since ", h("b", shortDate(new Date(r.source.first_play * 1000).toISOString()))] : ""),
      h("p.oobe-sub", r.stopped || !r.source.complete
        ? "TunesBack will fetch the rest of your history the next time it opens."
        : "New listens are fetched each time you open TunesBack."),
      h("button.btn.btn-primary.btn-large.oobe-cta", { onclick: () => go(next()) }, "Continue", icon("arrow")));
  }
  const needsKey = kind === "lastfm" && !flow.lastfmKey;
  const user = h("input.input", {
    id: `oobe-${kind}-user`, type: "text", value: a.username, placeholder: info.placeholder, spellcheck: "false",
    autocomplete: "username", "data-autofocus": true,
    oninput: (e) => { a.username = e.target.value; update(); },
  });
  const key = needsKey && h("input.input", {
    id: "oobe-lastfm-key", type: "text", value: a.apiKey, placeholder: "32 letters and numbers", spellcheck: "false",
    oninput: (e) => { a.apiKey = e.target.value; update(); },
  });
  const connect = h("button.btn.btn-primary", {
    onclick: async () => {
      a.status = "syncing";
      a.error = null;
      a.stage = "";
      show("none");
      const poll = setInterval(async () => {
        const p = await call("progress", { channel: "sync" });
        if (p.running && p.stage && a.status === "syncing" && a.stage !== "Stopping…") {
          a.stage = p.stage;
          const line = root.querySelector(".oobe-stage");
          if (line) line.textContent = p.stage;
        }
      }, 400);
      const result = await call("add_account", { kind, username: a.username, api_key: needsKey ? a.apiKey : null });
      clearInterval(poll);
      if (!result.error && result.problems?.length && !result.source.play_count) result.error = result.problems[0].error;
      if (result.error) {
        a.status = "form";
        a.error = result.error;
      } else {
        a.status = "done";
        a.result = result;
        flow.added.push(`${number(result.source.play_count)} listens from ${info.name}`);
      }
      if (flow.step === kind) show("none");
    },
  }, "Connect");
  const update = () => { connect.disabled = !a.username.trim() || (needsKey && !a.apiKey.trim()); };
  update();
  return [
    h("h2.oobe-heading", `Connect ${info.name}`),
    h("p.oobe-sub", info.lead),
    h("div.oobe-form",
      h("label.label", { for: `oobe-${kind}-user` }, "User name"), user,
      needsKey && [
        h("label.label", { for: "oobe-lastfm-key" }, "API key"), key,
        h("p.hint", "Last.fm asks apps for a free API key. ",
          h("a", { href: flow.lastfmKeyUrl, target: "_blank", rel: "noreferrer", onclick: (e) => openLink(e, flow.lastfmKeyUrl) }, "Create one here"),
          " (any app name works), then paste the “API key” it shows. TunesBack remembers it."),
      ]),
    a.error && h("p.oobe-result.error", a.error),
    footer(back(), h("div.oobe-footer-group",
      h("button.btn.btn-ghost", { onclick: () => go(next()) }, "Skip"),
      connect)),
  ];
}

/** Open a web page in the system browser (the desktop window can't navigate away). */
function openLink(event, url) {
  if (!state.info.desktop) return;
  event.preventDefault();
  call("open_url", { url });
}

// ---------- Spotify ----------

function spotify() {
  const s = (flow.accounts.spotify ||= { status: "form", error: null, result: null });
  if (s.status === "importing") {
    return h("div.oobe-center",
      h("div.spinner.oobe-spinner"),
      h("h2.oobe-heading", "Importing your Spotify history…"),
      h("p.oobe-sub", "Reading every listen in the download."));
  }
  if (s.status === "done") {
    const r = s.result;
    return h("div.oobe-center",
      h("div.oobe-success", icon("check")),
      h("h2.oobe-heading", "Got it!"),
      h("p.oobe-lead", h("b", number(r.source.play_count)), " listens",
        r.source.first_play ? [" since ", h("b", shortDate(new Date(r.source.first_play * 1000).toISOString()))] : ""),
      h("p.oobe-sub", "Request a new download from Spotify now and then and add it from the Library page to keep it current."),
      h("button.btn.btn-primary.btn-large.oobe-cta", { onclick: () => go(next()) }, "Continue", icon("arrow")));
  }
  const importFrom = async (path) => {
    if (!path) return;
    s.status = "importing";
    s.error = null;
    show("none");
    const result = await call("import_history", { kind: "spotify", path });
    if (result.error) {
      s.status = "form";
      s.error = result.error;
    } else {
      s.status = "done";
      s.result = result;
      flow.added.push(`${number(result.source.play_count)} listens from Spotify`);
    }
    if (flow.step === "spotify") show("none");
  };
  const pathInput = h("input.input", { type: "text", placeholder: "Path to my_spotify_data.zip or its folder", spellcheck: "false", "aria-label": "Spotify download" });
  return [
    h("h2.oobe-heading", "Import your Spotify history"),
    h("p.oobe-sub", "Spotify lets you download everything you've played. TunesBack reads that download."),
    h("details.oobe-help", { open: true },
      h("summary", "How do I get it?"),
      h("ol",
        h("li", "Open ", h("a", { href: LINKS.spotifyPrivacy, target: "_blank", rel: "noreferrer", onclick: (e) => openLink(e, LINKS.spotifyPrivacy) }, "Spotify's privacy settings"), " and sign in."),
        h("li", "Under “Download your data”, tick “Extended streaming history” and request it."),
        h("li", "Spotify emails you a link when it's ready. That can take a few days."),
        h("li", "Download it and choose the file here. No need to unzip it.")),
      h("p.hint", "Have the quicker “Account data” download instead? That works too, with your last year of listening.")),
    state.info.desktop
      ? h("div.oobe-options",
        h("button.oobe-option", { type: "button", onclick: async () => importFrom((await call("pick_file", { kind: "spotify" })).path) },
          h("span.oobe-option-icon", icon("download")), h("b", "Choose the download"), h("small", "The .zip file Spotify sent you")),
        h("button.oobe-option", { type: "button", onclick: async () => importFrom((await call("pick_folder")).path) },
          h("span.oobe-option-icon", icon("folder")), h("b", "Choose a folder"), h("small", "If you've already unzipped it")))
      : h("div.folder-row", pathInput, h("button.btn.btn-primary", { onclick: () => importFrom(pathInput.value.trim()) }, "Import")),
    s.error && h("p.oobe-result.error", s.error),
    footer(back(), h("button.btn.btn-ghost", { onclick: () => go(next()) }, "Skip for now")),
  ];
}

// ---------- done ----------

function done() {
  const added = flow.added;
  return h("div.oobe-center",
    h("div.oobe-success.big", icon("check")),
    h("h1.oobe-title", added.length ? "You're all set" : "Almost there"),
    added.length
      ? h("ul.oobe-summary", added.map((line) => h("li", icon("check"), line)))
      : h("p.oobe-lead", "Nothing was added yet. You can add your music any time from the Library page."),
    h("button.btn.btn-primary.btn-large.oobe-cta", {
      onclick: () => { close(); onFinish?.(); },
    }, added.length ? "See my stats" : "Go to TunesBack", icon("arrow")));
}
