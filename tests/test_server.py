import http.client
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
    srv = AppServer(Api(Settings(tmp_path / "settings.json")))
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


def test_scan_analyze_and_cards(server, library, tmp_path):
    library("start.xml", [track(1, "A", plays=1, Genre="Rock", Year=2000)], datetime(2025, 1, 1))
    library("end.xml", [track(1, "A", plays=6, Genre="Rock", Year=2000)], datetime(2025, 12, 31))

    scanned = api(server, "scan", folder=str(tmp_path))
    first, second = scanned["snapshots"]
    report = api(server, "analyze", start=first["id"], end=second["id"])["report"]
    assert report["mode"] == "compare" and report["total_plays"] == 5
    assert api(server, "analyze", start=second["id"], end=first["id"])["error"]

    cards = api(server, "generate_cards", rank_by="plays")["cards"]
    assert cards and cards[0]["preview"].startswith("data:image/jpeg")
    status, _ = request(server, "GET", f"/api/card/0.jpg?token={server.token}")
    assert status == 200
    assert request(server, "GET", "/api/card/0.jpg?token=nope")[0] == 403

    out = tmp_path / "out"
    assert api(server, "save_cards", indices=[0, 1], folder=str(out))["saved"] == 2
    assert len(list(out.glob("*.jpg"))) == 2


def test_settings_are_validated_and_saved(server, tmp_path):
    result = api(server, "update_settings", changes={"theme": "dark", "unit": "fortnights", "unknown": 1})
    assert result["settings"]["theme"] == "dark" and result["settings"]["unit"] == "hours"
    assert json.loads((tmp_path / "settings.json").read_text())["theme"] == "dark"
