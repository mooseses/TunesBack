"""Everything the interface can ask the Python side to do.

Each public method takes JSON-compatible arguments and returns a JSON-compatible
dict. Expected failures are returned as {"error": message}.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import sys
import threading
import webbrowser
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .. import __version__
from ..art.artwork import ThumbnailCache
from ..cards import CardChoice, CardData, build_data, catalog, draw, normalize, plan, resolve_theme
from ..cards.layouts.base import FORMATS
from ..cards.registry import CARD_TYPES
from ..cards.themes import THEMES
from ..library import LibraryStore
from ..sources import itunes_xml
from ..sources.catalog import CATALOG
from ..stats.report import Report, build_report
from .settings import Settings, cache_dir, configure_logging, data_dir, log_dir

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
        self._progress = {"running": False, "stage": ""}
        self._cancel = threading.Event()
        self._thumbs = ThumbnailCache(cache_dir=thumbnail_dir or cache_dir() / "thumbnails")
        self.store = LibraryStore(store_path or data_dir() / "library.sqlite")
        self._migrate_snapshot_folder()

    # --- dispatch ---

    ACTIONS = frozenset({
        "state", "update_settings", "open_logs", "open_website", "pick_folder", "pick_file", "progress", "cancel",
        "catalog", "discover", "add_library", "import_exports", "refresh_readings", "library", "remove_library",
        "analyze", "artwork", "card_options", "cards", "save_cards", "restart",
        "window_info", "window_minimize", "window_toggle_maximize", "window_close",
        "window_start_move", "window_start_resize",
    })

    def call(self, method: str, args: dict[str, Any]) -> dict:
        if method not in self.ACTIONS:
            return {"error": f"Unknown action: {method}"}
        handler = getattr(self, method)
        try:
            return handler(**args)
        except UserError as e:
            return {"error": str(e)}
        except TypeError as e:
            log.exception("Bad arguments for %s", method)
            return {"error": f"Bad request: {e}"}
        except Exception as e:  # keep the interface alive and leave a trace in the log
            log.exception("%s failed", method)
            return {"error": f"Something went wrong: {e}"}

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
        return {"settings": values}

    def open_website(self) -> dict:
        webbrowser.open(WEBSITE)
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

    def pick_file(self) -> dict:
        if self.window is None:
            return {"path": None, "unsupported": True}
        return {"path": self.window.pick_file(("Library exports (*.xml)",))}

    # --- set-up and library readings ---

    def catalog(self) -> dict:
        return {"sources": CATALOG}

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
            sources = self.store.sources()
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
        return {k: source.get(k) for k in ("id", "kind", "mode", "path", "location", "reading_count", "last_reading")}

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

    def progress(self) -> dict:
        with self._lock:
            return dict(self._progress)

    def cancel(self) -> dict:
        self._cancel.set()
        return {"ok": True}

    def _stage(self, text: str) -> None:
        if self._cancel.is_set():
            raise Cancelled
        with self._lock:
            self._progress = {"running": True, "stage": text}

    def analyze(self, end: int, start: Optional[int] = None) -> dict:
        if not self._analysis_lock.acquire(blocking=False):
            raise UserError("An analysis is already running.")
        self._cancel.clear()
        try:
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
            self._stage("Done")
            with self._lock:
                self._report = report
                self._report_version += 1
            return {"report": report.to_dict()}
        except Cancelled:
            return {"cancelled": True}
        finally:
            with self._lock:
                self._progress = {"running": False, "stage": ""}
            self._analysis_lock.release()

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
        key = (version, "time" if (rank_by or self.settings["rank_by"]) == "time" else "plays")
        with self._card_lock:
            if self._card_data_key != key:
                self._card_data = build_data(report, key[1])
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
                   rank_by: Optional[str] = None) -> Optional[bytes]:
        """One card as a JPEG (for the gallery, the editor or a download)."""
        if (card_type not in CARD_TYPES or layout not in CARD_TYPES[card_type].layouts
                or theme not in ("cover", *THEMES) or fmt not in FORMATS or size not in self.SIZES):
            return None
        data, key = self._data_for_cards(rank_by)
        cache_key = (key, card_type, layout, theme, fmt, size, seed)
        with self._card_lock:
            if cache_key in self._card_cache:
                self._card_cache.move_to_end(cache_key)
                return self._card_cache[cache_key]
        image = draw(CardChoice(card_type, layout, theme), data, fmt, self.SIZES[size], seed)
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
