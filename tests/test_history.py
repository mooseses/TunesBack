"""Play sources in the store, statistics from plays, and recaps mixing sources."""
import json
import sqlite3
import zipfile
from datetime import datetime, timedelta

import pytest

from tunesback.app.api import Api
from tunesback.app.settings import Settings
from tunesback.library import SCHEMA_VERSION, LibraryStore
from tunesback.recap import build_recap
from tunesback.sources import http, lastfm
from tunesback.sources.plays import Play, Stopped
from tunesback.stats.plays import AVERAGE_SONG_MS, Enricher, activity_from_plays, merge, timeline, Listen

from .conftest import track
from .test_sources import fake_lastfm


def ts(*args) -> int:
    return int(datetime(*args).timestamp())


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


def test_store_from_before_play_sources_is_upgraded(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE sources (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, mode TEXT NOT NULL, path TEXT NOT NULL,
            location TEXT NOT NULL, added_at TEXT NOT NULL, UNIQUE (kind, path));
        CREATE TABLE tracks (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, key TEXT NOT NULL, persistent_id TEXT,
            name TEXT, artist TEXT, album_artist TEXT, album TEXT, genre TEXT, year INTEGER, duration_ms INTEGER,
            date_added TEXT, location TEXT, UNIQUE (source_id, key));
        INSERT INTO sources VALUES (1, 'itunes', 'file', '/music/lib.xml', 'local', '2025-01-01T00:00:00');""")
    db.commit()
    db.close()
    store = LibraryStore(path)
    try:
        [source] = store.sources()
        assert source["path"] == "/music/lib.xml" and source["options"] == {} and source["play_count"] == 0
        assert store._db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.add_plays(1, [Play.make("A", "B", "C", 5)]) == 1
    finally:
        store.close()


def test_plays_take_details_from_the_library(store):
    source = store.add_source("lastfm", "account", "rj", "online")
    store.add_plays(source["id"], [
        Play.make("Song", "Artist feat. Guest", "Album", ts(2025, 3, 1, 9)),
        Play.make("Song", "Artist feat. Guest", "Album", ts(2025, 3, 2, 9)),
        Play.make("Unknown", "Nobody", "", ts(2025, 3, 2, 10)),
        Play.make("Skipped", "Nobody", "", ts(2025, 3, 2, 11), ms_played=4000, skipped=True),
    ])
    enricher = Enricher([{"name": "song", "artist": "Artist", "album": "Album", "genre": "Pop", "year": 2001,
                          "duration_ms": 200_000, "location": "file:///m/song.mp3"}])
    activity, listens, estimated = activity_from_plays(store.plays([source["id"]]), enricher)
    by_name = {a.track.name: a for a in activity}
    song = by_name["Song"]
    assert (song.plays, song.ms, song.track.genre, song.track.year) == (2, 400_000, "Pop", 2001)
    assert song.track.location == "file:///m/song.mp3"
    assert by_name["Unknown"].ms == AVERAGE_SONG_MS and estimated
    assert (by_name["Skipped"].plays, by_name["Skipped"].skips, by_name["Skipped"].ms) == (0, 1, 4000)
    assert len(listens) == 3


def test_merging_sources(store):
    itunes = store.add_source("lastfm", "account", "a", "online")
    other = store.add_source("listenbrainz", "account", "b", "online")
    store.add_plays(itunes["id"], [Play.make("Song", "Artist", "X", ts(2025, 1, d)) for d in range(1, 6)])
    store.add_plays(other["id"], [Play.make("Song", "Artist", "Y", ts(2025, 1, d, 1)) for d in range(1, 4)])
    a, _, _ = activity_from_plays(store.plays([itunes["id"]]), Enricher())
    b, _, _ = activity_from_plays(store.plays([other["id"]]), Enricher())
    [same] = merge([a, b], "same")
    [both] = merge([a, b], "separate")
    assert same.plays == 5 and both.plays == 8
    assert both.ms == 8 * AVERAGE_SONG_MS


def test_merging_counts_each_source_in_full(store):
    """A source that logged a song under two albums still counts all of its plays."""
    a_src = store.add_source("lastfm", "account", "a", "online")
    b_src = store.add_source("listenbrainz", "account", "b", "online")
    store.add_plays(a_src["id"], [Play.make("Song", "Artist", "Album", ts(2025, 1, d)) for d in range(1, 4)]
                    + [Play.make("Song", "Artist feat. Guest", "Album (Deluxe)", ts(2025, 2, d)) for d in range(1, 4)])
    store.add_plays(b_src["id"], [Play.make("Song", "Artist", "Album", ts(2025, 1, d, 1)) for d in range(1, 6)])
    a, _, _ = activity_from_plays(store.plays([a_src["id"]]), Enricher())
    b, _, _ = activity_from_plays(store.plays([b_src["id"]]), Enricher())
    assert len(a) == 2
    [same] = merge([a, b], "same")
    [both] = merge([a, b], "separate")
    assert same.plays == 6 and same.ms == 6 * AVERAGE_SONG_MS
    assert both.plays == 11


def test_timeline():
    listens = [Listen(ts(2025, 1, d, 22), 180_000, "A", "S1") for d in (1, 2, 3, 4)]
    listens += [Listen(ts(2025, 1, 10, 8), 180_000, "B", "S2"), Listen(ts(2025, 3, 5, 8), 180_000, "B", "S2")]
    result = timeline(listens, datetime(2025, 1, 1), datetime(2025, 4, 1),
                      first_played_artist={"a": ts(2024, 6, 1), "b": ts(2025, 1, 10)}, history_start=ts(2024, 6, 1))
    assert result["total"] == 6
    assert result["hours"]["plays"][22] == 4 and result["peak_hour"] == 22
    assert result["longest_streak"] == {"days": 4, "start": "2025-01-01", "end": "2025-01-04"}
    assert [m["month"] for m in result["months"]] == ["2025-01", "2025-02", "2025-03"]
    assert result["months"][0]["top_artist"] == "A" and result["months"][1]["plays"] == 0
    assert result["days_active"] == 6 and result["days"] == 90
    assert result["discoveries"] == {"artists": 1, "top": [{"name": "B", "plays": 2}]}
    # Without history before the period, everything would look new: no discoveries then.
    assert timeline(listens, datetime(2025, 1, 1), None, {"a": 0}, ts(2025, 1, 1))["discoveries"] is None


def test_recap_mixing_a_library_and_plays(store, library):
    first = library("a.xml", [track(1, "Lib Song", artist="Lib Artist", plays=2, Genre="Rock", Year=1999)],
                    datetime(2024, 12, 30))
    second = library("b.xml", [track(1, "Lib Song", artist="Lib Artist", plays=12, Genre="Rock", Year=1999)],
                     datetime(2026, 1, 2))
    itunes = store.add_source("itunes", "folder", str(first.parent), "local")
    store.refresh(itunes["id"])
    spotify = store.add_source("spotify", "export", "/x.zip", "local")
    store.add_plays(spotify["id"], [Play.make("Lib Song", "Lib Artist", "", ts(2025, 5, d, 12), ms_played=180_000)
                                    for d in range(1, 7)]
                    + [Play.make("Old", "Someone", "", ts(2023, 1, 1), ms_played=100_000)])
    sources = store.sources()
    year = (datetime(2025, 1, 1), datetime(2026, 1, 1))
    same = build_recap(store, sources, *year, "same")
    assert same.total_plays == 10  # iTunes' 10 plays win over Spotify's 6 of the same song
    assert same.genres[0].title == "Rock" and same.timeline["total"] == 6
    assert {s["kind"] for s in same.sources} == {"itunes", "spotify"}
    assert build_recap(store, sources, *year, "separate").total_plays == 16
    spotify_only = build_recap(store, [s for s in sources if s["kind"] == "spotify"], None, None)
    assert spotify_only.total_plays == 7 and spotify_only.mode == "single"
    assert spotify_only.genres[0].title == "Rock"  # filled in from the library


@pytest.fixture
def api(tmp_path):
    a = Api(Settings(tmp_path / "settings.json"), thumbnail_dir=tmp_path / "thumbs", store_path=tmp_path / "lib.sqlite")
    yield a
    a.store.close()


def test_spotify_import_and_recap(api, tmp_path):
    archive = tmp_path / "my_spotify_data.zip"
    entries = [{"ts": f"2025-0{m}-0{d}T20:00:00Z", "ms_played": 200000, "master_metadata_track_name": f"Song {d}",
                "master_metadata_album_artist_name": "Artist", "master_metadata_album_album_name": "Album"}
               for m in (1, 2) for d in (1, 2, 3)]
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Spotify Extended Streaming History/Streaming_History_Audio_2025.json", json.dumps(entries))
    result = api.call("import_history", {"path": str(archive), "kind": "spotify"})
    assert result["plays"] == 6 and result["new"] == 6 and result["source"]["name"] == "Spotify"
    assert api.call("import_history", {"path": str(archive)})["new"] == 0
    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr("Streaming_History_Audio_2025.json", json.dumps(entries + [{**entries[0], "ts": "2025-03-01T20:00:00Z"}]))
    again = api.call("import_history", {"path": str(newer)})
    assert again["new"] == 1 and again["source"]["id"] == result["source"]["id"]
    assert api.call("library", {})["sources"][0]["path"] == str(newer)
    assert api.settings["setup_done"] is True
    [source] = api.call("library", {})["sources"]
    assert source["play_count"] == 7 and not source["counter"]
    assert api.call("refresh_readings", {}) == {"new": 0, "problems": []}

    report = api.call("analyze", {"sources": [source["id"]], "period": {"start": "2025-01-01", "end": "2025-01-31"}})["report"]
    assert report["total_plays"] == 3 and report["mode"] == "compare" and report["timeline"]["total"] == 3
    everything = api.call("analyze", {"period": {"start": None, "end": None}})["report"]
    assert everything["total_plays"] == 7 and everything["mode"] == "single"
    assert "no plays" in api.call("analyze", {"period": {"start": "2020-01-01", "end": "2020-12-31"}})["error"]
    assert "dates" in api.call("analyze", {"period": {"start": "yesterday"}})["error"]
    cards = api.call("cards", {})
    assert "clock" in {c["type"] for c in cards["cards"]}


def test_lastfm_account(api, monkeypatch):
    service = fake_lastfm([1_700_000_000 + i * 600 for i in range(30)])
    monkeypatch.setattr(lastfm, "API", service.url)
    monkeypatch.delenv("TUNESBACK_LASTFM_API_KEY", raising=False)
    try:
        assert api.call("catalog", {})["lastfm_key"] is False
        assert "API key" in api.call("add_account", {"kind": "lastfm", "username": "rj"})["error"]
        assert "no Last.fm user" in api.call("add_account", {"kind": "lastfm", "username": "nobody", "api_key": "KEY"})["error"]
        added = api.call("add_account", {"kind": "lastfm", "username": "rj", "api_key": "KEY"})
        assert added["new"] == 30 and added["expected"] == 30 and added["source"]["complete"]
        assert api.settings["lastfm_api_key"] == "KEY" and api.call("catalog", {})["lastfm_key"]
        assert api.call("sync_sources", {}) == {"new": 0, "problems": [], "stopped": False}
    finally:
        service.close()
    problems = api.call("sync_sources", {})["problems"]
    assert problems and "Couldn't reach Last.fm" in problems[0]["error"]
