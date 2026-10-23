"""Start TunesBack: a native window if possible, otherwise the default browser."""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

from . import APP_NAME, __version__
from .app.api import Api
from .app.server import AppServer
from .app.settings import Settings, configure_logging

log = logging.getLogger("tunesback")

_BACKGROUNDS = {"light": "#F6F7F9", "dark": "#0F1115"}


def _run_browser(settings: Settings, port: int, open_browser: bool) -> None:
    server = AppServer(Api(settings), port)
    print(f"{APP_NAME} is running at {server.url}  (Ctrl+C to quit)")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _run_window(settings: Settings, debug: bool) -> bool:
    """Returns False if no native webview is available on this system."""
    try:
        import webview
    except ImportError as e:
        log.warning("pywebview is not installed (%s)", e)
        return False

    holder: dict = {}

    def pick_folder() -> str | None:
        dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        result = holder["window"].create_file_dialog(dialog)
        return result[0] if result else None

    server = AppServer(Api(settings, pick_folder=pick_folder))
    server.start_background()
    theme = settings["theme"] if settings["theme"] != "system" else "dark"
    holder["window"] = webview.create_window(
        APP_NAME, server.url, width=1280, height=840, min_size=(980, 660),
        background_color=_BACKGROUNDS[theme], text_select=True,
    )
    try:
        webview.start(debug=debug)
    except Exception as e:  # no GTK/Qt/WebView2 backend on this machine
        log.warning("Could not open a native window: %s", e)
        server.shutdown()
        return False
    server.shutdown()
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tunesback", description="Year-in-review statistics for iTunes and Apple Music.")
    parser.add_argument("--browser", action="store_true", help="open in your web browser instead of a window")
    parser.add_argument("--no-open", action="store_true", help="with --browser: don't open a browser tab")
    parser.add_argument("--port", type=int, default=0, help="with --browser: port to listen on (default: any free port)")
    parser.add_argument("--debug", action="store_true", help="verbose logging and web inspector")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)

    settings = Settings()
    configure_logging(args.debug or settings["debug_logging"])

    if args.browser:
        _run_browser(settings, args.port, not args.no_open)
    elif not _run_window(settings, args.debug):
        print("No native window support found; opening TunesBack in your browser instead.", file=sys.stderr)
        _run_browser(settings, args.port, True)


if __name__ == "__main__":
    main()
