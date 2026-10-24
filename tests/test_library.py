import os
from datetime import datetime

import pytest

from tunesback.library import LibraryStore
from tunesback.sources import itunes_xml
from tunesback.stats.report import build_report

from .conftest import SAMPLE_LIBRARY, track, write_library


@pytest.fixture
def store(tmp_path):
    s = LibraryStore(tmp_path / "data" / "library.sqlite")
    yield s
    s.close()


def bump(path, **mtime):
    """Change a file's modification time so it looks re-written."""
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + mtime.get("by", 10)))


def test_reading_round_trip(store, library):
    path = library("lib.xml", [track(1, "A", plays=3, skips=1, Genre="Rock", Year=1999,
                                     **{"Date Added": datetime(2020, 1, 2)})])
    source = store.add_source("itunes", "file", str(path), "local")
    [result] = store.refresh(source["id"])
    assert result.status == "new" and result.reading["track_count"] == 1 and result.reading["total_plays"] == 3

    snapshot = store.load(result.reading["id"])
    [t] = snapshot.tracks
    assert (t.name, t.play_count, t.skip_count, t.genre, t.year) == ("A", 3, 1, "Rock", 1999)
    assert t.date_added == datetime(2020, 1, 2)


def test_unchanged_file_is_not_read_twice(store, library):
    path = library("lib.xml", [track(1, "A", plays=3)])
    source = store.add_source("itunes", "file", str(path), "local")
    assert store.refresh(source["id"])[0].status == "new"
    assert store.refresh(source["id"])[0].status == "unchanged"
    write_library(path, [track(1, "A", plays=7)], datetime(2025, 6, 1))
    bump(path)
    assert store.refresh(source["id"])[0].status == "new"
    assert [r["total_plays"] for r in store.readings()] == [3, 7]


def test_two_readings_make_a_report(store, library):
    path = library("lib.xml", [track(1, "A", plays=3), track(2, "B", plays=1)], datetime(2025, 1, 1))
    source = store.add_source("itunes", "file", str(path), "local")
    store.refresh(source["id"])
    write_library(path, [track(1, "A", plays=10), track(2, "B", plays=1), track(3, "C", plays=2)], datetime(2025, 12, 1))
    bump(path)
    store.refresh(source["id"])
    first, second = store.readings()
    report = build_report(store.load(second["id"]), store.load(first["id"]))
    assert report.total_plays == 9
    assert {e.title for e in report.new_finds} == {"C"}


def test_missing_file_is_an_error_not_a_crash(store, tmp_path):
    source = store.add_source("itunes", "file", str(tmp_path / "gone.xml"), "network")
    [result] = store.refresh(source["id"])
    assert result.status == "error" and "connected" in result.error


def test_folder_source_imports_new_exports(store, library, tmp_path):
    library("a.xml", [track(1, "A", plays=1)], datetime(2024, 1, 1))
    source = store.add_source("itunes", "folder", str(tmp_path), "local")
    assert [r.status for r in store.refresh(source["id"])] == ["new"]
    library("b.xml", [track(1, "A", plays=5)], datetime(2025, 1, 1))
    assert sorted(r.status for r in store.refresh(source["id"])) == ["new", "unchanged"]
    assert [r["date"][:4] for r in store.readings()] == ["2024", "2025"]


def test_removing_a_source_removes_its_readings(store, library):
    source = store.add_source("itunes", "file", str(library("lib.xml", [track(1, "A")])), "local")
    store.refresh(source["id"])
    store.remove_source(source["id"])
    assert store.sources() == [] and store.readings() == []


def test_sample_library_round_trip(store):
    source = store.add_source("itunes", "file", str(SAMPLE_LIBRARY), "local")
    [result] = store.refresh(source["id"])
    loaded = store.load(result.reading["id"])
    original = itunes_xml.load_snapshot(str(SAMPLE_LIBRARY))
    assert build_report(loaded).total_plays == build_report(original).total_plays


# --- discovery ---

def test_discover_finds_library_and_export_folders(tmp_path, monkeypatch, library):
    monkeypatch.setattr(itunes_xml.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("APPDATA", raising=False)
    itunes = tmp_path / "Music" / "iTunes"
    itunes.mkdir(parents=True)
    write_library(itunes / "iTunes Library.xml", [track(1, "A")], datetime(2025, 3, 1))
    exports = tmp_path / "Documents"
    exports.mkdir()
    write_library(exports / "jan.xml", [track(1, "A")], datetime(2025, 1, 1))
    write_library(exports / "feb.xml", [track(1, "A")], datetime(2025, 2, 1))
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "notes.xml").write_text("<notes/>")

    found = itunes_xml.discover()
    assert [(c.kind, os.path.basename(c.path)) for c in found] == [("library", "iTunes Library.xml"), ("exports", "Documents")]


def test_discover_on_a_share(tmp_path):
    deep = tmp_path / "share" / "Media" / "iTunes"
    deep.mkdir(parents=True)
    write_library(deep / "iTunes Music Library.xml", [track(1, "A")])
    found = itunes_xml.discover(str(tmp_path / "share"))
    assert [os.path.basename(c.path) for c in found] == ["iTunes Music Library.xml"]


def test_discover_mentions_the_macos_music_app(tmp_path, monkeypatch):
    monkeypatch.setattr(itunes_xml.Path, "home", lambda: tmp_path)
    (tmp_path / "Music" / "Music" / "Music Library.musiclibrary").mkdir(parents=True)
    [found] = itunes_xml.discover()
    assert found.kind == "needs_export"
