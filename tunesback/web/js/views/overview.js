// Overview: a dashboard of widgets (views/widgets.js) arranged like tiles on the
// Windows Phone Start screen.
//
// The grid is made of square cells of one fixed size (what they are in the
// smallest window), as many columns as fit. Each widget is a tile of a fixed size:
// Medium 2×2, Wide 4×2 or Large 4×4 cells, the same at any window size, with its
// content laid out for that size (lists show the rows that fit). Tiles go in
// order, each into the first space it fits, so a later, smaller tile fills a gap
// left earlier. Customize turns on edit mode: drag to move, pick a size, remove,
// add from the panel, or reset. The order and sizes are saved in settings.

import { reducedMotion, render as renderApp, saveSettings, saveSettingsNow, state } from "../app.js";
import { h, icon, toast } from "../util.js";
import { DEFAULT_LAYOUT, shows, SIZE_LABELS, SIZE_NAMES, TILES, WIDGETS } from "./widgets.js";

let editing = false;
let flipFrom = null; // widget positions before the next redraw, to animate from
const live = h("div.sr-only", { "aria-live": "polite" });

export const isEditing = () => editing;

/** The saved layout, cleaned up: known widgets, allowed sizes, no repeats. */
function layout() {
  const saved = Array.isArray(state.settings.overview_tiles) ? state.settings.overview_tiles : DEFAULT_LAYOUT;
  const seen = new Set();
  return saved.filter((w) => WIDGETS[w?.id] && !seen.has(w.id) && seen.add(w.id))
    .map((w) => ({ id: w.id, size: WIDGETS[w.id].sizes.includes(w.size) ? w.size : WIDGETS[w.id].size }));
}

function save(next) {
  saveSettings({ overview_tiles: next });
}

// ---------- the tile grid ----------

// A cell's size (px), the same at every window size: the smallest window (980 px, with a
// sidebar up to 260 px wide and a scrollbar) fits four Medium tiles, eight cells, across.
const CELL = 70;
const GAP = 12;

/**
 * Columns for a grid this wide, in groups of four (like Windows Phone's tile groups): every
 * tile is two or four cells wide, so a Wide tile, a Large tile or a pair of Medium tiles
 * fills a group exactly and the standard layout packs without holes at any width.
 */
export function gridFor(width) {
  const fit = Math.floor((width + GAP) / (CELL + GAP));
  return { cols: Math.max(4, Math.min(24, fit - (fit % 4))), cell: CELL };
}

// ---------- the page ----------

export function render(root) {
  const report = state.report;
  const { unit, rank_by: by } = state.settings;
  const items = layout();
  const grid = h(`div.widgets${editing ? ".editing" : ""}`, { role: editing ? "list" : null, "aria-label": editing ? "Overview widgets" : null });
  for (const item of items) {
    const widget = WIDGETS[item.id];
    if (!shows(item.id, report)) {
      if (editing && item.id !== "age") grid.append(placeholder(item, widget));
      continue;
    }
    const card = widget.render(report, { by, unit });
    card.classList.add("w");
    card.dataset.id = item.id;
    card.dataset.size = item.size;
    if (editing) decorate(card, item, widget);
    grid.append(card);
  }
  root.append(grid, live);
  sizeWatch.disconnect();
  sizeWatch.observe(grid);
  if (editing) root.prepend(editBar());
  // Spans before the first paint (from the page's width), then again once the grid is in place.
  const content = document.getElementById("content");
  relayout(grid, (content?.clientWidth || 1264) - 64);
  requestAnimationFrame(() => {
    relayout(grid);
    playFlip(grid);
  });
}

/** Columns for the grid's width, each tile's place, and as much of each list as fits in its tile. */
function relayout(grid, width = grid.clientWidth) {
  const { cols, cell } = gridFor(width);
  lastWidth = width;
  lastCols = cols;
  grid.style.setProperty("--cols", cols);
  grid.style.setProperty("--cell", `${cell}px`);
  for (const card of grid.children) {
    const [w, rows] = TILES[card.dataset.size] || TILES.M;
    card.style.gridColumn = `span ${Math.min(w, cols)}`;
    card.style.gridRow = `span ${rows}`;
  }
  for (const card of grid.children) {
    fit(card);
    fitFigure(card.querySelector(".kpi > .value"));
  }
}

/** A tile's big number gets smaller until it fits on one line. */
function fitFigure(figure) {
  if (!figure) return;
  figure.style.fontSize = "";
  let size = parseFloat(getComputedStyle(figure).fontSize);
  while (figure.scrollWidth > figure.clientWidth + 0.5 && size > 18) {
    size -= 2;
    figure.style.fontSize = `${size}px`;
  }
}

// Rows of a list, chart legend or cover wall: the ones that don't fit their tile are left out.
const FIT_ITEMS = ".hbar, .mini-row, .legend > div, .cover";

function fit(card) {
  const items = [...card.querySelectorAll(FIT_ITEMS)];
  for (const item of items) item.style.display = "";
  let shown = items.length;
  while (shown > 1 && contentHeight(card) > card.clientHeight + 0.5) items[--shown].style.display = "none";
}

/** How tall a tile's content is (scrollHeight would leave out the padding below it). */
function contentHeight(card) {
  const top = card.getBoundingClientRect().top;
  const style = getComputedStyle(card);
  let bottom = 0;
  for (const child of card.children) {
    if (getComputedStyle(child).position === "absolute") continue; // the edit toolbar
    bottom = Math.max(bottom, child.getBoundingClientRect().bottom - top);
  }
  return bottom + parseFloat(style.paddingBottom) + parseFloat(style.borderBottomWidth);
}

// The grid's width changes with the window and with the sidebar (shown, hidden or resized).
let lastWidth = 0;
let resizeFrame = 0;
let lastCols = 0;
const sizeWatch = new ResizeObserver(([entry]) => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => {
    const grid = entry.target;
    if (!grid.isConnected || grid.clientWidth === lastWidth) return;
    // A change in the number of columns moves tiles: slide them to their new places.
    const before = gridFor(grid.clientWidth).cols !== lastCols ? rects(grid) : null;
    relayout(grid);
    if (before) playFlip(grid, before);
  });
});

// ---------- smooth changes ----------

function rects(grid) {
  return new Map([...grid.children].map((c) => [c.dataset.id, c.getBoundingClientRect()]));
}

/** Remember where widgets are, so the next redraw slides them to their new places. */
export function animateNext() {
  const grid = document.querySelector(".widgets");
  flipFrom = grid ? rects(grid) : null;
}

function playFlip(grid, from = flipFrom) {
  flipFrom = null;
  if (!from || reducedMotion()) return;
  for (const card of grid.children) {
    // A slide still running (the window is being resized) gives way to the new one, which
    // starts from where the tile is on screen now.
    for (const running of card.getAnimations()) running.cancel();
    const before = from.get(card.dataset.id);
    const after = card.getBoundingClientRect();
    if (!before) {
      card.animate([{ opacity: 0, transform: "scale(0.97)" }, { opacity: 1, transform: "none" }], { duration: 220, easing: "ease-out" });
      continue;
    }
    const dx = before.left - after.left;
    const dy = before.top - after.top;
    const sx = before.width / after.width;
    const sy = before.height / after.height;
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(sx - 1) < 0.01 && Math.abs(sy - 1) < 0.01) continue;
    card.animate([
      { transformOrigin: "top left", transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
      { transformOrigin: "top left", transform: "none" },
    ], { duration: 260, easing: "cubic-bezier(0.2, 0.7, 0.3, 1)" });
  }
}

/** Apply a layout change in place: reorder, resize, then slide everything into place. */
function change(next, message) {
  const grid = document.querySelector(".widgets");
  const before = grid ? rects(grid) : null;
  save(next);
  if (!grid) return renderApp();
  const order = new Map(next.map((w, i) => [w.id, i]));
  for (const card of [...grid.children].sort((a, b) => order.get(a.dataset.id) - order.get(b.dataset.id))) {
    const item = next.find((w) => w.id === card.dataset.id);
    if (item) {
      card.dataset.size = item.size;
      card.querySelectorAll(".widget-sizes button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.size === item.size)));
    }
    grid.append(card);
  }
  relayout(grid);
  playFlip(grid, before);
  if (message) live.textContent = message;
}

// ---------- edit mode ----------

/** Leaving the Overview ends editing. */
export function stopEditing() {
  editing = false;
  closeDrawer();
}

export function setEditing(on) {
  editing = on;
  animateNext();
  renderApp();
}

/** For the top bar: Customize, or the edit-mode buttons. */
export function topbarActions() {
  if (!editing) {
    return [h("button.btn.btn-icon", { onclick: () => setEditing(true), title: "Customize: move, resize, add and remove widgets",
      "aria-label": "Customize" }, icon("edit"))];
  }
  return [
    h("button.btn.btn-icon", { onclick: openDrawer, title: "Add widget", "aria-label": "Add widget" }, icon("plus")),
    h("button.btn.btn-ghost.btn-icon", { onclick: reset, title: "Back to the standard layout", "aria-label": "Reset" }, icon("undo")),
    h("button.btn.btn-primary", { onclick: () => { closeDrawer(); setEditing(false); } }, "Done"),
  ];
}

function editBar() {
  return h("div.edit-hint", icon("edit"),
    h("span", "Drag widgets to move them, pick a size, or remove the ones you don't need. With the keyboard: Alt+arrows move a widget, Alt+Shift+arrows resize it."));
}

function reset() {
  const before = state.settings.overview_tiles ?? null;
  animateNext();
  save(null);
  renderApp();
  toast("Back to the standard layout", { action: { label: "Undo", run: () => { animateNext(); save(before); renderApp(); } } });
}

function decorate(card, item, widget) {
  card.tabIndex = 0;
  card.setAttribute("role", "listitem");
  card.setAttribute("aria-label", `${widget.title}, ${SIZE_NAMES[item.size]}`);
  card.append(h("div.widget-edit",
    h("span.widget-grip", { "aria-hidden": "true", title: "Drag to move" }, grip()),
    widget.sizes.length > 1 && h("div.widget-sizes", { role: "group", "aria-label": "Size" },
      widget.sizes.map((size) => h("button", {
        type: "button", "data-size": size, "aria-pressed": String(size === item.size), title: SIZE_NAMES[size],
        onclick: () => resize(item.id, size),
      }, SIZE_LABELS[size]))),
    h("button.widget-remove", { type: "button", "aria-label": `Remove ${widget.title}`, title: "Remove", onclick: () => remove(item.id, card) }, icon("close"))));
  card.addEventListener("pointerdown", (e) => startDrag(e, card));
  card.addEventListener("keydown", (e) => keys(e, item.id));
}

function placeholder(item, widget) {
  const card = h("div.card.w.w-unavailable",
    h("div.card-title", widget.title),
    h("p.muted", widget.needs || "Nothing to show for this recap."));
  card.dataset.id = item.id;
  card.dataset.size = item.size;
  decorate(card, item, widget);
  return card;
}

function grip() {
  const span = document.createElement("span");
  span.innerHTML = '<svg viewBox="0 0 12 16" width="10" height="14" fill="currentColor" aria-hidden="true"><circle cx="3" cy="3" r="1.4"/><circle cx="9" cy="3" r="1.4"/><circle cx="3" cy="8" r="1.4"/><circle cx="9" cy="8" r="1.4"/><circle cx="3" cy="13" r="1.4"/><circle cx="9" cy="13" r="1.4"/></svg>';
  return span.firstChild;
}

function resize(id, size) {
  const next = layout().map((w) => (w.id === id ? { ...w, size } : w));
  change(next, `${WIDGETS[id].title}: ${SIZE_NAMES[size]}`);
  const card = document.querySelector(`.w[data-id="${id}"]`);
  card?.setAttribute("aria-label", `${WIDGETS[id].title}, ${SIZE_NAMES[size]}`);
}

function remove(id, card) {
  const before = layout();
  if (id === "age") {
    // The age widget's place is kept; whether it shows is its own opt-in.
    animateNext();
    saveSettingsNow({ age_overview: false }).then(renderApp);
  } else {
    card.classList.add("folding");
    setTimeout(() => { animateNext(); save(before.filter((w) => w.id !== id)); renderApp(); }, reducedMotion() ? 0 : 200);
  }
  live.textContent = `${WIDGETS[id].title} removed`;
  toast(`Removed ${WIDGETS[id].title}`, {
    action: {
      label: "Undo",
      run: () => {
        animateNext();
        if (id === "age") saveSettingsNow({ age_overview: true }).then(renderApp);
        else { save(before); renderApp(); }
      },
    },
  });
}

function move(id, delta) {
  const next = layout();
  const from = next.findIndex((w) => w.id === id);
  const to = Math.max(0, Math.min(next.length - 1, from + delta));
  if (from === to) return;
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  change(next, `${WIDGETS[id].title} moved to position ${to + 1} of ${next.length}`);
}

function keys(event, id) {
  if (!event.altKey) {
    if ((event.key === "Delete" || event.key === "Backspace") && event.target === event.currentTarget) {
      event.preventDefault();
      remove(id, event.currentTarget);
    }
    return;
  }
  const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
  const backward = event.key === "ArrowLeft" || event.key === "ArrowUp";
  if (!forward && !backward) return;
  event.preventDefault();
  if (event.shiftKey) {
    const item = layout().find((w) => w.id === id);
    const sizes = WIDGETS[id].sizes;
    const next = sizes[sizes.indexOf(item.size) + (event.key === "ArrowRight" || event.key === "ArrowUp" ? 1 : -1)];
    if (next) resize(id, next);
  } else {
    move(id, forward ? 1 : -1);
  }
  requestAnimationFrame(() => document.querySelector(`.w[data-id="${id}"]`)?.focus({ preventScroll: false }));
}

// ---------- dragging ----------

function startDrag(event, card) {
  if (event.button !== 0 || event.target.closest(".widget-sizes, .widget-remove")) return;
  event.preventDefault();
  card.focus({ preventScroll: true });
  const grid = card.parentElement;
  const id = card.dataset.id;
  const start = card.getBoundingClientRect();
  const offset = { x: event.clientX - start.left, y: event.clientY - start.top };
  const ghost = card.cloneNode(true);
  ghost.classList.add("w-ghost");
  Object.assign(ghost.style, { left: `${start.left}px`, top: `${start.top}px`, width: `${start.width}px`, height: `${start.height}px` });
  document.body.append(ghost);
  card.classList.add("w-placeholder");
  document.body.classList.add("dragging-widget");

  const scroller = document.getElementById("content");
  let pointer = { x: event.clientX, y: event.clientY };
  let lastSwap = 0;
  let frame = 0;
  let retry = 0;
  const tick = () => {
    // Scroll while the pointer is near the top or bottom of the page.
    const box = scroller.getBoundingClientRect();
    const edge = 70;
    const speed = pointer.y < box.top + edge ? -(box.top + edge - pointer.y) : pointer.y > box.bottom - edge ? pointer.y - (box.bottom - edge) : 0;
    if (speed) {
      scroller.scrollTop += speed * 0.35;
      place();
    }
    frame = requestAnimationFrame(tick);
  };
  const place = (settle = false) => {
    ghost.style.transform = `translate(${pointer.x - offset.x - start.left}px, ${pointer.y - offset.y - start.top}px)`;
    // A short pause after each move, so widgets sliding under the pointer don't make it flicker;
    // a pointer resting on a spot is placed once the pause is over.
    const wait = 140 - (performance.now() - lastSwap);
    clearTimeout(retry);
    if (wait > 0 && !settle) {
      retry = setTimeout(place, wait);
      return;
    }
    const target = document.elementFromPoint(pointer.x, pointer.y)?.closest(".w");
    if (!target || target === card || target.parentElement !== grid) return;
    const box = target.getBoundingClientRect();
    const after = pointer.x > box.left + box.width / 2;
    const next = layout();
    const from = next.findIndex((w) => w.id === id);
    const [item] = next.splice(from, 1);
    let to = next.findIndex((w) => w.id === target.dataset.id) + (after ? 1 : 0);
    next.splice(to, 0, item);
    to = next.findIndex((w) => w.id === id);
    if (to === from) return;
    lastSwap = performance.now();
    change(next);
  };
  const moveHandler = (e) => { pointer = { x: e.clientX, y: e.clientY }; place(); };
  // Listen on the window: reordering moves the card in the page, which would drop a pointer capture.
  const end = () => {
    clearTimeout(retry);
    place(true);
    cancelAnimationFrame(frame);
    window.removeEventListener("pointermove", moveHandler);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    document.body.classList.remove("dragging-widget");
    const to = card.getBoundingClientRect();
    const finish = () => { ghost.remove(); card.classList.remove("w-placeholder"); };
    if (reducedMotion()) return finish();
    ghost.style.transition = "transform 180ms cubic-bezier(0.2, 0.7, 0.3, 1)";
    ghost.style.transform = `translate(${to.left - start.left}px, ${to.top - start.top}px)`;
    setTimeout(finish, 190);
    live.textContent = `${WIDGETS[id].title} placed`;
  };
  window.addEventListener("pointermove", moveHandler);
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
  frame = requestAnimationFrame(tick);
}

// ---------- adding widgets ----------

let drawer = null;

function openDrawer() {
  closeDrawer();
  const report = state.report;
  const current = new Set(layout().map((w) => w.id));
  const hidden = Object.entries(WIDGETS).filter(([id]) =>
    (id === "age" ? state.settings.age_overview === false || !current.has(id) : !current.has(id)));
  const { unit, rank_by: by } = state.settings;
  drawer = h("aside.widget-drawer", { role: "dialog", "aria-label": "Add widgets" },
    h("div.widget-drawer-head", h("h2", "Add widgets"),
      h("button.btn.btn-ghost", { "aria-label": "Close", onclick: closeDrawer }, icon("close"))),
    h("div.widget-drawer-body",
      hidden.length ? hidden.map(([id, widget]) => {
        const ok = id === "age" || !widget.available || widget.available(report);
        let preview = null;
        if (ok) {
          try {
            preview = widget.render(report, { by, unit });
            preview.inert = true;
          } catch {
            preview = null;
          }
        }
        return h("div.widget-option",
          h("div.widget-option-text", h("b", widget.title), h("small", ok ? widget.description : widget.needs)),
          preview && h("div.widget-preview", { "aria-hidden": "true" }, preview),
          h("button.btn.btn-small", { onclick: () => add(id) }, icon("plus"), "Add"));
      }) : h("p.muted", "Every widget is already on your Overview.")));
  document.body.append(drawer);
  requestAnimationFrame(() => drawer?.classList.add("open"));
  drawer.querySelector("button")?.focus();
}

function closeDrawer() {
  if (!drawer) return;
  const old = drawer;
  drawer = null;
  old.classList.remove("open");
  setTimeout(() => old.remove(), reducedMotion() ? 0 : 220);
}

async function add(id) {
  const next = layout();
  if (!next.some((w) => w.id === id)) next.push({ id, size: WIDGETS[id].size });
  animateNext();
  save(next);
  if (id === "age") await saveSettingsNow({ age_overview: true });
  closeDrawer();
  renderApp();
  requestAnimationFrame(() => {
    const card = document.querySelector(`.w[data-id="${id}"]`);
    const content = document.getElementById("content");
    if (card && content) {
      // Scroll the page area only (scrollIntoView would also nudge the window's own layout).
      const top = card.getBoundingClientRect().top - content.getBoundingClientRect().top + content.scrollTop;
      content.scrollTo({ top: Math.max(0, top - content.clientHeight / 3), behavior: reducedMotion() ? "auto" : "smooth" });
    }
    card?.classList.add("w-new");
    card?.focus({ preventScroll: true });
  });
  live.textContent = `${WIDGETS[id].title} added`;
}
