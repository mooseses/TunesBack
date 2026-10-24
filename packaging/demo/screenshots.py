"""The README and website screenshots, taken from the demo library.

    python packaging/demo/screenshots.py DEMO_DIR OUT_DIR [--chromium PATH]

DEMO_DIR comes from build_demo.py. Sets TunesBack up in a throwaway home with the demo library
and listening history, runs it in browser mode and takes overview-dark, overview-light, charts,
wrapped and age (JPEG, 2x) with Playwright.
"""
import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZE = {"width": 1228, "height": 800}


def seed(demo: Path) -> None:
    """Set up TunesBack (in this process's home) with the demo, as if you'd done it yourself."""
    sys.path.insert(0, str(ROOT))
    from tunesback.app.api import Api
    from tunesback.app.settings import Settings

    api = Api(Settings())
    for action, params in [
        ("add_library", {"path": str(demo / "Library.xml")}),
        *[("import_history", {"path": str(history)}) for history in sorted(demo.glob("Streaming_History_Audio_*.json"))],
        ("update_settings", {"changes": {"setup_done": True, "age_calculated": True, "age_overview": True, "age_cards": True}}),
    ]:
        result = api.call(action, params)
        if isinstance(result, dict) and result.get("error"):
            raise SystemExit(f"{action}: {result['error']}")
    api.store.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def shoot(url: str, out: Path, chromium: str | None) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium) if chromium else await p.chromium.launch()
        context = await browser.new_context(viewport=SIZE, device_scale_factor=2, color_scheme="dark")
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        snap = lambda name: page.screenshot(path=str(out / f"{name}.jpg"), type="jpeg", quality=86)

        await page.goto(url)
        await page.wait_for_selector(".widgets .kpi", timeout=120_000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2500)  # covers fade in
        await snap("overview-dark")
        await page.emulate_media(color_scheme="light")
        await page.wait_for_timeout(800)
        await snap("overview-light")
        await page.emulate_media(color_scheme="dark")

        await page.click(".nav-item[data-view=charts]")
        await page.wait_for_timeout(2500)
        await snap("charts")

        await page.click(".nav-item[data-view=wrapped]")
        await page.wait_for_selector(".card-tile img", timeout=120_000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_function("[...document.querySelectorAll('.card-tile img')].filter((i) => i.getBoundingClientRect().top < innerHeight)"
                                     ".every((i) => i.complete && i.naturalWidth)",
                                     timeout=120_000)
        await page.wait_for_timeout(3000)
        await snap("wrapped")

        await page.click(".nav-item[data-view=age]")
        await page.wait_for_timeout(800)
        button = page.locator("button:has-text('Calculate'), button:has-text('Work it out')").first
        if await button.count():
            await button.click()
            await page.wait_for_timeout(6000)  # the reveal
        await snap("age")
        await browser.close()
        if errors:
            raise SystemExit(f"The page had errors: {errors}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("demo", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--chromium", help="a Chromium to use instead of Playwright's own")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as home:
        # TunesBack gets the throwaway home; Playwright keeps the real one, where its browser is.
        own = {"HOME": home, "XDG_CONFIG_HOME": f"{home}/.config",
               "XDG_CACHE_HOME": f"{home}/.cache", "XDG_DATA_HOME": f"{home}/.local"}
        real = dict(os.environ)
        os.environ.update(own)
        seed(args.demo.resolve())
        os.environ.clear()
        os.environ.update(real)
        port = free_port()
        server = subprocess.Popen([sys.executable, "-m", "tunesback", "--browser", "--no-open", "--port", str(port)],
                                  cwd=ROOT, env={**real, **own})
        try:
            url = f"http://127.0.0.1:{port}/"
            for _ in range(120):
                try:
                    urllib.request.urlopen(url, timeout=1)
                    break
                except OSError:
                    time.sleep(0.25)
            asyncio.run(shoot(url, args.out, args.chromium))
        finally:
            server.terminate()
            server.wait(10)
    print("\n".join(sorted(p.name for p in args.out.glob("*.jpg"))))


if __name__ == "__main__":
    main()
