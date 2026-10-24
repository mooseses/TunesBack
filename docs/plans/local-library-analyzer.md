# Plan: TunesBack as a local music library analyzer

Status: milestones 1–4 implemented for iTunes / Apple Music (set-up flow,
library store, discovery, automatic readings). Last.fm, ListenBrainz and
Spotify downloads followed (see cards-and-sources.md). Other players are
listed in set-up as "Coming Soon!".

Decisions so far:
- Every player is listed during set-up; unsupported ones show "Coming Soon!".
- The first reading is taken during set-up, right after the library is chosen.
  TunesBack remembers where the library is and reads it again on every launch.
- If automatic discovery or reading fails, set-up falls back to choosing the
  file or folder by hand, with export instructions.

## Goal

Today TunesBack assumes you arrive with a folder of dated iTunes exports. The
next version should work for someone who just has a music player:

1. A **start screen** on first launch.
2. A short **survey**: which players you use, and whether your library is on
   this computer or a network drive.
3. **Automatic discovery** of the library for each chosen player.
4. For counter-based sources like iTunes, **snapshots handled for you**:
   suggested, and ideally taken automatically, so comparisons "just work" over
   time.

## The key change: TunesBack keeps its own history

Most local players store only running totals (play count, skip count, last
played). Comparing two points in time needs two readings. Instead of asking
users to export files, TunesBack should **record a reading of each library every
time it opens** (when the library changed since the last reading) and keep
them in its own database. Users get:

- Lifetime stats on day one.
- Period comparisons from the second reading onward ("since you started using
  TunesBack on 3 March").
- Existing export folders can still be imported as historical readings.

Sources that already log individual plays (Rockbox playback log, Plex history,
Last.fm, ListenBrainz) skip this: their history is the log.

## Sources

| Source | What it stores | How we'd read it | Kind | First release |
|---|---|---|---|---|
| iTunes / Apple Music | Counters | Library XML (Windows iTunes, legacy macOS iTunes, manual exports); `iTunesLibrary` framework on macOS Music | counters | **yes** |
| MusicBee | Counters | Its optional iTunes-format XML export (same parser), else `.mbl` | counters | later (cheap) |
| foobar2000 | Counters (playback statistics component) | Exported statistics / component database | counters | later |
| MediaMonkey | Counters **and** play history | `MM.DB` SQLite (`Songs`, `Played` tables) | events | later |
| Strawberry / Clementine | Counters | SQLite `songs` table | counters | later |
| Rockbox | Counters + optional `playback.log` | `.rockbox/database_*.tcd`, `.rockbox/playback.log` on the mounted device | both | later |
| Plex / Plexamp | Play history | Plex Media Server API (token) or local `com.plexapp.plugins.library.db` | events | later |
| Jellyfin / Navidrome | Counters + dates | Server API / Navidrome SQLite | counters | later |

The survey lists them all; anything not implemented shows "Coming soon" and is
remembered, so we can tell users when it lands (and see which ones people want).

## First-run experience

```
Start screen ─► 1. Your players ─► 2. Where's your music? ─► 3. We found… ─► 4. History ─► Dashboard
```

**Start screen.** One sentence on what TunesBack does, a "Get started" button,
and a quiet "I already have library exports" link that jumps straight to step 3
with a folder picker (today's flow).

**1. Which players do you use?** Multi-select tiles with app icons: iTunes /
Apple Music, MusicBee, foobar2000, MediaMonkey, Rockbox, Plexamp / Plex,
Jellyfin, Navidrome, Strawberry, Other. Unimplemented ones are selectable but
badged "Coming soon"; if *only* those are picked, explain and offer to notify.

**2. Where is your library?** "On this computer", "On a network drive / NAS",
or "Both". The answer decides where discovery looks, whether we ask for a mount
point, and turns on network-friendly defaults (artwork from the thumbnail cache,
no blocking file checks, a reminder to mount shares before opening the app).

**3. We found your library.** Discovery runs per selected source and shows
candidates with name, path, track count and last-modified time. The user
confirms one or more, or browses manually. Nothing found → a short "how to find
it" with a browse button. Network: ask for the share path (`\\nas\music`,
`/Volumes/music`, `smb://…`) and offer a path-mapping test using one track.

**4. Keep a history (iTunes).** Explain in two lines why snapshots matter, then:
- **Automatic (recommended):** TunesBack records a reading each time it opens.
  On Windows iTunes this needs "Share iTunes Library XML with other
  applications" turned on; we check and show how if it's off. On macOS Music we
  read through `iTunesLibrary` (see open questions) or fall back to reminders.
- **I already export snapshots:** pick the folder; its files become history.
- **Remind me:** a monthly in-app nudge to export, with the exact menu path.

Finish on the dashboard with lifetime stats and a note like "Comparisons unlock
after your next reading".

Everything here is repeatable from **Settings → Sources** (add, remove, rescan,
change location, rerun the survey).

## iTunes discovery details

| Platform | Where | Notes |
|---|---|---|
| Windows iTunes (classic and Microsoft Store) | `%USERPROFILE%\Music\iTunes\iTunes Music Library.xml` or `iTunes Library.xml` | Custom locations: read `%APPDATA%\Apple Computer\iTunes\iTunesPrefs.xml`, which stores the library XML location (base64, UTF-16; **verify**). The XML is only written when sharing is enabled. |
| Windows "Apple Music" app | `%LOCALAPPDATA%\Packages\AppleInc.AppleMusicWin_*` | No XML known. **Verify** whether it supports Export Library; otherwise "coming soon". |
| macOS iTunes ≤ 12.9 | `~/Music/iTunes/iTunes Library.xml` | Written automatically. |
| macOS Music | `~/Music/Music/Music Library.musiclibrary` (binary) | No automatic XML. Read via `iTunesLibrary` framework, or manual File → Library → Export Library. |
| Network | User-supplied share path; scan for `*.xml` that pass the existing header check | Also look for an `iTunes` folder at the share root. |

Every candidate goes through the existing `is_library_export()` header check
before it's offered.

## Architecture

```
tunesback/
  sources/
    base.py          Source protocol + registry (id, name, kind, implemented)
    itunes_xml.py    existing parser, plus discover()
    itunes_native.py macOS iTunesLibrary reader (later in this milestone)
  store.py           SQLite in the app-data folder
  library.py         readings: take, import, list, choose two for a report
  stats/             unchanged: works on Snapshot pairs or play logs
```

- **Source protocol:** `discover(scope) -> list[Candidate]`,
  `read(candidate) -> Snapshot` (counter sources) or `plays(candidate, since)`
  (event sources), plus `kind`, `implemented`, and display metadata for the
  survey.
- **Store (SQLite):** `sources` (configured libraries and locations),
  `readings` (source, timestamp, file mtime/hash), `tracks` (stable key,
  metadata), `counts` (reading, track, plays, skips). Readings deduplicate on
  file mtime/hash, so opening the app twice records one reading. Counts are small;
  a 50k-track library is a few MB per reading, and we can thin old readings
  (keep monthly after a year).
- **Reports** take two readings (or one for lifetime) from the store instead of
  two XML paths. The existing `period_activity()` works unchanged on them.
- **Settings migration:** an existing `last_folder` becomes an "iTunes exports
  folder" source, and its files are imported as readings.
- **Network paths:** user-defined prefix mappings (`file://nas/music` →
  `/Volumes/music`) checked before the existing resolver heuristics.

## UI changes

- New first-run flow (separate views; same visual language and motion).
- "Library" in the sidebar becomes **Sources**: configured sources, their
  readings on a timeline, "Take a reading now", and import.
- Period picking moves to the top bar: a date-range picker over available
  readings (with presets: "Since last reading", "This year", "Last 12 months",
  "All time").
- Empty states that explain what will appear and when.

## Milestones

1. **Foundations:** source protocol and registry, SQLite store, readings, import
   of existing export folders, reports from stored readings, settings
   migration. Tests for store and dedupe.
2. **Onboarding UI:** start screen, survey (all sources listed, iTunes active),
   location step, results step, history step; Settings → Sources.
3. **iTunes discovery:** Windows default and custom locations, legacy macOS
   path, network scan and path mapping; "sharing is off" detection and guidance.
4. **Automatic readings:** record on launch when changed; period presets; the
   "comparisons unlock" state.
5. **macOS Music without exports:** `iTunesLibrary` reader (needs a usage
   description in the app bundle and probably signing; see below).

## Open questions

1. **Readings only when the app opens** (current), or also a lightweight
   background/scheduled task? Long gaps make periods coarse.
2. **macOS `iTunesLibrary` access:** it requires a Media Library privacy prompt
   and may need a signed app. Do we sign macOS builds (Apple Developer account)?
3. **Show unimplemented sources** as "Coming soon" (proposed) or hide them?
4. **Retention:** keep every reading, or thin to monthly after a year?
5. **Windows "Apple Music" app** support needs research before promising it.
