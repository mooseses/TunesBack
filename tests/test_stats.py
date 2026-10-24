from datetime import datetime

from tunesback.sources.itunes_xml import load_snapshot
from tunesback.stats.listening_age import calculate_listening_age
from tunesback.stats.period import period_activity
from tunesback.stats.report import build_report, split_artists

from .conftest import SAMPLE_LIBRARY, track

START = datetime(2025, 1, 1)
END = datetime(2025, 12, 31)


def load(path):
    return load_snapshot(str(path))


# --- period activity ---

def test_single_snapshot_counts_lifetime_plays(library):
    end = load(library("end.xml", [track(1, "A", plays=3), track(2, "B")]))
    [activity] = period_activity(end)
    assert activity.plays == 3 and activity.ms == 3 * 180_000 and not activity.is_new


def test_compare_counts_only_the_difference(library):
    start = load(library("s.xml", [track(1, "A", plays=3, skips=1)], START))
    end = load(library("e.xml", [track(1, "A", plays=10, skips=4)], END))
    [activity] = period_activity(end, start)
    assert (activity.plays, activity.skips) == (7, 3)


def test_counter_reset_is_not_negative(library):
    start = load(library("s.xml", [track(1, "A", plays=50)], START))
    end = load(library("e.xml", [track(1, "A", plays=2)], END))
    assert period_activity(end, start) == []


def test_rebuilt_library_matches_by_name(library):
    start = load(library("s.xml", [track(1, "A", plays=5)], START))
    end = load(library("e.xml", [track(2, "A", plays=8, **{"Persistent ID": "NEWID"})], END))
    [activity] = period_activity(end, start)
    assert activity.plays == 3 and not activity.is_new


def test_ambiguous_name_match_is_not_used(library):
    start = load(library("s.xml", [track(1, "A", plays=5), track(2, "A", plays=9)], START))
    end = load(library("e.xml", [track(3, "A", plays=4, **{"Persistent ID": "NEW"})], END))
    [activity] = period_activity(end, start)
    assert activity.plays == 4


def test_new_finds(library):
    start = load(library("s.xml", [track(1, "Old", plays=1), track(2, "Unplayed")], START))
    end = load(library("e.xml", [
        track(1, "Old", plays=5),
        track(2, "Unplayed", plays=2),  # was in the library already: not a new find
        track(3, "Fresh", plays=4, **{"Date Added": datetime(2025, 3, 1)}),
        track(4, "Unmatched old", plays=2, **{"Date Added": datetime(2020, 1, 1)}),
    ], END))
    new = {a.track.name for a in period_activity(end, start) if a.is_new}
    assert new == {"Fresh"}


# --- report ---

def test_split_artists_keeps_band_names():
    assert split_artists("Simon & Garfunkel") == ["Simon & Garfunkel"]
    assert split_artists("Earth, Wind & Fire") == ["Earth, Wind & Fire"]
    assert split_artists("AC/DC") == ["AC/DC"]
    assert split_artists("Calvin Harris feat. Rihanna") == ["Calvin Harris", "Rihanna"]
    assert split_artists("A ft. B; C") == ["A", "B", "C"]
    assert split_artists("Artist (featuring Guest)") == ["Artist", "Guest"]


def test_report_aggregates(library):
    end = load(library("e.xml", [
        track(1, "One", artist="X feat. Y", album="LP", plays=2, Genre="Rock", Year=1999),
        track(2, "Two", artist="X", album="LP", plays=3, Genre="Rock", Year=2001, **{"Album Artist": "X"}),
        track(3, "Three", artist="Z", album="Single", plays=1, skips=2, Genre="Pop", Year=2001),
    ], END))
    report = build_report(end)
    assert report.mode == "single" and report.total_plays == 6
    assert {e.title: e.plays for e in report.artists} == {"X": 5, "Y": 2, "Z": 1}
    assert {(e.title, e.subtitle): e.plays for e in report.albums} == {("LP", "X feat. Y"): 2, ("LP", "X"): 3, ("Single", "Z"): 1}
    assert {e.title: e.plays for e in report.genres} == {"Rock": 5, "Pop": 1}
    assert {e.title: e.plays for e in report.years} == {"1999": 2, "2001": 4}
    assert [e.title for e in report.skipped] == ["Three"]
    assert report.top("songs", "plays")[0].title == "Two"


def test_ranking_by_time_and_plays(library):
    end = load(library("e.xml", [
        track(1, "Short", plays=10, **{"Total Time": 60_000}),
        track(2, "Long", plays=2, **{"Total Time": 1_200_000}),
    ], END))
    report = build_report(end)
    assert report.top("songs", "plays")[0].title == "Short"
    assert report.top("songs", "time")[0].title == "Long"


def test_entry_art_comes_from_most_played_track(library):
    end = load(library("e.xml", [
        track(1, "A", album="LP", plays=1, Location="file:///a.mp3"),
        track(2, "B", album="LP", plays=9, Location="file:///b.mp3"),
    ], END))
    [album] = build_report(end).albums
    assert album.art == "file:///b.mp3"


def test_report_on_sample_library():
    report = build_report(load(SAMPLE_LIBRARY))
    assert report.total_plays == 215
    assert report.listening_age is not None
    assert report.to_dict()["listening_age"]["era_label"]


# --- listening age ---

def test_listening_age_uses_reference_year():
    age = calculate_listening_age({2010: 100}, 2023)
    assert (age.age, age.era_start, age.era_end) == (29, 2010, 2014)
    assert calculate_listening_age({2010: 100}, 2026).age == 32


def test_listening_age_picks_busiest_window():
    age = calculate_listening_age({1975: 10, 1976: 10, 1977: 10, 2015: 25}, 2025)
    assert age.era_start <= 1975 and age.era_end >= 1977
    assert age.era_label == "Late 70s"  # window 1975-1979, centred on 1977


def test_listening_age_ignores_bad_years():
    assert calculate_listening_age({0: 50, 1800: 50, 3000: 50}, 2025) is None
    assert calculate_listening_age({}, 2025) is None
