import sys

from tunesback.app import api as api_module
from tunesback.app.api import Api
from tunesback.app.menu import SEPARATOR, menu_for, menu_json
from tunesback.app.settings import Settings


def test_menu_has_no_stray_separators_and_hides_quit_on_macos():
    for platform in ("windows", "linux", "macos"):
        for _, entries in menu_for(platform):
            assert entries and entries[0] is not SEPARATOR and entries[-1] is not SEPARATOR
            assert all(not (a is SEPARATOR and b is SEPARATOR) for a, b in zip(entries, entries[1:]))
    commands = lambda p: {i["command"] for m in menu_json(p) for i in m["items"] if i}
    assert "quit" in commands("windows") and "quit" not in commands("macos")


def test_menu_shortcuts_are_unique():
    shortcuts = [i["shortcut"] for m in menu_json("linux") for i in m["items"] if i and i["shortcut"]]
    assert len(shortcuts) == len(set(shortcuts))


def test_title_bar_setting(tmp_path):
    settings = Settings(tmp_path / "s.json")
    assert settings["title_bar"] == "custom"
    assert settings.update({"title_bar": "native"})["title_bar"] == "native"
    assert settings.update({"title_bar": "fancy"})["title_bar"] == "native"


def test_window_actions_without_a_window(tmp_path):
    api = Api(Settings(tmp_path / "s.json"), thumbnail_dir=tmp_path / "t", store_path=tmp_path / "l.sqlite")
    assert api.call("window_info", {}) == {"window": None}
    assert "error" in api.call("window_minimize", {})
    assert "error" in api.call("restart", {})
    assert api.call("state", {})["desktop"] is False


def test_relaunch_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["tunesback", "--debug"])
    assert api_module.relaunch_command() == [sys.executable, "-m", "tunesback", "--debug"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert api_module.relaunch_command() == [sys.executable, "--debug"]


def test_pre_2_snapshot_folder_is_adopted(tmp_path, library):
    from datetime import datetime
    from .conftest import track
    folder = library("2024.xml", [track(1, "A", plays=2)], datetime(2024, 1, 1)).parent
    settings = Settings(tmp_path / "s.json")
    settings.update({"last_folder": str(folder)})
    api = Api(settings, thumbnail_dir=tmp_path / "t", store_path=tmp_path / "l.sqlite")
    assert settings["setup_done"] is True
    assert len(api.call("library", {})["readings"]) == 1
