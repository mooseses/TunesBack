"""Roll per-track activity up into the rankings shown in the app and on cards."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Literal, Optional

from ..model import Snapshot
from .listening_age import ListeningAge, calculate_listening_age
from .period import TrackActivity, period_activity

RankBy = Literal["plays", "time"]

# Only explicit multi-artist credits are split. Splitting on "&" or "," would
# break up acts such as "Simon & Garfunkel" or "Earth, Wind & Fire".
_ARTIST_SEPARATORS = re.compile(r"\s+[(\[]?(?:feat\.?|ft\.?|featuring)\s+|\s*;\s*|\s+/\s+", re.IGNORECASE)


def split_artists(credit: str) -> list[str]:
    parts = [p.strip(" ()[]") for p in _ARTIST_SEPARATORS.split(credit)]
    return [p for p in parts if p] or [credit]


@dataclass(slots=True)
class Entry:
    """One row of a ranking (a song, album, artist, genre or year)."""

    title: str
    subtitle: Optional[str] = None
    plays: int = 0
    ms: int = 0
    skips: int = 0
    art: Optional[str] = None  # location of the most-played track, for artwork
    _art_plays: int = field(default=-1, repr=False)

    def add(self, item: TrackActivity) -> None:
        self.plays += item.plays
        self.ms += item.ms
        self.skips += item.skips
        if item.track.location and item.plays > self._art_plays:
            self.art, self._art_plays = item.track.location, item.plays

    def to_dict(self) -> dict:
        return {"title": self.title, "subtitle": self.subtitle, "plays": self.plays,
                "ms": self.ms, "skips": self.skips, "art": self.art}


def rank(entries: Iterable[Entry], by: RankBy = "plays") -> list[Entry]:
    if by == "time":
        key = lambda e: (-e.ms, -e.plays, e.title.casefold())
    else:
        key = lambda e: (-e.plays, -e.ms, e.title.casefold())
    return sorted(entries, key=key)


@dataclass(slots=True)
class Report:
    mode: Literal["single", "compare"]
    start_date: Optional[datetime]
    end_date: datetime
    total_ms: int
    total_plays: int
    total_skips: int
    songs: list[Entry]
    albums: list[Entry]
    artists: list[Entry]
    genres: list[Entry]
    years: list[Entry]
    new_finds: list[Entry]
    skipped: list[Entry]
    listening_age: Optional[ListeningAge]
    timeline: Optional[dict] = None  # when and how you listened (sources with timestamps only)
    estimated_time: bool = False  # some listening times are guessed from song lengths
    sources: list = field(default_factory=list)  # which sources went in, and the dates each covers

    def top(self, category: str, by: RankBy = "plays", limit: Optional[int] = None) -> list[Entry]:
        entries = getattr(self, category)
        ranked = sorted(entries, key=lambda e: (-e.skips, e.title.casefold())) if category == "skipped" else rank(entries, by)
        return ranked[:limit] if limit else ranked

    def to_dict(self) -> dict:
        age = self.listening_age
        return {
            "mode": self.mode,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat(),
            "total_ms": self.total_ms,
            "total_plays": self.total_plays,
            "total_skips": self.total_skips,
            "listening_age": None if age is None else {
                "age": age.age, "era_start": age.era_start, "era_end": age.era_end, "era_label": age.era_label,
            },
            **{name: [e.to_dict() for e in getattr(self, name)] for name in
               ("songs", "albums", "artists", "genres", "years", "new_finds", "skipped")},
            "timeline": self.timeline,
            "estimated_time": self.estimated_time,
            "sources": self.sources,
        }


def build_report(end: Snapshot, start: Optional[Snapshot] = None) -> Report:
    """A report from two readings of a counter source (or one, for all time)."""
    return report_from_activity(period_activity(end, start), start.date if start else None, end.date)


def report_from_activity(activity: list[TrackActivity], start_date: Optional[datetime], end_date: datetime,
                         timeline: Optional[dict] = None, estimated_time: bool = False) -> Report:
    """Roll per-track activity for a period up into a report."""

    songs: dict[tuple, Entry] = {}
    albums: dict[tuple, Entry] = {}
    artists: dict[str, Entry] = {}
    genres: dict[str, Entry] = {}
    years: dict[int, Entry] = {}
    new_finds: list[Entry] = []
    plays_per_year: Counter = Counter()

    def bucket(table: dict, key, title: str, subtitle: Optional[str] = None) -> Entry:
        if key not in table:
            table[key] = Entry(title=title, subtitle=subtitle)
        return table[key]

    for item in activity:
        t = item.track
        song = bucket(songs, (t.match_key[0], t.match_key[1]), t.name, t.artist)
        song.add(item)
        if item.plays:
            bucket(albums, (t.album.casefold(), t.album_artist.casefold()), t.album, t.album_artist).add(item)
            for artist in split_artists(t.artist):
                bucket(artists, artist.casefold(), artist).add(item)
            if t.genre:
                bucket(genres, t.genre.casefold(), t.genre).add(item)
            if t.year and t.year > 1900:
                bucket(years, t.year, str(t.year)).add(item)
                plays_per_year[t.year] += item.plays
        if item.is_new:
            entry = Entry(title=t.name, subtitle=t.artist)
            entry.add(item)
            new_finds.append(entry)

    played_songs = [e for e in songs.values() if e.plays]
    return Report(
        mode="compare" if start_date else "single",
        start_date=start_date,
        end_date=end_date,
        total_ms=sum(a.ms for a in activity),
        total_plays=sum(a.plays for a in activity),
        total_skips=sum(a.skips for a in activity),
        songs=played_songs,
        albums=list(albums.values()),
        artists=list(artists.values()),
        genres=list(genres.values()),
        years=list(years.values()),
        new_finds=new_finds,
        skipped=[e for e in songs.values() if e.skips],
        listening_age=calculate_listening_age(plays_per_year, end_date.year),
        timeline=timeline,
        estimated_time=estimated_time,
    )
