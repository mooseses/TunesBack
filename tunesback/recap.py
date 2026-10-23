"""Building a recap from one or more sources over a period."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from .library import LibraryStore
from .model import normalize_key
from .stats.period import period_activity
from .stats.plays import Enricher, activity_from_plays, merge, song_key, timeline
from .stats.report import Report, report_from_activity, split_artists

COUNTER_MODES = ("file", "folder")
NAMES = {"itunes": "iTunes", "lastfm": "Last.fm", "listenbrainz": "ListenBrainz", "spotify": "Spotify"}


def source_name(source: dict) -> str:
    name = NAMES.get(source["kind"], source["kind"])
    return f"{name} ({source['path']})" if source["mode"] == "account" else name


def _readings_for(store: LibraryStore, source_id: int) -> list[dict]:
    return [r for r in store.readings() if r["source_id"] == source_id]


def _pick_readings(readings: list[dict], start: Optional[datetime], end: Optional[datetime]):
    """The readings closest to the ends of a period: (start reading or None, end reading or None).

    Readings rarely fall exactly on the period's ends, so the nearest ones are
    used, on either side; the recap says which dates they actually cover.
    """
    dated = sorted(((datetime.fromisoformat(r["date"]), r) for r in readings), key=lambda x: x[0])
    if not dated:
        return None, None
    near = lambda target: (lambda x: abs((x[0] - target).total_seconds()))
    end_date, end_reading = dated[-1] if end is None else min(dated, key=near(end))
    if start is None:
        return None, end_reading
    earlier = [x for x in dated if x[0] < end_date]
    if not earlier:
        return None, None  # nothing before it to compare with
    return min(earlier, key=near(start))[1], end_reading


def build_recap(store: LibraryStore, sources: Sequence[dict], start: Optional[datetime], end: Optional[datetime],
                combine: str = "same", stage=lambda text: None) -> Report:
    """A report for [start, end) from the given sources. `start` None means all time."""
    counter = [s for s in sources if s["mode"] in COUNTER_MODES]
    plays = [s for s in sources if s["mode"] not in COUNTER_MODES]
    activities, described = [], []
    listens_by_source = []
    estimated = False

    for source in counter:
        stage(f"Reading {source_name(source)}…")
        first, last = _pick_readings(_readings_for(store, source["id"]), start, end)
        if last is None:
            described.append({"id": source["id"], "name": source_name(source), "kind": source["kind"], "covers": None})
            continue
        activity = period_activity(store.load(last["id"]), store.load(first["id"]) if first else None)
        activities.append(activity)
        described.append({"id": source["id"], "name": source_name(source), "kind": source["kind"],
                          "covers": {"start": first["date"] if first else None, "end": last["date"]}})

    first_song: dict = {}
    first_artist: dict = {}
    history_start = None
    if plays:
        stage("Counting your listens…")
        ids = [s["id"] for s in plays]
        enricher = Enricher(store.library_tracks())
        for row in store.first_plays(ids):
            key = song_key(row["name"], row["artist"])
            first_song[key] = min(first_song.get(key, row["first"]), row["first"])
            artist = normalize_key(split_artists(row["artist"])[0])
            first_artist[artist] = min(first_artist.get(artist, row["first"]), row["first"])
            history_start = row["first"] if history_start is None else min(history_start, row["first"])
        start_ts = int(start.timestamp()) if start else None
        end_ts = int(end.timestamp()) if end else None
        for source in plays:
            rows = store.plays([source["id"]], start_ts, end_ts)
            activity, listens, guessed = activity_from_plays(rows, enricher, first_song if start else None, start_ts)
            estimated = estimated or guessed
            activities.append(activity)
            listens_by_source.append(listens)
            covers = {"start": datetime.fromtimestamp(rows[0]["played_at"]).isoformat(timespec="seconds"),
                      "end": datetime.fromtimestamp(rows[-1]["played_at"]).isoformat(timespec="seconds")} if rows else None
            described.append({"id": source["id"], "name": source_name(source), "kind": source["kind"], "covers": covers})

    stage("Crunching numbers…")
    merged = merge(activities, combine) if activities else []
    # The timeline comes from play sources; when they log the same listening, use the fullest one.
    if combine == "separate":
        listens = sorted((l for group in listens_by_source for l in group), key=lambda l: l.at)
    else:
        listens = max(listens_by_source, key=len, default=[])

    end_date = (end - timedelta(seconds=1)) if end else _latest(described)
    report = report_from_activity(merged, start, end_date,
                                  timeline(listens, start, end, first_artist, history_start) if listens else None,
                                  estimated)
    report.sources = described
    return report


def _latest(described: list[dict]) -> datetime:
    ends = [datetime.fromisoformat(d["covers"]["end"]) for d in described if d["covers"]]
    return max(ends) if ends else datetime.now()
