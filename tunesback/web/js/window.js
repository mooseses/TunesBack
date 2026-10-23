// Custom title bar, in-app menu bar, window resizing and keyboard shortcuts.
//
// The Python side tells us how the window is set up (window_info). When the
// title bar is ours, dragging and resizing are handed to the operating system
// through the API so they behave natively.

import { call } from "./api.js";
import { h } from "./util.js";

let info = null;
let hooks = null; // { run(command), isChecked(item), isEnabled(command) }
const titlebar = document.getElementById("titlebar");

const SVG = {
  minimize: '<path d="M1 5.5h9"/>',
  maximize: '<rect x="1.5" y="1.5" width="8" height="8" rx="0.5"/>',
  restore: '<rect x="1.5" y="3.5" width="6" height="6" rx="0.5"/><path d="M3.5 3.5V2a.5.5 0 0 1 .5-.5h5.5a.5.5 0 0 1 .5.5v5.5a.5.5 0 0 1-.5.5H7.5"/>',
  close: '<path d="M1.5 1.5l8 8M9.5 1.5l-8 8"/>',
  check: '<path d="M2 6l2.5 2.5L10 3"/>',
  sidebar: '<rect x="1" y="1.5" width="9" height="8" rx="1"/><path d="M4 1.5v8"/>',
};

function glyph(name) {
  const span = document.createElement("span");
  span.innerHTML = `<svg viewBox="0 0 11 11" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.1" aria-hidden="true">${SVG[name]}</svg>`;
  return span.firstChild;
}

const isMac = () => (info ? info.platform === "macos" : navigator.platform.startsWith("Mac"));

export function shortcutLabel(shortcut) {
  if (!shortcut) return "";
  if (isMac()) return shortcut.replace("Mod+", "⌘").replace("Shift+", "⇧").replace("Enter", "↩");
  return shortcut.replace("Mod+", "Ctrl+");
}

/** Called once at start-up with the window description from the server (null in a browser). */
export function initWindow(windowInfo, appHooks) {
  hooks = appHooks;
  window.tunesback = {
    command: (id) => hooks.run(id),
    // Updates are sent from different threads and can arrive out of order: keep the newest.
    windowChanged: (next) => {
      if (info && next && (next.seq ?? 0) < (info.seq ?? 0)) return;
      info = next;
      applyWindow();
    },
  };
  info = windowInfo;
  document.addEventListener("keydown", onShortcut);
  applyWindow();
}

function applyWindow() {
  const custom = !!(info && info.custom_title_bar);
  document.documentElement.classList.toggle("material-mica", !!info && info.material === "mica");
  // With the native macOS sidebar, the page's controls take on Liquid Glass to match it.
  document.documentElement.classList.toggle("material-glass", !!info && info.platform === "macos" && info.sidebar === "native");
  document.body.classList.toggle("custom-titlebar", custom && info.platform !== "macos");
  document.body.classList.toggle("mac-inset-titlebar", custom && info.platform === "macos");
  document.body.classList.toggle("maximized", !!(info && info.maximized));
  document.body.dataset.platform = info ? info.platform : "browser";
  // Our bar: the whole title bar when it's custom, or just a menu strip under a
  // system title bar when the platform has no native menu for this window.
  const menuOnly = !!info && !custom && info.menu === "html";
  titlebar.hidden = !((custom && info.platform !== "macos") || menuOnly);
  titlebar.classList.toggle("menu-only", menuOnly);
  if (!titlebar.hidden) renderTitlebar(menuOnly);
  renderResizeHandles(custom && info.platform !== "macos" && !info.maximized);
  hooks.windowChanged?.(info);
}

// ---------- title bar ----------

function renderTitlebar(menuOnly) {
  titlebar.classList.toggle("menu-hidden", hooks.menuShown?.() === false);
  if (menuOnly) {
    titlebar.replaceChildren(menubar());
    return;
  }
  const controls = h("div.titlebar-controls",
    h("button.titlebar-button", { "aria-label": "Minimize", title: "Minimize", onclick: () => call("window_minimize") }, glyph("minimize")),
    h("button.titlebar-button", {
      "aria-label": info.maximized ? "Restore" : "Maximize", title: info.maximized ? "Restore" : "Maximize",
      onclick: () => call("window_toggle_maximize"),
    }, glyph(info.maximized ? "restore" : "maximize")),
    h("button.titlebar-button.close", { "aria-label": "Close", title: "Close", onclick: () => call("window_close") }, glyph("close")));

  titlebar.replaceChildren(...[
    h("button.titlebar-button.titlebar-sidebar", { "aria-label": "Show or hide sidebar", title: "Show or hide sidebar",
      onclick: () => hooks.run("sidebar") }, glyph("sidebar")),
    h("div.titlebar-brand", h("img", { src: "/assets/icon.png", alt: "", width: 16, height: 16 }), "TunesBack"),
    info.menu === "html" && menubar(),
    h("div.titlebar-drag"),
    controls,
  ].filter(Boolean));
}

// Dragging: once the pointer moves a few pixels with the button held, hand the
// drag to the window manager. Starting on the press itself would let the
// window manager grab the pointer and swallow double-clicks.
let pending = null;
titlebar.addEventListener("mousedown", (event) => {
  if (titlebar.classList.contains("menu-only")) return;
  if (event.button !== 0 || event.target.closest("button, .menubar, .menu-popup")) return;
  event.preventDefault();
  pending = { x: event.screenX, y: event.screenY };
});
window.addEventListener("mousemove", (event) => {
  if (!pending) return;
  if (!(event.buttons & 1)) { pending = null; return; }
  if (Math.abs(event.screenX - pending.x) + Math.abs(event.screenY - pending.y) < 4) return;
  pending = null;
  call("window_start_move");
});
window.addEventListener("mouseup", () => { pending = null; });
// macOS: the page runs under a transparent title bar. A native strip drags the
// window from the top edge; the empty parts of the top bar drag it too, like a
// toolbar would.
const topbar = document.querySelector(".topbar");
const INTERACTIVE = "button, a, input, select, textarea, .segmented, .period-chip, [role=button]";
topbar.addEventListener("mousedown", (event) => {
  if (!info || info.platform !== "macos" || !info.custom_title_bar) return;
  if (event.button !== 0 || event.target.closest(INTERACTIVE)) return;
  event.preventDefault();
  pending = { x: event.screenX, y: event.screenY };
});
topbar.addEventListener("dblclick", (event) => {
  if (!info || info.platform !== "macos" || !info.custom_title_bar || event.target.closest(INTERACTIVE)) return;
  call("window_toggle_maximize");
});
titlebar.addEventListener("dblclick", (event) => {
  if (titlebar.classList.contains("menu-only") || event.target.closest("button, .menubar")) return;
  call("window_toggle_maximize");
});

function renderResizeHandles(show) {
  document.querySelectorAll(".resize-handle").forEach((el) => el.remove());
  if (!show) return;
  for (const edge of ["n", "s", "e", "w", "ne", "nw", "se", "sw"]) {
    const handle = h(`div.resize-handle.${edge}`, { "aria-hidden": "true" });
    handle.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      call("window_start_resize", { edge });
    });
    document.body.append(handle);
  }
}

// ---------- in-app menu bar ----------

/** Show or hide the menu bar in the title bar. Hidden, Alt shows it until you're done with it. */
export function setTitleBarMenu(visible) {
  titlebar.classList.toggle("menu-hidden", !visible);
  titlebar.classList.remove("menu-peek");
}

// Alt on its own (pressed and released with nothing else) shows a hidden menu bar, and hides it again.
let altAlone = false;
window.addEventListener("keydown", (event) => { altAlone = event.key === "Alt" && !event.repeat; }, true);
window.addEventListener("keyup", (event) => {
  if (event.key !== "Alt" || !altAlone || !titlebar.classList.contains("menu-hidden")) return;
  altAlone = false;
  const peek = !titlebar.classList.contains("menu-peek");
  titlebar.classList.toggle("menu-peek", peek);
  if (peek) titlebar.querySelector(".menu-trigger")?.focus();
}, true);
document.addEventListener("mousedown", (event) => {
  if (titlebar.classList.contains("menu-peek") && !event.target.closest(".menubar, .menu-popup")) titlebar.classList.remove("menu-peek");
});

let openMenu = null; // { trigger, popup }

function menubar() {
  const bar = h("div.menubar", { role: "menubar" });
  for (const menu of info.menu_spec) {
    const trigger = h("button.menu-trigger", { role: "menuitem", "aria-haspopup": "true", "aria-expanded": "false" }, menu.title);
    trigger.addEventListener("mousedown", (event) => {
      event.preventDefault();
      if (openMenu && openMenu.trigger === trigger) closeMenu();
      else showMenu(trigger, menu);
    });
    trigger.addEventListener("mouseenter", () => { if (openMenu && openMenu.trigger !== trigger) showMenu(trigger, menu); });
    trigger.addEventListener("keydown", (event) => {
      if (["Enter", " ", "ArrowDown"].includes(event.key)) {
        event.preventDefault();
        showMenu(trigger, menu, true);
      }
    });
    bar.append(trigger);
  }
  return bar;
}

function showMenu(trigger, menu, focusFirst = false) {
  closeMenu();
  const popup = h("div.menu-popup", { role: "menu", "aria-label": menu.title });
  for (const item of menu.items) {
    if (!item) {
      popup.append(h("div.menu-separator", { role: "separator" }));
      continue;
    }
    const checked = item.group ? hooks.isChecked(item) : false;
    const enabled = hooks.isEnabled(item.command);
    const row = h("button.menu-item", {
      role: item.group ? "menuitemradio" : "menuitem",
      "aria-checked": item.group ? String(checked) : null,
      disabled: !enabled,
    },
      h("span.menu-check", checked ? glyph("check") : null),
      h("span.menu-label", item.label),
      h("span.menu-shortcut", shortcutLabel(item.shortcut)));
    row.addEventListener("click", () => { closeMenu(); titlebar.classList.remove("menu-peek"); hooks.run(item.command); });
    popup.append(row);
  }
  popup.addEventListener("keydown", (event) => menuKeys(event, trigger));
  const rect = trigger.getBoundingClientRect();
  popup.style.left = `${rect.left}px`;
  popup.style.top = `${rect.bottom + 2}px`;
  document.body.append(popup);
  trigger.setAttribute("aria-expanded", "true");
  trigger.classList.add("open");
  openMenu = { trigger, popup };
  if (focusFirst) popup.querySelector(".menu-item:not(:disabled)")?.focus();
}

function closeMenu() {
  if (!openMenu) return;
  openMenu.popup.remove();
  openMenu.trigger.setAttribute("aria-expanded", "false");
  openMenu.trigger.classList.remove("open");
  openMenu = null;
}

function menuKeys(event, trigger) {
  const items = [...openMenu.popup.querySelectorAll(".menu-item:not(:disabled)")];
  const index = items.indexOf(document.activeElement);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    items[(index + step + items.length) % items.length]?.focus();
  } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
    event.preventDefault();
    const triggers = [...titlebar.querySelectorAll(".menu-trigger")];
    const next = triggers[(triggers.indexOf(trigger) + (event.key === "ArrowRight" ? 1 : -1) + triggers.length) % triggers.length];
    next.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeMenu();
    trigger.focus();
  }
}

document.addEventListener("mousedown", (event) => {
  if (openMenu && !event.target.closest(".menu-popup, .menu-trigger")) closeMenu();
});
window.addEventListener("blur", closeMenu);

// ---------- keyboard shortcuts ----------

function onShortcut(event) {
  if (info && info.platform === "macos" && info.menu === "native") return; // the menu bar owns ⌘ shortcuts
  const mod = isMac() ? event.metaKey : event.ctrlKey;
  if (!mod || event.altKey) return;
  const key = event.key === "Enter" ? "Enter" : event.key.length === 1 ? event.key.toUpperCase() : event.key;
  const pressed = `Mod+${event.shiftKey ? "Shift+" : ""}${key}`;
  const spec = info ? info.menu_spec : MENU_FALLBACK;
  for (const menu of spec) {
    for (const item of menu.items) {
      if (item && item.shortcut && item.shortcut.toUpperCase() === pressed.toUpperCase()) {
        event.preventDefault();
        if (hooks.isEnabled(item.command)) hooks.run(item.command);
        return;
      }
    }
  }
}

// Shortcuts still work in a plain browser tab, where there is no window info.
const MENU_FALLBACK = [{ items: [
  { command: "open_folder", shortcut: "Mod+O" }, { command: "generate", shortcut: "Mod+Enter" },
  { command: "settings", shortcut: "Mod+," }, { command: "view:setup", shortcut: "Mod+1" },
  { command: "view:overview", shortcut: "Mod+2" }, { command: "view:charts", shortcut: "Mod+3" },
  { command: "view:wrapped", shortcut: "Mod+4" }, { command: "view:age", shortcut: "Mod+5" },
  { command: "view:services", shortcut: "Mod+6" }, { command: "sidebar", shortcut: "Mod+B" },
] }];
