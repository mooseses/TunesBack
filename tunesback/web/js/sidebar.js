// The sidebar: drag its edge to resize it, drag it narrow enough (or press the
// button, the menu item or Ctrl/Cmd+B) to hide it. Width and visibility are saved.

import { call } from "./api.js";
import { icon } from "./util.js";

const MIN = 180;
const MAX = 360;
const HIDE_BELOW = 130; // dragging narrower than this hides the sidebar on release
const DEFAULT = 220;

let nav, resizer, settings, save;
let native = false; // macOS: an AppKit sidebar replaces the page's (see app/macos.py)

export function initSidebar(currentSettings, saveSettings) {
  settings = currentSettings;
  save = saveSettings;
  nav = document.getElementById("nav");
  resizer = document.getElementById("nav-resizer");
  document.getElementById("hide-sidebar").append(icon("sidebar"));
  document.getElementById("show-sidebar").append(icon("sidebar"));
  document.getElementById("hide-sidebar").addEventListener("click", () => setHidden(true));
  document.getElementById("show-sidebar").addEventListener("click", () => (native ? toggleSidebar() : setHidden(false)));
  setWidth(settings.sidebar_width || DEFAULT);
  apply(!!settings.sidebar_hidden, false);

  resizer.addEventListener("pointerdown", startDrag);
  resizer.addEventListener("dblclick", () => { setWidth(DEFAULT); save({ sidebar_width: DEFAULT }); });
  resizer.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 40 : 10;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const width = clamp(currentWidth() + (event.key === "ArrowRight" ? step : -step));
      setWidth(width);
      save({ sidebar_width: width });
    }
  });
}

export function toggleSidebar() {
  if (native) call("window_toggle_sidebar");
  else setHidden(!document.body.classList.contains("sidebar-hidden"));
}

/** The window has a native sidebar: hide ours, and keep a toggle in the top bar. */
export function setNativeSidebar(on) {
  native = on;
  document.body.classList.toggle("native-sidebar", on);
  const show = document.getElementById("show-sidebar");
  show.hidden = !on && !document.body.classList.contains("sidebar-hidden");
  show.title = on ? "Show or hide sidebar" : "Show sidebar";
  show.setAttribute("aria-label", show.title);
}

const clamp = (width) => Math.round(Math.min(MAX, Math.max(MIN, width)));
const currentWidth = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width")) || DEFAULT;

function setWidth(width) {
  document.documentElement.style.setProperty("--sidebar-width", `${clamp(width)}px`);
  resizer.setAttribute("aria-valuenow", String(clamp(width)));
}

function setHidden(hidden) {
  apply(hidden, true);
  save({ sidebar_hidden: hidden });
}

function apply(hidden, animate) {
  document.body.classList.toggle("sidebar-animate", animate);
  document.body.classList.toggle("sidebar-hidden", hidden);
  nav.setAttribute("aria-hidden", String(hidden));
  nav.inert = hidden;
  document.getElementById("show-sidebar").hidden = !hidden && !native;
  if (animate) setTimeout(() => document.body.classList.remove("sidebar-animate"), 260);
}

function startDrag(event) {
  if (event.button !== 0) return;
  event.preventDefault();
  resizer.setPointerCapture(event.pointerId);
  const left = nav.getBoundingClientRect().left;
  document.body.classList.add("sidebar-resizing");
  let wanted = currentWidth();
  const move = (e) => {
    wanted = e.clientX - left;
    nav.classList.toggle("will-hide", wanted < HIDE_BELOW);
    setWidth(wanted);
  };
  const end = () => {
    resizer.removeEventListener("pointermove", move);
    document.body.classList.remove("sidebar-resizing");
    nav.classList.remove("will-hide");
    if (wanted < HIDE_BELOW) {
      setWidth(settings.sidebar_width || DEFAULT);
      setHidden(true);
    } else {
      save({ sidebar_width: clamp(wanted) });
    }
  };
  resizer.addEventListener("pointermove", move);
  resizer.addEventListener("pointerup", end, { once: true });
  resizer.addEventListener("pointercancel", end, { once: true });
}
