# Changelog

Each release's section here becomes its notes on GitHub (`packaging/release_notes.py`).

## 2.0.0b1

**TunesBack 2.0 Beta 1.** A rebuilt TunesBack: more sources, an Overview you arrange yourself, Wrapped cards, and a window that feels at home on each system. This is a beta, so expect rough edges; please [report what you find](https://github.com/mooseses/TunesBack/issues/new/choose).

### New

- **More sources:** Last.fm and ListenBrainz (every scrobble, with when you played it) and Spotify's listening history download, alongside iTunes / Apple Music. Use them on their own or together, without counting the same listen twice.
- **When you listen:** listening by hour and weekday, month by month, your longest streak, busiest day and the artists you discovered (for sources with listening times).
- **Overview tiles:** widgets arranged like the Windows Phone Start screen (Medium, Wide and Large tiles); add, remove, resize and rearrange them.
- **Wrapped cards:** story or square images in several layouts and nine themes, with Shuffle, Mix and per-card editing.
- **Listening Age** has its own page, with the calculation explained using your own numbers. It's opt-in for the Overview and Wrapped.
- **Services page:** sync status, history imported and recent syncs for your accounts.
- **Native window styles:** the macOS sidebar and Liquid Glass controls on macOS Tahoe, Mica on Windows 11, a menu bar everywhere (the global menu on KDE Plasma).
- **Check for updates** from About TunesBack, and once a day on its own (you can turn that off in Settings).
- **Privacy policy:** TunesBack collects no data. It lists every online service TunesBack talks to, including GitHub for update checks.

### Downloads

- **Intel Macs** have their own download again (fixes [#5](https://github.com/mooseses/TunesBack/issues/5)).
- **Linux:** `.deb`, `.rpm`, Arch (`.pkg.tar.zst`), Flatpak and AppImage, plus a `.tar.gz`.
- **Windows:** a portable `.zip` next to the installer.
- The app icon is sized like other apps' in the Dock, taskbar and launchers (fixes [#6](https://github.com/mooseses/TunesBack/issues/6)).

### Changed

- The interface is now a web page in a native window (pywebview) instead of Flet, so it starts faster and looks the same everywhere.
