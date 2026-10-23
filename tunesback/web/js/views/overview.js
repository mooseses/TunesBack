// Overview: a dashboard of widgets (views/widgets.js) you can arrange.
//
// Widgets flow left to right on a 12-column grid. Rows are worked out from the
// whole layout, including widgets with nothing to show for this recap, so every
// widget keeps its place. Then the widgets shown in each row share its full
// width: when one is missing, the rest of its row closes the gap (and cards in a
// row share its height). Nothing jumps up from the next row. Customize turns on edit mode: drag to move, pick a size,
// remove, add from the panel, or reset. The layout is saved in settings.

import { reducedMotion, render as renderApp, saveSettings, saveSettingsNow, state } from "../app.js";
import { h, icon, toast } from "../util.js";
import { DEFAULT_LAYOUT, shows, SIZE_NAMES, SIZES, WIDGETS } from "./widgets.js";

let editing = false;
let flipFrom = null; // widget positions before the next redraw, to animate from
const live = h("div.sr-only", { "aria-live": "polite" });

export const isEditing = () => editing;

/** The saved layout, cleaned up: known widgets, allowed sizes, no repeats. */
function layout() {
  const saved = Array.isArray(state.settings.overview_layout) ? state.settings.overview_layout : DEFAULT_LAYOUT;
  const seen = new Set();
  return saved.filter((w) => WIDGETS[w?.id] && !seen.has(w.id) && seen.add(w.id))
    .map((w) => ({ id: w.id, size: WIDGETS[w.id].sizes.includes(w.size) ? w.size : WIDGETS[w.id].size }));
}

function save(next) {
  saveSettings({ overview_layout: next });
}

// ---------- packing ----------

function columnsFor(width) {
  return width >= 900 ? 12 : width >= 560 ? 6 : 1;
}

function spanFor(size, cols) {
  if (cols === 12) return SIZES[size];
  if (cols === 6) return size === "S" || size === "M" ? 3 : 6;
  return 1;
}

/**
 * Column spans for the widgets in `visible`. Rows come from every item in the layout, in
 * order; then each row's visible widgets are stretched to fill it, in proportion to their size.
 */
export function pack(items, cols, visible) {
  const rows = [];
  let row = [];
  let used = 0;
  for (const item of items) {
    const span = Math.min(cols, spanFor(item.size, cols));
    if (row.length && used + span > cols) {
      rows.push(row);
      row = [];
      used = 0;
    }
    row.push({ id: item.id, span });
    used += span;
  }
  if (row.length) rows.push(row);
  const spans = new Map();
  for (const all of rows) {
    const shown = all.filter((w) => visible.has(w.id));
    const total = shown.reduce((sum, w) => sum + w.span, 0);
    let given = 0;
    shown.forEach((w, i) => {
      const extra = i === shown.length - 1 ? cols - total - given : Math.round(((cols - total) * w.span) / total);
      given += extra;
      spans.set(w.id, w.span + extra);
    });
  }
  return spans;
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
  if (editing) root.prepend(editBar());
  // Spans before the first paint (from the page's width), then again once the grid is in place.
  const content = document.getElementById("content");
  relayout(grid, (content?.clientWidth || 1264) - 64);
  requestAnimationFrame(() => {
    relayout(grid);
    playFlip(grid);
  });
}

/** Spans for the grid (its width decides the number of columns). */
function relayout(grid, width = grid.clientWidth) {
  const cols = columnsFor(width);
  lastCols = cols;
  grid.style.setProperty("--cols", cols);
  const cards = [...grid.children];
  const spans = pack(layout(), cols, new Set(cards.map((c) => c.dataset.id)));
  for (const card of cards) card.style.gridColumn = `span ${spans.get(card.dataset.id) || cols}`;
}

let resizeTimer = null;
let lastCols = 0;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const grid = document.querySelector(".widgets");
    if (!grid) return;
    const cols = columnsFor(grid.clientWidth);
    if (cols !== lastCols) { lastCols = cols; relayout(grid); }
  }, 80);
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
    return [h("button.btn", { onclick: () => setEditing(true), title: "Move, resize, add and remove widgets" }, icon("edit"), "Customize")];
  }
  return [
    h("button.btn", { onclick: openDrawer }, icon("plus"), "Add widget"),
    h("button.btn.btn-ghost", { onclick: reset }, icon("undo"), "Reset"),
    h("button.btn.btn-primary", { onclick: () => { closeDrawer(); setEditing(false); } }, "Done"),
  ];
}

function editBar() {
  return h("div.edit-hint", icon("edit"),
    h("span", "Drag widgets to move them, pick a size, or remove the ones you don't need. With the keyboard: Alt+arrows move a widget, Alt+Shift+arrows resize it."));
}

function reset() {
  const before = state.settings.overview_layout ?? null;
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
      }, size))),
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
