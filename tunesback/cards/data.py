"""What the cards show, taken from a report and independent of any design."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from PIL import Image

from ..art.artwork import load_artwork
from ..stats.report import Entry, RankBy, Report

ArtLoader = Callable[[Optional[str]], Optional[Image.Image]]


def default_art(location: Optional[str]) -> Optional[Image.Image]:
    return load_artwork(location, max_size=1000) if location else None


@dataclass
class Item:
    title: str
    subtitle: Optional[str]
    plays: int
    ms: int
    art: Optional[str] = None  # artwork location
    share: float = 0.0  # of the period's total, by the deck's ranking

    @classmethod
    def of(cls, entry: Entry, total: float, by: RankBy) -> "Item":
        value = entry.ms if by == "time" else entry.plays
        return cls(entry.title, entry.subtitle, entry.plays, entry.ms, entry.art, value / total if total else 0.0)


def _day(d: datetime, year: bool = True) -> str:
    # strftime's "%-d" (no leading zero) doesn't exist on Windows.
    return f"{d.day} {d:%b %Y}" if year else f"{d.day} {d:%b}"


def _format_period(report: Report) -> tuple[str, str]:
    """(short, long) labels, e.g. ("2025", "1 Jan 2025 – 31 Dec 2025") or ("All time", "Up to 3 Mar 2025")."""
    end = report.end_date
    if report.start_date is None:
        return "All time", f"Up to {_day(end)}"
    start = report.start_date
    span = f"{_day(start, start.year != end.year)} – {_day(end)}"
    # Close enough to a calendar year (readings are rarely taken exactly on 1 January).
    for year in range(start.year, end.year + 1):
        if (abs(start - datetime(year, 1, 1)) <= timedelta(days=21)
                and abs(end - datetime(year + 1, 1, 1)) <= timedelta(days=21)):
            return str(year), span
    if start.year == end.year:
        return f"{start:%b} – {end:%b %Y}", span
    return f"{start:%b %Y} – {end:%b %Y}", span


@dataclass
class CardData:
    rank_by: RankBy
    period: str
    period_long: str
    lifetime: bool
    songs: list[Item]
    albums: list[Item]
    artists: list[Item]
    genres: list[Item]
    new_finds: list[Item]
    total_ms: int
    total_plays: int
    song_count: int
    artist_count: int
    album_count: int
    listening_age: Optional[dict]
    days: Optional[int] = None  # length of the period, when it has a start
    timeline: Optional[dict] = None
    estimated_time: bool = False
    load_art: ArtLoader = field(default=default_art, repr=False)
    _art: dict = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def art(self, item: Optional[Item]) -> Optional[Image.Image]:
        """Artwork for an item (loaded once, then cached)."""
        location = item.art if item else None
        if not location:
            return None
        with self._lock:
            if location not in self._art:
                try:
                    self._art[location] = self.load_art(location)
                except Exception:
                    self._art[location] = None
            return self._art[location]

    def metric(self, item: Item, short: bool = False) -> str:
        """How an item ranks: "123 plays" or "1,234 min", following the deck's ranking."""
        if self.rank_by == "time":
            return f"{item.ms // 60000:,} min"
        if short:
            return f"{item.plays:,}"
        return f"{item.plays:,} play" + ("" if item.plays == 1 else "s")

    @property
    def minutes(self) -> int:
        return self.total_ms // 60000

    @property
    def top_art(self) -> Optional[Image.Image]:
        """The artwork that best represents the period, for colours and backgrounds."""
        for item in (*self.albums[:3], *self.songs[:3]):
            art = self.art(item)
            if art is not None:
                return art
        return None

    def fingerprint(self) -> Any:
        return (self.rank_by, self.period, self.total_ms, self.total_plays, len(self.songs))


def build_data(report: Report, rank_by: RankBy = "plays", load_art: ArtLoader = default_art) -> CardData:
    by: RankBy = "time" if rank_by == "time" else "plays"

    def total(entries: list[Entry]) -> float:
        return sum(e.ms if by == "time" else e.plays for e in entries)

    def top(category: str, limit: int) -> list[Item]:
        entries = getattr(report, category)
        whole = total(entries)
        return [Item.of(e, whole, by) for e in report.top(category, by, limit)]

    short, long = _format_period(report)
    age = report.listening_age
    return CardData(
        rank_by=by, period=short, period_long=long, lifetime=report.start_date is None,
        songs=top("songs", 10), albums=top("albums", 9), artists=top("artists", 10), genres=top("genres", 8),
        new_finds=top("new_finds", 10),
        total_ms=report.total_ms, total_plays=report.total_plays, song_count=len(report.songs),
        artist_count=len(report.artists), album_count=len(report.albums),
        listening_age=None if age is None else {"age": age.age, "era_label": age.era_label,
                                                "era_start": age.era_start, "era_end": age.era_end},
        days=max(1, (report.end_date - report.start_date).days) if report.start_date else None,
        timeline=getattr(report, "timeline", None),
        estimated_time=getattr(report, "estimated_time", False),
        load_art=load_art,
    )
