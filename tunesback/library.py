"""TunesBack's own history of your listening.

Sources come in two kinds:

- Counter sources (iTunes and most players) only keep running totals per
  track, so comparing two points in time needs two readings. TunesBack takes
  those readings itself: a live library file it re-reads whenever it changed,
  or a folder of exports it imports new files from. A *reading* is the state
  of one source at one moment.
- Play sources (Last.fm, ListenBrainz, a Spotify data export) log every
  listen with a timestamp. Those are kept as *plays*, one row per listen, so
  any date range can be counted directly.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .model import Snapshot, Track, normalize_key
from .sources import itunes_xml
from .sources.plays import Play

# Bumped whenever the schema changes; LibraryStore migrates older files on open.
SCHEMA_VERSION = 2

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,            -- "itunes", "lastfm", "listenbrainz", "spotify"
    mode TEXT NOT NULL,            -- "file" (live library file), "folder" (of exports),
                                   -- "account" (an online profile) or "export" (a data download)
    path TEXT NOT NULL,            -- file or folder, or the account's user name
    location TEXT NOT NULL,        -- "local", "network" or "online"
    added_at TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '{}',  -- JSON: sync progress and the like
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
    art_url TEXT,
    UNIQUE (source_id, key)
);
CREATE TABLE IF NOT EXISTS counts (
    reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL,
    plays INTEGER NOT NULL,
    skips INTEGER NOT NULL,
    PRIMARY KEY (reading_id, track_id)
);
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    played_at INTEGER NOT NULL,    -- when the listen started, Unix time (UTC)
    ms_played INTEGER,             -- how long, when the source says
    skipped INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_id, played_at, track_id)
);
CREATE INDEX IF NOT EXISTS plays_by_time ON plays (source_id, played_at);
"""

# Steps from each older schema version to the next.
_MIGRATIONS = {
    1: ["ALTER TABLE sources ADD COLUMN options TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE tracks ADD COLUMN art_url TEXT"],
}


def _with_options(row: sqlite3.Row) -> dict:
    out = dict(row)
    try:
        out["options"] = json.loads(out.get("options") or "{}")
    except ValueError:
        out["options"] = {}
    return out


@dataclass(frozen=True)
class ReadingResult:
    status: str  # "new", "unchanged" or "error"
    reading: Optional[dict] = None
    error: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _track_key(track: Track) -> str:
    return track.persistent_id or "k:" + "\x1f".join(track.match_key)


def play_key(play: Play) -> str:
    """How a listened-to track is keyed in the store (title, artist, album)."""
    return "k:" + "\x1f".join((normalize_key(play.name), normalize_key(play.artist), normalize_key(play.album)))


_play_key = play_key


class LibraryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock, self._db:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._migrate()
            self._db.executescript(SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        exists = self._db.execute("SELECT 1 FROM sqlite_master WHERE name = 'sources'").fetchone()
        if not exists:
            return  # a new file: the schema below creates everything
        version = version or 1  # files from before versioning
        while version < SCHEMA_VERSION:
            for statement in _MIGRATIONS.get(version, []):
                self._db.execute(statement)
            version += 1

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
                SELECT s.*,
                       (SELECT COUNT(*) FROM readings r WHERE r.source_id = s.id) AS reading_count,
                       (SELECT MAX(taken_at) FROM readings r WHERE r.source_id = s.id) AS last_reading,
                       (SELECT COUNT(*) FROM plays p WHERE p.source_id = s.id) AS play_count,
                       (SELECT MIN(played_at) FROM plays p WHERE p.source_id = s.id) AS first_play,
                       (SELECT MAX(played_at) FROM plays p WHERE p.source_id = s.id) AS last_play
                FROM sources s ORDER BY s.id""").fetchall()
        return [_with_options(r) for r in rows]

    def source(self, source_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return _with_options(row) if row else None

    def set_path(self, source_id: int, path: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE sources SET path = ? WHERE id = ?", (path, source_id))

    def set_options(self, source_id: int, **changes) -> dict:
        """Merge changes into a source's options (e.g. how far a sync got)."""
        with self._lock, self._db:
            row = self._db.execute("SELECT options FROM sources WHERE id = ?", (source_id,)).fetchone()
            options = {**json.loads(row["options"] or "{}"), **changes} if row else dict(changes)
            self._db.execute("UPDATE sources SET options = ? WHERE id = ?", (json.dumps(options), source_id))
        return options

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
        if source["mode"] not in ("file", "folder"):
            return []  # play sources are synced, not read
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

    # --- plays ---

    def add_plays(self, source_id: int, plays: Iterable[Play]) -> int:
        """Store listens; ones already stored are skipped. Returns how many were new."""
        plays = list(plays)
        if not plays:
            return 0
        with self._lock, self._db:
            tracks: dict[str, Play] = {}
            for play in plays:
                tracks.setdefault(_play_key(play), play)
            # Keep what's known about a track: a later play without a length or art doesn't erase it.
            self._db.executemany(
                """INSERT INTO tracks (source_id, key, name, artist, album_artist, album, duration_ms, art_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (source_id, key) DO UPDATE SET
                     duration_ms = COALESCE(excluded.duration_ms, tracks.duration_ms),
                     art_url = COALESCE(excluded.art_url, tracks.art_url)""",
                [(source_id, key, p.name, p.artist, p.album_artist or p.artist, p.album, p.duration_ms, p.art_url)
                 for key, p in tracks.items()])
            ids = dict(self._db.execute("SELECT key, id FROM tracks WHERE source_id = ?", (source_id,)).fetchall())
            before = self._db.total_changes
            self._db.executemany(
                "INSERT OR IGNORE INTO plays (source_id, track_id, played_at, ms_played, skipped) VALUES (?, ?, ?, ?, ?)",
                [(source_id, ids[_play_key(p)], p.played_at, p.ms_played, int(p.skipped)) for p in plays])
            return self._db.total_changes - before

    def plays(self, source_ids: Iterable[int], start: Optional[int] = None, end: Optional[int] = None) -> list[sqlite3.Row]:
        """Listens from these sources with start <= played_at < end, oldest first, with track details."""
        ids = list(source_ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        query = f"""SELECT p.source_id, p.played_at, p.ms_played, p.skipped, t.id AS track_id, t.name, t.artist,
                           t.album_artist, t.album, t.genre, t.year, t.duration_ms, t.location, t.art_url
                    FROM plays p JOIN tracks t ON t.id = p.track_id
                    WHERE p.source_id IN ({marks}) AND p.played_at >= ? AND p.played_at < ?
                    ORDER BY p.played_at"""
        with self._lock:
            return self._db.execute(query, (*ids, start if start is not None else -2**62,
                                            end if end is not None else 2**62)).fetchall()

    def existing_plays(self, source_id: int, start: int, end: int) -> set[tuple[int, str]]:
        """(played_at, track key) of stored listens with start <= played_at <= end."""
        with self._lock:
            rows = self._db.execute("""SELECT p.played_at, t.key FROM plays p JOIN tracks t ON t.id = p.track_id
                                       WHERE p.source_id = ? AND p.played_at BETWEEN ? AND ?""",
                                    (source_id, start, end)).fetchall()
        return {(r[0], r[1]) for r in rows}

    def forget_plays(self, source_id: int) -> int:
        """Delete a source's listens and sync progress (it then imports everything again)."""
        with self._lock, self._db:
            deleted = self._db.execute("DELETE FROM plays WHERE source_id = ?", (source_id,)).rowcount
        self.set_options(source_id, sync={})
        return deleted

    def stats(self) -> dict:
        with self._lock:
            counts = {table: self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("sources", "readings", "tracks", "counts", "plays")}
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
        return {"schema": version, "rows": counts}

    def first_plays(self, source_ids: Iterable[int]) -> list[sqlite3.Row]:
        """When each track was first played (for spotting what was new in a period)."""
        ids = list(source_ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        with self._lock:
            return self._db.execute(f"""
                SELECT t.name, t.artist, MIN(p.played_at) AS first
                FROM plays p JOIN tracks t ON t.id = p.track_id
                WHERE p.source_id IN ({marks}) AND p.skipped = 0 GROUP BY t.id""", ids).fetchall()

    def library_tracks(self) -> list[sqlite3.Row]:
        """Every track of every counter source, newest details first: used to fill in what
        play sources don't know (genre, year, length, the music file for artwork)."""
        with self._lock:
            return self._db.execute("""
                SELECT t.name, t.artist, t.album, t.genre, t.year, t.duration_ms, t.location
                FROM tracks t JOIN sources s ON s.id = t.source_id
                WHERE s.mode IN ('file', 'folder') ORDER BY t.id DESC""").fetchall()
