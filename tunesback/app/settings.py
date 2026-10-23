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
    "lastfm_api_key": None,  # entered during set-up when this build doesn't come with one
    "recap": {},  # the last recap chosen on the Library page: source, period preset, dates, combine
    "sidebar_width": 220,  # pixels
    "sidebar_hidden": False,
    "sync_on_launch": True,  # fetch new listens from online accounts when TunesBack opens
    "dev_mode": False,  # show the Dev space
    "flags": {},  # Dev space feature flags (see FLAGS)
    # Listening age is opt-in: worked out on its own page, then shown elsewhere only if you choose.
    "age_calculated": False,
    "age_overview": None,  # on the Overview: None until you choose, then True or False
    "age_cards": False,  # listening age cards in Wrapped
    "native_sidebar": True,  # macOS: an AppKit sidebar (Liquid Glass on macOS 26) instead of the page's
    "mica": True,  # Windows 11: Mica behind the window
    # The Overview's tiles, [{"id", "size"}] in order; None for the standard layout. (Builds before
    # the tile grid saved a row layout as "overview_layout"; unknown keys are dropped on load.)
    "overview_tiles": None,
    "title_bar_menu": True,
    "update_check": True,  # look for a new version on GitHub once a day
    "update_last": 0,  # when that last happened (Unix time)
    "update_skipped": "",  # a release tag you said not to be reminded about  # show the menu bar in TunesBack's title bar (Alt shows it when hidden)
}

# Feature flags for trying things out and tracking down problems, set in the Dev space.
FLAGS = {
    "card_guides": "Draw margins and text boxes on Wrapped cards",
    "offline": "Pretend there's no internet connection (online services fail at once)",
    "slow_network": "Wait 1.5 seconds before every request to an online service",
    "log_http": "Write every request to online services to the log (keys hidden)",
    "show_ids": "Show the internal numbers of sources and readings",
    "reduced_motion": "Turn animations off, as with the system's reduced motion setting",
}
SIDEBAR_WIDTH = (180, 360)

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
            if key in ("cards", "recap") and not isinstance(value, dict):
                continue
            if key == "lastfm_api_key" and value is not None and not isinstance(value, str):
                continue
            if key == "sidebar_width":
                if not isinstance(value, (int, float)):
                    continue
                value = int(min(max(value, SIDEBAR_WIDTH[0]), SIDEBAR_WIDTH[1]))
            if key in ("sidebar_hidden", "sync_on_launch", "dev_mode", "age_calculated", "age_cards",
                       "native_sidebar", "mica", "title_bar_menu", "update_check"):
                value = bool(value)
            if key == "update_last":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                value = max(0, int(value))
            if key == "update_skipped":
                value = str(value)[:60] if value else ""
            if key == "age_overview" and value is not None:
                value = bool(value)
            if key == "overview_tiles" and value is not None:
                if not isinstance(value, list):
                    continue
                seen, layout = set(), []
                for item in value[:60]:
                    if (isinstance(item, dict) and isinstance(item.get("id"), str) and len(item["id"]) <= 40
                            and item.get("size") in ("M", "L", "XL") and item["id"] not in seen):
                        seen.add(item["id"])
                        layout.append({"id": item["id"], "size": item["size"]})
                value = layout
            if key == "flags":
                if not isinstance(value, dict):
                    continue
                value = {name: bool(on) for name, on in value.items() if name in FLAGS}
            clean[key] = value
        return clean

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._values)

    def __getitem__(self, key: str):
        with self._lock:
            return self._values[key]

    def reset(self) -> dict:
        """Everything back to how a new installation starts."""
        with self._lock:
            self._values = dict(DEFAULTS)
        return self.update({})

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
