"""The application menu, defined once for the native menu bar and the in-app one.

Each item names a command that the interface knows how to run. Shortcuts use
"Mod" for Ctrl on Windows/Linux and Cmd on macOS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class Item:
    command: str
    label: str
    shortcut: Optional[str] = None
    group: Optional[str] = None  # radio group whose value this item selects, e.g. "unit"
    exclude: tuple[str, ...] = ()  # platforms where the item is left out


SEPARATOR = None
Entry = Union[Item, None]

MENU: list[tuple[str, list[Entry]]] = [
    ("File", [
        Item("add_library", "Add Source…", "Mod+O"),
        Item("import_exports", "Import Older iTunes Exports…"),
        Item("refresh", "Check for New Listens", "Mod+R"),
        SEPARATOR,
        Item("generate", "Generate Recap", "Mod+Enter"),
        SEPARATOR,
        Item("save_cards", "Save Wrapped Cards…", "Mod+S"),
        SEPARATOR,
        Item("settings", "Settings…", "Mod+,"),
        SEPARATOR,
        Item("quit", "Quit", "Mod+Q", exclude=("macos",)),  # macOS has Quit in the app menu
    ]),
    ("View", [
        Item("view:setup", "Library", "Mod+1"),
        Item("view:overview", "Overview", "Mod+2"),
        Item("view:charts", "Top Charts", "Mod+3"),
        Item("view:wrapped", "Wrapped", "Mod+4"),
        SEPARATOR,
        Item("rank:plays", "Rank by Plays", group="rank_by"),
        Item("rank:time", "Rank by Time", group="rank_by"),
        SEPARATOR,
        Item("unit:hours", "Show Hours", group="unit"),
        Item("unit:minutes", "Show Minutes", group="unit"),
        Item("unit:days", "Show Days", group="unit"),
        SEPARATOR,
        Item("theme:system", "System Appearance", group="theme"),
        Item("theme:light", "Light Appearance", group="theme"),
        Item("theme:dark", "Dark Appearance", group="theme"),
    ]),
    ("Help", [
        Item("open_logs", "Open Log Folder"),
        Item("website", "TunesBack on GitHub"),
        SEPARATOR,
        Item("about", "About TunesBack"),
    ]),
]


def menu_for(platform: str) -> list[tuple[str, list[Entry]]]:
    """The menu with platform-specific items removed and no doubled separators."""
    result = []
    for title, entries in MENU:
        kept: list[Entry] = []
        for entry in entries:
            if entry is SEPARATOR:
                if kept and kept[-1] is not SEPARATOR:
                    kept.append(SEPARATOR)
            elif platform not in entry.exclude:
                kept.append(entry)
        while kept and kept[-1] is SEPARATOR:
            kept.pop()
        result.append((title, kept))
    return result


def menu_json(platform: str) -> list[dict]:
    return [
        {"title": title, "items": [None if e is SEPARATOR else
                                   {"command": e.command, "label": e.label, "shortcut": e.shortcut, "group": e.group}
                                   for e in entries]}
        for title, entries in menu_for(platform)
    ]
