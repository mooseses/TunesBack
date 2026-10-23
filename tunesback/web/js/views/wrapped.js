// Wrapped: shareable cards. Pick a format and a theme for the whole deck,
// shuffle the designs, or open a card to choose its layout and theme.

import { call, cardImageUrl } from "../api.js";
import { render as renderApp, state } from "../app.js";
import { h, icon, segmented, toast } from "../util.js";

let options = null; // card types, layouts and themes (never changes)
let loading = null; // the request for the current deck, while it runs
const shown = new Map(); // card type -> URL of the image currently on screen

/** Ask for the deck (optionally saving a changed design), then redraw. */
async function load(deck) {
  const rank_by = state.settings.rank_by;
  const request = Promise.all([
    options ? Promise.resolve(options) : call("card_options"),
    call("cards", deck ? { deck, rank_by } : { rank_by }),
  ]);
  loading = request;
  const [opts, result] = await request;
  if (loading !== request) return; // a newer request replaced this one
  loading = null;
  if (opts.error || result.error) {
    state.deck = { error: opts.error || result.error, rank: rank_by };
  } else {
    options = opts;
    state.deck = { ...result, rank: rank_by };
    const types = new Set(result.cards.map((c) => c.type));
    for (const type of state.selectedCards) if (!types.has(type)) state.selectedCards.delete(type);
  }
  if (state.view === "wrapped") renderApp();
  if (editing) renderEditor();
  if (pendingEdit && state.deck.cards) {
    const type = pendingEdit;
    pendingEdit = null;
    openEditor(type);
  }
}

const url = (card, size, extra) => cardImageUrl(card, state.deck.deck.format, size, state.deck.deck.seed, state.deck.rank, extra);
const themeName = (id) => options?.themes.find((t) => t.id === id)?.name ?? id;

export function render(root) {
  if (!state.deck || state.deck.rank !== state.settings.rank_by) {
    if (!loading) load();
    root.append(h("div.card.style-bar.skeleton"), h("div.gallery", Array.from({ length: 8 }, () => h("div.card-tile.skeleton"))));
    return;
  }
  if (state.deck.error) {
    root.append(h("div.card.empty", state.deck.error));
    return;
  }
  const { deck, cards } = state.deck;
  const visible = cards.filter((c) => !c.hidden);

  const format = segmented(options.formats.map((f) => [f.id, f.name]), deck.format,
    (value) => change({ ...deck, format: value }), "Format");
  const shuffleButton = h("button.btn", { onclick: shuffle, title: "Give every card a new design" }, icon("shuffle"), "Shuffle");

  root.append(
    h("div.card.style-bar",
      h("div.style-group", h("span.label", "Format"), format),
      h("div.style-group.grow", h("span.label", "Theme"),
        themeChips(deck.theme, (theme) => change({ ...deck, theme, cards: withoutKey(deck.cards, "theme") }))),
      shuffleButton),
    h(`div.gallery${deck.format === "square" ? ".square" : ""}`, cards.map(tile)),
    saveBar(visible));
}

function tile(card) {
  const selected = state.selectedCards.has(card.type);
  const src = url(card, "preview");
  const img = h("img", { alt: `${card.name} card`, decoding: "async" });
  const box = h(`div.card-tile${card.hidden ? ".is-hidden" : ""}${selected ? ".selected" : ""}`,
    h("button.tile-open", { type: "button", "aria-label": `Edit the ${card.name} card`, onclick: () => openEditor(card.type) },
      img, h("span.tile-edit", icon("edit"), "Edit")),
    !card.hidden && h("button.check", {
      type: "button", "aria-pressed": String(selected), "aria-label": `Select ${card.name}`,
      onclick: () => {
        if (state.selectedCards.has(card.type)) state.selectedCards.delete(card.type);
        else state.selectedCards.add(card.type);
        renderApp();
      },
    }, icon("check")),
    card.hidden && h("span.tile-hidden", icon("hidden"), "Hidden"),
    h("div.tile-meta", h("b", card.name), h("span", `${card.layout_name} · ${themeName(card.theme)}`)));
  showImage(img, box, card.type, src);
  return box;
}

/** Keep the previous image up until the new one has loaded, so changes never flash. */
function showImage(img, box, key, src) {
  const previous = shown.get(key);
  if (previous === src) {
    img.src = src;
    return;
  }
  if (previous) img.src = previous;
  box.classList.add(previous ? "updating" : "loading");
  const next = new Image();
  next.decoding = "async";
  next.onload = () => {
    img.src = src;
    shown.set(key, src);
    box.classList.remove("updating", "loading");
  };
  next.onerror = () => box.classList.remove("updating", "loading");
  next.src = src;
}

function themeChips(current, onPick, { inherit } = {}) {
  const chips = h("div.theme-chips", { role: "group", "aria-label": "Theme" });
  const entries = inherit ? [{ id: null, name: inherit }, ...options.themes.filter((t) => t.id !== "mix")] : options.themes;
  for (const theme of entries) {
    const colors = theme.id === "cover" ? state.deck.cover_swatch : theme.swatch;
    const swatch = theme.id === null ? h("span.swatch.inherit", icon("undo"))
      : h("span.swatch", { style: { background: `conic-gradient(${colors.map((c, i) => `${c} ${i * 25}% ${(i + 1) * 25}%`).join(", ")})` } });
    const chip = h("button.theme-chip", { type: "button", "aria-pressed": String(theme.id === current), title: theme.name },
      swatch, h("span", theme.name));
    chip.addEventListener("click", () => {
      if (theme.id === current) return;
      chips.querySelectorAll(".theme-chip").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
      onPick(theme.id);
    });
    chips.append(chip);
  }
  return chips;
}

function withoutKey(cards, key) {
  const out = {};
  for (const [type, choice] of Object.entries(cards)) {
    const rest = { ...choice };
    delete rest[key];
    if (Object.keys(rest).length) out[type] = rest;
  }
  return out;
}

function change(deck) {
  state.deck = { ...state.deck, deck };
  return load(deck);
}

function shuffle() {
  const before = state.deck.deck;
  const seed = 1 + Math.floor(Math.random() * 2 ** 31);
  // A shuffle redesigns every card, so per-card layouts and themes start over (hidden cards stay hidden).
  const cards = {};
  for (const [type, choice] of Object.entries(before.cards)) if (choice.hidden) cards[type] = { hidden: true };
  change({ ...before, seed, cards });
  toast("Shuffled the designs", { action: { label: "Undo", run: () => change(before) } });
}

function saveBar(visible) {
  const selected = state.selectedCards;
  return h("div.save-bar",
    h("button.btn.btn-ghost", {
      onclick: () => {
        const all = selected.size !== visible.length;
        selected.clear();
        if (all) visible.forEach((c) => selected.add(c.type));
        renderApp();
      },
    }, selected.size === visible.length ? "Select none" : "Select all"),
    h("button.btn", { disabled: !selected.size, onclick: () => save([...selected]) }, icon("download"), `Save selected (${selected.size})`),
    h("button.btn.btn-primary", { disabled: !visible.length, onclick: () => save(null) }, icon("download"), `Save all (${visible.length})`));
}

/** Save cards at full size: the given types, or every card that isn't hidden. */
export async function save(types) {
  if (!state.deck?.cards) return;
  if (!state.info.desktop) {
    // In a browser, hand the images to the browser's own downloads.
    const cards = state.deck.cards.filter((c) => (types ? types.includes(c.type) : !c.hidden));
    for (const card of cards) {
      h("a", { href: url(card, "full", { download: 1 }), download: "" }).click();
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    return;
  }
  toast("Saving…");
  const result = await call("save_cards", { types, rank_by: state.deck.rank });
  if (result.error) return toast(result.error, { error: true });
  if (result.saved) toast(`Saved ${result.saved} card${result.saved === 1 ? "" : "s"} to ${result.folder}`);
}

// ---------- the card editor ----------

let editing = null; // the card type open in the editor
let pendingEdit = null; // a card to open once the deck is drawn

/** Open a card's editor from another page, as soon as the deck is ready. */
export function editCard(type) {
  if (state.deck?.cards && state.deck.rank === state.settings.rank_by) openEditor(type);
  else pendingEdit = type;
}

function openEditor(type) {
  editing = type;
  const dialog = document.getElementById("card-dialog");
  renderEditor();
  dialog.addEventListener("close", () => { editing = null; }, { once: true });
  dialog.showModal();
}

function renderEditor() {
  const dialog = document.getElementById("card-dialog");
  const card = state.deck?.cards?.find((c) => c.type === editing);
  if (!card) {
    if (dialog.open) dialog.close();
    return;
  }
  const { deck } = state.deck;
  const own = deck.cards[card.type] || {};
  const type = options.cards.find((c) => c.id === card.type);
  const setOwn = (changes) => {
    const next = { ...own, ...changes };
    for (const key of Object.keys(next)) if (next[key] === null || next[key] === false) delete next[key];
    const cards = { ...deck.cards };
    if (Object.keys(next).length) cards[card.type] = next; else delete cards[card.type];
    change({ ...deck, cards });
  };

  const preview = h("img", { alt: `${card.name} card` });
  const frame = h(`div.editor-preview${deck.format === "square" ? ".square" : ""}`, preview);
  showImage(preview, frame, `editor:${card.type}`, url(card, "preview"));

  const layouts = h("div.layout-options", type.layouts.map((layout) => {
    const option = h("button.layout-option", { type: "button", "aria-pressed": String(layout.id === card.layout), onclick: () => setOwn({ layout: layout.id }) },
      h(`span.layout-thumb${deck.format === "square" ? ".square" : ""}`,
        h("img", { src: cardImageUrl({ ...card, layout: layout.id }, deck.format, "thumb", deck.seed, state.deck.rank), alt: "", loading: "lazy" })),
      h("span", layout.name));
    return option;
  }));
  const deckTheme = deck.theme === "mix" ? "Mix" : themeName(deck.theme);

  dialog.replaceChildren(
    h("div.dialog-head", h("h2", { id: "card-title", tabindex: "-1", autofocus: true }, card.name),
      h("button.btn.btn-ghost", { "aria-label": "Close", onclick: () => dialog.close() }, icon("close"))),
    h("div.editor",
      frame,
      h("div.editor-side",
        h("div.editor-section", h("span.label", "Layout"), layouts),
        h("div.editor-section", h("span.label", "Theme"),
          themeChips(own.theme ?? null, (theme) => setOwn({ theme }), { inherit: `Deck (${deckTheme})` })),
        h("div.editor-actions",
          h("button.btn", {
            onclick: () => {
              const pick = (list) => list[Math.floor(Math.random() * list.length)];
              const others = type.layouts.filter((l) => l.id !== card.layout);
              setOwn({
                layout: pick(others.length ? others : type.layouts).id,
                theme: pick(options.themes.filter((t) => t.id !== "mix" && t.id !== card.theme)).id,
              });
            },
          }, icon("shuffle"), "Shuffle this card"),
          h("button.btn", { onclick: () => { setOwn({ hidden: !card.hidden }); if (!card.hidden) state.selectedCards.delete(card.type); } },
            icon("hidden"), card.hidden ? "Show in deck" : "Hide from deck"),
          (own.layout || own.theme) && h("button.btn.btn-ghost", { onclick: () => setOwn({ layout: null, theme: null }) }, "Reset"),
          h("button.btn.btn-primary", { onclick: () => save([card.type]) }, icon("download"), "Save image")))),
  );
}
