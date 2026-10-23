"""TunesBack's own history of your libraries.

Most players only keep running totals (play count, skip count), so comparing
two points in time needs two readings of the library. TunesBack takes those
readings itself and keeps them here, so nobody has to export files by hand.

A *source* is somewhere TunesBack reads from: a live library file it re-reads
whenever it changed, or a folder of exports it imports new files from. A
*reading* is the state of one source at one moment.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .model import Snapshot, Track
from .sources import itunes_xml

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,            -- player, e.g. "itunes"
    mode TEXT NOT NULL,            -- "file": a live library file; "folder": a folder of exports
    path TEXT NOT NULL,
    location TEXT NOT NULL,        -- "local" or "network"
    added_at TEXT NOT NULL,
    UNIQUE (kind, path)
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    date TEXT NOT NULL,            -- when the library was in this state
    taken_at TEXT NOT NULL,        -- when TunesBack read it
    origin TEXT NOT NULL,          -- "automatic" or "imported"
    file_path TEXT NOT NULL,
    file_mtime REAL NOT NULL,
    file_size INTEGER NOT NULL,
    track_count INTEGER NOT NULL,
    total_plays INTEGER NOT NULL,
    UNIQUE (source_id, file_path, file_mtime, file_size)
);
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    persistent_id TEXT, name TEXT, artist TEXT, album_artist TEXT, album TEXT, genre TEXT,
    year INTEGER, duration_ms INTEGER, date_added TEXT, location TEXT,
    UNIQUE (source_id, key)
);
CREATE TABLE IF NOT EXISTS counts (
    reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL,
    plays INTEGER NOT NULL,
    skips INTEGER NOT NULL,
    PRIMARY KEY (reading_id, track_id)
);
"""


@dataclass(frozen=True)
class ReadingResult:
    status: str  # "new", "unchanged" or "error"
    reading: Optional[dict] = None
    error: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _track_key(track: Track) -> str:
    return track.persistent_id or "k:" + "\x1f".join(track.match_key)


class LibraryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock, self._db:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # --- sources ---

    def add_source(self, kind: str, mode: str, path: str, location: str) -> dict:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO sources (kind, mode, path, location, added_at) VALUES (?, ?, ?, ?, ?)",
                (kind, mode, path, location, _now()))
            row = self._db.execute("SELECT * FROM sources WHERE kind = ? AND path = ?", (kind, path)).fetchone()
        return dict(row)

    def sources(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("""
                SELECT s.*, COUNT(r.id) AS reading_count, MAX(r.taken_at) AS last_reading
                FROM sources s LEFT JOIN readings r ON r.source_id = s.id
                GROUP BY s.id ORDER BY s.id""").fetchall()
        return [dict(r) for r in rows]

    def source(self, source_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return dict(row) if row else None

    def remove_source(self, source_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    # --- readings ---

    def readings(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("""
                SELECT r.id, r.source_id, r.date, r.taken_at, r.origin, r.file_path,
                       r.track_count, r.total_plays, s.kind, s.mode, s.path AS source_path
                FROM readings r JOIN sources s ON s.id = r.source_id
                ORDER BY r.date, r.id""").fetchall()
        return [dict(r) for r in rows]

    def refresh(self, source_id: int) -> list[ReadingResult]:
        """Read a source again: a changed library file, or new files in an exports folder."""
        source = self.source(source_id)
        if source is None:
            return [ReadingResult("error", error="That library is no longer set up.")]
        if source["mode"] == "folder":
            return self.import_folder(source_id, source["path"], origin="automatic")
        return [self.read_file(source_id, source["path"], origin="automatic")]

    def import_folder(self, source_id: int, folder: str, origin: str = "imported") -> list[ReadingResult]:
        if not os.path.isdir(folder):
            return [ReadingResult("error", error=f"Can't reach {folder}. Is the drive connected?")]
        return [self.read_file(source_id, info.path, origin, info.date) for info in itunes_xml.scan_folder(folder)]

    def read_file(self, source_id: int, path: str, origin: str, date: Optional[datetime] = None) -> ReadingResult:
        """Record a reading of one library file, unless that exact file was read before."""
        try:
            st = os.stat(path)
        except OSError:
            return ReadingResult("error", error=f"Can't reach {path}. Is the drive connected?")
        with self._lock:
            existing = self._db.execute(
                "SELECT id FROM readings WHERE source_id = ? AND file_path = ? AND file_mtime = ? AND file_size = ?",
                (source_id, path, st.st_mtime, st.st_size)).fetchone()
        if existing:
            return ReadingResult("unchanged", reading=self._reading(existing["id"]))
        try:
            snapshot = itunes_xml.load_snapshot(path, date)
        except (ValueError, OSError) as e:
            return ReadingResult("error", error=str(e))
        reading_id = self._store(source_id, snapshot, origin, path, st)
        log.info("Recorded reading %s of %s (%d tracks)", reading_id, path, len(snapshot.tracks))
        return ReadingResult("new", reading=self._reading(reading_id))

    def _store(self, source_id: int, snapshot: Snapshot, origin: str, path: str, st: os.stat_result) -> int:
        with self._lock, self._db:
            cursor = self._db.execute(
                """INSERT INTO readings (source_id, date, taken_at, origin, file_path, file_mtime, file_size,
                                         track_count, total_plays) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_id, snapshot.date.isoformat(timespec="seconds"), _now(), origin, path, st.st_mtime,
                 st.st_size, len(snapshot.tracks), sum(t.play_count for t in snapshot.tracks)))
            reading_id = cursor.lastrowid
            # Track details are kept once per source and updated to the newest reading.
            self._db.executemany(
                """INSERT INTO tracks (source_id, key, persistent_id, name, artist, album_artist, album, genre,
                                       year, duration_ms, date_added, location)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (source_id, key) DO UPDATE SET
                     name = excluded.name, artist = excluded.artist, album_artist = excluded.album_artist,
                     album = excluded.album, genre = excluded.genre, year = excluded.year,
                     duration_ms = excluded.duration_ms, date_added = excluded.date_added,
                     location = excluded.location""",
                [(source_id, _track_key(t), t.persistent_id, t.name, t.artist, t.album_artist, t.album, t.genre,
                  t.year, t.duration_ms, t.date_added.isoformat() if t.date_added else None, t.location)
                 for t in snapshot.tracks])
            ids = dict(self._db.execute("SELECT key, id FROM tracks WHERE source_id = ?", (source_id,)).fetchall())
            self._db.executemany(
                "INSERT OR REPLACE INTO counts (reading_id, track_id, plays, skips) VALUES (?, ?, ?, ?)",
                [(reading_id, ids[_track_key(t)], t.play_count, t.skip_count) for t in snapshot.tracks])
        return reading_id

    def _reading(self, reading_id: int) -> Optional[dict]:
        return next((r for r in self.readings() if r["id"] == reading_id), None)

    def load(self, reading_id: int) -> Snapshot:
        with self._lock:
            reading = self._db.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
            if reading is None:
                raise KeyError(reading_id)
            rows = self._db.execute("""
                SELECT t.*, c.plays, c.skips FROM counts c JOIN tracks t ON t.id = c.track_id
                WHERE c.reading_id = ?""", (reading_id,)).fetchall()
        tracks = [Track(
            persistent_id=r["persistent_id"], name=r["name"], artist=r["artist"], album_artist=r["album_artist"],
            album=r["album"], genre=r["genre"], year=r["year"], duration_ms=r["duration_ms"] or 0,
            play_count=r["plays"], skip_count=r["skips"],
            date_added=datetime.fromisoformat(r["date_added"]) if r["date_added"] else None,
            location=r["location"]) for r in rows]
        return Snapshot(path=reading["file_path"], date=datetime.fromisoformat(reading["date"]), tracks=tracks)

    def remove_readings(self, reading_ids: Iterable[int]) -> None:
        with self._lock, self._db:
            self._db.executemany("DELETE FROM readings WHERE id = ?", [(i,) for i in reading_ids])
