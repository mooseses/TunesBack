from datetime import datetime

from tunesback.cards import build_context, render_cards
from tunesback.sources.itunes_xml import load_snapshot
from tunesback.stats.report import build_report

from .conftest import SAMPLE_LIBRARY, track


def no_art(_location):
    return None


def test_full_card_stack_from_sample_library():
    report = build_report(load_snapshot(str(SAMPLE_LIBRARY)))
    cards = render_cards(report, artwork=no_art)
    assert [c.info["card_name"] for c in cards] == [
        "Top_Albums", "Top_Genres", "Listening_Age", "Top_Songs_List", "Top_Song_Single", "Minutes_Listened", "Summary",
    ]
    assert all(c.size == (1080, 1920) for c in cards)


def test_library_without_genres_or_years(library):
    end = load_snapshot(str(library("e.xml", [track(1, "Line\nbreak", plays=3)], datetime(2019, 5, 1))))
    report = build_report(end)
    context = build_context(report, artwork=no_art)
    assert context["genres"] == [] and context["age_data"] is None
    assert context["year_label"] == "2019"
    names = [c.info["card_name"] for c in render_cards(report, artwork=no_art)]
    assert "Top_Genres" not in names and "Listening_Age" not in names and "Summary" in names


def test_context_follows_ranking(library):
    end = load_snapshot(str(library("e.xml", [
        track(1, "Frequent", plays=10, **{"Total Time": 60_000}),
        track(2, "Epic", plays=2, **{"Total Time": 1_200_000}),
    ])))
    report = build_report(end)
    assert build_context(report, "plays", artwork=no_art)["top_songs"][0]["name"] == "Frequent"
    assert build_context(report, "time", artwork=no_art)["top_songs"][0]["name"] == "Epic"
    assert build_context(report, artwork=no_art)["total_minutes"] == 50
