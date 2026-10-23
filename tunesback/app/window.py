"""The native application window: title bar, window controls and menu bar.

With the custom title bar (the default) the window has no system frame on
Windows and Linux; the interface draws its own title bar and asks this module
to start native moves and resizes, so snapping, Wayland and multi-monitor
setups behave like any other window. On macOS the system title bar is made
transparent instead, which keeps the traffic-light buttons and native resizing.

The menu bar is native on macOS and, through Qt, in KDE Plasma's global menu.
Everywhere else the interface draws the same menu inside its title bar.
"""
from __future__ import annotations

import functools
import json
import logging
import operator
import os
import platform
import threading
from pathlib import Path
from typing import Callable, Optional

from .. import APP_NAME
from .menu import SEPARATOR, menu_for, menu_json

log = logging.getLogger(__name__)

SYSTEM = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
EDGES = ("n", "s", "e", "w", "ne", "nw", "se", "sw")
_BACKGROUNDS = {"light": "#F6F7F9", "dark": "#0F1115"}


def is_kde() -> bool:
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")


def qt_available() -> bool:
    try:
        from qtpy import QtWebEngineWidgets  # noqa: F401
        return True
    except Exception:
        return False


def preferred_gui() -> Optional[str]:
    """Qt on KDE Plasma (its menus reach the global menu bar); pywebview's default elsewhere."""
    if SYSTEM == "linux" and is_kde() and qt_available():
        return "qt"
    return None


class DesktopWindow:
    """Owns the pywebview window and everything the interface asks of it."""

    def __init__(self, url: str, title_bar: str, theme: str):
        import webview

        self.custom = title_bar == "custom"
        self._webview = webview
        self._maximized = False
        self._menu_mode = "pending"  # "native", "html" or "pending" until the window exists
        self._backend: Optional[str] = None
        self._invoke: Callable[[Callable[[], None]], None] = lambda fn: fn()

        native_menu = self._wants_native_menu()
        self.window = webview.create_window(
            APP_NAME, url,
            width=1280, height=840, min_size=(980, 660),
            background_color=_BACKGROUNDS["dark" if theme == "system" else theme],
            text_select=True,
            frameless=self.custom and SYSTEM != "macos",
            easy_drag=False,
            shadow=True,
            menu=self._native_menu() if native_menu else [],
        )
        if not native_menu:
            self._menu_mode = "html"
        self.window.events.shown += self._on_shown
        self.window.events.maximized += lambda *_: self._set_maximized(True)
        self.window.events.restored += lambda *_: self._set_maximized(False)

    # --- set-up ---

    def _wants_native_menu(self) -> bool:
        if SYSTEM == "macos":
            return True
        if SYSTEM == "windows":
            return not self.custom  # a native menu strip only fits under the system title bar
        # Linux: Qt can export the menu to a global menu bar (checked once shown).
        # GTK windows can't have their own native menu, so they use ours.
        return preferred_gui() == "qt"

    def _native_menu(self) -> list:
        from webview.menu import Menu, MenuAction, MenuSeparator

        def action(command: str) -> Callable[[], None]:
            return lambda: self.run_command(command)

        return [
            Menu(title, [MenuSeparator() if e is SEPARATOR else MenuAction(e.label, action(e.command)) for e in entries])
            for title, entries in menu_for(SYSTEM)
        ]

    def _on_shown(self) -> None:
        guilib = getattr(self._webview, "guilib", None)
        self._backend = (getattr(guilib, "__name__", "") or "").rsplit(".", 1)[-1] or None
        log.info("Window shown using the %s backend", self._backend)
        try:
            setup = {
                "winforms": self._setup_winforms,
                "qt": self._setup_qt,
                "gtk": self._setup_gtk,
                "cocoa": self._setup_cocoa,
            }.get(self._backend)
            if setup:
                setup()
        except Exception:
            log.exception("Window integration failed; falling back to basic behaviour")
        try:
            self._fit_to_screen()
        except Exception:
            log.exception("Could not fit the window to the screen")
        if self._menu_mode == "pending":
            self._menu_mode = "native"
        self._push_state()

    def _fit_to_screen(self) -> None:
        """Shrink and centre the window if it opened larger than the screen."""
        screens = getattr(self._webview, "screens", None) or []
        if not screens:
            return
        screen = screens[0]
        width, height = self.window.width, self.window.height
        if width <= screen.width * 0.95 and height <= screen.height * 0.9:
            return
        width = max(980, min(width, int(screen.width * 0.9)))
        height = max(660, min(height, int(screen.height * 0.85)))
        self.window.resize(width, height)
        self.window.move(screen.x + (screen.width - width) // 2, screen.y + max(0, (screen.height - height) // 2))
        log.info("Resized window to %dx%d to fit a %dx%d screen", width, height, screen.width, screen.height)

    # --- backends ---

    def _setup_winforms(self) -> None:
        from System import Func, Type  # provided by pythonnet, which pywebview uses on Windows

        form = self.window.native

        def invoke(fn: Callable[[], None]) -> None:
            def run():
                fn()
                return None
            if form.InvokeRequired:
                form.Invoke(Func[Type](run))
            else:
                run()

        self._invoke = invoke
        if self.custom:
            user32 = _user32()
            GWL_STYLE, WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_SYSMENU = -16, 0x00020000, 0x00010000, 0x00080000
            hwnd = form.Handle.ToInt64()

            def add_styles():
                # Without a frame, these let the taskbar button minimise and restore the window.
                style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
            invoke(add_styles)

    def _setup_qt(self) -> None:
        from qtpy.QtCore import QCoreApplication, QObject, Signal, Slot

        class Invoker(QObject):
            call = Signal(object)

            @Slot(object)
            def run(self, fn):
                fn()

        invoker = Invoker()
        invoker.call.connect(invoker.run)
        invoker.moveToThread(QCoreApplication.instance().thread())
        self._qt_invoker = invoker  # keep a reference
        self._invoke = lambda fn: invoker.call.emit(fn)

        done = threading.Event()

        def decide_menu():
            try:
                menubar = self.window.native.menuBar()
                if self._menu_mode == "pending":
                    if not self.custom or (menubar.isNativeMenuBar() and _global_menu_reliable()):
                        self._menu_mode = "native"  # global menu, or Qt's own strip under the system title bar
                    else:
                        # No global menu: draw the menu in our title bar instead of Qt's strip.
                        menubar.setNativeMenuBar(False)
                        menubar.hide()
                        self._menu_mode = "html"
            finally:
                done.set()

        self._invoke(decide_menu)
        done.wait(5)
        log.info("Qt menu bar: %s", self._menu_mode)

    def _setup_gtk(self) -> None:
        from gi.repository import GLib

        def invoke(fn: Callable[[], None]) -> None:
            def run():
                fn()
                return False
            GLib.idle_add(run)

        self._invoke = invoke

    def _setup_cocoa(self) -> None:
        from PyObjCTools import AppHelper

        self._invoke = AppHelper.callAfter
        native = self.window.native

        def setup():
            # Runs on the main thread, where exceptions would otherwise go unseen.
            try:
                # pywebview rebuilds the menu bar whenever a window becomes key and
                # it thinks the menu changed; mark ours current so it stays arranged.
                from webview.platforms.cocoa import BrowserView
                instance = BrowserView.instances.get(self.window.uid)
                if instance is not None:
                    BrowserView.current_menu = instance.menu
                _cocoa_arrange_menu()
            except Exception:
                log.exception("Could not arrange the macOS menu bar")
            if self.custom:
                try:
                    _cocoa_transparent_titlebar(native)
                    log.info("Transparent title bar applied")
                except Exception:
                    log.exception("Could not make the title bar transparent")

        AppHelper.callAfter(setup)

    # --- state for the interface ---

    def _set_maximized(self, value: bool) -> None:
        self._maximized = value
        self._push_state()

    def info(self) -> dict:
        return {
            "custom_title_bar": self.custom,
            "platform": SYSTEM,
            "backend": self._backend,
            "menu": self._menu_mode,
            "menu_spec": menu_json(SYSTEM),
            "maximized": self._maximized,
        }

    def _push_state(self) -> None:
        self._eval(f"window.tunesback && window.tunesback.windowChanged({json.dumps(self.info())})")

    def _eval(self, script: str) -> None:
        # evaluate_js waits for the page; never do that on a GUI or request thread.
        threading.Thread(target=self._safe_eval, args=(script,), daemon=True).start()

    def _safe_eval(self, script: str) -> None:
        try:
            self.window.evaluate_js(script)
        except Exception as e:
            log.debug("evaluate_js failed: %s", e)

    # --- commands ---

    def run_command(self, command: str) -> None:
        """A native menu item was chosen."""
        if command == "quit":
            self.close()
        else:
            self._eval(f"window.tunesback && window.tunesback.command({json.dumps(command)})")

    def pick_folder(self) -> Optional[str]:
        webview = self._webview
        dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        result = self.window.create_file_dialog(dialog)
        return result[0] if result else None

    def minimize(self) -> None:
        self.window.minimize()

    def toggle_maximize(self) -> None:
        if self._maximized:
            self.window.restore()
        elif self._backend == "winforms" and self.custom:
            self._invoke(self._winforms_maximize)
        else:
            self.window.maximize()

    def _winforms_maximize(self) -> None:
        # A frameless WinForms window would otherwise maximise over the taskbar.
        from System.Windows.Forms import FormWindowState, Screen

        form = self.window.native
        form.MaximizedBounds = Screen.FromHandle(form.Handle).WorkingArea
        form.WindowState = FormWindowState.Maximized

    def close(self) -> None:
        self.window.destroy()

    def start_move(self) -> None:
        """Hand the current mouse drag to the window manager."""
        if not self.custom:
            return
        backend = self._backend
        if backend == "winforms":
            self._invoke(lambda: _winforms_drag(self.window.native, 2))  # HTCAPTION
        elif backend == "qt":
            self._invoke(lambda: self.window.native.windowHandle().startSystemMove())
        elif backend == "gtk":
            self._invoke(lambda: _gtk_drag(self.window.native, None))

    def start_resize(self, edge: str) -> None:
        if not self.custom or edge not in EDGES or self._maximized:
            return
        backend = self._backend
        if backend == "winforms":
            # A frameless WinForms window has no sizing frame for Windows to use,
            # so follow the mouse ourselves until the button is released.
            form = self.window.native
            minimum = {}
            self._invoke(lambda: minimum.update(w=form.MinimumSize.Width, h=form.MinimumSize.Height))
            threading.Thread(target=_winforms_resize_loop,
                             args=(form.Handle.ToInt64(), edge, minimum.get("w", 0), minimum.get("h", 0)),
                             daemon=True).start()
        elif backend == "qt":
            from qtpy.QtCore import Qt
            flags = [flag for letter, flag in (("n", Qt.Edge.TopEdge), ("s", Qt.Edge.BottomEdge),
                                               ("e", Qt.Edge.RightEdge), ("w", Qt.Edge.LeftEdge)) if letter in edge]
            edges = functools.reduce(operator.or_, flags)
            self._invoke(lambda: self.window.native.windowHandle().startSystemResize(edges))
        elif backend == "gtk":
            self._invoke(lambda: _gtk_drag(self.window.native, edge))


# --- platform helpers ---

def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.ReleaseCapture.restype = wintypes.BOOL
    return user32


def _winforms_drag(form, hit_test: int) -> None:
    """Start a native move (HTCAPTION) or resize (HTLEFT...) as if the frame was clicked."""
    user32 = _user32()
    WM_NCLBUTTONDOWN = 0x00A1
    user32.ReleaseCapture()
    user32.SendMessageW(form.Handle.ToInt64(), WM_NCLBUTTONDOWN, hit_test, 0)


def _winforms_resize_loop(hwnd: int, edge: str, min_width: int, min_height: int) -> None:
    import ctypes
    import time
    from ctypes import wintypes

    user32 = _user32()
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    button = 0x02 if user32.GetSystemMetrics(23) else 0x01  # SM_SWAPBUTTON: left-handed mouse

    start, rect = wintypes.POINT(), wintypes.RECT()
    user32.GetCursorPos(ctypes.byref(start))
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    point = wintypes.POINT()
    while user32.GetAsyncKeyState(button) & 0x8000:
        user32.GetCursorPos(ctypes.byref(point))
        dx, dy = point.x - start.x, point.y - start.y
        new_left, new_top, new_right, new_bottom = left, top, right, bottom
        if "w" in edge:
            new_left = min(left + dx, right - min_width)
        if "e" in edge:
            new_right = max(right + dx, left + min_width)
        if "n" in edge:
            new_top = min(top + dy, bottom - min_height)
        if "s" in edge:
            new_bottom = max(bottom + dy, top + min_height)
        user32.SetWindowPos(hwnd, None, new_left, new_top, new_right - new_left, new_bottom - new_top,
                            SWP_NOZORDER | SWP_NOACTIVATE)
        time.sleep(0.012)


def _gtk_drag(window, edge: Optional[str]) -> None:
    from gi.repository import Gdk

    seat = Gdk.Display.get_default().get_default_seat()
    _, x, y = seat.get_pointer().get_position()
    if edge is None:
        window.begin_move_drag(1, x, y, Gdk.CURRENT_TIME)
        return
    edges = {
        "n": Gdk.WindowEdge.NORTH, "s": Gdk.WindowEdge.SOUTH, "e": Gdk.WindowEdge.EAST, "w": Gdk.WindowEdge.WEST,
        "ne": Gdk.WindowEdge.NORTH_EAST, "nw": Gdk.WindowEdge.NORTH_WEST,
        "se": Gdk.WindowEdge.SOUTH_EAST, "sw": Gdk.WindowEdge.SOUTH_WEST,
    }
    window.begin_resize_drag(edges[edge], 1, x, y, Gdk.CURRENT_TIME)


def _global_menu_reliable() -> bool:
    """Whether a Qt global menu will actually show up somewhere.

    On X11 Qt's own D-Bus menu support works with any Qt build. On Wayland the
    window has to be announced through KDE's protocol, which only the Plasma
    platform theme plugin does, so require it to be installed for this Qt.
    """
    from qtpy.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "wayland":
        return True
    try:
        from qtpy.QtCore import QLibraryInfo
        try:
            plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        except AttributeError:  # Qt 5
            plugins = QLibraryInfo.location(QLibraryInfo.PluginsPath)
        themes = Path(plugins) / "platformthemes"
        return any(themes.glob("KDEPlasmaPlatformTheme*"))
    except Exception:
        return False


def _cocoa_arrange_menu() -> None:
    """Make pywebview's menu bar look like a Mac app's.

    pywebview adds its own Edit and View menus; merge our View into its View,
    order the menus TunesBack, File, Edit, View, Help, move Settings into the
    app menu and give items their Command-key shortcuts.
    """
    import AppKit

    main = AppKit.NSApp.mainMenu()
    if main is None:
        return
    shortcuts = {e.label: e.shortcut for _, entries in menu_for("macos") for e in entries if e and e.shortcut}
    ours = {title for title, _ in menu_for("macos")}

    def items(menu):
        return [menu.itemAtIndex_(i) for i in range(menu.numberOfItems())]

    def titled(title):
        return [i for i in items(main) if i.submenu() is not None and i.submenu().title() == title]

    # Two "View" menus: ours contains "Library". Keep ours, append pywebview's items to it.
    views = titled("View")
    our_view = next((v for v in views if v.submenu().itemWithTitle_("Library") is not None), None)
    for other in views:
        if other is our_view or our_view is None:
            continue
        extra = items(other.submenu())
        if extra:
            our_view.submenu().addItem_(AppKit.NSMenuItem.separatorItem())
        for item in extra:
            other.submenu().removeItem_(item)
            our_view.submenu().addItem_(item)
        main.removeItem_(other)

    # Settings belongs in the app menu, after About.
    files = titled("File")
    app_menu = main.itemAtIndex_(0).submenu()
    if files and app_menu is not None:
        settings = files[0].submenu().itemWithTitle_("Settings…")
        if settings is not None:
            files[0].submenu().removeItem_(settings)
            app_menu.insertItem_atIndex_(AppKit.NSMenuItem.separatorItem(), 1)
            app_menu.insertItem_atIndex_(settings, 2)

    # Conventional order after the app menu.
    for position, title in enumerate(("File", "Edit", "View", "Help"), start=1):
        found = titled(title)
        if found and position < main.numberOfItems():
            main.removeItem_(found[0])
            main.insertItem_atIndex_(found[0], position)

    # Shortcuts, and no stray separators left behind.
    key_names = {"Enter": "\r"}
    for top in items(main):
        menu = top.submenu()
        if menu is None:
            continue
        for item in items(menu):
            shortcut = shortcuts.get(item.title())
            if shortcut and (menu.title() in ours or menu is app_menu):
                key = shortcut.split("+")[-1]
                item.setKeyEquivalent_(key_names.get(key, key.lower()))
                item.setKeyEquivalentModifierMask_(AppKit.NSCommandKeyMask)
        entries = items(menu)
        for i, item in enumerate(entries):
            if item.isSeparatorItem() and (i == 0 or i == len(entries) - 1 or entries[i - 1].isSeparatorItem()):
                menu.removeItem_(item)


_drag_view_class = None


def _cocoa_transparent_titlebar(ns_window) -> None:
    """Let the page extend under a transparent title bar, keeping the traffic lights."""
    global _drag_view_class
    import AppKit

    full_size_content = 1 << 15
    ns_window.setTitlebarAppearsTransparent_(True)
    ns_window.setTitleVisibility_(AppKit.NSWindowTitleHidden)
    ns_window.setStyleMask_(ns_window.styleMask() | full_size_content)

    # pywebview paints the title bar container with an opaque colour for
    # windows with a frame; clear it so the page shows through.
    theme_frame = ns_window.contentView().superview()
    for view in theme_frame.subviews():
        name = str(view.className())
        log.debug("Theme frame subview: %s", name)
        if "Titlebar" in name and view.respondsToSelector_("setBackgroundColor:"):
            view.setBackgroundColor_(AppKit.NSColor.clearColor())

    if _drag_view_class is None:
        class TunesBackTitlebarDragView(AppKit.NSView):
            # The web view would swallow clicks in the title area; this strip
            # gives them back to the window so it drags and zooms natively.
            def mouseDown_(self, event):
                log.debug("Title strip mouse down (clicks=%d)", event.clickCount())
                if event.clickCount() == 2:
                    self.window().performZoom_(None)
                else:
                    self.window().performWindowDragWithEvent_(event)

            def acceptsFirstMouse_(self, event):
                return True

        _drag_view_class = TunesBackTitlebarDragView

    # Attach to the window frame rather than the content view: pywebview swaps
    # the content view for the web view once the page has loaded.
    bounds = theme_frame.bounds()
    height = 28.0
    flipped = theme_frame.isFlipped()
    strip = _drag_view_class.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, 0 if flipped else bounds.size.height - height, bounds.size.width, height))
    strip.setAutoresizingMask_(AppKit.NSViewWidthSizable | (AppKit.NSViewMaxYMargin if flipped else AppKit.NSViewMinYMargin))
    theme_frame.addSubview_positioned_relativeTo_(strip, AppKit.NSWindowAbove, ns_window.contentView())
