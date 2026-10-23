from datetime import datetime

import pytest
from PIL import Image

from tunesback.cards import CardChoice, build_data, catalog, draw, normalize, plan
from tunesback.cards.fonts import FontSpec, text_width
from tunesback.cards.registry import CARD_TYPES
from tunesback.cards.text import ELLIPSIS, Style, fit
from tunesback.cards.themes import THEMES, cover_theme
from tunesback.sources.itunes_xml import load_snapshot
from tunesback.stats.report import build_report

from .conftest import SAMPLE_LIBRARY, track


def no_art(_location):
    return None


def some_art(location):
    return Image.new("RGB", (300, 300), (200, 60, 90)) if location else None


@pytest.fixture(scope="module")
def sample_data():
    return build_data(build_report(load_snapshot(str(SAMPLE_LIBRARY))), load_art=some_art)


def test_every_layout_theme_and_format_renders(sample_data):
    for card in CARD_TYPES.values():
        if not card.layouts or not card.applies(sample_data):
            continue
        for layout in card.layouts:
            for theme in ("cover", *THEMES):
                for fmt, size in (("story", (270, 480)), ("square", (270, 270))):
                    image = draw(CardChoice(card.id, layout, theme), sample_data, fmt, scale=0.25)
                    assert image.size == size, (card.id, layout, theme, fmt)


def test_long_and_international_text(library):
    long = "A Considerably Longer Song Title That Goes On and On (2011 Remaster) " * 3
    end = load_snapshot(str(library("e.xml", [
        track(1, long, artist="The Extremely Long Named Orchestra and Chorus of Somewhere", plays=9,
              Genre="Singer/Songwriter/Something Else Entirely", Year=2005),
        track(2, "群青日和", artist="東京事変", album="教育", plays=5, Genre="J-Pop", Year=2004),
        track(3, "사랑했나봐", artist="윤도현", plays=4),
        track(4, "Привет, мир", artist="Кино", plays=3),
    ], datetime(2025, 12, 31))))
    data = build_data(build_report(end), load_art=no_art)
    for choice in plan(data, {"seed": 7}):
        for layout in CARD_TYPES[choice.type].layouts:
            draw(CardChoice(choice.type, layout, choice.theme), data, "story", scale=0.2)
            draw(CardChoice(choice.type, layout, choice.theme), data, "square", scale=0.2)


def test_text_shrinks_wraps_then_ends_with_ellipsis():
    style = Style(FontSpec("Figtree", 900), 100, max_lines=2)
    short = fit("Short", style, 800)
    assert short.lines == ("Short",) and short.size == 100
    long = fit("A Considerably Longer Song Title That Goes On and On and On", style, 800)
    assert len(long.lines) == 2 and long.lines[-1].endswith(ELLIPSIS) and long.size < 100
    assert all(text_width(line, style.font, long.size) <= 800 for line in long.lines)
    assert fit("", style, 800).lines == ()
    assert fit("Hey   Jude\n", Style(FontSpec("Figtree"), 50), 800).lines == ("Hey Jude",)


def test_deck_follows_the_data_and_the_seed(library):
    end = load_snapshot(str(library("e.xml", [track(1, "Line\nbreak", plays=3)], datetime(2019, 5, 1))))
    data = build_data(build_report(end), load_art=no_art)
    types = [c.type for c in plan(data)]
    assert "genres" not in types and "listening_age" not in types and "clock" not in types
    assert types[0] == "top_songs" and "summary" in types
    assert data.period == "All time"

    sample = build_data(build_report(load_snapshot(str(SAMPLE_LIBRARY))), load_art=no_art)
    default = plan(sample)
    assert all(c.layout == next(iter(CARD_TYPES[c.type].layouts)) for c in default)
    assert plan(sample, {"seed": 42}) == plan(sample, {"seed": 42})
    assert plan(sample, {"seed": 42}) != plan(sample, {"seed": 43})
    chosen = plan(sample, {"seed": 42, "theme": "paper", "cards": {"top_songs": {"layout": "receipt", "hidden": True}}})
    assert all(c.theme == "paper" for c in chosen)
    assert chosen[0] == CardChoice("top_songs", "receipt", "paper", hidden=True)


def test_saved_deck_is_cleaned_up():
    deck = normalize({"format": "poster", "theme": "nope", "seed": -1,
                      "cards": {"top_songs": {"layout": "bogus", "theme": "mint"}, "unknown": {}}})
    assert deck == {"format": "story", "theme": "mix", "seed": 0, "cards": {"top_songs": {"theme": "mint"}}}


def test_period_labels(library):
    def label(start, end):
        tracks = [track(1, "A", plays=1)]
        s = load_snapshot(str(library("s.xml", tracks, start)))
        e = load_snapshot(str(library("e.xml", [track(1, "A", plays=5)], end)))
        return build_data(build_report(e, s), load_art=no_art).period
    assert label(datetime(2024, 12, 28), datetime(2026, 1, 3)) == "2025"
    assert label(datetime(2025, 3, 1), datetime(2025, 9, 1)) == "Mar – Sep 2025"
    assert label(datetime(2024, 6, 1), datetime(2025, 6, 1)) == "Jun 2024 – Jun 2025"


def test_ranking_changes_the_cards(library):
    end = load_snapshot(str(library("e.xml", [
        track(1, "Frequent", plays=10, **{"Total Time": 60_000}),
        track(2, "Epic", plays=2, **{"Total Time": 1_200_000}),
    ])))
    report = build_report(end)
    assert build_data(report, "plays", load_art=no_art).songs[0].title == "Frequent"
    assert build_data(report, "time", load_art=no_art).songs[0].title == "Epic"
    assert build_data(report, load_art=no_art).minutes == 50


def test_cover_theme_uses_the_artwork():
    red = cover_theme(Image.new("RGB", (64, 64), (220, 30, 40)))
    assert red.id == "cover" and red.bg != THEMES["midnight"].bg
    assert cover_theme(None).bg == THEMES["midnight"].bg


def test_catalog_lists_layouts_and_themes():
    info = catalog()
    assert {f["id"] for f in info["formats"]} == {"story", "square"}
    assert {"mix", "cover", "midnight", "paper"} <= {t["id"] for t in info["themes"]}
    assert all(c["layouts"] for c in info["cards"])


def test_timeline_cards_render(sample_data):
    import random
    from dataclasses import replace

    from tunesback.stats.plays import Listen, timeline

    rnd = random.Random(1)
    start = datetime(2025, 1, 1)
    listens = sorted((Listen(int(start.timestamp()) + rnd.randrange(365 * 86400), 200_000, rnd.choice("ABCDE"), "S")
                      for _ in range(2000)), key=lambda l: l.at)
    data = replace(sample_data, timeline=timeline(listens, start, datetime(2026, 1, 1),
                                                  {"a": 0, "b": int(datetime(2025, 6, 1).timestamp())}, 0))
    types = {c.type for c in plan(data)}
    assert {"clock", "months", "streak", "discoveries"} <= types
    for card in ("clock", "months", "streak", "discoveries"):
        for layout in CARD_TYPES[card].layouts:
            for theme in THEMES:
                for fmt in ("story", "square"):
                    draw(CardChoice(card, layout, theme), data, fmt, scale=0.2)
