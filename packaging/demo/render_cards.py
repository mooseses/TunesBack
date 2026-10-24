"""Every Wrapped card design, drawn from the demo library, for the website's card browser.

    python packaging/demo/render_cards.py DEMO_DIR OUT_DIR

DEMO_DIR comes from build_demo.py. Writes OUT_DIR/<card>-<layout>-<theme>.webp (story format,
540 x 960) and OUT_DIR/cards.json describing them, in the order the app shows them.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from tunesback.app.api import Api  # noqa: E402
from tunesback.app.settings import Settings  # noqa: E402
from tunesback.cards import catalog  # noqa: E402


def recap(demo: Path, home: Path) -> Api:
    api = Api(Settings(home / "settings.json"), thumbnail_dir=home / "thumbs", store_path=home / "library.sqlite")
    api.call("add_library", {"path": str(demo / "Library.xml")})
    for history in sorted(demo.glob("Streaming_History_Audio_*.json")):
        api.call("import_history", {"path": str(history)})
    api.call("update_settings", {"changes": {"age_calculated": True, "age_overview": True, "age_cards": True}})
    result = api.call("analyze", {"period": {"start": "2025-01-01", "end": "2025-12-31"}, "combine": "same"})
    if result.get("error"):
        raise SystemExit(result["error"])
    return api


def main(demo: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as home:
        api = recap(demo, Path(home))
        options = catalog()
        themes = [t for t in options["themes"] if t["id"] != "mix"]
        cards = []
        for card in options["cards"]:
            layouts = []
            for layout in card["layouts"]:
                drawn = 0
                for theme in themes:
                    jpeg = api.card_image(card["id"], layout["id"], theme["id"], "story", "preview")
                    if jpeg is None:  # this recap has nothing for the card
                        break
                    Image.open(io.BytesIO(jpeg)).save(out / f"{card['id']}-{layout['id']}-{theme['id']}.webp",
                                                      "WEBP", quality=78, method=6)
                    drawn += 1
                if drawn:
                    layouts.append({"id": layout["id"], "name": layout["name"]})
            if layouts:
                cards.append({"id": card["id"], "name": card["name"], "layouts": layouts})
        manifest = {"cards": cards, "themes": [{"id": t["id"], "name": t["name"], "swatch": t["swatch"]} for t in themes]}
        (out / "cards.json").write_text(json.dumps(manifest, indent=1))
        images = sum(len(c["layouts"]) for c in cards) * len(themes)
        size = sum(p.stat().st_size for p in out.glob("*.webp"))
        print(f"{len(cards)} cards, {images} images, {size / 1e6:.1f} MB")
        api.store.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
