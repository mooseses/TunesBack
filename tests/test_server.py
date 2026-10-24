import http.client
import os
import json
import re
from datetime import datetime

import pytest

from tunesback.app.api import Api
from tunesback.app.server import AppServer
from tunesback.app.settings import Settings

from .conftest import track


@pytest.fixture
def server(tmp_path):
    srv = AppServer(Api(Settings(tmp_path / "settings.json"), thumbnail_dir=tmp_path / "thumbs",
                        store_path=tmp_path / "library.sqlite"))
    srv.start_background()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    return response.status, response.read()


def api(srv, action, **args):
    status, body = request(srv, "POST", f"/api/{action}", json.dumps(args), {"X-TunesBack-Token": srv.token})
    assert status == 200
    return json.loads(body)


def test_page_carries_token(server):
    status, body = request(server, "GET", "/")
    assert status == 200
    assert re.search(rb'name="tunesback-token" content="([^"]+)"', body).group(1).decode() == server.token


def test_api_requires_token(server):
    status, _ = request(server, "POST", "/api/state", "{}")
    assert status == 403
    status, _ = request(server, "POST", "/api/state", "{}", {"X-TunesBack-Token": "wrong"})
    assert status == 403


def test_foreign_host_is_rejected(server):
    status, _ = request(server, "GET", "/", headers={"Host": "attacker.example"})
    assert status == 403


def test_static_files_stay_inside_package(server):
    assert request(server, "GET", "/assets/fonts/Figtree-Bold.ttf")[0] == 200
    assert request(server, "GET", "/../../pyproject.toml")[0] == 404
    assert request(server, "GET", "/assets/../app/api.py")[0] == 404


def test_unknown_action(server):
    assert "error" in api(server, "card_jpeg", index=0)
    assert "Generate a recap first" in api(server, "cards")["error"]


def test_setup_reading_analysis_and_cards(server, library, tmp_path):
    path = library("Library.xml", [track(1, "A", plays=1, Genre="Rock", Year=2000)], datetime(2025, 1, 1))
    added = api(server, "add_library", path=str(path), location="local")
    assert added["tracks"] == 1 and added["source"]["mode"] == "file"
    assert api(server, "state")["settings"]["setup_done"] is True

    library("Library.xml", [track(1, "A", plays=6, Genre="Rock", Year=2000)], datetime(2025, 12, 31))
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))
    assert api(server, "refresh_readings")["new"] == 1

    first, second = api(server, "library")["readings"]
    report = api(server, "analyze", start=first["id"], end=second["id"])["report"]
    assert report["mode"] == "compare" and report["total_plays"] == 5
    assert api(server, "analyze", start=second["id"], end=first["id"])["error"]

    deck = api(server, "cards", rank_by="plays")
    first_card = deck["cards"][0]
    assert first_card["type"] == "top_songs" and deck["deck"]["format"] == "story"
    path = f"/api/card/{first_card['type']}/{first_card['layout']}/{first_card['theme']}/story/preview.jpg"
    status, body = request(server, "GET", f"{path}?s=0&r=plays&token={server.token}")
    assert status == 200 and body[:2] == b"\xff\xd8"
    assert request(server, "GET", f"{path}?token=nope")[0] == 403
    assert request(server, "GET", f"/api/card/top_songs/nope/midnight/story/preview.jpg?token={server.token}")[0] == 404

    # Listening age cards only once you've chosen to have them.
    assert report["listening_age"] and "listening_age" not in {c["type"] for c in deck["cards"]}
    age_card = "/api/card/listening_age/big/midnight/story/preview.jpg"
    assert request(server, "GET", f"{age_card}?s=0&r=plays&token={server.token}")[0] == 404
    api(server, "update_settings", changes={"age_calculated": True, "age_cards": True, "age_overview": "yes"})
    assert api(server, "state")["settings"]["age_overview"] is True
    assert "listening_age" in {c["type"] for c in api(server, "cards", rank_by="plays")["cards"]}
    assert request(server, "GET", f"{age_card}?s=0&r=plays&token={server.token}")[0] == 200
    api(server, "update_settings", changes={"age_cards": False})

    # Changing the design is saved with the settings.
    designed = api(server, "cards", deck={"format": "square", "theme": "paper", "seed": 3,
                                          "cards": {"top_songs": {"hidden": True}}})
    assert designed["deck"]["format"] == "square" and all(c["theme"] == "paper" for c in designed["cards"])
    assert api(server, "state")["settings"]["cards"]["theme"] == "paper"

    out = tmp_path / "out"
    saved = api(server, "save_cards", folder=str(out))
    assert saved["saved"] == len(designed["cards"]) - 1  # the hidden card is left out
    assert api(server, "save_cards", types=["top_songs"], folder=str(out))["saved"] == 1
    assert len(list(out.glob("*.jpg"))) == len(designed["cards"])


def test_add_library_rejects_other_files(server, tmp_path):
    other = tmp_path / "notes.xml"
    other.write_text("<notes/>")
    assert "isn't an iTunes" in api(server, "add_library", path=str(other))["error"]
    assert "Can't find" in api(server, "add_library", path=str(tmp_path / "missing.xml"))["error"]
    assert api(server, "library")["sources"] == []


def test_settings_are_validated_and_saved(server, tmp_path):
    result = api(server, "update_settings", changes={"theme": "dark", "unit": "fortnights", "unknown": 1})
    assert result["settings"]["theme"] == "dark" and result["settings"]["unit"] == "hours"
    assert json.loads((tmp_path / "settings.json").read_text())["theme"] == "dark"
