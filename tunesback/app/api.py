"""Everything the interface can ask the Python side to do.

Each public method takes JSON-compatible arguments and returns a JSON-compatible
dict. Expected failures are returned as {"error": message}.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections import OrderedDict, deque
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlsplit

from .. import __version__
from ..art import artwork
from ..art.artwork import ThumbnailCache
from ..cards import CardChoice, CardData, build_data, catalog, draw, normalize, plan, resolve_theme
from ..cards.layouts.base import FORMATS
from ..cards.registry import CARD_TYPES
from ..cards.themes import THEMES
from ..library import LibraryStore
from ..cards import canvas as card_canvas
from ..cards.selftest import sample_data
from ..recap import COUNTER_MODES, build_recap, source_name
from ..sources import http, itunes_xml, lastfm, spotify
from ..sources.catalog import CATALOG
from ..sources.lastfm import LastFm
from ..sources.listenbrainz import ListenBrainz
from ..sources.plays import SourceError, Stopped, sync_history
from ..stats.report import Report, build_report
from . import devtools
from .settings import FLAGS, Settings, cache_dir, config_dir, configure_logging, data_dir, log_dir

if TYPE_CHECKING:
    from .window import DesktopWindow

log = logging.getLogger(__name__)

WEBSITE = "https://github.com/mooseses/TunesBack"


def relaunch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, "-m", "tunesback", *sys.argv[1:]]


class UserError(Exception):
    """A problem to show to the user as-is."""


class Cancelled(Exception):
    pass


class Api:
    def __init__(self, settings: Settings, thumbnail_dir: Optional[Path] = None, store_path: Optional[Path] = None):
        self.settings = settings
        self.window: Optional["DesktopWindow"] = None  # None when running in a plain browser
        self._lock = threading.Lock()
        self._analysis_lock = threading.Lock()
        self._report: Optional[Report] = None
        self._report_version = 0
        self._card_lock = threading.Lock()
        self._card_data: Optional[CardData] = None
        self._card_data_key: Optional[tuple] = None
        self._card_cache: OrderedDict[tuple, bytes] = OrderedDict()
        # Long jobs report progress on their own channel, so a sync in the
        # background and an analysis in the foreground don't mix.
        self._progress = {"analysis": {"running": False, "stage": ""}, "sync": {"running": False, "stage": ""}}
        self._cancel = {"analysis": threading.Event(), "sync": threading.Event()}
        self._sync_lock = threading.Lock()
        self._thumb_dir = thumbnail_dir or cache_dir() / "thumbnails"
        self._thumbs = ThumbnailCache(cache_dir=self._thumb_dir)
        artwork.REMOTE_CACHE = self._thumb_dir.parent / "covers"
        self._store_path = store_path or data_dir() / "library.sqlite"
        self._calls: deque = deque(maxlen=200)  # recent API calls, for the Dev space
        self._render_times: deque = deque(maxlen=60)
        self._apply_flags()
        self.store = LibraryStore(self._store_path)
        self._migrate_snapshot_folder()

    # --- dispatch ---

    ACTIONS = frozenset({
        "state", "update_settings", "open_logs", "open_website", "open_url", "pick_folder", "pick_file", "progress", "cancel",
        "catalog", "discover", "add_library", "import_exports", "refresh_readings", "library", "remove_library",
        "add_account", "import_history", "sync_sources", "set_lastfm_key",
        "dev_info", "dev_log", "dry_run_sync", "reset_sync", "forget_plays", "clear_caches",
        "window_set_controls_visible",
        "analyze", "artwork", "card_options", "cards", "save_cards", "restart",
        "window_info", "window_minimize", "window_toggle_maximize", "window_close",
        "window_start_move", "window_start_resize",
    })

    def call(self, method: str, args: dict[str, Any]) -> dict:
        if method not in self.ACTIONS:
            return {"error": f"Unknown action: {method}"}
        handler = getattr(self, method)
        started = time.perf_counter()
        try:
            result = handler(**args)
        except UserError as e:
            result = {"error": str(e)}
        except TypeError as e:
            log.exception("Bad arguments for %s", method)
            result = {"error": f"Bad request: {e}"}
        except Exception as e:  # keep the interface alive and leave a trace in the log
            log.exception("%s failed", method)
            result = {"error": f"Something went wrong: {e}"}
        if method not in ("dev_log", "progress"):
            self._calls.append({"at": time.strftime("%H:%M:%S"), "action": method,
                                "ms": round((time.perf_counter() - started) * 1000, 1),
                                "error": result.get("error") if isinstance(result, dict) else None})
        return result

    # --- app state ---

    def state(self) -> dict:
        return {
            "version": __version__,
            "platform": platform.system(),
            "desktop": self.window is not None,
            "window": self.window.info() if self.window else None,
            "settings": self.settings.as_dict(),
            "log_dir": str(log_dir()),
        }

    def update_settings(self, changes: dict) -> dict:
        before = self.settings["debug_logging"]
        values = self.settings.update(changes)
        if values["debug_logging"] != before:
            configure_logging(values["debug_logging"])
        if "flags" in changes:
            self._apply_flags()
        return {"settings": values}

    def _apply_flags(self) -> None:
        flags = self.settings["flags"]
        for name in http.SIMULATE:
            http.SIMULATE[name] = bool(flags.get(name))
        if card_canvas.GUIDES != bool(flags.get("card_guides")):
            card_canvas.GUIDES = bool(flags.get("card_guides"))
            with self._card_lock:
                self._card_cache.clear()

    def open_website(self) -> dict:
        webbrowser.open(WEBSITE)
        return {"ok": True}

    # Pages the interface may open in the system browser (help for setting up sources).
    LINK_HOSTS = ("www.last.fm", "www.spotify.com", "listenbrainz.org", "github.com")

    def open_url(self, url: str) -> dict:
        parts = urlsplit(str(url))
        if parts.scheme != "https" or parts.hostname not in self.LINK_HOSTS:
            raise UserError("TunesBack only opens its help pages.")
        webbrowser.open(parts.geturl())
        return {"ok": True}

    def restart(self) -> dict:
        """Start a fresh copy of the app, then close this one (e.g. to apply the title bar setting)."""
        if self.window is None:
            raise UserError("Restart TunesBack to apply this change.")
        kwargs: dict[str, Any] = {"close_fds": True}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(relaunch_command(), **kwargs)
        self.window.close()
        return {"ok": True}

    # --- window controls (custom title bar) ---

    def _window(self) -> "DesktopWindow":
        if self.window is None:
            raise UserError("Not available in the browser.")
        return self.window

    def window_info(self) -> dict:
        return {"window": self.window.info() if self.window else None}

    def window_minimize(self) -> dict:
        self._window().minimize()
        return {"ok": True}

    def window_toggle_maximize(self) -> dict:
        self._window().toggle_maximize()
        return {"ok": True}

    def window_close(self) -> dict:
        self._window().close()
        return {"ok": True}

    def window_start_move(self) -> dict:
        self._window().start_move()
        return {"ok": True}

    def window_start_resize(self, edge: str) -> dict:
        self._window().start_resize(edge)
        return {"ok": True}

    def open_logs(self) -> dict:
        path = log_dir()
        path.mkdir(parents=True, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if system == "Darwin" else "xdg-open", str(path)])
        return {"path": str(path)}

    # --- choosing files ---

    def pick_folder(self) -> dict:
        if self.window is None:
            return {"path": None, "unsupported": True}
        return {"path": self.window.pick_folder()}

    def pick_file(self, kind: str = "itunes") -> dict:
        if self.window is None:
            return {"path": None, "unsupported": True}
        types = {"spotify": ("Spotify data (*.zip;*.json)",)}.get(kind, ("Library exports (*.xml)",))
        return {"path": self.window.pick_file(types)}

    # --- set-up and library readings ---

    def catalog(self) -> dict:
        return {"sources": CATALOG, "lastfm_key": bool(self._lastfm_key()), "lastfm_key_url": lastfm.KEY_URL,
                "lastfm_key_info": self._key_info()}

    def discover(self, root: Optional[str] = None) -> dict:
        if root is not None:
            root = os.path.expanduser(root.strip())
            if not os.path.isdir(root):
                raise UserError("That folder doesn't exist, or the drive isn't connected.")
        return {"candidates": [
            {"path": c.path, "kind": c.kind, "date": c.date.isoformat() if c.date else None,
             "size": c.size, "note": c.note}
            for c in itunes_xml.discover(root)
        ]}

    def add_library(self, path: str, location: str = "local") -> dict:
        """Remember a library (file or folder of exports) and take its first reading."""
        path = os.path.expanduser((path or "").strip())
        location = "network" if location == "network" else "local"
        if os.path.isdir(path):
            if not itunes_xml.scan_folder(path):
                raise UserError("There are no library exports in that folder.")
            mode = "folder"
        elif os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    header = f.read(16 * 1024)
            except OSError as e:
                raise UserError(f"Can't open that file: {e}") from e
            if not itunes_xml.is_library_export(header):
                raise UserError("That file isn't an iTunes or Apple Music library export.")
            mode = "file"
        else:
            raise UserError("Can't find that file or folder. Is the drive connected?")

        source = self.store.add_source("itunes", mode, path, location)
        results = self.store.refresh(source["id"])
        errors = [r.error for r in results if r.status == "error"]
        readings = [r.reading for r in results if r.reading]
        if not readings:
            self.store.remove_source(source["id"])
            raise UserError(errors[0] if errors else "TunesBack couldn't read that library.")
        self.settings.update({"setup_done": True})
        latest = max(readings, key=lambda r: r["date"])
        return {"source": self._source_json(source["id"]), "readings": len(readings),
                "tracks": latest["track_count"], "plays": latest["total_plays"]}

    def import_exports(self, folder: str, source_id: Optional[int] = None) -> dict:
        """Add a folder of older exports as history for a library."""
        folder = os.path.expanduser((folder or "").strip())
        if source_id is None:
            sources = [s for s in self.store.sources() if s["kind"] == "itunes"]
            if not sources:
                return self.add_library(folder)
            source_id = sources[0]["id"]
        results = self.store.import_folder(int(source_id), folder)
        new = sum(1 for r in results if r.status == "new")
        errors = [r.error for r in results if r.status == "error"]
        if not new and errors:
            raise UserError(errors[0])
        if not results:
            raise UserError("There are no library exports in that folder.")
        return {"imported": new, "skipped": len(results) - new}

    def refresh_readings(self) -> dict:
        """Take a new reading of every library that changed (done at start-up)."""
        new, problems = 0, []
        for source in self.store.sources():
            for result in self.store.refresh(source["id"]):
                if result.status == "new":
                    new += 1
                elif result.status == "error":
                    problems.append({"source": source["path"], "error": result.error})
        return {"new": new, "problems": problems}

    # --- play sources ---

    def _lastfm_key(self) -> Optional[str]:
        return lastfm.bundled_key() or self.settings["lastfm_api_key"]

    def _service(self, source: dict, api_key: Optional[str] = None):
        stop = self._cancel["sync"].is_set
        if source["kind"] == "lastfm":
            key = api_key or self._lastfm_key()
            if not key:
                raise UserError("Last.fm needs an API key. Add one in set-up.")
            return LastFm(source["path"], key, stop=stop)
        if source["kind"] == "listenbrainz":
            return ListenBrainz(source["path"], stop=stop)
        raise UserError("That source can't be synced.")

    def add_account(self, kind: str, username: str, api_key: Optional[str] = None) -> dict:
        """Connect a Last.fm or ListenBrainz profile and import its history."""
        username = (username or "").strip()
        if kind not in ("lastfm", "listenbrainz"):
            raise UserError("Unknown kind of account.")
        if not username:
            raise UserError("Enter a user name.")
        api_key = (api_key or "").strip() or None
        self._cancel["sync"].clear()
        try:
            account = self._service({"kind": kind, "path": username}, api_key).check()
        except SourceError as e:
            raise UserError(str(e)) from e
        except Stopped as e:
            raise UserError("Stopped before anything was imported.") from e
        if kind == "lastfm" and api_key and not lastfm.bundled_key():
            self.settings.update({"lastfm_api_key": api_key})
        source = self.store.add_source(kind, "account", account["name"], "online")
        self.settings.update({"setup_done": True})
        result = self.sync_sources(source_id=source["id"], keep_stop=True)
        return {"source": self._source_json(source["id"]), "expected": account["plays"], **result}

    def import_history(self, path: str, kind: str = "spotify") -> dict:
        """Import a downloaded listening history (Spotify)."""
        path = os.path.expanduser((path or "").strip())
        if kind != "spotify":
            raise UserError("Unknown kind of history.")
        if not os.path.exists(path):
            raise UserError("Can't find that file or folder.")
        try:
            plays = spotify.read_export(path)
        except SourceError as e:
            raise UserError(str(e)) from e
        # A newer download of the same account goes into the same source; listens already there are skipped.
        existing = next((s for s in self.store.sources() if s["kind"] == "spotify"), None)
        if existing:
            self.store.set_path(existing["id"], path)
            source = existing
        else:
            source = self.store.add_source("spotify", "export", path, "local")
        new = self.store.add_plays(source["id"], plays)
        self.settings.update({"setup_done": True})
        return {"source": self._source_json(source["id"]), "plays": len(plays), "new": new}

    def sync_sources(self, source_id: Optional[int] = None, quiet: bool = False, keep_stop: bool = False) -> dict:
        """Fetch new listens from online accounts (one, or all of them). `quiet`: return
        at once if a sync is already running. `keep_stop`: honour a Stop pressed earlier."""
        if not self._sync_lock.acquire(blocking=not quiet):
            return {"new": 0, "problems": [], "busy": True}
        if not keep_stop:
            self._cancel["sync"].clear()
        new, problems, stopped = 0, [], False
        try:
            accounts = [s for s in self.store.sources() if s["mode"] == "account"
                        and (source_id is None or s["id"] == int(source_id))]
            for source in accounts:
                name = source_name(source)
                found, error = 0, None
                before = source.get("play_count") or 0
                with self._lock:
                    self._progress["sync"] = {"running": True, "stage": f"{name}: connecting…", "source": source["id"]}
                try:
                    service = self._service(source)
                    found = sync_history(self.store, source["id"], service.newer, service.older,
                                         progress=lambda text, name=name, sid=source["id"]: self._set_stage(
                                             "sync", f"{name}: {text}", source=sid),
                                         stop=self._cancel["sync"].is_set)
                    new += found
                except Stopped:
                    # What was fetched before the stop is kept.
                    stopped = True
                    found = next((s["play_count"] for s in self.store.sources() if s["id"] == source["id"]), before) - before
                    new += found
                    self._record_sync(source["id"], found, None, stopped=True)
                    break
                except (SourceError, UserError) as e:
                    error = str(e)
                    problems.append({"source": name, "error": error})
                self._record_sync(source["id"], found, error)
        finally:
            with self._lock:
                self._progress["sync"] = {"running": False, "stage": ""}
            self._sync_lock.release()
        return {"new": new, "problems": problems, "stopped": stopped}

    def _record_sync(self, source_id: int, new: int, error: Optional[str], stopped: bool = False) -> None:
        """Remember how a sync went: shown on the Services page."""
        options = (self.store.source(source_id) or {}).get("options", {})
        entry = {"at": datetime.now().isoformat(timespec="seconds"), "new": new, "error": error, "stopped": stopped}
        history = [entry, *(options.get("history") or [])][:10]
        self.store.set_options(source_id, last_sync=entry, history=history)

    def set_lastfm_key(self, api_key: str) -> dict:
        """Change the Last.fm API key (checked against a connected account first)."""
        api_key = (api_key or "").strip()
        if not api_key:
            raise UserError("Enter an API key.")
        account = next((s for s in self.store.sources() if s["kind"] == "lastfm"), None)
        if account:
            try:
                LastFm(account["path"], api_key, stop=self._cancel["sync"].is_set).check()
            except SourceError as e:
                raise UserError(str(e)) from e
        self.settings.update({"lastfm_api_key": api_key})
        return {"ok": True, "lastfm_key": self._key_info()}

    def _key_info(self) -> dict:
        if lastfm.bundled_key():
            return {"source": "bundled"}
        key = self.settings["lastfm_api_key"]
        return {"source": "yours", "ends": key[-4:]} if key else {"source": None}

    def library(self) -> dict:
        return {
            "sources": [self._source_json(s["id"]) for s in self.store.sources()],
            "readings": self.store.readings(),
        }

    def remove_library(self, source_id: int) -> dict:
        self.store.remove_source(int(source_id))
        if not self.store.sources():
            self.settings.update({"setup_done": False})
        return self.library()

    def _source_json(self, source_id: int) -> dict:
        source = next((s for s in self.store.sources() if s["id"] == source_id), None) or {}
        out = {k: source.get(k) for k in ("id", "kind", "mode", "path", "location", "reading_count", "last_reading",
                                          "play_count", "first_play", "last_play")}
        out["name"] = source_name(source) if source else None
        out["counter"] = source.get("mode") in COUNTER_MODES
        options = source.get("options") or {}
        sync = options.get("sync") or {}
        out["complete"] = sync.get("complete", True) if source.get("mode") == "account" else True
        out["synced_back_to"] = sync.get("oldest")
        out["last_sync"] = options.get("last_sync")
        out["history"] = options.get("history") or []
        return out

    def _migrate_snapshot_folder(self) -> None:
        """TunesBack 1.x pointed at a folder of exports; adopt it as a library."""
        folder = self.settings["last_folder"]
        if self.settings["setup_done"] or self.store.sources() or not folder or not os.path.isdir(folder):
            return
        if itunes_xml.scan_folder(folder):
            source = self.store.add_source("itunes", "folder", folder, "local")
            self.store.refresh(source["id"])
            self.settings.update({"setup_done": True})

    # --- analysis ---

    def progress(self, channel: str = "analysis") -> dict:
        with self._lock:
            return dict(self._progress.get(channel, {"running": False, "stage": ""}))

    def cancel(self, channel: str = "analysis") -> dict:
        if channel in self._cancel:
            self._cancel[channel].set()
        return {"ok": True}

    def _set_stage(self, channel: str, text: str, **extra) -> None:
        with self._lock:
            self._progress[channel] = {"running": True, "stage": text, **extra}

    def _stage(self, text: str) -> None:
        if self._cancel["analysis"].is_set():
            raise Cancelled
        self._set_stage("analysis", text)

    def analyze(self, end: Optional[int] = None, start: Optional[int] = None, sources: Optional[list] = None,
                period: Optional[dict] = None, combine: str = "same") -> dict:
        """Build a recap: between two readings (`start`, `end` reading ids), or for a date
        range (`period` {"start", "end"} as YYYY-MM-DD, start null for all time) over `sources`."""
        if not self._analysis_lock.acquire(blocking=False):
            raise UserError("An analysis is already running.")
        self._cancel["analysis"].clear()
        try:
            report = self._readings_report(end, start) if end is not None else self._range_report(sources, period, combine)
            self._stage("Done")
            with self._lock:
                self._report = report
                self._report_version += 1
            return {"report": report.to_dict()}
        except Cancelled:
            return {"cancelled": True}
        finally:
            with self._lock:
                self._progress["analysis"] = {"running": False, "stage": ""}
            self._analysis_lock.release()

    def _readings_report(self, end: int, start: Optional[int]) -> Report:
        readings = {r["id"]: r for r in self.store.readings()}
        end_info = readings.get(int(end))
        start_info = readings.get(int(start)) if start is not None else None
        if end_info is None or (start is not None and start_info is None):
            raise UserError("Pick a reading first.")
        if start_info and start_info["date"] > end_info["date"]:
            raise UserError("The start of the period is after its end.")
        if start_info and start_info["id"] == end_info["id"]:
            raise UserError("Pick two different readings to compare.")
        start_snapshot = None
        if start_info:
            self._stage("Loading the start of the period…")
            start_snapshot = self.store.load(start_info["id"])
        self._stage("Loading the end of the period…")
        end_snapshot = self.store.load(end_info["id"])
        self._stage("Crunching numbers…")
        report = build_report(end_snapshot, start_snapshot)
        source = self.store.source(end_info["source_id"])
        report.sources = [{"id": source["id"], "name": source_name(source), "kind": source["kind"],
                           "covers": {"start": start_info["date"] if start_info else None, "end": end_info["date"]}}]
        return report

    def _range_report(self, source_ids: Optional[list], period: Optional[dict], combine: str) -> Report:
        everything = self.store.sources()
        wanted = {int(i) for i in source_ids} if source_ids else {s["id"] for s in everything}
        chosen = [s for s in everything if s["id"] in wanted]
        if not chosen:
            raise UserError("Pick a source first.")
        period = period or {}
        try:
            start = datetime.strptime(period["start"], "%Y-%m-%d") if period.get("start") else None
            end = datetime.strptime(period["end"], "%Y-%m-%d") + timedelta(days=1) if period.get("end") else None
        except (TypeError, ValueError) as e:
            raise UserError("Those dates don't look right.") from e
        if start and end and start >= end:
            raise UserError("The start of the period is after its end.")
        report = build_recap(self.store, chosen, start, end, "separate" if combine == "separate" else "same", self._stage)
        if not report.total_plays and not report.total_skips:
            raise UserError("There are no plays in that period. Try a longer one, or another source.")
        return report

    def artwork(self, locations: list) -> dict:
        wanted = [loc for loc in locations[:200] if isinstance(loc, str)]
        return {"art": self._thumbs.get_many(wanted)}

    # --- wrapped cards ---

    SIZES = {"thumb": 0.24, "preview": 0.5, "full": 1.0}

    def _data_for_cards(self, rank_by: Optional[str] = None) -> tuple[CardData, tuple]:
        """The current recap, prepared for the cards (rebuilt when the recap or ranking changes)."""
        with self._lock:
            report, version = self._report, self._report_version
        if report is None:
            raise UserError("Generate a recap first.")
        key = (version, "time" if (rank_by or self.settings["rank_by"]) == "time" else "plays",
               bool(self.settings["age_cards"]))
        with self._card_lock:
            if self._card_data_key != key:
                data = build_data(report, key[1])
                # Listening age cards only once you've chosen to have them.
                self._card_data = data if key[2] else dataclasses.replace(data, listening_age=None)
                self._card_data_key = key
                self._card_cache.clear()
            return self._card_data, key

    def card_options(self) -> dict:
        return catalog()

    def cards(self, deck: Optional[dict] = None, rank_by: Optional[str] = None) -> dict:
        """The deck for the current recap. Passing `deck` saves it as the new design."""
        if deck is not None:
            self.settings.update({"cards": normalize(deck)})
        deck = normalize(self.settings["cards"])
        data, key = self._data_for_cards(rank_by)
        return {
            "deck": deck,
            "version": f"{key[0]}-{key[1]}",
            "period": data.period,
            "cover_swatch": resolve_theme("cover", data).swatch,
            "cards": [{"type": c.type, "name": CARD_TYPES[c.type].name, "layout": c.layout,
                       "layout_name": CARD_TYPES[c.type].layouts[c.layout].name, "theme": c.theme, "hidden": c.hidden}
                      for c in plan(data, deck)],
        }

    def card_image(self, card_type: str, layout: str, theme: str, fmt: str, size: str, seed: int = 0,
                   rank_by: Optional[str] = None, sample: Optional[str] = None) -> Optional[bytes]:
        """One card as a JPEG (for the gallery, the editor or a download). `sample` draws
        made-up data instead of the recap (the Dev space's card lab)."""
        if (card_type not in CARD_TYPES or layout not in CARD_TYPES[card_type].layouts
                or theme not in ("cover", *THEMES) or fmt not in FORMATS or size not in self.SIZES):
            return None
        if sample:
            data, key = sample_data(sample), ("sample", sample)
        else:
            data, key = self._data_for_cards(rank_by)
        if not CARD_TYPES[card_type].applies(data):
            return None
        cache_key = (key, card_type, layout, theme, fmt, size, seed)
        with self._card_lock:
            if cache_key in self._card_cache:
                self._card_cache.move_to_end(cache_key)
                return self._card_cache[cache_key]
        started = time.perf_counter()
        image = draw(CardChoice(card_type, layout, theme), data, fmt, self.SIZES[size], seed)
        self._render_times.append({"card": f"{card_type} · {layout} · {theme}", "format": fmt, "size": size,
                                   "ms": round((time.perf_counter() - started) * 1000)})
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=95 if size == "full" else 86, subsampling=0 if size == "full" else 2)
        jpeg = buf.getvalue()
        with self._card_lock:
            self._card_cache[cache_key] = jpeg
            while len(self._card_cache) > 80:
                self._card_cache.popitem(last=False)
        return jpeg

    def card_filename(self, card_type: str) -> str:
        data, _key = self._data_for_cards()
        name = CARD_TYPES[card_type].name if card_type in CARD_TYPES else "Card"
        safe = re.sub(r"[^\w\- ]+", "", f"TunesBack {data.period} {name}").strip()
        return re.sub(r"\s+", " ", safe) + ".jpg"

    def save_cards(self, types: Optional[list] = None, folder: Optional[str] = None,
                   rank_by: Optional[str] = None) -> dict:
        """Save cards at full size: the given card types, or every card that isn't hidden."""
        deck = normalize(self.settings["cards"])
        data, _key = self._data_for_cards(rank_by)
        chosen = [c for c in plan(data, deck) if (c.type in types if types is not None else not c.hidden)]
        if not chosen:
            raise UserError("Choose at least one card to save.")
        if folder is None:
            if self.window is None:
                raise UserError("Choose where to save the cards.")
            folder = self.window.pick_folder()
            if not folder:
                return {"saved": 0, "cancelled": True}
        os.makedirs(folder, exist_ok=True)
        for choice in chosen:
            jpeg = self.card_image(choice.type, choice.layout, choice.theme, deck["format"], "full", deck["seed"], rank_by)
            with open(os.path.join(folder, self.card_filename(choice.type)), "wb") as f:
                f.write(jpeg)
        return {"saved": len(chosen), "folder": folder}

    # --- the Dev space ---

    def dev_info(self) -> dict:
        db = self._store_path
        return {
            "versions": devtools.versions(self.window.info().get("backend") if self.window else None),
            "paths": {"Settings": str(config_dir()), "Library database": str(db), "Logs": str(log_dir()),
                      "Thumbnails": str(self._thumb_dir), "Covers": str(artwork.REMOTE_CACHE)},
            "database": {**self.store.stats(), "size": db.stat().st_size if db.exists() else 0},
            "caches": {"thumbnails": devtools.folder_size(self._thumb_dir),
                       "covers": devtools.folder_size(artwork.REMOTE_CACHE) if artwork.REMOTE_CACHE else 0,
                       "cards in memory": len(self._card_cache)},
            "fonts": devtools.font_report(),
            "flags": [{"id": k, "label": v, "on": bool(self.settings["flags"].get(k))} for k, v in FLAGS.items()],
        }

    def dev_log(self) -> dict:
        return {"calls": list(self._calls)[::-1], "renders": list(self._render_times)[::-1]}

    def dry_run_sync(self, source_id: Optional[int] = None, kind: Optional[str] = None, username: Optional[str] = None,
                     api_key: Optional[str] = None, batches: int = 3, fresh: bool = False) -> dict:
        """Fetch from an account as a sync would, without storing anything; reports what it saw."""
        if source_id is not None:
            source = self.store.source(int(source_id))
            if source is None or source["mode"] != "account":
                raise UserError("Pick an online account.")
        else:
            if kind not in ("lastfm", "listenbrainz") or not (username or "").strip():
                raise UserError("Pick a service and enter a user name.")
            source = {"id": None, "kind": kind, "path": username.strip()}
        if not self._sync_lock.acquire(blocking=False):
            raise UserError("A sync is running. Try again when it's done.")
        self._cancel["sync"].clear()
        service = None
        try:
            service = self._service(source, (api_key or "").strip() or None)
            fresh = bool(fresh) or source["id"] is None  # an account that isn't connected starts from nothing
            run = devtools.DryRun(self.store, source["id"], fresh, max(1, min(int(batches), 50)))
            outcome = "finished"
            try:
                sync_history(run, source["id"] or 0, service.newer, service.older,
                             progress=lambda text: self._set_stage("sync", f"Dry run: {text}"),
                             stop=self._cancel["sync"].is_set)
            except devtools.LimitReached:
                outcome = "stopped after the batch limit"
            except Stopped:
                outcome = "cancelled"
            except SourceError as e:
                outcome = f"failed: {e}"
            return run.report(outcome, service.client.stats)
        finally:
            with self._lock:
                self._progress["sync"] = {"running": False, "stage": ""}
            self._sync_lock.release()

    def reset_sync(self, source_id: int) -> dict:
        """Forget how far a sync got; the next one fetches everything again (nothing is duplicated)."""
        self.store.set_options(int(source_id), sync={})
        return self.library()

    def forget_plays(self, source_id: int) -> dict:
        deleted = self.store.forget_plays(int(source_id))
        return {"deleted": deleted, **self.library()}

    def clear_caches(self) -> dict:
        freed = devtools.empty_folder(self._thumb_dir)
        if artwork.REMOTE_CACHE:
            freed += devtools.empty_folder(artwork.REMOTE_CACHE)
        self._thumbs.clear()
        with self._card_lock:
            self._card_cache.clear()
        return {"freed": freed}

    def window_set_controls_visible(self, visible: bool) -> dict:
        if self.window is not None:
            self.window.set_controls_visible(bool(visible))
        return {"ok": True}
