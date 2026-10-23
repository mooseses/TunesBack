"""Per-user settings and file locations."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import sys
import threading
from pathlib import Path

from .. import APP_NAME

log = logging.getLogger(__name__)

DEFAULTS = {
    "theme": "system",  # system | light | dark
    "title_bar": "custom",  # custom | native (applies after a restart)
    "unit": "hours",  # hours | minutes | days
    "rank_by": "plays",  # plays | time
    "show_art": True,
    "debug_logging": False,
    "last_folder": None,  # pre-2.0 snapshot folder, imported into the library on first start
    "setup_done": False,
    "sources_wanted": [],  # players picked during set-up that aren't supported yet
    "cards": {},  # the Wrapped deck's design: format, theme, shuffle seed and per-card choices
}

_CHOICES = {
    "theme": {"system", "light", "dark"},
    "title_bar": {"custom", "native"},
    "unit": {"hours", "minutes", "days"},
    "rank_by": {"plays", "time"},
}


def config_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def log_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME / "Logs"
    if system == "Darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_NAME / "logs"


def data_dir() -> Path:
    """Where TunesBack keeps its library readings."""
    system = platform.system()
    if system in ("Windows", "Darwin"):
        return config_dir()
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


def cache_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME / "Cache"
    if system == "Darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_NAME


def configure_logging(debug: bool) -> None:
    """Warnings always go to the log file; debug mode adds everything else."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.DEBUG if debug else logging.WARNING)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            directory / "tunesback.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        log.warning("File logging unavailable: %s", e)


class Settings:
    def __init__(self, path: Path | None = None):
        self._path = path or config_dir() / "settings.json"
        self._lock = threading.Lock()
        self._values = dict(DEFAULTS)
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
            self._values.update(self._validated(stored))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("Ignoring unreadable settings file %s: %s", self._path, e)

    @staticmethod
    def _validated(changes: dict) -> dict:
        clean = {}
        for key, value in changes.items():
            if key not in DEFAULTS:
                continue
            if key in _CHOICES and value not in _CHOICES[key]:
                continue
            if key == "sources_wanted":
                if not isinstance(value, list):
                    continue
                value = [str(v) for v in value][:20]
            if key in ("show_art", "debug_logging", "setup_done"):
                value = bool(value)
            if key == "last_folder" and value is not None and not isinstance(value, str):
                continue
            if key == "cards" and not isinstance(value, dict):
                continue
            clean[key] = value
        return clean

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._values)

    def __getitem__(self, key: str):
        with self._lock:
            return self._values[key]

    def update(self, changes: dict) -> dict:
        with self._lock:
            self._values.update(self._validated(changes))
            values = dict(self._values)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(values, indent=2), encoding="utf-8")
        except OSError as e:
            log.warning("Could not save settings: %s", e)
        return values
