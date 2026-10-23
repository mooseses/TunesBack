// First-run set-up: a few friendly steps that end with TunesBack knowing where
// your library lives and holding its first reading of it.

import { call } from "../api.js";
import { state } from "../app.js";
import { h, icon, number, relativeTime, shortDate } from "../util.js";

const STEPS = ["welcome", "apps", "location", "find", "history", "done"];
const PROGRESS = ["apps", "location", "find", "history"];
const TINTS = ["#e0284f", "#7b61ff", "#0ea5a4", "#f59e0b", "#3b82f6", "#ec4899", "#22c55e", "#8b5cf6", "#f97316"];

let root = null;
let flow = null;
let onFinish = null;

/** Show set-up. `start` skips the welcome (e.g. when adding another library). */
export function openOnboarding({ start = "welcome", finish, cancellable = false } = {}) {
  onFinish = finish;
  flow = {
    step: start, apps: new Set(["itunes"]), location: "local", root: "", catalog: [],
    search: "idle", candidates: [], selected: null, reading: null, error: null, imported: null, cancellable,
  };
  root = document.getElementById("onboarding");
  root.hidden = false;
  document.body.classList.add("onboarding-open");
  call("catalog").then((r) => { flow.catalog = r.sources || []; if (flow.step === "apps") show(); });
  show();
}

function close() {
  root.hidden = true;
  root.replaceChildren();
  document.body.classList.remove("onboarding-open");
}

function go(step) {
  const forward = STEPS.indexOf(step) >= STEPS.indexOf(flow.step);
  flow.step = step;
  show(forward ? "forward" : "back");
  if (step === "find" && flow.search === "idle") search();
}

function show(direction = "forward") {
  const body = { welcome, apps, location, find, history, done }[flow.step]();
  const page = h(`div.oobe-step.enter-${direction}`, body);
  const progress = PROGRESS.includes(flow.step) && h("div.oobe-progress", { "aria-label": `Step ${PROGRESS.indexOf(flow.step) + 1} of ${PROGRESS.length}` },
    PROGRESS.map((s, i) => h(`span${i <= PROGRESS.indexOf(flow.step) ? ".on" : ""}`)));
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

function back(step) {
  return h("button.btn.btn-ghost", { onclick: () => go(step) }, "Back");
}

// ---------- steps ----------

function welcome() {
  return h("div.oobe-center",
    h("img.oobe-logo", { src: "/assets/icon.png", alt: "" }),
    h("h1.oobe-title", "Welcome to TunesBack"),
    h("p.oobe-lead", "Your year in music, from the library you already have."),
    h("button.btn.btn-primary.btn-large.oobe-cta", { onclick: () => go("apps") },
      "Get started", icon("arrow")),
    h("p.oobe-fine", "Everything stays on this computer."));
}

function apps() {
  const tiles = (flow.catalog.length ? flow.catalog : [{ id: "itunes", name: "iTunes / Apple Music", blurb: "", available: true }])
    .map((source, i) => {
      const picked = flow.apps.has(source.id);
      const tile = h(`button.oobe-tile${picked ? ".picked" : ""}${source.available ? "" : ".soon"}`, {
        type: "button", "aria-pressed": source.available ? String(picked) : null, disabled: !source.available,
        title: source.available ? null : `${source.name} support is coming soon`,
      },
        h("span.oobe-monogram", { style: { background: TINTS[i % TINTS.length] } }, source.name[0]),
        h("span.oobe-tile-text", h("b", source.name), source.blurb && h("small", source.blurb),
          !source.available && h("span.oobe-soon", "Coming Soon!")),
        source.available && h("span.oobe-check", icon("check")));
      if (source.available) {
        tile.addEventListener("click", () => {
          if (flow.apps.has(source.id)) flow.apps.delete(source.id); else flow.apps.add(source.id);
          tile.classList.toggle("picked");
          tile.setAttribute("aria-pressed", String(flow.apps.has(source.id)));
          next.disabled = !flow.apps.size;
        });
      }
      return tile;
    });
  const next = h("button.btn.btn-primary", { disabled: !flow.apps.size, onclick: () => go("location") }, "Continue");
  return [
    h("h2.oobe-heading", "Which music apps do you use?"),
    h("p.oobe-sub", "Pick the ones you listen with. More are on the way."),
    h("div.oobe-tiles", tiles),
    footer(back("welcome"), next),
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
    oninput: (e) => { flow.root = e.target.value; next.disabled = !flow.root.trim(); },
  });
  const browse = state.info.desktop && h("button.btn", {
    onclick: async () => {
      const r = await call("pick_folder");
      if (r.path) { flow.root = rootInput.value = r.path; next.disabled = false; }
    },
  }, icon("folder"), "Browse…");
  const next = h("button.btn.btn-primary", {
    disabled: flow.location === "network" && !flow.root.trim(),
    onclick: () => { flow.search = "idle"; go("find"); },
  }, "Continue");
  return [
    h("h2.oobe-heading", "Where does your music live?"),
    h("p.oobe-sub", "TunesBack will look for your iTunes library there."),
    h("div.oobe-options",
      option("local", "computer", "On this computer", "In your Music folder or iTunes folder"),
      option("network", "server", "On a network drive", "A NAS or shared folder")),
    flow.location === "network" && h("div.oobe-network",
      h("label.label", { for: "oobe-root" }, "Network folder"),
      h("div.folder-row", rootInput, browse),
      h("p.hint", "Connect the drive first, then point TunesBack at it. It searches a few folders deep.")),
    footer(back("apps"), next),
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
      footer(back("location"), h("button.btn.btn-primary", { disabled: !flow.selected, onclick: () => useLibrary(flow.selected) }, "Use this library")),
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
    footer(back("location"), h("button.btn", { onclick: () => { flow.search = "idle"; search(); } }, icon("refresh"), "Search again")),
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
    footer(h("span"), h("button.btn.btn-primary", { onclick: () => go("done") }, result && !result.error ? "Continue" : "Skip for now")),
  ];
}

function done() {
  const r = flow.reading;
  return h("div.oobe-center",
    h("div.oobe-success.big", icon("check")),
    h("h1.oobe-title", "You're all set"),
    h("p.oobe-lead", r ? `${number(r.tracks)} songs ready to explore.` : "Your library is ready."),
    h("button.btn.btn-primary.btn-large.oobe-cta", {
      onclick: () => { close(); onFinish?.(); },
    }, "See my stats", icon("arrow")));
}
