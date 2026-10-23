"""macOS window chrome: a title strip that drags the window, and a native sidebar.

pywebview makes its WKWebView the window's content view, and a WKWebView never
lets a click move the window. With the page running under a transparent title
bar, that left nothing to drag the window by. Here the web view moves into a
container with a thin transparent strip over its top, which drags the window
(and handles double-clicks) the way a title bar does.

With the native sidebar, that container becomes the content of an
NSSplitViewController whose sidebar is an AppKit source list. On macOS 26 the
sidebar is drawn in Liquid Glass, as long as the app's executable says it was
built with the macOS 26 SDK (the release build stamps it).

Everything here runs on the main thread.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import AppKit
import objc
from Foundation import NSObject

log = logging.getLogger(__name__)

STRIP = 28  # the title bar's height: the strip that drags the window
SYMBOLS = {
    "overview": "square.grid.2x2", "charts": "list.number", "age": "hourglass", "wrapped": "sparkles",
    "setup": "folder", "services": "cloud", "dev": "testtube.2", "settings": "gearshape",
}
GROUPS = {"recap": "Your recap", "manage": "Manage"}
STATUS_COLORS = {"ok": "systemGreenColor", "busy": "systemOrangeColor", "error": "systemRedColor"}


def double_click_title_bar(window) -> None:
    """Do what the user set for double-clicking a title bar (System Settings → Desktop & Dock)."""
    action = AppKit.NSUserDefaults.standardUserDefaults().stringForKey_("AppleActionOnDoubleClick")
    if action == "Minimize":
        window.performMiniaturize_(None)
    elif action not in ("None", "Do Nothing"):
        window.performZoom_(None)


class TitleStripView(AppKit.NSView):
    """Transparent. A press drags the window; a double-click acts like a title bar's."""

    def mouseDownCanMoveWindow(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        window = self.window()
        if event.clickCount() >= 2:
            double_click_title_bar(window)
        else:
            window.performWindowDragWithEvent_(event)


def start_drag(window) -> None:
    """Start a window drag from the mouse press the page reported (if the button is still down)."""
    if not AppKit.NSEvent.pressedMouseButtons() & 1:
        return
    # The press itself went to the web view; start from where the pointer is now.
    event = AppKit.NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
        AppKit.NSEventTypeLeftMouseDown, window.mouseLocationOutsideOfEventStream(), 0,
        AppKit.NSProcessInfo.processInfo().systemUptime(), window.windowNumber(), None, 0, 1, 1.0)
    window.performWindowDragWithEvent_(event)


def make_container(webview, strip: bool):
    """A plain view holding the web view, with the title strip over its top (`strip`: the page
    runs under a transparent title bar, so nothing else would drag the window)."""
    frame = webview.frame()
    container = AppKit.NSView.alloc().initWithFrame_(frame)
    container.addSubview_(webview)
    webview.setFrame_(container.bounds())
    webview.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
    if strip:
        width, height = frame.size.width, frame.size.height
        view = TitleStripView.alloc().initWithFrame_(((0, height - STRIP), (width, STRIP)))
        view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
        container.addSubview_(view)  # above the web view
    return container


def _protocols(*names):
    found = []
    for name in names:
        try:
            found.append(objc.protocolNamed(name))
        except Exception:
            log.debug("Protocol %s not found", name)
    return found


class SidebarController(NSObject, protocols=_protocols("NSTableViewDataSource", "NSTableViewDelegate")):
    """A source list mirroring the page's sidebar. Rows are group headers and items."""

    def init(self):
        self = objc.super(SidebarController, self).init()
        if self is None:
            return None
        self.rows = []
        self.on_select = None
        self.updating = False
        self.table = None
        return self

    # data source

    def numberOfRowsInTableView_(self, table):
        return len(self.rows)

    # delegate

    def tableView_isGroupRow_(self, table, row):
        return self.rows[row]["kind"] == "header"

    def tableView_shouldSelectRow_(self, table, row):
        r = self.rows[row]
        return r["kind"] == "item" and r.get("enabled", True)

    def tableView_heightOfRow_(self, table, row):
        return 24.0 if self.rows[row]["kind"] == "header" else 30.0

    def tableView_viewForTableColumn_row_(self, table, column, row):
        r = self.rows[row]
        width = column.width() if column is not None else table.frame().size.width
        height = self.tableView_heightOfRow_(table, row)
        cell = AppKit.NSTableCellView.alloc().initWithFrame_(((0, 0), (width, height)))
        if r["kind"] == "header":
            text = AppKit.NSTextField.labelWithString_(r["label"])
            text.setFont_(AppKit.NSFont.systemFontOfSize_weight_(11, AppKit.NSFontWeightSemibold))
            text.setTextColor_(AppKit.NSColor.secondaryLabelColor())
            text.setFrame_(((2, 4), (width - 4, 16)))
            text.setAutoresizingMask_(AppKit.NSViewWidthSizable)
            cell.addSubview_(text)
            cell.setTextField_(text)
            return cell
        enabled = r.get("enabled", True)
        image = AppKit.NSImageView.alloc().initWithFrame_(((2, (height - 18) / 2), (20, 18)))
        symbol = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(SYMBOLS.get(r["id"], "circle"), None)
        if symbol is not None:
            image.setImage_(symbol)
        image.setContentTintColor_(AppKit.NSColor.controlAccentColor() if enabled else AppKit.NSColor.tertiaryLabelColor())
        cell.addSubview_(image)
        cell.setImageView_(image)
        trailing = 18 if r.get("status") else 4
        text = AppKit.NSTextField.labelWithString_(r["label"])
        text.setFrame_(((28, (height - 17) / 2), (width - 28 - trailing, 17)))
        text.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        text.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        if not enabled:
            text.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
        cell.addSubview_(text)
        cell.setTextField_(text)
        if r.get("status") in STATUS_COLORS:
            dot = AppKit.NSView.alloc().initWithFrame_(((width - 14, (height - 7) / 2), (7, 7)))
            dot.setWantsLayer_(True)
            dot.layer().setCornerRadius_(3.5)
            dot.layer().setBackgroundColor_(getattr(AppKit.NSColor, STATUS_COLORS[r["status"]])().CGColor())
            dot.setAutoresizingMask_(AppKit.NSViewMinXMargin)
            cell.addSubview_(dot)
        return cell

    def tableViewSelectionDidChange_(self, notification):
        if self.updating or self.table is None:
            return
        row = self.table.selectedRow()
        if 0 <= row < len(self.rows) and self.on_select is not None:
            self.on_select(self.rows[row]["id"])

    # from the page

    @objc.python_method
    def apply(self, model: dict) -> None:
        """Show the page's sidebar model: {"items": [{id, label, group, enabled, hidden, status}], "active": id}."""
        rows, group = [], None
        for item in model.get("items", []):
            if item.get("hidden"):
                continue
            if item.get("group") != group:
                group = item.get("group")
                if group in GROUPS:
                    rows.append({"kind": "header", "label": GROUPS[group], "id": f"group:{group}"})
            rows.append({"kind": "item", **item})
        self.updating = True
        try:
            self.rows = rows
            self.table.reloadData()
            active = next((i for i, r in enumerate(rows) if r["kind"] == "item" and r["id"] == model.get("active")), -1)
            if active >= 0:
                self.table.selectRowIndexes_byExtendingSelection_(AppKit.NSIndexSet.indexSetWithIndex_(active), False)
            else:
                self.table.deselectAll_(None)
        finally:
            self.updating = False


class Chrome:
    """What TunesBack adds to its macOS window. Created on the main thread once the window shows."""

    def __init__(self, ns_window, webview, native_sidebar: bool, strip: bool, on_select: Callable[[str], None]):
        self.window = ns_window
        self.webview = webview
        self.custom_title_bar = strip  # the page runs under a transparent title bar
        self.split = None
        self.sidebar_item = None
        self.sidebar: Optional[SidebarController] = None
        self._collapsed_before_hiding: Optional[bool] = None
        container = make_container(webview, strip)
        if native_sidebar:
            try:
                self._install_sidebar(container, on_select)
            except Exception:
                log.exception("Native sidebar failed; using the page's own")
                self.split = None
        if self.split is None:
            self.window.setContentView_(container)
        self.window.makeFirstResponder_(webview)

    @property
    def native_sidebar(self) -> bool:
        return self.split is not None

    def _install_sidebar(self, container, on_select) -> None:
        sidebar = SidebarController.alloc().init()
        sidebar.on_select = on_select
        table = AppKit.NSTableView.alloc().initWithFrame_(((0, 0), (220, 400)))
        column = AppKit.NSTableColumn.alloc().initWithIdentifier_("item")
        column.setResizingMask_(AppKit.NSTableColumnAutoresizingMask)
        table.addTableColumn_(column)
        table.setHeaderView_(None)
        table.setColumnAutoresizingStyle_(AppKit.NSTableViewUniformColumnAutoresizingStyle)
        if hasattr(AppKit, "NSTableViewStyleSourceList"):
            table.setStyle_(AppKit.NSTableViewStyleSourceList)
        else:
            table.setSelectionHighlightStyle_(AppKit.NSTableViewSelectionHighlightStyleSourceList)
        table.setBackgroundColor_(AppKit.NSColor.clearColor())
        table.setDataSource_(sidebar)
        table.setDelegate_(sidebar)
        sidebar.table = table

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(((0, 0), (220, 400)))
        scroll.setDocumentView_(table)
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)

        sidebar_vc = AppKit.NSViewController.alloc().init()
        sidebar_vc.setView_(scroll)
        content_vc = AppKit.NSViewController.alloc().init()
        content_vc.setView_(container)

        split = AppKit.NSSplitViewController.alloc().init()
        item = AppKit.NSSplitViewItem.sidebarWithViewController_(sidebar_vc)
        item.setMinimumThickness_(180)
        item.setMaximumThickness_(320)
        item.setCanCollapse_(True)
        if item.respondsToSelector_("setAllowsFullHeightLayout:"):
            item.setAllowsFullHeightLayout_(True)
        split.addSplitViewItem_(item)
        split.addSplitViewItem_(AppKit.NSSplitViewItem.splitViewItemWithViewController_(content_vc))

        frame = self.window.frame()
        self.window.setContentViewController_(split)
        self.window.setFrame_display_(frame, True)  # setting a view controller resizes the window to fit it
        split.splitView().setAutosaveName_("TunesBack Sidebar")
        if not AppKit.NSUserDefaults.standardUserDefaults().objectForKey_("NSSplitView Subview Frames TunesBack Sidebar"):
            split.splitView().setPosition_ofDividerAtIndex_(220, 0)
        self.split, self.sidebar_item, self.sidebar = split, item, sidebar
        log.info("Native sidebar installed")

    # --- requests from the page ---

    def set_sidebar_model(self, model: dict) -> None:
        if self.sidebar is not None:
            self.sidebar.apply(model)

    def toggle_sidebar(self) -> None:
        if self.sidebar_item is not None:
            self.sidebar_item.animator().setCollapsed_(not self.sidebar_item.isCollapsed())

    def set_controls_visible(self, visible: bool) -> None:
        """Hide the traffic lights (and the native sidebar) while set-up covers the window."""
        if self.custom_title_bar:  # with the system's title bar, set-up doesn't cover the buttons
            for button in (AppKit.NSWindowCloseButton, AppKit.NSWindowMiniaturizeButton, AppKit.NSWindowZoomButton):
                control = self.window.standardWindowButton_(button)
                if control is not None:
                    control.setHidden_(not visible)
        if self.sidebar_item is None:
            return
        if not visible:
            if self._collapsed_before_hiding is None:
                self._collapsed_before_hiding = bool(self.sidebar_item.isCollapsed())
            self.sidebar_item.setCollapsed_(True)
        elif self._collapsed_before_hiding is not None:
            self.sidebar_item.setCollapsed_(self._collapsed_before_hiding)
            self._collapsed_before_hiding = None


def set_appearance(theme: str) -> None:
    """Follow TunesBack's theme in the window's native parts (title bar, sidebar)."""
    names = {"dark": AppKit.NSAppearanceNameDarkAqua, "light": AppKit.NSAppearanceNameAqua}
    AppKit.NSApp.setAppearance_(AppKit.NSAppearance.appearanceNamed_(names[theme]) if theme in names else None)
