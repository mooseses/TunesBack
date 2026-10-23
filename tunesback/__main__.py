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
        from .app.window import DesktopWindow, preferred_gui, prepare_qt_sandbox
    except ImportError as e:
        log.warning("pywebview is not installed (%s)", e)
        return False

    gui = preferred_gui()
    if gui == "qt":
        prepare_qt_sandbox()
    api = Api(settings)
    server = AppServer(api)
    server.start_background()
    api.window = DesktopWindow(server.url, settings["title_bar"], settings["theme"],
                               native_sidebar=settings["native_sidebar"], mica=settings["mica"],
                               sidebar_hidden=settings["sidebar_hidden"])
    try:
        webview.start(debug=debug, gui=gui)
    except Exception as e:  # no GTK/Qt/WebView2 backend on this machine
        log.warning("Could not open a native window: %s", e)
        server.shutdown()
        return False
    server.shutdown()
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tunesback", description="Year-in-review statistics for your music library.")
    parser.add_argument("--browser", action="store_true", help="open in your web browser instead of a window")
    parser.add_argument("--no-open", action="store_true", help="with --browser: don't open a browser tab")
    parser.add_argument("--port", type=int, default=0, help="with --browser: port to listen on (default: any free port)")
    parser.add_argument("--debug", action="store_true", help="verbose logging and web inspector")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--selftest", metavar="IMAGE", help=argparse.SUPPRESS)  # draw sample cards (used by CI)
    # Set up with this iTunes library and exit, so the next start opens on a recap (used by CI).
    parser.add_argument("--add-library", metavar="XML", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.selftest:
        from .cards.selftest import run
        sys.exit(run(args.selftest))

    settings = Settings()
    configure_logging(args.debug or settings["debug_logging"])
    if args.add_library:
        result = Api(settings).call("add_library", {"path": args.add_library, "location": "local"})
        print(result.get("error") or f"Added {result['tracks']} songs from {args.add_library}")
        sys.exit(1 if result.get("error") else 0)

    if args.browser:
        _run_browser(settings, args.port, not args.no_open)
    elif not _run_window(settings, args.debug):
        print("No native window support found; opening TunesBack in your browser instead.", file=sys.stderr)
        _run_browser(settings, args.port, True)


if __name__ == "__main__":
    main()
