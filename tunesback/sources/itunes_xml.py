"""iTunes / Apple Music "Export Library" XML snapshots."""
from __future__ import annotations

import logging
import os
import plistlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from dateutil import parser as date_parser

from ..model import Snapshot, Track, clean_text

log = logging.getLogger(__name__)

# The export date lives in the plist header, well within the first few KB.
_HEADER_BYTES = 16 * 1024
_HEADER_DATE = re.compile(rb"<key>Date</key>\s*<date>([^<]+)</date>")
_HEADER_MARKERS = (b"<key>Major Version</key>", b"<key>Library Persistent ID</key>", b"<key>Tracks</key>")

# Tracks that are not music listening.
_EXCLUDED_FLAGS = ("Podcast", "Movie", "Has Video", "TV Show", "iTunesU")


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    """A snapshot file found on disk, before it has been parsed."""

    path: str
    date: datetime
    label: str
    size: int
    date_source: str  # "library", "filename" or "modified"

    @property
    def file(self) -> str:
        return os.path.basename(self.path)


def _read_header(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read(_HEADER_BYTES)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _date_from_filename(path: str) -> Optional[datetime]:
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        return _naive_utc(date_parser.parse(stem, fuzzy=True, default=datetime(1900, 1, 1)))
    except (ValueError, OverflowError):
        return None


def snapshot_date(path: str, header: Optional[bytes] = None) -> tuple[datetime, str]:
    """Best available export date: the library's own header, then the filename, then mtime."""
    header = _read_header(path) if header is None else header
    match = _HEADER_DATE.search(header)
    if match:
        try:
            return _naive_utc(datetime.fromisoformat(match.group(1).decode().replace("Z", "+00:00"))), "library"
        except ValueError:
            pass
    from_name = _date_from_filename(path)
    if from_name and from_name.year > 1900:
        return from_name, "filename"
    return _naive_utc(datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)), "modified"


def is_library_export(header: bytes) -> bool:
    return b"<plist" in header and any(m in header for m in _HEADER_MARKERS)


def scan_folder(folder: str) -> list[SnapshotInfo]:
    """Find library exports in a folder, oldest first, with unique labels."""
    if not os.path.isdir(folder):
        return []
    found = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not name.lower().endswith(".xml") or not os.path.isfile(path):
            continue
        try:
            header = _read_header(path)
            if not is_library_export(header):
                log.info("Skipping %s: not a library export", name)
                continue
            date, source = snapshot_date(path, header)
            found.append((path, date, source, os.path.getsize(path)))
        except OSError as e:
            log.warning("Could not read %s: %s", path, e)

    found.sort(key=lambda item: (item[1], item[0]))
    counts = Counter(d.strftime("%Y-%m-%d") for _, d, _, _ in found)
    seen: Counter = Counter()
    snapshots = []
    for path, date, source, size in found:
        label = date.strftime("%Y-%m-%d")
        if counts[label] > 1:
            seen[label] += 1
            label = f"{label} ({seen[label]})"
        snapshots.append(SnapshotInfo(path=path, date=date, label=label, size=size, date_source=source))
    log.info("Found %d snapshots in %s", len(snapshots), folder)
    return snapshots


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_music(attrs: dict) -> bool:
    if any(attrs.get(flag) for flag in _EXCLUDED_FLAGS):
        return False
    return "audiobook" not in (attrs.get("Kind") or "").lower()


def parse_track(attrs: dict) -> Optional[Track]:
    if not _is_music(attrs):
        return None
    artist = clean_text(attrs.get("Artist")) or "Unknown Artist"
    year = _int(attrs.get("Year")) or None
    date_added = attrs.get("Date Added")
    return Track(
        persistent_id=attrs.get("Persistent ID"),
        name=clean_text(attrs.get("Name")) or "Unknown",
        artist=artist,
        album_artist=clean_text(attrs.get("Album Artist")) or artist,
        album=clean_text(attrs.get("Album")) or "Unknown Album",
        genre=clean_text(attrs.get("Genre")),
        year=year,
        duration_ms=_int(attrs.get("Total Time")),
        play_count=_int(attrs.get("Play Count")),
        skip_count=_int(attrs.get("Skip Count")),
        date_added=_naive_utc(date_added) if isinstance(date_added, datetime) else None,
        location=attrs.get("Location"),
    )


def load_snapshot(path: str, date: Optional[datetime] = None) -> Snapshot:
    """Parse a library export. Raises ValueError if the file is not a library."""
    log.info("Parsing %s", path)
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
    except plistlib.InvalidFileException as e:
        raise ValueError(f"{os.path.basename(path)} is not a valid library export") from e
    if not isinstance(data, dict) or not isinstance(data.get("Tracks"), dict):
        raise ValueError(f"{os.path.basename(path)} has no track list")

    if date is None:
        header_date = data.get("Date")
        date = _naive_utc(header_date) if isinstance(header_date, datetime) else snapshot_date(path)[0]

    tracks = [t for t in map(parse_track, data["Tracks"].values()) if t is not None]
    log.info("Parsed %d music tracks (%d entries)", len(tracks), len(data["Tracks"]))
    return Snapshot(path=path, date=date, tracks=tracks, library_id=data.get("Library Persistent ID"))
