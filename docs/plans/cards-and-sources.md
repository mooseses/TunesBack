# Plan: card designs (phase 3) and listening history sources (phase 4)

Status: implemented. Two changes from the plan as first written:

- **Shuffle** starts every card over (per-card layouts and themes are reset;
  hidden cards stay hidden) rather than skipping cards you changed, so it
  always visibly does something. Undo brings the previous design back.
- A newer **Spotify download** goes into the existing Spotify source
  (listens already there are skipped) instead of becoming a second source.

## Where this lands in the app

Nothing gets a new top-level page. Each part goes where people already look:

| Part | Where it shows up |
|---|---|
| Card designs | **Wrapped**: a style bar above the cards (format, theme, shuffle) and a card editor that opens when you click a card |
| Last.fm, ListenBrainz, Spotify | **Set-up** (they stop being "Coming Soon!"), the **Library** page (sources list, sync) and the menu |
| Picking sources and dates | The **Recap** card on the Library page (source picker, date presets) |
| Listening patterns | **Overview**: a "When you listen" section when the period has timestamps, and a short invitation to connect a scrobbler when it doesn't |
| New stats | New cards in **Wrapped** (listening clock, week, months, streak, discoveries) |

## Phase 3: the card engine

### Rendering: SVG + resvg

Cards are built as SVG and rasterised with [resvg](https://github.com/linebender/resvg)
(the `resvg-py` wheel: abi3, Windows/macOS/Linux, no system libraries).
The old Pillow code drew everything by hand; SVG gives anti-aliased shapes,
gradients, clipping (rounded artwork), opacity and real typography for free,
and a design reads like what it draws.

Measured on 1080×1920:

| What | Time |
|---|---|
| Text, shapes, artwork | ~70 ms |
| `feGaussianBlur` (large) | ~840 ms |
| `feTurbulence` grain | ~2.1 s |
| Loading all system fonts | ~3.5 s, on every call |

So:

- **No SVG filters.** Soft things (glows, blurred colour blobs, shadows) are drawn
  by Pillow on a small "backdrop" (¼ scale, blurred, scaled up), then the crisp
  SVG layer goes on top. Film grain is a cached noise tile, blended in Pillow.
- **Fonts are passed explicitly**: the bundled fonts, plus a fallback font for
  any characters they don't cover (CJK, Arabic, Cyrillic...). This is found
  once per session by reading the `cmap` tables of the system's fonts, with
  well-known fonts first (Noto, Segoe UI, Yu Gothic, Malgun, PingFang/Hiragino,
  Arial Unicode...). Text with only Latin letters never touches system fonts.

**Layouts are Python, not Jinja templates** (a change from the first proposal).
Every layout needs to measure text before it can place the next thing ("how
many lines did the title take?"), which templates can't do cleanly. Each layout
is still one small function in its own module, written against a drawing kit:
`canvas.text(...)`, `canvas.art(...)`, `canvas.rect(...)`.

### Text that always fits

`canvas.text(text, box, style, fit=...)`:
- measures with the same font files resvg uses (Pillow `FreeTypeFont.getlength`;
  fallback fonts for uncovered characters);
- shrinks from the design size down to a minimum, wraps to at most N lines
  (breaking at spaces, or anywhere for CJK), then ends with "…";
- whitespace is already cleaned at import (`clean_text`).

### Designs = layout × theme

- **Card types** (what the card says): Top songs, #1 song, Top albums, Top
  artists, Top genres, Minutes listened, Listening age, Summary. Phase 4 adds
  Listening clock, Your week, Year in months, Streak and Discoveries. A card type
  says when it applies (Listening age needs release years; timeline cards need
  timestamps), so the deck only offers cards it can fill.
- **Layouts** (how it's arranged): 2–3 per card type, e.g. Top songs as *List*,
  *Spotlight* (big #1, the rest small) or *Receipt*. Every layout handles both
  formats and any number of items, including none.
- **Themes** (how it looks): palette, fonts and background. Midnight, Sunset,
  Paper (serif, editorial), Poster (condensed type), Mint, Mono, Classic (the
  TunesBack 1.x colours and patterns) and **Cover**, which takes its colours
  from the artwork of your top album.
- **Formats**: Story 1080×1920 and Square 1080×1080.

Bundled fonts (all SIL OFL): Figtree (existing), Instrument Serif, Space Mono,
Anton. About 510 KB together.

### Shuffle, and keeping a design

- The deck is described by `{format, theme, seed, cards: {type: {layout, theme, off}}}`
  and saved in settings, so the same design comes back next time and after new data.
- **Shuffle** picks a new seed. Layouts (and themes, when the theme is "Mix") come
  from `Random(f"{seed}:{card}")`, so one seed always gives the same deck.
  Changes you make to a single card win over the shuffle. After a shuffle, a toast
  offers "Undo".

### Wrapped view

```
┌ Wrapped ─────────────────────────────────────────── [Story|Square] [By plays|By time] ┐
│ Theme  (Mix) (Cover) (Midnight) (Sunset) (Paper) …                   [⟳ Shuffle]      │
│ ┌────┐ ┌────┐ ┌────┐ ┌────┐                                                           │
│ │card│ │card│ │card│ │card│   hover: "Edit"   check: include in save                  │
│ └────┘ └────┘ └────┘ └────┘                                                           │
│                                   [Select all] [Save selected (3)] [Save all]         │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

- Cards are generated as soon as you open Wrapped; there's no extra
  "Generate" step. Changing the format, theme or shuffle re-renders in place,
  with the old previews dimmed until the new ones arrive.
- **Card editor** (a dialog): a big preview, a row of layout thumbnails, theme
  swatches, "Shuffle this card", "Hide this card", "Save image".
- Previews are rendered at half size; full size only when saving.

## Phase 4: listening history

### Two kinds of source

| Kind | Sources | What we get |
|---|---|---|
| Counters | iTunes / Apple Music (and later MusicBee, Strawberry...) | Totals per track; periods need two readings |
| Plays | Last.fm, ListenBrainz, Spotify data export | Every listen with a timestamp |

Plays are stored in a new `plays` table (`source_id`, `track_id`,
`played_at` UTC, `ms_played` if known, `skipped`), unique on
`(source_id, played_at, track_id)`, so re-syncing and re-importing never
double count. The schema is versioned with `PRAGMA user_version` and
migrated on open.

### Last.fm

- `user.getRecentTracks`, 200 per page, `extended=1`.
- Needs a username and an API key. Builds can ship a key
  (`TUNESBACK_LASTFM_API_KEY` at build time); otherwise set-up asks for one
  with a link to create it (free, takes a minute).
- **Sync** catches up from the newest stored scrobble, then backfills older
  history page by page, remembering where it got to. An interrupted first
  import resumes instead of leaving a hole. At most ~4 requests a second,
  with backoff on errors 8, 11, 16 and 29 and on HTTP 5xx.
- Album art: Last.fm image URLs, skipping its blank placeholder.
- Track lengths: Last.fm doesn't record them. Time comes from a matching song
  in another source; otherwise an average song length, and the app marks those
  times as estimated.
- Private profiles (error 17) get a clear message.

### ListenBrainz

- `GET /1/user/{name}/listens`, `count=1000`, paged by `max_ts`/`min_ts`, no
  key needed. Same catch-up and backfill. `duration_ms` when submitted; Cover
  Art Archive art from `mbid_mapping.caa_release_mbid`/`caa_id`.

### Spotify

- Import the "Extended streaming history" (`Streaming_History_Audio_*.json`,
  exact `ms_played`, `skipped`) or the one-year "Account data"
  (`StreamingHistory_music_*.json`), from the `.zip` or the extracted folder.
- A play counts from 30 seconds, as Spotify does. Podcasts are ignored.
- Set-up explains how to request the data (it takes Spotify a few days).

### Combining sources

The Recap card on the Library page gains:

- **Source**: one source, or "All sources".
- **Period**:
  - iTunes alone keeps "Compare two readings / Lifetime".
  - Play sources (and "All sources") use date presets: *This year*, *Last
    year*, *Last 12 months*, *All time*, *Custom*.
  - Counter sources in a date range use the readings closest to its ends, and
    the recap says which dates it actually covers.
- **"All sources" asks one question**: *Do these sources record the same
  listening?*
  - **Same** (e.g. iTunes scrobbles to Last.fm): each song counts once,
    using the higher number. This is the default.
  - **Separate** (e.g. phone and computer): the numbers add up.

  Songs are matched by normalised title + artist (+ album when both have one).

### New statistics (play sources only)

All computed in local time, for the selected period:

- Listening by hour of day and by weekday.
- Month-by-month timeline, with the top artist of each month.
- Days listened, longest streak, busiest day.
- **Discoveries**: artists and songs first played in this period, judged
  against the source's whole history. Only shown when that history starts well
  before the period, so the first month of a new account isn't "all new".

They appear in **Overview** ("When you listen": clock, week, months, streak
tiles) and as **cards**.

## Linux build

- Built on Ubuntu 22.04 (glibc 2.35) with PyInstaller and the **Qt** backend
  (PyQt6 + QtWebEngine wheels), so the build is self-contained and doesn't depend
  on the system's WebKitGTK version. Qt is also what KDE users get today.
- Published as an **AppImage** and a **.tar.gz** of the same folder.
- Qt WebEngine's Chromium sandbox can't start where unprivileged user
  namespaces are restricted (Ubuntu 23.10+), so the packaged app turns it off
  only there. The page only ever shows TunesBack's own local content.
- **Smoke test**: Xvfb with a window manager. Start the app, drag, resize,
  maximise and close through the custom title bar with `xdotool`, take
  screenshots.

## Order of work

1. Linux CI job (independent; it can run while the rest is built).
2. Card engine: canvas, text fitting, fonts and fallback, backdrop, themes,
   layouts for today's card types, deck and shuffle. Tests render every
   layout × theme × format with full, empty, long-text and CJK data.
3. Wrapped view: style bar, live previews, card editor, settings persistence.
4. Store v2 and play sources: plays table, Spotify import, ListenBrainz and
   Last.fm sync with fake servers in tests.
5. Reports from plays and merged sources; timeline statistics.
6. UI: set-up flows for the new sources, Library sources and Recap card,
   Overview "When you listen".
7. Timeline cards.
8. Docs, README, CI run with screenshots.
