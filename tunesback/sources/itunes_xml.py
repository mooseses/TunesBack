"""iTunes / Apple Music "Export Library" XML snapshots."""
from __future__ import annotations

import logging
import os
import plistlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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


# --- discovery ---

@dataclass(frozen=True, slots=True)
class Candidate:
    """A place a library might be."""

    path: str
    kind: str  # "library": a library file to read; "exports": a folder of exports; "needs_export": found, but unreadable
    date: Optional[datetime] = None
    size: int = 0
    note: Optional[str] = None


_LIBRARY_NAMES = ("iTunes Library.xml", "iTunes Music Library.xml")


def _windows_prefs_locations() -> list[str]:
    """Library XML locations recorded in iTunes for Windows' preferences, if any."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    prefs = os.path.join(appdata, "Apple Computer", "iTunes", "iTunesPrefs.xml")
    try:
        with open(prefs, "rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return []
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.startswith("iTunes Library XML Location") and isinstance(value, bytes):
                    path = value.decode("utf-16-le", errors="ignore").rstrip("\x00")
                    if path:
                        found.append(path)
                else:
                    walk(value)

    walk(data)
    return found


def _local_library_paths() -> list[str]:
    home = Path.home()
    music = [home / "Music", home / "OneDrive" / "Music"]
    paths = [str(m / "iTunes" / name) for m in music for name in _LIBRARY_NAMES]
    paths += _windows_prefs_locations()
    # iTunes under Wine on Linux
    for users in (home / ".wine" / "drive_c" / "users").glob("*"):
        for folder in ("Music", "My Music"):
            paths += [str(users / folder / "iTunes" / name) for name in _LIBRARY_NAMES]
    return paths


def _xml_exports_in(folders: list[Path]) -> list[str]:
    found = []
    for folder in folders:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        found += [str(folder / n) for n in names if n.lower().endswith(".xml")]
    return found


def _describe(path: str, kind: str = "library") -> Optional[Candidate]:
    try:
        header = _read_header(path)
        if not is_library_export(header):
            return None
        date, _ = snapshot_date(path, header)
        return Candidate(path=path, kind=kind, date=date, size=os.path.getsize(path))
    except OSError:
        return None


def discover(root: Optional[str] = None, max_dirs: int = 4000) -> list[Candidate]:
    """Look for iTunes / Apple Music libraries.

    Without `root`, check where iTunes keeps its library on this computer and
    a few places people save exports. With `root` (e.g. a mounted network
    share), search inside it a few levels deep.
    """
    found: dict[str, Candidate] = {}

    def add(candidate: Optional[Candidate]) -> None:
        if candidate and candidate.path not in found:
            found[candidate.path] = candidate

    if root is None:
        for path in _local_library_paths():
            if os.path.isfile(path):
                add(_describe(path))
        home = Path.home()
        for path in _xml_exports_in([home / "Music", home / "Music" / "iTunes", home / "Desktop",
                                     home / "Documents", home / "Downloads"]):
            add(_describe(path))
        music_app = home / "Music" / "Music" / "Music Library.musiclibrary"
        if music_app.exists():
            add(Candidate(path=str(music_app), kind="needs_export",
                          note="The Music app on macOS doesn't share its library automatically."))
    else:
        root = os.path.expanduser(root)
        visited = 0
        for current, dirs, files in os.walk(root):
            visited += 1
            depth = os.path.relpath(current, root).count(os.sep)
            if depth >= 3 or visited > max_dirs:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.lower().endswith(".xml"):
                    add(_describe(os.path.join(current, name)))

    # Folders holding several exports are better offered as a folder.
    by_folder: dict[str, list[Candidate]] = {}
    for c in found.values():
        if c.kind == "library":
            by_folder.setdefault(os.path.dirname(c.path), []).append(c)
    results = [c for c in found.values() if c.kind != "library"]
    for folder, items in by_folder.items():
        if len(items) > 1 and not any(os.path.basename(c.path) in _LIBRARY_NAMES for c in items):
            newest = max(items, key=lambda c: c.date or datetime.min)
            results.append(Candidate(path=folder, kind="exports", date=newest.date, size=len(items)))
        else:
            results += items
    order = {"library": 0, "exports": 1, "needs_export": 2}
    return sorted(results, key=lambda c: (order[c.kind], -(c.date.timestamp() if c.date else 0)))
