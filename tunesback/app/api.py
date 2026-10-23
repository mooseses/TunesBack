"""Everything the interface can ask the Python side to do.

Each public method takes JSON-compatible arguments and returns a JSON-compatible
dict. Expected failures are returned as {"error": message}.
"""
from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import threading
from io import BytesIO
from typing import Any, Callable, Optional

from PIL import Image

from .. import __version__
from ..art.artwork import ThumbnailCache
from ..cards import render_cards, save_card_stack
from ..model import Snapshot
from ..sources import itunes_xml
from ..stats.report import Report, build_report
from .settings import Settings, configure_logging, log_dir

log = logging.getLogger(__name__)


class UserError(Exception):
    """A problem to show to the user as-is."""


class Cancelled(Exception):
    pass


class Api:
    def __init__(self, settings: Settings, pick_folder: Optional[Callable[[], Optional[str]]] = None):
        self.settings = settings
        self._pick_folder = pick_folder  # None when running in a plain browser
        self._lock = threading.Lock()
        self._analysis_lock = threading.Lock()
        self._snapshots: dict[str, itunes_xml.SnapshotInfo] = {}
        self._parsed: dict[tuple[str, float], Snapshot] = {}
        self._report: Optional[Report] = None
        self._cards: list[Image.Image] = []
        self._progress = {"running": False, "stage": ""}
        self._cancel = threading.Event()
        self._thumbs = ThumbnailCache()

    # --- dispatch ---

    ACTIONS = frozenset({
        "state", "update_settings", "open_logs", "pick_folder", "scan", "progress", "cancel",
        "analyze", "artwork", "generate_cards", "save_cards",
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
            "desktop": self._pick_folder is not None,
            "settings": self.settings.as_dict(),
            "log_dir": str(log_dir()),
        }

    def update_settings(self, changes: dict) -> dict:
        before = self.settings["debug_logging"]
        values = self.settings.update(changes)
        if values["debug_logging"] != before:
            configure_logging(values["debug_logging"])
        return {"settings": values}

    def open_logs(self) -> dict:
        path = log_dir()
        path.mkdir(parents=True, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if system == "Darwin" else "xdg-open", str(path)])
        return {"path": str(path)}

    # --- snapshots ---

    def pick_folder(self) -> dict:
        if self._pick_folder is None:
            return {"path": None, "unsupported": True}
        return {"path": self._pick_folder()}

    def scan(self, folder: str) -> dict:
        folder = os.path.expanduser((folder or "").strip())
        if not os.path.isdir(folder):
            raise UserError("That folder doesn't exist.")
        found = itunes_xml.scan_folder(folder)
        with self._lock:
            self._snapshots = {str(i): s for i, s in enumerate(found)}
        self.settings.update({"last_folder": folder})
        return {
            "folder": folder,
            "snapshots": [
                {"id": str(i), "label": s.label, "date": s.date.isoformat(), "file": s.file,
                 "size": s.size, "date_source": s.date_source}
                for i, s in enumerate(found)
            ],
        }

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

    def _load(self, info: itunes_xml.SnapshotInfo) -> Snapshot:
        key = (info.path, os.path.getmtime(info.path))
        with self._lock:
            cached = self._parsed.get(key)
        if cached:
            return cached
        try:
            snapshot = itunes_xml.load_snapshot(info.path, info.date)
        except ValueError as e:
            raise UserError(str(e)) from e
        with self._lock:
            # Keep the two most recent parses: enough to tweak one end of a period cheaply.
            self._parsed = dict(list(self._parsed.items())[-1:])
            self._parsed[key] = snapshot
        return snapshot

    def analyze(self, end: str, start: Optional[str] = None) -> dict:
        if not self._analysis_lock.acquire(blocking=False):
            raise UserError("An analysis is already running.")
        self._cancel.clear()
        try:
            with self._lock:
                end_info = self._snapshots.get(end)
                start_info = self._snapshots.get(start) if start else None
            if end_info is None or (start and start_info is None):
                raise UserError("Pick a snapshot first.")
            if start_info and start_info.date > end_info.date:
                raise UserError("The start snapshot is newer than the end snapshot.")
            if start_info and start_info.path == end_info.path:
                raise UserError("Pick two different snapshots to compare.")

            start_snapshot = None
            if start_info:
                self._stage(f"Reading {start_info.label}…")
                start_snapshot = self._load(start_info)
            self._stage(f"Reading {end_info.label}…")
            end_snapshot = self._load(end_info)
            self._stage("Crunching numbers…")
            report = build_report(end_snapshot, start_snapshot)
            self._stage("Done")
            with self._lock:
                self._report = report
                self._cards = []
            result = report.to_dict()
            result["start_label"] = start_info.label if start_info else None
            result["end_label"] = end_info.label
            return {"report": result}
        except Cancelled:
            return {"cancelled": True}
        finally:
            with self._lock:
                self._progress = {"running": False, "stage": ""}
            self._analysis_lock.release()

    def artwork(self, locations: list) -> dict:
        return {"art": {loc: self._thumbs.get(loc) for loc in locations[:200] if isinstance(loc, str)}}

    # --- wrapped cards ---

    def generate_cards(self, rank_by: str = "plays") -> dict:
        with self._lock:
            report = self._report
        if report is None:
            raise UserError("Generate a recap first.")
        cards = render_cards(report, "time" if rank_by == "time" else "plays")
        with self._lock:
            self._cards = cards
        previews = []
        for i, card in enumerate(cards):
            preview = card.convert("RGB")
            preview.thumbnail((540, 960))
            buf = BytesIO()
            preview.save(buf, format="JPEG", quality=88)
            previews.append({"index": i, "name": card.info.get("card_name", f"Card {i + 1}").replace("_", " "),
                             "preview": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()})
        return {"cards": previews}

    def save_cards(self, indices: Optional[list] = None, folder: Optional[str] = None) -> dict:
        with self._lock:
            cards = list(self._cards)
        if not cards:
            raise UserError("Generate the cards first.")
        if folder is None:
            if self._pick_folder is None:
                raise UserError("Choose where to save the cards.")
            folder = self._pick_folder()
            if not folder:
                return {"saved": 0, "cancelled": True}
        chosen = None if indices is None else {int(i) for i in indices}
        saved = save_card_stack(cards, folder, chosen)
        return {"saved": saved, "folder": folder}

    def card_jpeg(self, index: int) -> Optional[bytes]:
        with self._lock:
            cards = list(self._cards)
        if not 0 <= index < len(cards):
            return None
        buf = BytesIO()
        cards[index].convert("RGB").save(buf, format="JPEG", quality=95)
        return buf.getvalue()

    def card_filename(self, index: int) -> str:
        with self._lock:
            name = self._cards[index].info.get("card_name", f"Card_{index + 1}") if index < len(self._cards) else "Card"
        return f"TunesBack_{name}.jpg"
