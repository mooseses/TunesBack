"""Make the platform icons from tunesback/assets/icon.png (a full-bleed rounded square).

    python packaging/make_icons.py

The app's own pages use the full-bleed icon. Desktops expect padding around it:
macOS draws icons on Apple's grid (an 824 px body on a 1024 px canvas, with a soft
shadow), and Windows and Linux icons leave a little room too. Without it TunesBack
looks bigger than every other app in the Dock, taskbar and launcher.
"""
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tunesback" / "assets" / "icon.png"
OUT = ROOT / "packaging" / "icons"


def padded(source: Image.Image, canvas: int, body: int, shadow: bool) -> Image.Image:
    art = source.resize((body, body), Image.LANCZOS)
    offset = (canvas - body) // 2
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    if shadow:
        # Apple's template: black at 30%, 10 px down, 10 px blur (at 1024 px).
        scale = canvas / 1024
        alpha = art.getchannel("A").point(lambda a: a * 0.3)
        layer = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        layer.paste(Image.new("RGBA", art.size, (0, 0, 0, 255)), (offset, offset + round(10 * scale)), alpha)
        out = Image.alpha_composite(out, layer.filter(ImageFilter.GaussianBlur(10 * scale)))
    out.alpha_composite(art, (offset, offset))
    return out


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    OUT.mkdir(exist_ok=True)
    padded(source, 1024, 824, shadow=True).save(OUT / "macos.png")
    # Linux (hicolor) and Windows: the body fills about 88% of the square.
    linux = padded(source, 512, 452, shadow=False)
    linux.save(OUT / "linux.png")
    windows = padded(source, 256, 232, shadow=False)
    windows.save(ROOT / "packaging" / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                                                         (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
