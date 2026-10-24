"""The Services page's sync records, and the Dev space: flags, dry runs and housekeeping."""
import pytest

from tunesback.app.api import Api
from tunesback.app.settings import Settings
from tunesback.cards import canvas
from tunesback.cards.registry import CARD_TYPES
from tunesback.sources import http, lastfm
from tunesback.sources.plays import Stopped

from .test_sources import fake_lastfm

TIMES = [1_700_000_000 + i * 600 for i in range(450)]


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    def wait(self, seconds):
        if self.stop():
            raise Stopped
    monkeypatch.setattr(http.Client, "_wait", wait)
    # Flags are module-wide; give each test its own copy.
    monkeypatch.setattr(http, "SIMULATE", dict.fromkeys(http.SIMULATE, False))
    monkeypatch.setattr(canvas, "GUIDES", False)


@pytest.fixture
def api(tmp_path):
    a = Api(Settings(tmp_path / "settings.json"), thumbnail_dir=tmp_path / "thumbs", store_path=tmp_path / "lib.sqlite")
    yield a
    a.store.close()


@pytest.fixture
def service(monkeypatch):
    s = fake_lastfm(TIMES)
    monkeypatch.setattr(lastfm, "API", s.url)
    monkeypatch.delenv("TUNESBACK_LASTFM_API_KEY", raising=False)
    yield s
    s.close()


def test_settings_validate_sidebar_and_flags(tmp_path):
    settings = Settings(tmp_path / "settings.json")
    settings.update({"sidebar_width": 9000, "sidebar_hidden": 1, "dev_mode": "yes",
                     "flags": {"offline": 1, "made_up": True, "card_guides": False}})
    assert settings["sidebar_width"] == 360 and settings["sidebar_hidden"] is True and settings["dev_mode"] is True
    assert settings["flags"] == {"offline": True, "card_guides": False}
    settings.update({"sidebar_width": 10, "flags": "nonsense"})
    assert settings["sidebar_width"] == 180 and settings["flags"] == {"offline": True, "card_guides": False}


def test_sync_history_is_recorded(api, service):
    added = api.call("add_account", {"kind": "lastfm", "username": "rj", "api_key": "KEY"})
    source = added["source"]
    assert source["last_sync"]["new"] == 450 and source["last_sync"]["error"] is None and len(source["history"]) == 1
    assert source["synced_back_to"] == TIMES[0]
    api.call("sync_sources", {"source_id": source["id"]})
    [source] = api.call("library", {})["sources"]
    assert [h["new"] for h in source["history"]] == [0, 450]


def test_dry_run_stores_nothing(api, service):
    source = api.call("add_account", {"kind": "lastfm", "username": "rj", "api_key": "KEY"})["source"]
    rows = api.store.stats()["rows"]

    nothing_new = api.call("dry_run_sync", {"source_id": source["id"]})
    assert nothing_new["outcome"] == "finished" and nothing_new["new"] == 0 and nothing_new["requests"] >= 1

    fresh = api.call("dry_run_sync", {"source_id": source["id"], "fresh": True, "batches": 1})
    assert fresh["outcome"] == "stopped after the batch limit" and len(fresh["batches"]) == 1
    assert fresh["plays"] == 200 and fresh["new"] == 0 and fresh["already_stored"] == 200
    assert fresh["samples"][0]["name"].startswith("Song") and len(fresh["samples"]) == 8

    other = api.call("dry_run_sync", {"kind": "lastfm", "username": "someone", "api_key": "KEY", "batches": 2})
    assert other["mode"] == "from scratch" and other["plays"] == 400 and other["new"] == 400

    assert api.store.stats()["rows"] == rows
    assert api.store.source(source["id"])["options"]["sync"]["complete"] is True
    assert "user name" in api.call("dry_run_sync", {"kind": "lastfm"})["error"]


def test_reset_and_forget(api, service):
    source = api.call("add_account", {"kind": "lastfm", "username": "rj", "api_key": "KEY"})["source"]
    api.call("reset_sync", {"source_id": source["id"]})
    assert api.call("sync_sources", {})["new"] == 0  # fetched everything again, stored nothing twice
    forgotten = api.call("forget_plays", {"source_id": source["id"]})
    assert forgotten["deleted"] == 450 and forgotten["sources"][0]["play_count"] == 0
    assert api.call("sync_sources", {})["new"] == 450


def test_offline_flag(api, service):
    api.call("add_account", {"kind": "lastfm", "username": "rj", "api_key": "KEY"})
    api.call("update_settings", {"changes": {"flags": {"offline": True}}})
    assert http.SIMULATE["offline"] is True
    problems = api.call("sync_sources", {})["problems"]
    assert problems and "Couldn't reach Last.fm" in problems[0]["error"]
    [source] = api.call("library", {})["sources"]
    assert source["last_sync"]["error"] == problems[0]["error"]
    api.call("update_settings", {"changes": {"flags": {}}})
    assert api.call("sync_sources", {})["problems"] == []


def test_card_lab_guides_and_caches(api, tmp_path):
    layout = next(iter(CARD_TYPES["top_songs"].layouts))
    plain = api.card_image("top_songs", layout, "midnight", "story", "thumb", seed=1, sample="plain")
    assert plain[:2] == b"\xff\xd8"  # a JPEG, without any recap
    api.call("update_settings", {"changes": {"flags": {"card_guides": True}}})
    assert canvas.GUIDES is True
    assert api.card_image("top_songs", layout, "midnight", "story", "thumb", seed=1, sample="plain") != plain

    (tmp_path / "thumbs" / "a.jpg").write_bytes(b"x" * 5000)
    info = api.call("dev_info", {})
    assert info["caches"]["thumbnails"] == 5000 and info["database"]["rows"]["plays"] == 0
    assert {f["id"] for f in info["flags"]} >= {"offline", "card_guides"}
    assert api.call("clear_caches", {})["freed"] >= 5000
    assert not (tmp_path / "thumbs" / "a.jpg").exists()
    log = api.call("dev_log", {})
    assert log["calls"][0]["action"] == "clear_caches" and log["renders"]


def test_stopped_sync_records_what_it_kept(api, service, monkeypatch):
    source = api.call("add_account", {"kind": "lastfm", "username": "rj", "api_key": "KEY"})["source"]
    api.call("forget_plays", {"source_id": source["id"]})
    real = api.store.add_plays

    def add_then_stop(source_id, plays):
        added = real(source_id, plays)
        api._cancel["sync"].set()  # Stop pressed while the first batch was being saved
        return added
    monkeypatch.setattr(api.store, "add_plays", add_then_stop)
    result = api.call("sync_sources", {})
    assert result["stopped"] and result["new"] == 200
    [source] = api.call("library", {})["sources"]
    assert source["last_sync"] == {**source["last_sync"], "new": 200, "stopped": True}


def test_request_log_hides_keys():
    assert http._SECRET_PARAMS.sub(r"\1=…", "https://x/?method=a&api_key=SECRET&task=keep&sk=S") \
        == "https://x/?method=a&api_key=…&task=keep&sk=…"


def test_overview_layout_and_window_settings(tmp_path):
    settings = Settings(tmp_path / "settings.json")
    settings.update({"overview_tiles": [{"id": "plays", "size": "M"}, {"id": "plays", "size": "L"}, {"id": "x" * 50, "size": "M"},
                                        {"id": "genres", "size": "S"}, "junk", {"id": "top-songs", "size": "XL"}],
                     "native_sidebar": 0, "mica": "yes"})
    assert settings["overview_tiles"] == [{"id": "plays", "size": "M"}, {"id": "top-songs", "size": "XL"}]
    assert settings["native_sidebar"] is False and settings["mica"] is True
    settings.update({"overview_tiles": None})
    assert settings["overview_tiles"] is None
    settings.update({"overview_tiles": "nope"})
    assert settings["overview_tiles"] is None


def test_reset_all(api, service):
    api.call("add_account", {"kind": "lastfm", "username": "rj", "api_key": "KEY"})
    api.call("update_settings", {"changes": {"theme": "dark", "dev_mode": True, "flags": {"offline": True}, "title_bar_menu": False}})
    assert api.call("reset_all", {}) == {"ok": True}
    settings = api.call("state", {})["settings"]
    assert settings["setup_done"] is False and settings["theme"] == "system" and settings["dev_mode"] is False
    assert settings["flags"] == {} and settings["title_bar_menu"] is True and http.SIMULATE["offline"] is False
    assert len(api.call("library", {})["sources"]) == 1  # the library stays unless asked
    api.call("reset_all", {"forget_library": True})
    assert api.call("library", {})["sources"] == []


def test_window_size_and_first_launch_layout(tmp_path):
    settings = Settings(tmp_path / "settings.json")
    assert settings["window_size"] is None and settings["sidebar_width"] == 180
    settings.update({"window_size": [1400.6, 900]})
    assert settings["window_size"] == [1400, 900]
    settings.update({"window_size": [100, 100]})
    assert settings["window_size"] == [980, 660]
    settings.update({"window_size": "big"})
    assert settings["window_size"] == [980, 660]
    settings.reset()
    assert settings["window_size"] is None
