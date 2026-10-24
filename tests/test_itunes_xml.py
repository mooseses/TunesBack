from datetime import datetime

import pytest

from tunesback.sources.itunes_xml import load_snapshot, scan_folder

from .conftest import SAMPLE_LIBRARY, track


def test_whitespace_in_metadata_is_collapsed(library):
    path = library("lib.xml", [track(1, "Song\n\t\tTitle", album="Box Set\n\t\t\t[Remastered]", plays=1)])
    t = load_snapshot(str(path)).tracks[0]
    assert t.name == "Song Title"
    assert t.album == "Box Set [Remastered]"


def test_non_music_is_excluded(library):
    path = library("lib.xml", [
        track(1, "Song", plays=1),
        track(2, "Episode", plays=1, Podcast=True),
        track(3, "Film", plays=1, Movie=True),
        track(4, "Clip", plays=1, **{"Has Video": True}),
        track(5, "Chapter", plays=1, Kind="Audible audiobook"),
    ])
    assert [t.name for t in load_snapshot(str(path)).tracks] == ["Song"]


def test_missing_fields_get_defaults(library):
    path = library("lib.xml", [{"Track ID": 1, "Play Count": 2}])
    t = load_snapshot(str(path)).tracks[0]
    assert (t.name, t.artist, t.album_artist, t.album) == ("Unknown", "Unknown Artist", "Unknown Artist", "Unknown Album")
    assert t.duration_ms == 0 and t.play_count == 2 and t.genre is None


def test_album_artist_falls_back_to_artist(library):
    path = library("lib.xml", [track(1, "A", artist="Solo"), track(2, "B", artist="Guest", **{"Album Artist": "Band"})])
    a, b = load_snapshot(str(path)).tracks
    assert a.album_artist == "Solo" and b.album_artist == "Band"


def test_location_is_kept_encoded(library):
    uri = "file:///Users/me/Music/Symphony%20%235.mp3"
    path = library("lib.xml", [track(1, "Symphony #5", Location=uri)])
    assert load_snapshot(str(path)).tracks[0].location == uri


def test_snapshot_date_comes_from_library_header(library):
    path = library("export.xml", [], date=datetime(2024, 6, 30, 12, 0))
    assert load_snapshot(str(path)).date == datetime(2024, 6, 30, 12, 0)


def test_invalid_file_raises_value_error(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<not a plist")
    with pytest.raises(ValueError):
        load_snapshot(str(bad))


def test_scan_orders_by_header_date_and_ignores_names(library, tmp_path):
    library("zzz.xml", [], date=datetime(2023, 1, 1))
    library("aaa.xml", [], date=datetime(2025, 1, 1))
    (tmp_path / "notes.xml").write_text("<?xml version='1.0'?><notes/>")
    (tmp_path / "readme.txt").write_text("hi")
    found = scan_folder(str(tmp_path))
    assert [s.file for s in found] == ["zzz.xml", "aaa.xml"]
    assert all(s.date_source == "library" for s in found)


def test_scan_falls_back_to_filename_date(library, tmp_path):
    library("2022-03-04 backup.xml", [], date=None)
    [found] = scan_folder(str(tmp_path))
    assert found.date.date() == datetime(2022, 3, 4).date()
    assert found.date_source == "filename"


def test_scan_gives_duplicate_dates_unique_labels(library, tmp_path):
    library("a.xml", [], date=datetime(2025, 5, 1, 9))
    library("b.xml", [], date=datetime(2025, 5, 1, 18))
    assert [s.label for s in scan_folder(str(tmp_path))] == ["2025-05-01 (1)", "2025-05-01 (2)"]


def test_scan_missing_folder_returns_nothing(tmp_path):
    assert scan_folder(str(tmp_path / "nope")) == []


def test_sample_library_parses():
    snapshot = load_snapshot(str(SAMPLE_LIBRARY))
    assert snapshot.date == datetime(2017, 3, 27, 11, 36, 59)
    assert len(snapshot.tracks) > 300
    assert all("\n" not in t.album for t in snapshot.tracks)
