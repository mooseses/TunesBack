"""The card types and their layouts.

A card type is what a card says (your top songs); a layout is one way of
arranging it. Layout modules register themselves with `@layout(...)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .data import CardData
    from .layouts.base import Ctx


@dataclass
class Layout:
    id: str
    name: str
    draw: Callable[["Ctx"], None]


@dataclass
class CardType:
    id: str
    name: str
    applies: Callable[["CardData"], bool]
    layouts: dict[str, Layout] = field(default_factory=dict)


CARD_TYPES: dict[str, CardType] = {}


def card_type(id: str, name: str, applies: Callable[["CardData"], bool]) -> None:
    CARD_TYPES[id] = CardType(id, name, applies)


# The deck, in the order the cards are shown. Timeline cards need plays with
# timestamps, which counter-based libraries (iTunes) don't have.
card_type("top_songs", "Top songs", lambda d: bool(d.songs))
card_type("top_song", "#1 song", lambda d: bool(d.songs))
card_type("top_albums", "Top albums", lambda d: bool(d.albums))
card_type("top_artists", "Top artists", lambda d: bool(d.artists))
card_type("genres", "Top genres", lambda d: bool(d.genres))
card_type("minutes", "Minutes listened", lambda d: d.total_ms > 0)
card_type("clock", "Listening clock", lambda d: bool(d.timeline and d.timeline.get("total")))
card_type("months", "Year in months", lambda d: bool(d.timeline and len(d.timeline.get("months", [])) >= 2))
card_type("streak", "Streak", lambda d: bool(d.timeline and (d.timeline.get("longest_streak") or {}).get("days", 0) >= 2))
card_type("discoveries", "Discoveries", lambda d: bool(d.timeline and (d.timeline.get("discoveries") or {}).get("artists")))
card_type("listening_age", "Listening age", lambda d: d.listening_age is not None)
card_type("summary", "Summary", lambda d: bool(d.songs))


def layout(card: str, id: str, name: str) -> Callable[[Callable[["Ctx"], None]], Callable[["Ctx"], None]]:
    def register(draw: Callable[["Ctx"], None]) -> Callable[["Ctx"], None]:
        CARD_TYPES[card].layouts[id] = Layout(id, name, draw)
        return draw
    return register
