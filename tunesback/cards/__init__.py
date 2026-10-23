"""Shareable "Wrapped" cards."""
from __future__ import annotations

from typing import Callable, Optional

from PIL import Image

from ..art.artwork import load_artwork
from ..stats.report import RankBy, Report
from .designs import generate_card_stack, save_card_stack

__all__ = ["build_context", "render_cards", "save_card_stack"]


def build_context(report: Report, rank_by: RankBy = "plays",
                  artwork: Callable[[Optional[str]], Optional[Image.Image]] = load_artwork) -> dict:
    """Everything the card designs need, independent of any UI state."""
    cache: dict[Optional[str], Optional[Image.Image]] = {}

    def art(location: Optional[str]) -> Optional[Image.Image]:
        if location not in cache:
            cache[location] = artwork(location) if location else None
        return cache[location]

    def minutes(ms: int) -> int:
        return int(ms // 60000)

    songs = report.top("songs", rank_by, 5)
    albums = report.top("albums", rank_by, 5)
    artists = report.top("artists", rank_by, 5)
    context = {
        "top_songs": [{"name": e.title, "sub": e.subtitle or "", "image": art(e.art), "count": e.plays} for e in songs],
        "top_albums": [{"name": e.title, "sub": e.subtitle or "", "image": art(e.art), "minutes": minutes(e.ms)} for e in albums],
        "top_artists_list": [{"name": e.title, "image": None} for e in artists],
        "genres": [e.title for e in report.top("genres", rank_by, 10)],
        "total_minutes": minutes(report.total_ms),
        "year_label": str(report.end_date.year),
        "age_data": None,
    }
    if report.listening_age:
        context["age_data"] = {"age": report.listening_age.age, "era_label": report.listening_age.era_label}
    if artists:
        top = artists[0]
        context["top_artist"] = {"name": top.title, "minutes": minutes(top.ms), "image": art(top.art)}
    return context


def render_cards(report: Report, rank_by: RankBy = "plays", **kwargs) -> list[Image.Image]:
    return generate_card_stack(build_context(report, rank_by, **kwargs))
