// DOM, formatting and feedback helpers shared by every view.

/** Create an element: h("div.card.wide", {onclick}, child, "text", [more]) */
export function h(tag, attrs, ...children) {
  const [name, ...classes] = tag.split(".");
  const el = document.createElement(name || "div");
  if (classes.length) el.className = classes.join(" ");
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key === "html") el.innerHTML = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

const ICONS = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  charts: '<path d="M4 6h10M4 12h16M4 18h7"/>',
  wrapped: '<path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  library: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  song: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  album: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  artist: '<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v4M8 21h8"/>',
  genre: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  year: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  new: '<path d="M12 2l2.9 6.9L22 9.3l-5.5 4.8 1.7 7.2L12 17.5l-6.2 3.8 1.7-7.2L2 9.3l7.1-.4z"/>',
  skip: '<path d="M5 4l10 8-10 8zM19 5v14"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  computer: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  shuffle: '<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  hidden: '<path d="M9.9 4.2A10 10 0 0 1 12 4c7 0 10 8 10 8a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3 8 10 8a9.7 9.7 0 0 0 5.4-1.6M3 3l18 18M14.1 14.1a3 3 0 0 1-4.2-4.2"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
};

export function icon(name) {
  const span = document.createElement("span");
  span.innerHTML = `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  return span.firstChild;
}

// ---------- formatting ----------

const UNITS = {
  hours: { ms: 3.6e6, short: "h", long: "hours" },
  minutes: { ms: 6e4, short: "min", long: "minutes" },
  days: { ms: 8.64e7, short: "d", long: "days" },
};

export const unitInfo = (unit) => UNITS[unit] || UNITS.hours;

export function duration(ms, unit) {
  const value = ms / unitInfo(unit).ms;
  const digits = value >= 100 || unit === "minutes" ? 0 : 1;
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export const number = (n) => Number(n).toLocaleString();

export function shortDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

export function fileSize(bytes) {
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export function relativeTime(iso) {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  const units = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return format.format(-Math.round(seconds / size), unit);
  }
  return "just now";
}

export const plural = (n, word) => `${number(n)} ${word}${n === 1 ? "" : "s"}`;

// ---------- feedback ----------

/** A short message at the bottom. `action` ({label, run}) adds a button, e.g. Undo. */
export function toast(message, { error = false, timeout = 3200, action = null } = {}) {
  const el = h(`div.toast${error ? ".error" : ""}`, { role: error ? "alert" : "status" }, message,
    action && h("button.toast-action", { type: "button", onclick: () => { el.remove(); action.run(); } }, action.label));
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), action ? Math.max(timeout, 6000) : timeout);
}

export function showMessage(title, message) {
  const dialog = document.getElementById("message-dialog");
  dialog.replaceChildren(
    h("div.dialog-head", h("h2", { id: "message-title", tabindex: "-1", autofocus: true }, title)),
    h("div.dialog-body", h("p", message)),
    h("div.dialog-foot", h("button.btn.btn-primary", { onclick: () => dialog.close() }, "OK")),
  );
  dialog.showModal();
}

/** An in-app yes/no question; resolves to true when confirmed. */
export function confirmAction(title, message, confirmLabel) {
  const dialog = document.getElementById("message-dialog");
  return new Promise((resolve) => {
    const finish = (value) => { dialog.close(); resolve(value); };
    dialog.replaceChildren(
      h("div.dialog-head", h("h2", { id: "message-title", tabindex: "-1", autofocus: true }, title)),
      h("div.dialog-body", h("p", message)),
      h("div.dialog-foot",
        h("button.btn", { onclick: () => finish(false) }, "Cancel"),
        h("button.btn.btn-primary", { onclick: () => finish(true) }, confirmLabel)));
    dialog.addEventListener("cancel", () => resolve(false), { once: true });
    dialog.showModal();
  });
}

/**
 * A row of mutually exclusive options with an indicator that slides to the
 * chosen one. `group.setValue(key)` moves it without firing onChange.
 */
export function segmented(options, value, onChange, label) {
  const group = h("div.segmented", { role: "group", "aria-label": label });
  const indicator = h("span.segmented-indicator", { "aria-hidden": "true" });
  group.append(indicator);
  const buttons = new Map();
  let current = value;

  const place = (animate) => {
    const button = buttons.get(current);
    if (!button || !button.offsetWidth) return;
    group.classList.toggle("animate", animate);
    indicator.style.width = `${button.offsetWidth}px`;
    indicator.style.transform = `translateX(${button.offsetLeft - 3}px)`;
    indicator.style.opacity = "1";
  };

  group.setValue = (key, animate = true) => {
    current = key;
    buttons.forEach((b, k) => b.setAttribute("aria-pressed", String(k === key)));
    place(animate);
  };

  for (const [key, text] of options) {
    const button = h("button", { type: "button", "aria-pressed": String(key === value) }, text);
    button.addEventListener("click", () => {
      if (current === key) return;
      group.setValue(key);
      onChange(key);
    });
    buttons.set(key, button);
    group.append(button);
  }
  // Position without animation once laid out (and again if fonts or size change).
  new ResizeObserver(() => place(false)).observe(group);
  return group;
}
