# Research and plan: a native sidebar on Windows and macOS

Status: built (October 23, 2026). Windows: a Fluent-styled HTML sidebar on Mica (Windows 11 22H2
and later), in `app/window.py`. macOS: a real AppKit sidebar (`app/macos.py`), in Liquid Glass on
macOS 26 because the release build stamps the launcher with the macOS 26 SDK. Both can be turned
off in Settings, and fall back to the page's own sidebar if anything fails.

## Decisions

1. **macOS: the Tahoe floating glass sidebar is the target.** That means option A below (a real
   `NSSplitViewController` sidebar), no longer just an experiment. It's built behind a Dev space
   flag first, then becomes the default on macOS once it holds up on 15 and 26.
2. **Windows: a Fluent-styled HTML sidebar on Mica comes first** (option C). The scope comparison
   below explains why. A native WinUI sidebar is reconsidered only if the Mica prototype fails.

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

## Windows: native WinUI versus Fluent HTML on Mica

Both put Mica behind the sidebar. The difference is who draws the sidebar itself.

| | Truly native (WinUI 3 `NavigationView`) | Fluent-styled HTML on Mica |
|---|---|---|
| What gets built | Either a WinUI island (`DesktopWindowXamlSource`) inside today's WinForms window, or a second window backend: a WinUI 3 window holding its own WebView2, with title bar, drag, resize, menus and file dialogs reimplemented | One window attribute (`DWMWA_SYSTEMBACKDROP_TYPE`), the frame extended into the client area, a transparent WebView2 background, and CSS for the sidebar |
| New dependencies | The Windows App Runtime, installed separately or bundled self-contained, plus PyWinRT's `winui3-*` packages | None |
| Python support | PyWinRT's WinUI 3 bindings are community-maintained. Unpackaged apps must call the bootstrapper at start-up, and that call fails on Microsoft Store Python ([PyWinRT docs](https://pywinrt.readthedocs.io/en/stable/api/winui3/index.html)) | Plain `ctypes` calls, the same way the custom title bar already reaches past pywebview |
| Known risks | XAML Islands were tested only with C++ apps when they arrived in Windows App SDK 1.4 ([release notes](https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/release-notes/windows-app-sdk-1-4)). Focus and keyboard routing between the island and WebView2. PyInstaller packaging of the runtime | Whether Mica shows through a transparent WebView2 in our borderless form. Community reports go both ways: it works when the frame is extended with margins of -1 and the client area painted black, and fails without that. That's what the prototype settles |
| Windows versions | Windows 10 1809+ for WinUI; Mica on 11 only | Mica on Windows 11 22H2+; earlier versions keep today's solid sidebar |
| Linux and macOS | Windows-only code, a third sidebar to keep in step | The same HTML sidebar everywhere, restyled per platform |
| Rough size | Weeks: a window backend or an island host, model syncing, packaging and CI | Days: about 100 lines of Python, CSS, and CI screenshots |
| What users get | The exact Windows 11 Settings look, including system animations and accessibility for free | Very close to it: Mica, 40 px items, the accent pill, Segoe UI Variable and Segoe Fluent Icons; keyboard and screen reader support stays ours to keep right |

**Decision: Fluent HTML on Mica.** It delivers almost all of the native look for a small fraction of
the work, adds no runtime to install, keeps one sidebar for every platform, and can be switched off
at once if something goes wrong. Native WinUI would buy the last few percent of authenticity at the
cost of a second window stack and a dependency we'd have to ship and support.

**The gate:** a CI prototype on the Windows runner (screenshots of Mica behind a transparent WebView2
in the borderless form). If Mica can't be made to show through, the options are a solid Fluent
sidebar (still option C, without the material), or reopening the WinUI route with that evidence.

## Linux

Stays HTML. GTK and Qt sidebars look different on every desktop, and Kirigami
(KDE) can't be embedded in a pywebview window.

## Plan

1. **Windows: Mica prototype (the gate).** Mica behind a transparent WebView2 in the borderless
   form, behind the Dev space flag "Mica (Windows)", with CI screenshots on Windows 11.
2. **Windows: the Fluent sidebar.** NavigationView's metrics and accent pill in CSS, Segoe UI
   Variable and Segoe Fluent Icons, plus Snap Layouts on the maximize button.
3. **macOS: the native sidebar** (option A), aiming at Tahoe's floating glass, behind the flag
   "Native sidebar (macOS)", tried on macOS 15 and 26; then the default on macOS.
4. **macOS before 26 or if A misbehaves:** option B (the sidebar material behind the HTML sidebar)
   is the fallback.
5. Linux keeps the HTML sidebar.

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

1. Windows Mica prototype on CI, with screenshots. Check that the Windows runner supports system
   backdrops at all (a Windows Server image may not; if not, a manual check on Windows 11).
2. Windows Fluent sidebar styles and Snap Layouts.
3. macOS native split view behind its flag: view-tree surgery, sidebar model sync, SF Symbols,
   toolbar toggle, VoiceOver check; screenshots on the macOS 15 and 26 runners.
4. Defaults per platform from what the screenshots and testing show.
