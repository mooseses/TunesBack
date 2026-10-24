"""Promotional images for social media, made from the real app: its fonts, icon, service logos,
the screenshots in docs/screenshots and Wrapped cards drawn from the demo library.

    python packaging/demo/promo.py DEMO_DIR SCREENSHOTS_DIR OUT_DIR [--chromium PATH]

Writes OUT_DIR/<name>.png at the sizes social sites use: square 1080 x 1080, portrait 1080 x 1350
(Instagram, Reddit), landscape 1200 x 675 (X, Bluesky, Mastodon, link previews), story 1080 x 1920.
"""
import argparse
import asyncio
import functools
import http.server
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from render_cards import recap  # noqa: E402

SITE = "mooseses.github.io/TunesBack"

# The cards the images use: (file name, card, layout, theme).
CARDS = [
    ("songs", "top_songs", "list", "midnight"),
    ("song", "top_song", "vinyl", "sunset"),
    ("albums", "top_albums", "grid", "sunset"),
    ("artists", "top_artists", "billboard", "poster"),
    ("minutes", "minutes", "big", "neon"),
    ("genres", "genres", "bars", "mint"),
    ("age", "listening_age", "era", "paper"),
    ("summary", "summary", "classic", "midnight"),
]

STYLE = """
@font-face { font-family: Figtree; font-weight: 400; src: url(fonts/Figtree-Regular.ttf); }
@font-face { font-family: Figtree; font-weight: 600; src: url(fonts/Figtree-SemiBold.ttf); }
@font-face { font-family: Figtree; font-weight: 700; src: url(fonts/Figtree-Bold.ttf); }
@font-face { font-family: Figtree; font-weight: 800; src: url(fonts/Figtree-ExtraBold.ttf); }
:root { --accent: #ff4d6d; --violet: #7b61ff; --text: #eef0f4; --muted: #a2abba; --border: #2a2f3a; --surface: #171a21; }
* { box-sizing: border-box; margin: 0; }
html, body { width: 100%; height: 100%; overflow: hidden; }
body {
  position: relative; color: var(--text); font-family: Figtree, sans-serif; -webkit-font-smoothing: antialiased;
  background:
    radial-gradient(70% 55% at 8% -5%, rgba(255, 77, 109, 0.30), transparent 70%),
    radial-gradient(65% 60% at 108% 45%, rgba(123, 97, 255, 0.26), transparent 70%),
    radial-gradient(60% 45% at -10% 105%, rgba(255, 77, 109, 0.18), transparent 70%),
    #0c0e12;
}
.brand { display: flex; align-items: center; gap: 14px; font-weight: 800; font-size: 30px; letter-spacing: -0.01em; }
.brand img { width: 52px; height: 52px; border-radius: 12px; }
h1 { font-weight: 800; letter-spacing: -0.035em; line-height: 1.02; }
h1 em { font-style: normal; color: var(--accent); }
.lead { color: var(--muted); font-weight: 600; line-height: 1.35; }
.pill { display: inline-flex; align-items: center; gap: 10px; padding: 12px 22px; border-radius: 999px;
  background: var(--accent); color: #1a0b10; font-weight: 800; font-size: 24px; }
.tag { display: inline-flex; padding: 8px 16px; border-radius: 999px; border: 1.5px solid rgba(255,255,255,0.18);
  color: var(--text); font-weight: 700; font-size: 20px; background: #1b1e26; box-shadow: 0 10px 30px rgba(0,0,0,0.45); }
.shot { border-radius: 18px; box-shadow: 0 40px 120px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.08); }
.card { position: absolute; border-radius: 18px; box-shadow: 0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.06); }
.foot { position: absolute; display: flex; align-items: center; justify-content: space-between; color: var(--muted); font-weight: 700; }
.logo-tile { display: flex; align-items: center; gap: 18px; padding: 18px 22px; border-radius: 18px;
  border: 1.5px solid var(--border); background: rgba(23, 26, 33, 0.85); }
.logo-tile b { display: block; font-size: 24px; }
.logo-tile small { display: block; color: var(--muted); font-size: 17px; font-weight: 600; }
.brand-icon svg { display: block; border-radius: 25%; }
.brand-spotify svg { border-radius: 50%; }
"""

BRAND = '<div class="brand"><img src="icon.png" alt="">TunesBack</div>'


def fan(names, width, centre_x, top, spread, tilt, drop):
    """Cards fanned out from the middle: the first name in front."""
    height = width * 16 / 9
    n = len(names)
    order = sorted(range(n), key=lambda i: -abs(i - (n - 1) / 2))  # outer cards first, so the middle is on top
    html = []
    for i in order:
        offset = i - (n - 1) / 2
        left = centre_x - width / 2 + offset * spread
        y = top + abs(offset) * drop
        scale = 1 - abs(offset) * 0.06
        html.append(f'<img class="card" src="cards/{names[i]}.jpg" style="left:{left}px;top:{y}px;width:{width}px;'
                    f'height:{height}px;transform:rotate({offset * tilt}deg) scale({scale})">')
    return "".join(html)


PAGES = {
    # The launch post: what it is, in one look.
    "launch-square": ((1080, 1080), f"""
      <div style="position:absolute;left:72px;top:68px">{BRAND}</div>
      <h1 style="position:absolute;left:72px;top:160px;width:900px;font-size:92px">Your music year,<br>from <em>your own</em> library.</h1>
      <p class="lead" style="position:absolute;left:72px;top:392px;width:820px;font-size:30px">Stats and Wrapped cards for iTunes, Apple Music, Last.fm, ListenBrainz and Spotify.</p>
      <img class="shot" src="shots/overview-dark.jpg" style="position:absolute;left:150px;top:520px;width:1100px;transform:rotate(-4deg)">
      <div style="position:absolute;left:72px;bottom:60px;display:flex;gap:12px;align-items:center">
        <span class="pill" style="box-shadow:0 10px 30px rgba(0,0,0,0.45)">TunesBack 2.0 Beta</span><span class="tag">Free</span><span class="tag">Mac · Windows · Linux</span></div>
    """),
    # Wrapped cards, fanned out.
    "cards-portrait": ((1080, 1350), f"""
      <div style="position:absolute;left:72px;top:68px">{BRAND}</div>
      <h1 style="position:absolute;left:72px;top:150px;width:940px;font-size:86px">Wrapped,<br>for the music <em>you own</em>.</h1>
      <p class="lead" style="position:absolute;left:72px;top:352px;width:900px;font-size:30px">Story and square cards in every layout and nine themes. Shuffle, and every card gets its own look.</p>
      {fan(["albums", "songs", "song", "artists", "minutes"], 330, 540, 520, 175, 7, 46)}
      <div class="foot" style="left:72px;right:72px;bottom:52px;font-size:24px"><span>Free for Mac, Windows and Linux</span><span>{SITE}</span></div>
    """),
    # Sources, with their real logos.
    "sources-landscape": ((1200, 675), f"""
      <div style="position:absolute;left:64px;top:56px">{BRAND}</div>
      <h1 style="position:absolute;left:64px;top:140px;width:560px;font-size:60px">Works with the music apps you <em>already use</em>.</h1>
      <p class="lead" style="position:absolute;left:64px;top:370px;width:520px;font-size:24px">Use one, or several at once: TunesBack matches the same song across them, so a listen never counts twice.</p>
      <div style="position:absolute;left:64px;bottom:52px;color:var(--muted);font-weight:700;font-size:20px">{SITE}</div>
      <div style="position:absolute;right:64px;top:118px;width:470px;display:grid;gap:16px">
        <div class="logo-tile" data-brand="itunes"><span class="logo"></span><span><b>iTunes / Apple Music</b><small>Your library, on your computer</small></span></div>
        <div class="logo-tile" data-brand="lastfm"><span class="logo"></span><span><b>Last.fm</b><small>Every scrobble, with when you played it</small></span></div>
        <div class="logo-tile" data-brand="listenbrainz"><span class="logo"></span><span><b>ListenBrainz</b><small>Every listen, just your user name</small></span></div>
        <div class="logo-tile" data-brand="spotify"><span class="logo"></span><span><b>Spotify</b><small>The listening history you download</small></span></div>
      </div>
    """),
    # Listening age.
    "age-portrait": ((1080, 1350), f"""
      <div style="position:absolute;left:72px;top:68px">{BRAND}</div>
      <h1 style="position:absolute;left:72px;top:150px;width:940px;font-size:86px">Find out which <em>era</em><br>your music comes from.</h1>
      <p class="lead" style="position:absolute;left:72px;top:352px;width:880px;font-size:30px">Listening Age looks at the release years you play most, and shows its working with your own numbers.</p>
      <img class="shot" src="shots/age.jpg" style="position:absolute;left:72px;top:490px;width:980px">
      <img class="card" src="cards/age.jpg" style="left:680px;top:560px;width:330px;height:586.7px;transform:rotate(5deg)">
      <div class="foot" style="left:72px;right:72px;bottom:52px;font-size:24px"><span>Free for Mac, Windows and Linux</span><span>{SITE}</span></div>
    """),
    # The Overview.
    "overview-landscape": ((1200, 675), f"""
      <div style="position:absolute;left:64px;top:56px">{BRAND}</div>
      <h1 style="position:absolute;left:64px;top:140px;width:440px;font-size:58px">Your year at a glance, <em>your way</em>.</h1>
      <p class="lead" style="position:absolute;left:64px;top:360px;width:420px;font-size:23px">Top artists, songs and albums, when you listen, streaks and new finds, in tiles you arrange yourself.</p>
      <div style="position:absolute;left:64px;bottom:52px;color:var(--muted);font-weight:700;font-size:20px">{SITE}</div>
      <img class="shot" src="shots/overview-light.jpg" style="position:absolute;left:540px;top:70px;width:900px">
    """),
    # A story (Instagram, TikTok).
    "story": ((1080, 1920), f"""
      <div style="position:absolute;left:0;right:0;top:110px;display:flex;justify-content:center">{BRAND}</div>
      <h1 style="position:absolute;left:60px;right:60px;top:230px;text-align:center;font-size:104px">Your music year,<br>from <em>your own</em><br>library.</h1>
      <p class="lead" style="position:absolute;left:110px;right:110px;top:600px;text-align:center;font-size:34px">Stats and Wrapped cards for iTunes, Apple Music, Last.fm, ListenBrainz and Spotify.</p>
      {fan(["genres", "songs", "song", "artists", "summary"], 380, 540, 820, 190, 7, 52)}
      <div style="position:absolute;left:0;right:0;bottom:150px;display:flex;flex-direction:column;align-items:center;gap:22px">
        <span class="pill" style="font-size:30px;padding:16px 30px">Free · Mac · Windows · Linux</span>
        <span style="color:var(--muted);font-weight:700;font-size:30px">{SITE}</span></div>
    """),
}


def page(body: str) -> str:
    return f"""<!doctype html><meta charset="utf-8"><style>{STYLE}</style><body>{body}
<script type="module">
  import {{ brandIcon }} from "./brands.js";
  for (const tile of document.querySelectorAll("[data-brand]")) tile.querySelector(".logo").append(brandIcon(tile.dataset.brand, 56));
</script>"""


def gather(demo: Path, shots: Path, work: Path) -> None:
    """Fonts, icon, logos, screenshots and freshly drawn cards, side by side in `work`."""
    (work / "fonts").mkdir()
    for font in (ROOT / "tunesback/assets/fonts").glob("Figtree-*.ttf"):
        shutil.copy(font, work / "fonts")
    shutil.copy(ROOT / "tunesback/assets/icon.png", work)
    shutil.copy(ROOT / "tunesback/web/js/brands.js", work)
    shutil.copytree(shots, work / "shots")
    (work / "cards").mkdir()
    with tempfile.TemporaryDirectory() as home:
        api = recap(demo, Path(home))
        for name, card, layout, theme in CARDS:
            jpeg = api.card_image(card, layout, theme, "story", "full")
            if jpeg is None:
                raise SystemExit(f"The demo recap has no {card} card")
            (work / "cards" / f"{name}.jpg").write_bytes(jpeg)
        api.store.close()


async def shoot(url: str, out: Path, chromium: str | None) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium) if chromium else await p.chromium.launch()
        for name, ((width, height), _) in PAGES.items():
            page_ = await browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page_.on("pageerror", lambda e: errors.append(str(e)))
            await page_.goto(f"{url}/{name}.html")
            await page_.wait_for_load_state("networkidle")
            await page_.evaluate("document.fonts.ready")
            await page_.screenshot(path=str(out / f"{name}.png"))
            await page_.close()
            if errors:
                raise SystemExit(f"{name}: {errors}")
        await browser.close()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("demo", type=Path)
    parser.add_argument("shots", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--chromium", help="a Chromium to use instead of Playwright's own")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        gather(args.demo.resolve(), args.shots.resolve(), work)
        for name, (_, body) in PAGES.items():
            (work / f"{name}.html").write_text(page(body))
        handler = functools.partial(Quiet, directory=str(work))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            asyncio.run(shoot(f"http://127.0.0.1:{server.server_port}", args.out, args.chromium))
        finally:
            server.shutdown()
    print("\n".join(sorted(p.name for p in args.out.glob("*.png"))))


if __name__ == "__main__":
    main()
