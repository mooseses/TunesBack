"""Source-independent data model.

Every source (iTunes XML today, scrobble services later) is reduced to these
types before any statistics are computed.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

_WHITESPACE = re.compile(r"\s+")


def clean_text(value: object) -> Optional[str]:
    """Collapse all whitespace (including newlines and tabs) to single spaces.

    Library metadata regularly contains embedded line breaks, which break
    single-line layouts and text measurement downstream.
    """
    if value is None:
        return None
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return text or None


def normalize_key(value: Optional[str]) -> str:
    """Case- and accent-insensitive key used to match tracks across snapshots."""
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


@dataclass(frozen=True, slots=True)
class Track:
    """A track as it appears in one library snapshot, with cumulative counters."""

    persistent_id: Optional[str]
    name: str
    artist: str
    album_artist: str
    album: str
    genre: Optional[str]
    year: Optional[int]
    duration_ms: int
    play_count: int
    skip_count: int
    date_added: Optional[datetime]
    location: Optional[str]  # raw file:// URI exactly as stored in the library

    @property
    def match_key(self) -> tuple[str, str, str]:
        """Fallback identity for when persistent IDs differ (e.g. a rebuilt library)."""
        return (normalize_key(self.name), normalize_key(self.artist), normalize_key(self.album))


@dataclass(slots=True)
class Snapshot:
    """One exported library at a point in time."""

    path: str
    date: datetime
    tracks: list[Track] = field(default_factory=list)
    library_id: Optional[str] = None
