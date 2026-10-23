# Research and plan: a native sidebar on Windows and macOS

Status: research done, proposal.

## The question

Can the system's own UI replace TunesBack's HTML sidebar on Windows and macOS?

## How the window is built today

pywebview gives each window one web view:
- **macOS:** an `NSWindow` holding a `WKWebView`, driven through PyObjC.
- **Windows:** a WinForms `Form` holding WebView2, driven through pythonnet.

TunesBack already reaches past pywebview to the native objects (the custom title
bar, the macOS menu bar, window moves and resizes). A native sidebar would go
further: it would change how the window is put together.

## macOS

**A. A real AppKit sidebar.** Wrap the window's content in an
`NSSplitViewController`:
- a sidebar item with a source-list `NSOutlineView` and SF Symbols icons;
- the `WKWebView` moved into the content item.

What that brings:
- the true macOS sidebar: vibrancy, the system's selection style, native
  resizing and collapsing;
- a sidebar button in an `NSToolbar` (`toggleSidebar:`);
- full keyboard support and VoiceOver;
- on **macOS 26 (Tahoe)**, the floating Liquid Glass sidebar, for free.
  AppKit's split view also extends content beneath the glass sidebar and
  provides a safe-area guide
  ([WWDC25 session 310](https://developer.apple.com/videos/play/wwdc2025/310/)).

What it costs:
- **Rebuilding pywebview's view tree after the window opens.** That relies on
  pywebview internals (how it sizes the web view, its own title bar handling),
  which can change between pywebview versions.
- **Two-way sync:** native selection becomes a `tunesback.command("view:…")`
  call into the page, and the page pushes the sidebar's model back to the
  native side: items, which are enabled, which is selected, badges.
- **Tahoe quirks:** split view dividers and glass toolbars are reported to
  misbehave
  ([forum thread](https://developer.apple.com/forums/thread/818282)).
- **Testing:** only on CI runners and real Macs; there's no macOS in this sandbox.

**B. The native material behind the HTML sidebar.** Keep the HTML sidebar and
make it transparent, with an `NSVisualEffectView` (material `.sidebar`, blending
behind the window) underneath, sized to the sidebar.
- pywebview already does a simpler version of this for its `vibrancy` option:
  a full-window effect view plus a transparent `WKWebView`.
- We'd do it for the sidebar only, so the window keeps its shadow; pywebview's
  `transparent` option turns the shadow off.
- When the sidebar is resized or hidden, the page tells Python the new width.
- Small and low-risk. It looks right on macOS 12–15, but it isn't Tahoe's
  floating glass.

## Windows

**A. WinUI 3 `NavigationView`** (the sidebar of Settings and the new apps).
It can only be hosted in a WinForms window through XAML Islands
(`DesktopWindowXamlSource`), which needs:
- the Windows App SDK runtime (installed separately or bundled, tens of MB);
- WinRT projections from pythonnet;
- careful focus and input routing between the island and WebView2.

That's a large, fragile stack for one control. **Not recommended.**

**B. Classic WinForms controls** (`TreeView`, `ListBox`). Native, but with the
Windows 7-era look, a step down from the current sidebar. **No.**

**C. Mica behind a Fluent-styled HTML sidebar.** On Windows 11 22H2+:
- **Backdrop:** call `DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE = 38, DWMSBT_MAINWINDOW)`
  for Mica, or `DWMSBT_TABBEDWINDOW` for Mica Alt
  ([docs](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type)),
  extend the frame into the client area, and make WebView2's background
  transparent.
- **Transparency limit:** WebView2 only supports fully transparent or fully
  opaque backgrounds (alpha 0 or 255), so transparency comes from the page's CSS
  ([docs](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2controller2)).
  pywebview's `transparent` option already sets the transparent background.
- **Styling:** the sidebar takes NavigationView's metrics (40 px items, the
  accent "pill" on the selected item, Segoe UI Variable, Segoe Fluent Icons).
- **Not confirmed:** whether Mica shows through a transparent WebView2 in a
  borderless window. The research didn't settle it; it needs a prototype
  ([an open pywebview issue](https://github.com/r0x0r/pywebview/issues/745)
  asks for exactly this). Windows 10 keeps the solid background.

**Related fix worth doing anyway:** with a custom title bar, Windows 11's
**Snap Layouts** flyout doesn't appear over our maximize button. Answering
`WM_NCHITTEST` with `HTMAXBUTTON` over that button (in the form's `WndProc`)
brings it back.

## Linux

Stays HTML. GTK and Qt sidebars look different on every desktop, and Kirigami
(KDE) can't be embedded in a pywebview window.

## Recommendation

1. **First, materials on both platforms (macOS B, Windows C).**
   - Most of the visual gain at little risk.
   - Each is behind a check: if the effect can't be applied (Windows 10, older
     macOS, an error), the current solid sidebar stays.
   - Ship it as an experimental flag in the Dev space first.
2. **Then, macOS A as an experiment.** A native sidebar behind the flag
   "Native sidebar (macOS)", tried on macOS 15 and 26. If it holds up on Tahoe,
   make it the default on macOS.
3. **Windows: no native NavigationView.** C plus Snap Layouts is the practical
   ceiling.

## How it would fit the app

- **The window tells the page what's in charge.** `window_info()` gains
  `sidebar: "html" | "material" | "native"`. With `"native"`, the page hides its
  own sidebar, and the resize handle and the hide button from the resizable
  sidebar work go to the native split view.
- **The page keeps the sidebar's model.** A small JSON model goes to Python
  whenever it changes:
  `[{id, label, icon, enabled, selected, badge}]`, plus the bottom group.
  Native clicks come back as the same commands the menu bar uses.
- **The same commands drive both.** Show/Hide Sidebar in the View menu and its
  shortcut work with either sidebar.

## Steps

1. Prototype on CI:
   - Windows: Mica plus transparent WebView2 on the borderless window, with
     screenshots. Check that the Windows runner supports system backdrops at all.
   - macOS: the effect view behind a transparent sidebar.
2. Ship the materials behind a Dev space flag. Collect screenshots on Windows 11
   and macOS 14/15/26.
3. Snap Layouts on the custom maximize button (Windows).
4. macOS native split view behind its own flag: view-tree surgery, sidebar
   model sync, SF Symbols, toolbar toggle, VoiceOver check.
5. Decide defaults per platform from what the screenshots and testing show.

## Questions for you

1. Is Tahoe's floating glass the look you're after on macOS? If so, step 4 is
   the one that matters.
2. On Windows, is Mica behind a Fluent-styled HTML sidebar close enough to
   "native", given that NavigationView itself isn't practical?
