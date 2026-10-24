"""Spotify's downloadable listening history.

Spotify sends two kinds of download (Account → Privacy → Download your data):

- "Extended streaming history": every stream since the account was made, in
  Streaming_History_Audio_*.json files. Each entry has the end time (`ts`,
  UTC), how long it played and whether it was skipped.
- "Account data": the past year only, in StreamingHistory_music_*.json (or
  StreamingHistory0.json in older downloads), with `endTime` and `msPlayed`.

Either can be imported as the .zip Spotify sends or as the extracted folder.
Podcasts, audiobooks and videos are left out. Like Spotify, a listen only
counts as a play from 30 seconds on; shorter ones count as skips.
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import datetime, timezone
from typing import Iterator, Optional

from .plays import Play, SourceError

MIN_PLAY_MS = 30_000
_EXTENDED = re.compile(r"Streaming_History_Audio_.*\.json$", re.IGNORECASE)
_ACCOUNT = re.compile(r"StreamingHistory(_music_\d+|\d+)\.json$", re.IGNORECASE)


def _wanted(name: str) -> bool:
    base = os.path.basename(name)
    return bool(_EXTENDED.search(base) or _ACCOUNT.search(base))


def _documents(path: str) -> Iterator[tuple[str, bytes]]:
    """(name, contents) of every history file in a zip, a folder or a single file."""
    if os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for name in sorted(files):
                if name.lower().endswith(".zip"):
                    yield from _documents(os.path.join(root, name))
                elif _wanted(name):
                    with open(os.path.join(root, name), "rb") as f:
                        yield name, f.read()
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if _wanted(name):
                    yield name, archive.read(name)
    elif os.path.isfile(path):
        with open(path, "rb") as f:
            yield os.path.basename(path), f.read()


def _timestamp(value: str) -> Optional[int]:
    value = value.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.fromisoformat(value) if fmt is None else datetime.strptime(value, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return None


def _play(entry: dict) -> Optional[Play]:
    if not isinstance(entry, dict):
        return None
    if "ts" in entry:  # extended history
        name = entry.get("master_metadata_track_name")
        artist = entry.get("master_metadata_album_artist_name")
        album = entry.get("master_metadata_album_album_name")
        ended = _timestamp(str(entry.get("ts") or ""))
        ms = entry.get("ms_played")
    else:  # account data
        name, artist, album = entry.get("trackName"), entry.get("artistName"), ""
        ended = _timestamp(str(entry.get("endTime") or ""))
        ms = entry.get("msPlayed")
    if ended is None or not isinstance(ms, int):
        return None
    return Play.make(name, artist, album, ended - ms // 1000, ms_played=ms, skipped=ms < MIN_PLAY_MS)


def read_export(path: str) -> list[Play]:
    """Every music listen in a Spotify download. Raises SourceError if there's none."""
    plays: list[Play] = []
    files = 0
    try:
        for name, data in _documents(path):
            try:
                entries = json.loads(data.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError) as e:
                raise SourceError(f"{name} isn't a Spotify history file ({e}).") from e
            if not isinstance(entries, list):
                continue
            files += 1
            plays.extend(p for p in map(_play, entries) if p is not None)
    except (OSError, zipfile.BadZipFile) as e:
        raise SourceError(f"Can't read {path}: {e}") from e
    if not files:
        raise SourceError("There's no Spotify listening history there. Choose the .zip Spotify sent you, "
                          "or the folder you extracted it to.")
    if not plays:
        raise SourceError("That Spotify download has no music listens in it.")
    return plays
