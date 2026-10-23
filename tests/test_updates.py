"""Version numbers, and checking GitHub releases for a newer TunesBack."""
import pytest

from tunesback import updates
from tunesback.app.api import Api
from tunesback.app.settings import Settings
from tunesback.sources.plays import SourceError
from tunesback.version import parse, spellings


def test_tags_in_every_style_sort_properly():
    tags = ["1.0.0", "1.2.0-b1", "1.2.0-RC", "1.2.0", "2.0.0.dev0", "v2.0.0-beta.1", "2.0.0b2", "2.0.0rc1", "v2.0.0", "2.0.1"]
    assert sorted(tags[::-1], key=lambda t: parse(t).key()) == tags
    assert parse("not a version") is None
    assert parse("v2.0.0-beta.1") == parse("2.0.0b1") and parse("2.0.0b1").prerelease and not parse("2.0").prerelease


def test_spellings():
    s = spellings("2.0.0b1")
    assert (s["display"], s["tag"], s["deb"], s["pacman"], s["prerelease"]) == ("2.0.0 Beta 1", "v2.0.0-beta.1", "2.0.0~beta1", "2.0.0beta1", "true")
    s = spellings("2.1.0")
    assert (s["display"], s["tag"], s["deb"], s["windows"], s["prerelease"]) == ("2.1.0", "v2.1.0", "2.1.0", "2.1.0.999", "false")


class FakeClient:
    def __init__(self, releases, status=200):
        self.releases, self.status = releases, status

    def get(self, path, params=None):
        assert path == "/repos/mooseses/TunesBack/releases"
        return self.status, self.releases


def release(tag, prerelease=False, draft=False, assets=()):
    return {"tag_name": tag, "name": tag, "prerelease": prerelease, "draft": draft, "body": f"Notes for {tag}",
            "html_url": f"https://github.com/mooseses/TunesBack/releases/tag/{tag}", "published_at": "2026-11-01T10:00:00Z",
            "assets": [{"name": n, "browser_download_url": f"https://github.com/mooseses/TunesBack/releases/download/{tag}/{n}"} for n in assets]}


RELEASES = [release("v2.1.0-beta.1", prerelease=True), release("v3.0.0", draft=True),
            release("v2.0.0", assets=["TunesBack-macOS-v2.0.0-arm64.dmg", "TunesBack-Windows-v2.0.0-x64.exe"]),
            release("v2.0.0-beta.2", prerelease=True), release("1.2.0")]


def test_betas_see_betas_and_releases_see_releases(monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "x64.exe")
    beta = updates.check("2.0.0b1", client=FakeClient(RELEASES))
    assert beta["available"] and beta["version"] == "2.1.0 Beta 1" and beta["prerelease"] and beta["download"] is None
    final = updates.check("2.0.0b2", betas=False, client=FakeClient(RELEASES))
    assert final["version"] == "2.0.0" and final["download"].endswith("TunesBack-Windows-v2.0.0-x64.exe")
    assert final["notes"] == "Notes for v2.0.0" and final["url"].endswith("/tag/v2.0.0")
    assert updates.check("2.0.0", client=FakeClient(RELEASES)) == {"current": "2.0.0", "available": False}
    with pytest.raises(SourceError):
        updates.check("2.0.0", client=FakeClient({"message": "rate limited"}, status=403))


def test_automatic_checks(tmp_path, monkeypatch):
    api = Api(Settings(tmp_path / "settings.json"), thumbnail_dir=tmp_path / "t", store_path=tmp_path / "lib.sqlite")
    calls = []

    def fake_check():
        calls.append(1)
        return {"current": "2.0.0 Beta 1", "available": True, "version": "2.0.0", "tag": "v2.0.0"}
    monkeypatch.setattr(updates, "check", fake_check)
    assert api.call("check_updates", {"automatic": True})["available"] is True
    assert api.call("check_updates", {"automatic": True}) == {"checked": False}  # once a day
    assert api.call("check_updates", {})["available"] is True and len(calls) == 2  # asking always checks
    api.call("update_settings", {"changes": {"update_last": 0, "update_skipped": "v2.0.0"}})
    assert api.call("check_updates", {"automatic": True})["available"] is False  # skipped
    api.call("update_settings", {"changes": {"update_last": 0, "update_check": False}})
    assert api.call("check_updates", {"automatic": True}) == {"checked": False} and len(calls) == 3

    def offline():
        raise SourceError("Couldn't reach GitHub.")
    monkeypatch.setattr(updates, "check", offline)
    assert api.call("check_updates", {}) == {"error": "Couldn't reach GitHub."}
    api.store.close()
