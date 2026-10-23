# Plan: an Overview you can arrange

Status: proposal.

## Goal

The Overview becomes a dashboard of **widgets**. You can move them, resize them,
hide the ones you don't care about and add ones that are off by default. The
layout is remembered.

## What a widget is

Everything on today's Overview becomes a widget, and a few new ones join:

| Widget | Sizes | Needs |
|---|---|---|
| Listening time, Plays, New finds, Skips, Artists (one number each) | S | – |
| Top artist / Top album / Top song | S, M | – |
| Top artists (bars) | M, L | – |
| Genres | M, L | genres in the library |
| Listening age (teaser, links to its tab) | S, M | release years |
| Release decades | M, L | release years |
| Longest streak, Days with music, Busiest day, New artists, Peak time | S | a source with listening dates |
| Time of day, Day of the week | M, L | listening dates |
| Month by month | L | listening dates |
| **New:** Top songs (short list), Top albums (cover grid), Most skipped, Discoveries list | M, L | – / listening dates |

Each widget is a small module:

```js
export default {
  id: "time-of-day",
  title: "Time of day",
  sizes: ["M", "L"], defaultSize: "M",
  available: (report) => !!report.timeline,        // can it show anything?
  render(report, { size, by, unit }) { return element; },
};
```

## Layout

- A 12-column grid: **S** spans 3 columns, **M** 6 and **L** 12. Heights follow
  the content (rows are `grid-auto-rows: min-content`; dense packing keeps gaps small).
- The layout is an ordered list saved in settings:
  `"overview_layout": [{"id": "listening-time", "size": "S"}, …]`. Unknown ids and
  sizes are dropped when loading, and the default is today's Overview, so
  nothing changes until you customize it.
- Below 1100 px wide the grid has 6 columns (S = 3, M and L = 6); below 760 px,
  one. Sizes are kept; only the columns change.
- A widget that can't show anything for the current recap (say, Time of day for
  an iTunes-only recap) is left out of the page but keeps its place in the layout.

## Editing

- A **Customize** button (pencil) in the Overview top bar starts edit mode. The
  top bar then shows **Add widget**, **Reset** and **Done**.
- In edit mode each widget gets:
  - a drag handle (the whole card can be dragged too);
  - a size switch (S / M / L, only the sizes it supports);
  - a remove button.
  Unavailable widgets show as dashed placeholders ("Needs a source with
  listening dates"), so they can still be arranged.
- **Moving** uses pointer events rather than HTML drag and drop, which behaves
  differently in WebKitGTK, WKWebView and Qt WebEngine. While dragging:
  - a placeholder shows where the widget will land;
  - the other widgets slide out of the way (FLIP animation);
  - the page scrolls when the pointer nears the top or bottom.
- **Keyboard:** focus a widget, then Alt+Arrow keys move it and Alt+Shift+Arrow
  keys change its size. Changes are announced through an `aria-live` region.
- **Add widget** opens a side panel listing hidden widgets with a small preview
  rendered from the current recap; clicking one adds it at the end.
- **Reset** returns to the default layout (with Undo in a toast). Changes save as
  you make them (debounced, like other settings), and **Done** leaves edit mode.
- Reduced motion: no sliding, just instant moves.

## Implementation steps

1. Split `views/overview.js` into `views/widgets/*.js` (one module per widget or
   small family) plus a registry. Render the default layout. The page should look
   exactly as today, which is the check that the refactor is safe.
2. Layout engine: read `overview_layout`, validate it, render the grid, and
   handle responsive columns. Add settings validation in `app/settings.py`.
3. Edit mode: handles, size switch, remove, the Add widget panel, Reset.
4. Pointer dragging with placeholder, FLIP and auto-scroll, then keyboard moves.
5. New widgets: Top songs, Top albums, Most skipped, Discoveries.
6. Tests:
   - settings validation (unknown ids, sizes, duplicates);
   - a Playwright script that drags a widget, resizes another, removes and
     re-adds one, reloads, and checks the layout survived.

## Out of scope (for now)

Several saved dashboards, widgets on other pages, free-form (pixel) placement, and
custom widgets.

## Questions for you

1. Should the Overview's charts follow the **By plays / By time** switch as now,
   or should each widget have its own?
2. Keep the "When you listen" heading as a group, or let those widgets mix freely
   with the rest (this plan assumes they mix)?
