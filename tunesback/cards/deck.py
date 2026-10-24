"""Choosing a design for every card, and drawing them.

A deck is described by a small settings dict, saved between sessions:

    {"format": "story", "theme": "mix", "seed": 0,
     "cards": {"top_songs": {"layout": "receipt", "theme": "paper", "hidden": false}}}

Seed 0 is the curated default. Shuffling picks a new seed; the same seed
always gives the same deck, and choices made for a single card win over it.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from PIL import Image

from . import layouts  # noqa: F401  (registers the layouts)
from .canvas import Canvas
from .data import CardData
from .layouts.base import FORMATS, Ctx
from .registry import CARD_TYPES
from .themes import MIX_ROTATION, THEMES, Theme, cover_theme

DEFAULT_DECK = {"format": "story", "theme": "mix", "seed": 0, "cards": {}}
THEME_IDS = ("cover", *THEMES)


@dataclass(frozen=True)
class CardChoice:
    type: str
    layout: str
    theme: str
    hidden: bool = False

    @property
    def key(self) -> str:
        return f"{self.type}.{self.layout}.{self.theme}"


def normalize(deck: Optional[dict]) -> dict:
    """A valid deck from whatever was saved (unknown values fall back to defaults)."""
    deck = dict(deck or {})
    out = dict(DEFAULT_DECK)
    if deck.get("format") in FORMATS:
        out["format"] = deck["format"]
    if deck.get("theme") in (*THEME_IDS, "mix"):
        out["theme"] = deck["theme"]
    if isinstance(deck.get("seed"), int) and deck["seed"] >= 0:
        out["seed"] = deck["seed"]
    cards = {}
    for type_id, choice in (deck.get("cards") or {}).items():
        if type_id not in CARD_TYPES or not isinstance(choice, dict):
            continue
        clean = {}
        if choice.get("layout") in CARD_TYPES[type_id].layouts:
            clean["layout"] = choice["layout"]
        if choice.get("theme") in THEME_IDS:
            clean["theme"] = choice["theme"]
        if choice.get("hidden") is True:
            clean["hidden"] = True
        if clean:
            cards[type_id] = clean
    out["cards"] = cards
    return out


def plan(data: CardData, deck: Optional[dict] = None) -> list[CardChoice]:
    """The cards this data can fill, each with its layout and theme."""
    deck = normalize(deck)
    seed = deck["seed"]
    choices = []
    applicable = [t for t in CARD_TYPES.values() if t.layouts and t.applies(data)]
    # Mix after a shuffle deals the themes out in a shuffled order, so cards next to
    # each other differ and none repeats until every theme has been used.
    dealt = list(THEME_IDS)
    random.Random(f"{seed}:themes").shuffle(dealt)
    for position, card in enumerate(applicable):
        own = deck["cards"].get(card.id, {})
        rng = random.Random(f"{seed}:{card.id}")
        layout_ids = list(card.layouts)
        layout = own.get("layout") or (layout_ids[0] if seed == 0 else rng.choice(layout_ids))
        if own.get("theme"):
            theme = own["theme"]
        elif deck["theme"] != "mix":
            theme = deck["theme"]
        elif seed == 0:
            theme = MIX_ROTATION[position % len(MIX_ROTATION)]
        else:
            theme = dealt[position % len(dealt)]
        choices.append(CardChoice(card.id, layout, theme, bool(own.get("hidden"))))
    return choices


def resolve_theme(theme_id: str, data: CardData) -> Theme:
    if theme_id == "cover":
        return cover_theme(data.top_art)
    return THEMES.get(theme_id, THEMES["midnight"])


def draw(choice: CardChoice, data: CardData, fmt: str = "story", scale: float = 1.0,
         seed: int = 0) -> Image.Image:
    """Render one card."""
    card = CARD_TYPES[choice.type]
    layout = card.layouts.get(choice.layout) or next(iter(card.layouts.values()))
    width, height = FORMATS.get(fmt, FORMATS["story"])
    canvas = Canvas(width, height, detail=scale)
    rng = random.Random(f"{seed}:{choice.type}:{choice.theme}:{fmt}")
    layout.draw(Ctx(canvas, resolve_theme(choice.theme, data), data, rng, fmt))
    return canvas.render(scale)


def catalog() -> dict:
    """Card types, layouts and themes, for the interface."""
    themes = [{"id": "mix", "name": "Mix", "swatch": ["#8C7BFF", "#FF4F9A", "#FFE14D", "#0E9F6E"]},
              {"id": "cover", "name": "Cover", "swatch": None}]
    themes += [{"id": t.id, "name": t.name, "swatch": t.swatch} for t in THEMES.values()]
    return {
        "formats": [{"id": "story", "name": "Story", "size": FORMATS["story"]},
                    {"id": "square", "name": "Square", "size": FORMATS["square"]}],
        "themes": themes,
        "cards": [{"id": c.id, "name": c.name, "layouts": [{"id": l.id, "name": l.name} for l in c.layouts.values()]}
                  for c in CARD_TYPES.values() if c.layouts],
    }
