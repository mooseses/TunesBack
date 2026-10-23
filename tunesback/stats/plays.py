"""Statistics from sources that log every listen (Last.fm, ListenBrainz, Spotify).

Those sources know when you listened but little about the music (no genre,
release year or file), so details are filled in from your library when the
same song is in it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Optional, Sequence

from ..model import Track, normalize_key
from .period import TrackActivity
from .report import split_artists

# Used for listening time when neither the source nor your library knows a song's length.
AVERAGE_SONG_MS = 210_000
# Discoveries are only meaningful with some history before the period to compare against.
DISCOVERY_HISTORY_DAYS = 30


def song_key(name: str, artist: str) -> tuple[str, str]:
    """Matches a song across sources: title and main artist, ignoring case and accents."""
    return normalize_key(name), normalize_key(split_artists(artist)[0] if artist else "")


@dataclass(frozen=True)
class LibraryInfo:
    album: str
    genre: Optional[str]
    year: Optional[int]
    duration_ms: Optional[int]
    location: Optional[str]


class Enricher:
    """Looks up what your library knows about a song."""

    def __init__(self, rows: Iterable[Mapping] = ()):
        self._index: dict[tuple[str, str], LibraryInfo] = {}
        for row in rows:  # newest first: the first one seen wins
            key = song_key(row["name"] or "", row["artist"] or "")
            if key[0] and key not in self._index:
                self._index[key] = LibraryInfo(row["album"] or "", row["genre"], row["year"], row["duration_ms"],
                                               row["location"])

    def get(self, name: str, artist: str) -> Optional[LibraryInfo]:
        return self._index.get(song_key(name, artist))


@dataclass
class Listen:
    """A counted play, for the timeline."""

    at: int  # Unix time
    ms: int
    artist: str
    song: str


def activity_from_plays(rows: Sequence[Mapping], enricher: Enricher,
                        first_played: Optional[Mapping[tuple[str, str], int]] = None,
                        period_start: Optional[int] = None) -> tuple[list[TrackActivity], list[Listen], bool]:
    """Per-song activity from listens (rows from LibraryStore.plays).

    Returns (activity, the counted listens, whether some times were estimated).
    A song is a new find when its first play ever falls in the period.
    """
    groups: dict[tuple, list[Mapping]] = defaultdict(list)
    for row in rows:
        groups[(normalize_key(row["name"]), normalize_key(row["artist"]), normalize_key(row["album"]))].append(row)

    activity: list[TrackActivity] = []
    listens: list[Listen] = []
    estimated = False
    for group in groups.values():
        first = group[0]
        info = enricher.get(first["name"], first["artist"])
        length = first["duration_ms"] or (info.duration_ms if info else None)
        ms = 0
        plays = skips = 0
        for row in group:
            if row["ms_played"] is not None:
                listened = row["ms_played"]
            else:
                listened = length or AVERAGE_SONG_MS
                estimated = estimated or not length
            ms += listened
            if row["skipped"]:
                skips += 1
            else:
                plays += 1
                listens.append(Listen(row["played_at"], listened, first["artist"], first["name"]))
        track = Track(
            persistent_id=None, name=first["name"], artist=first["artist"],
            album_artist=first["album_artist"] or first["artist"],
            album=first["album"] or (info.album if info else ""),
            genre=first["genre"] or (info.genre if info else None),
            year=first["year"] or (info.year if info else None),
            duration_ms=length or AVERAGE_SONG_MS, play_count=plays, skip_count=skips, date_added=None,
            location=(info.location if info and info.location else None) or first["location"] or first["art_url"])
        is_new = False
        if first_played is not None and period_start is not None and plays:
            seen = first_played.get(song_key(first["name"], first["artist"]))
            is_new = seen is not None and seen >= period_start
        activity.append(TrackActivity(track, plays, skips, is_new, listened_ms=ms))
    listens.sort(key=lambda l: l.at)
    return activity, listens, estimated


def merge(activities: Sequence[list[TrackActivity]], combine: str = "same") -> list[TrackActivity]:
    """Combine activity from several sources, matching songs by title and artist.

    "same": the sources record the same listening (say, iTunes scrobbling to
    Last.fm), so each song counts once, using the source with most plays.
    "separate": they record different listening, so the numbers add up.
    """
    if len(activities) == 1:
        return list(activities[0])
    merged: dict[tuple[str, str], TrackActivity] = {}
    for items in activities:
        # One source can list a song more than once (under two albums, say): those plays add up
        # before the sources are compared.
        own: dict[tuple[str, str], TrackActivity] = {}
        for item in items:
            key = song_key(item.track.name, item.track.artist)
            own[key] = _combine(own[key], item, "separate") if key in own else item
        for key, item in own.items():
            merged[key] = _combine(merged[key], item, combine) if key in merged else item
    return list(merged.values())


def _combine(have: TrackActivity, item: TrackActivity, combine: str) -> TrackActivity:
    # Keep the richer track details (a library track has genre, year and a file).
    track = have.track if (have.track.location and have.track.genre) or not item.track.location else item.track
    if combine == "separate":
        return replace(have, track=track, plays=have.plays + item.plays, skips=have.skips + item.skips,
                       is_new=have.is_new and item.is_new, listened_ms=have.ms + item.ms)
    best = item if (item.plays, item.ms) > (have.plays, have.ms) else have
    return replace(best, track=track, is_new=have.is_new and item.is_new,
                   listened_ms=best.ms, skips=max(have.skips, item.skips))


def timeline(listens: Sequence[Listen], start: Optional[datetime], end: Optional[datetime],
             first_played_artist: Optional[Mapping[str, int]] = None,
             history_start: Optional[int] = None) -> Optional[dict]:
    """When you listened: by hour, weekday and month, streaks, and discoveries. In local time."""
    if not listens:
        return None
    hours_plays, hours_ms = [0] * 24, [0] * 24
    week_plays, week_ms = [0] * 7, [0] * 7
    per_day: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    months: dict[str, dict] = {}
    month_artists: dict[str, Counter] = defaultdict(Counter)
    month_songs: dict[str, Counter] = defaultdict(Counter)
    artist_plays: Counter = Counter()

    for listen in listens:
        at = datetime.fromtimestamp(listen.at)
        hours_plays[at.hour] += 1
        hours_ms[at.hour] += listen.ms
        week_plays[at.weekday()] += 1
        week_ms[at.weekday()] += listen.ms
        day = per_day[at.date()]
        day[0] += 1
        day[1] += listen.ms
        month = f"{at.year:04d}-{at.month:02d}"
        entry = months.setdefault(month, {"month": month, "plays": 0, "ms": 0})
        entry["plays"] += 1
        entry["ms"] += listen.ms
        artist = split_artists(listen.artist)[0]
        month_artists[month][artist] += 1
        month_songs[month][(listen.song, listen.artist)] += 1
        artist_plays[artist] += 1

    first_day = (start.date() if start else min(per_day))
    last_day = (end.date() - timedelta(days=1) if end else max(per_day))
    for month, entry in months.items():
        entry["top_artist"] = month_artists[month].most_common(1)[0][0]
        song, artist = month_songs[month].most_common(1)[0][0]
        entry["top_song"] = {"title": song, "artist": artist}
    # Every month of the period, including quiet ones.
    cursor = date(first_day.year, first_day.month, 1)
    timeline_months = []
    while cursor <= last_day:
        key = f"{cursor.year:04d}-{cursor.month:02d}"
        timeline_months.append(months.get(key, {"month": key, "plays": 0, "ms": 0, "top_artist": None, "top_song": None}))
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)

    days = sorted(per_day)
    best = run = 1
    best_end = run_end = days[0]
    for previous, current in zip(days, days[1:]):
        run = run + 1 if current - previous == timedelta(days=1) else 1
        run_end = current
        if run > best:
            best, best_end = run, run_end
    busiest = max(days, key=lambda d: (per_day[d][1], per_day[d][0]))

    discoveries = None
    if first_played_artist is not None and start is not None and history_start is not None \
            and history_start <= start.timestamp() - DISCOVERY_HISTORY_DAYS * 86400:
        new_artists = [a for a in artist_plays if first_played_artist.get(normalize_key(a), 0) >= start.timestamp()]
        top = sorted(new_artists, key=lambda a: -artist_plays[a])[:5]
        discoveries = {"artists": len(new_artists), "top": [{"name": a, "plays": artist_plays[a]} for a in top]}

    return {
        "total": len(listens),
        "hours": {"plays": hours_plays, "ms": hours_ms},
        "weekdays": {"plays": week_plays, "ms": week_ms},
        "months": timeline_months,
        "days_active": len(days),
        "days": (last_day - first_day).days + 1,
        "longest_streak": {"days": best, "start": (best_end - timedelta(days=best - 1)).isoformat(),
                           "end": best_end.isoformat()},
        "busiest_day": {"date": busiest.isoformat(), "plays": per_day[busiest][0], "ms": per_day[busiest][1]},
        "daily": {d.isoformat(): per_day[d][0] for d in days},
        "peak_hour": max(range(24), key=lambda h: hours_plays[h]),
        "peak_weekday": max(range(7), key=lambda d: week_plays[d]),
        "discoveries": discoveries,
    }
