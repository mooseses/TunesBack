"""The Dev space: dry runs, diagnostics and housekeeping for tracking down problems."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import __version__
from ..library import LibraryStore, play_key
from ..sources.plays import Play, Stopped

# Text in different scripts, to see which installed font draws each on cards.
SCRIPT_SAMPLES = [
    ("Japanese", "夜に駆ける"), ("Chinese", "群青日和"), ("Korean", "윤도현"), ("Cyrillic", "Привет"),
    ("Greek", "Καλημέρα"), ("Arabic", "مرحبا"), ("Hebrew", "שלום"), ("Thai", "สวัสดี"),
    ("Devanagari", "नमस्ते"), ("Emoji", "🎧"),
]


class LimitReached(Stopped):
    """A dry run fetched as many batches as it was asked to."""


class DryRun:
    """Stands in for the library store during a sync: fetches and parses for real,
    but only counts what would be stored, and never writes anything."""

    def __init__(self, store: LibraryStore, source_id: Optional[int], fresh: bool, limit: int):
        self.store = store
        self.source_id = source_id
        self.fresh = fresh  # act as if nothing had been imported yet
        self.limit = limit
        self.batches: list[dict] = []
        self.samples: list[dict] = []
        self.plays = self.new = self.no_album = self.with_art = 0
        self.would_save: dict = {}

    # The parts of LibraryStore that sync_history uses:

    def source(self, source_id: int) -> dict:
        if self.fresh or self.source_id is None:
            return {"options": {}}
        return self.store.source(source_id) or {"options": {}}

    def set_options(self, source_id: int, **changes) -> dict:
        self.would_save = changes
        return changes

    def add_plays(self, source_id: int, plays: list[Play]) -> int:
        if len(self.batches) >= self.limit:
            raise LimitReached
        low, high = min(p.played_at for p in plays), max(p.played_at for p in plays)
        stored = self.store.existing_plays(self.source_id, low, high) if self.source_id is not None else set()
        new = sum((p.played_at, play_key(p)) not in stored for p in plays)
        self.batches.append({"plays": len(plays), "new": new, "oldest": _iso(low), "newest": _iso(high)})
        self.plays += len(plays)
        self.new += new
        self.no_album += sum(not p.album for p in plays)
        self.with_art += sum(bool(p.art_url) for p in plays)
        for p in plays[: max(0, 8 - len(self.samples))]:
            self.samples.append({"name": p.name, "artist": p.artist, "album": p.album, "played_at": _iso(p.played_at),
                                 "ms_played": p.ms_played, "duration_ms": p.duration_ms, "art_url": p.art_url})
        return new

    def report(self, outcome: str, client_stats: dict) -> dict:
        times = [b["oldest"] for b in self.batches] + [b["newest"] for b in self.batches]
        return {
            "outcome": outcome, "mode": "from scratch" if self.fresh else "next sync",
            "batches": self.batches, "plays": self.plays, "new": self.new, "already_stored": self.plays - self.new,
            "oldest": min(times) if times else None, "newest": max(times) if times else None,
            "without_album": self.no_album, "with_artwork": self.with_art, "samples": self.samples,
            "would_save": self.would_save.get("sync"), "requests": client_stats.get("requests", 0),
            "retries": client_stats.get("retries", 0), "seconds": round(client_stats.get("seconds", 0.0), 2),
        }


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def folder_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def empty_folder(path: Path) -> int:
    """Delete everything in a folder (keeping the folder). Returns the bytes freed."""
    freed = folder_size(path)
    if path.is_dir():
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    return freed


def versions(backend: Optional[str]) -> dict:
    def version_of(module: str) -> str:
        try:
            from importlib.metadata import version
            return version(module)
        except Exception:
            return "?"
    return {
        "TunesBack": __version__, "Python": platform.python_version(), "Platform": platform.platform(),
        "Packaged": "yes" if getattr(sys, "frozen", False) else "no", "Window": backend or "browser",
        "pywebview": version_of("pywebview"), "Pillow": version_of("Pillow"), "resvg-py": version_of("resvg-py"),
    }


def font_report() -> dict:
    from ..cards.fonts import FontSpec, bundled_face, runs, _bundled
    design = bundled_face(FontSpec("Figtree", 700))
    fallbacks = []
    for script, text in SCRIPT_SAMPLES:
        faces = {f.families[0] if f else "(none)": (f.path if f else "") for f, _piece in runs(text, design)
                 if f is not design}
        name, path = next(iter(faces.items()), ("Figtree", ""))
        fallbacks.append({"script": script, "sample": text, "font": name, "file": path})
    return {"bundled": sorted({f.family for f in _bundled()}), "fallbacks": fallbacks}
