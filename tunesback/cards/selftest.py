"""Render a few cards from made-up data: proves a packaged build can draw cards
(resvg, the bundled fonts, and a system font for other scripts)."""
from __future__ import annotations

import random
from datetime import datetime

from PIL import Image

from .data import CardData, Item
from .deck import CardChoice, draw
from .fonts import FontSpec, bundled_face, runs


def _data() -> CardData:
    songs = [("Midnight City", "M83"), ("群青日和", "東京事変"), ("사랑했나봐", "윤도현"), ("Привет, мир", "Кино"),
             ("A Considerably Longer Song Title That Goes On (2011 Remaster)", "The Extremely Long Named Orchestra")]
    items = [Item(t, a, 300 - i * 40, (300 - i * 40) * 200_000, f"art{i}", 0.3 - i * 0.04) for i, (t, a) in enumerate(songs)]
    rnd = random.Random(1)
    art = {f"art{i}": Image.new("RGB", (300, 300), tuple(rnd.randrange(40, 220) for _ in range(3))) for i in range(5)}
    return CardData(rank_by="plays", period="2025", period_long="1 Jan 2025 – 31 Dec 2025", lifetime=False,
                    songs=items, albums=items, artists=[Item(a, None, i.plays, i.ms) for (t, a), i in zip(songs, items)],
                    genres=[Item("Indie Pop", None, 10, 0, share=0.4)], new_finds=[], total_ms=12_345 * 60_000,
                    total_plays=1234, song_count=500, artist_count=120, album_count=200,
                    listening_age={"age": 34, "era_label": "Mid 00s", "era_start": 2003, "era_end": 2007},
                    load_art=art.get)


def run(path: str) -> int:
    """Draw a strip of cards into `path` (JPEG or PNG). Returns a process exit code."""
    data = _data()
    cards = [draw(CardChoice(t, l, th), data, "story", 0.4) for t, l, th in (
        ("top_songs", "list", "midnight"), ("top_artists", "billboard", "paper"), ("summary", "receipt", "poster"))]
    strip = Image.new("RGB", (sum(c.width for c in cards) + 10 * (len(cards) + 1), cards[0].height + 20), (40, 40, 40))
    for i, card in enumerate(cards):
        strip.paste(card, (10 + i * (card.width + 10), 10))
    strip.save(path, quality=80)
    # Which installed fonts drew what, for checking a platform's fallbacks.
    lines = []
    design = bundled_face(FontSpec("Figtree", 700))
    for item in data.songs:
        for text in (item.title, item.subtitle or ""):
            for face, piece in runs(text, design):
                if face is not design:
                    lines.append(f"{piece!r}: {face.families if face else None} {face.path if face else ''}")
    with open(path + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Drew {len(cards)} cards to {path} at {datetime.now():%H:%M:%S}")
    return 0
