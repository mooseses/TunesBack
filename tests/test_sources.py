"""Play sources: Spotify downloads, and Last.fm / ListenBrainz against fake servers."""
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from tunesback.library import LibraryStore
from tunesback.sources import http, spotify
from tunesback.sources.lastfm import LastFm
from tunesback.sources.listenbrainz import ListenBrainz
from tunesback.sources.plays import SourceError, Stopped, sync_history


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    def wait(self, seconds):
        if self.stop():
            raise Stopped
    monkeypatch.setattr(http.Client, "_wait", wait)


@pytest.fixture
def store(tmp_path):
    s = LibraryStore(tmp_path / "library.sqlite")
    yield s
    s.close()


class FakeService:
    """A tiny HTTP server answering from a handler function: handler(path, query) -> (status, body)."""

    def __init__(self, handler):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                service.requests.append((url.path, query))
                status, body = handler(url.path, query)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


# ---------- Spotify ----------

def test_spotify_extended_history_zip(tmp_path):
    entries = [
        {"ts": "2025-03-01T12:03:30Z", "ms_played": 210000, "master_metadata_track_name": "Song A",
         "master_metadata_album_artist_name": "Artist", "master_metadata_album_album_name": "Album", "skipped": False},
        {"ts": "2025-03-01T12:04:00Z", "ms_played": 5000, "master_metadata_track_name": "Song B",
         "master_metadata_album_artist_name": "Artist", "master_metadata_album_album_name": "Album", "skipped": True},
        {"ts": "2025-03-01T13:00:00Z", "ms_played": 1800000, "master_metadata_track_name": None,
         "episode_name": "A podcast", "episode_show_name": "Show"},
    ]
    archive = tmp_path / "my_spotify_data.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Spotify Extended Streaming History/Streaming_History_Audio_2025.json", json.dumps(entries))
        z.writestr("Spotify Extended Streaming History/Streaming_History_Video_2025.json", "[]")
        z.writestr("Spotify Extended Streaming History/ReadMeFirst.pdf", "x")
    plays = spotify.read_export(str(archive))
    assert [(p.name, p.skipped, p.ms_played) for p in plays] == [("Song A", False, 210000), ("Song B", True, 5000)]
    assert plays[0].played_at == 1740830610 - 210  # the start: end time minus the time played


def test_spotify_account_data_folder(tmp_path):
    folder = tmp_path / "MyData"
    folder.mkdir()
    (folder / "StreamingHistory_music_0.json").write_text(json.dumps([
        {"endTime": "2024-12-31 23:59", "artistName": "Artist", "trackName": "Song", "msPlayed": 200000}]))
    (folder / "StreamingHistory_podcast_0.json").write_text(json.dumps([
        {"endTime": "2024-12-31 22:00", "podcastName": "Pod", "episodeName": "Ep", "msPlayed": 9}]))
    [play] = spotify.read_export(str(folder))
    assert (play.name, play.album, play.ms_played) == ("Song", "", 200000)

    with pytest.raises(SourceError, match="no music listens"):
        spotify.read_export(str(tmp_path / "MyData" / "StreamingHistory_podcast_0.json"))
    (tmp_path / "empty").mkdir()
    with pytest.raises(SourceError, match="no Spotify listening history"):
        spotify.read_export(str(tmp_path / "empty"))


# ---------- Last.fm ----------

def scrobble(i, ts):
    return {"name": f"Song {i % 7}", "artist": {"name": f"Artist {i % 3}", "#text": ""},
            "album": {"#text": "Album"}, "date": {"uts": str(ts)},
            "image": [{"size": "small", "#text": "http://x/small.jpg"}, {"size": "extralarge", "#text": f"http://x/{i}.jpg"}]}


def fake_lastfm(scrobbles, fail_once=False):
    """scrobbles: list of timestamps. Behaves like user.getRecentTracks (newest first, inclusive bounds)."""
    state = {"failed": False}

    def handler(path, q):
        if q.get("api_key") != "KEY":
            return 403, {"error": 10, "message": "Invalid API key"}
        if q["user"] == "nobody":
            return 404, {"error": 6, "message": "User not found"}
        if q["user"] == "private" and q["method"] == "user.getRecentTracks":
            return 403, {"error": 17, "message": "Login: User requires to be logged in"}
        if fail_once and not state["failed"]:
            state["failed"] = True
            return 500, {"error": 29, "message": "Rate limit exceeded"}
        if q["method"] == "user.getInfo":
            return 200, {"user": {"name": q["user"], "playcount": str(len(scrobbles)), "registered": {"unixtime": "1000"}}}
        low, high = int(q.get("from", 0)), int(q.get("to", 2**40))
        chosen = sorted((t for t in scrobbles if low <= t <= high), reverse=True)
        limit, page = int(q.get("limit", 50)), int(q.get("page", 1))
        tracks = [scrobble(t, t) for t in chosen[(page - 1) * limit: page * limit]]
        if page == 1 and q.get("from") is None:
            tracks.insert(0, {**scrobble(0, 0), "@attr": {"nowplaying": "true"}, "date": None})
        pages = max(1, -(-len(chosen) // limit)) if chosen else 0
        return 200, {"recenttracks": {"track": tracks, "@attr": {"page": str(page), "totalPages": str(pages), "total": str(len(chosen))}}}
    return FakeService(handler)


def test_lastfm_full_sync_then_catch_up(store):
    times = [1_700_000_000 + i * 600 for i in range(450)]
    service = fake_lastfm(times)
    try:
        source = store.add_source("lastfm", "account", "rj", "online")
        api = LastFm("rj", "KEY", base_url=service.url)
        assert api.check()["plays"] == 450
        assert sync_history(store, source["id"], api.newer, api.older) == 450
        assert store.source(source["id"])["options"]["sync"] == {"oldest": times[0], "newest": times[-1], "complete": True}
        assert store.sources()[0]["play_count"] == 450

        times.extend([times[-1] + 600, times[-1] + 1200])
        assert sync_history(store, source["id"], api.newer, api.older) == 2
        assert sync_history(store, source["id"], api.newer, api.older) == 0
        row = store.plays([source["id"]])[-1]
        assert row["art_url"] == f"http://x/{times[-1]}.jpg" and row["artist"] == "Artist " + str(times[-1] % 3)
    finally:
        service.close()


def test_lastfm_interrupted_import_resumes(store):
    times = [1_700_000_000 + i * 600 for i in range(450)]
    service = fake_lastfm(times)
    try:
        source = store.add_source("lastfm", "account", "rj", "online")
        api = LastFm("rj", "KEY", base_url=service.url)
        batches = {"n": 0}

        def stop():
            return batches["n"] >= 1

        def progress(text):
            batches["n"] += 1

        with pytest.raises(Stopped):
            sync_history(store, source["id"], api.newer, api.older, progress, stop)
        assert store.sources()[0]["play_count"] == 200
        assert sync_history(store, source["id"], api.newer, api.older) == 250
        assert store.sources()[0]["play_count"] == 450
    finally:
        service.close()


def test_lastfm_errors_and_retries(store):
    service = fake_lastfm([1_700_000_000], fail_once=True)
    try:
        assert LastFm("rj", "KEY", base_url=service.url).check()["plays"] == 1  # retried after the 500
        with pytest.raises(SourceError, match="no Last.fm user"):
            LastFm("nobody", "KEY", base_url=service.url).check()
        with pytest.raises(SourceError, match="private"):
            LastFm("private", "KEY", base_url=service.url).check()
        with pytest.raises(SourceError, match="API key"):
            LastFm("rj", "WRONG", base_url=service.url).check()
    finally:
        service.close()
    with pytest.raises(SourceError, match="Couldn't reach Last.fm"):
        LastFm("rj", "KEY", base_url=service.url).check()  # the server is gone


# ---------- ListenBrainz ----------

def fake_listenbrainz(times):
    def listen(ts):
        return {"listened_at": ts, "recording_msid": str(ts), "track_metadata": {
            "artist_name": "Artist", "track_name": f"Song {ts % 5}", "release_name": "Album",
            "additional_info": {"duration_ms": 200000},
            "mbid_mapping": {"caa_release_mbid": "rel", "caa_id": 42}}}

    def handler(path, q):
        user = path.split("/")[2]
        if user != "rob":
            return 404, {"code": 404, "error": "Cannot find user: " + user}
        if path.endswith("listen-count"):
            return 200, {"payload": {"count": len(times)}}
        count = int(q.get("count", 25))
        if "min_ts" in q:
            chosen = sorted(t for t in times if t > int(q["min_ts"]))[:count]
            chosen.reverse()
        else:
            chosen = sorted((t for t in times if t < int(q.get("max_ts", 2**40))), reverse=True)[:count]
        return 200, {"payload": {"count": len(chosen), "listens": [listen(t) for t in chosen], "user_id": user}}
    return FakeService(handler)


def test_listenbrainz_sync(store):
    times = [1_600_000_000 + i * 300 for i in range(2500)]
    service = fake_listenbrainz(times)
    try:
        source = store.add_source("listenbrainz", "account", "rob", "online")
        api = ListenBrainz("rob", base_url=service.url)
        assert api.check()["plays"] == 2500
        assert sync_history(store, source["id"], api.newer, api.older) == 2500
        times.extend(times[-1] + 300 * i for i in range(1, 1500))
        assert sync_history(store, source["id"], api.newer, api.older) == 1499
        rows = store.plays([source["id"]])
        assert len(rows) == 3999 and rows[0]["duration_ms"] == 200000
        assert rows[0]["art_url"] == "https://coverartarchive.org/release/rel/42-250.jpg"
        with pytest.raises(SourceError, match="no ListenBrainz user"):
            ListenBrainz("nope", base_url=service.url).check()
    finally:
        service.close()
