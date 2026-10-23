"""Local HTTP server that serves the interface and the API.

It only listens on 127.0.0.1. Every API request must carry the token baked
into the page, and the Host header must name this server, so other websites
open in a browser cannot drive it.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .api import Api

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = PACKAGE_DIR / "web"
ASSETS_DIR = PACKAGE_DIR / "assets"
TOKEN_HEADER = "X-TunesBack-Token"
MAX_BODY = 1_000_000

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/ttf", ".ttf")


def _static_path(url_path: str) -> Path | None:
    """Map a URL to a file inside the web or assets folders, refusing anything else."""
    if url_path in ("", "/"):
        url_path = "/index.html"
    if url_path.startswith("/assets/"):
        root, relative = ASSETS_DIR, url_path[len("/assets/"):]
    else:
        root, relative = WEB_DIR, url_path.lstrip("/")
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, api: Api, port: int = 0):
        self.api = api
        self.token = secrets.token_urlsafe(24)
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, name="tunesback-server", daemon=True)
        thread.start()
        return thread


class _Handler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)

    # --- helpers ---

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    # --- verbs ---

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
        url = urlsplit(self.path)

        if url.path.startswith("/api/card/"):
            query = parse_qs(url.query)
            if query.get("token", [""])[0] != self.server.token:
                return self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
            try:
                index = int(url.path.rsplit("/", 1)[-1].split(".")[0])
            except ValueError:
                return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
            data = self.server.api.card_jpeg(index)
            if data is None:
                return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
            name = self.server.api.card_filename(index)
            return self._send(HTTPStatus.OK, data, "image/jpeg",
                              {"Content-Disposition": f'attachment; filename="{name}"'})

        path = _static_path(url.path)
        if path is None:
            return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
        body = path.read_bytes()
        if path.name == "index.html":
            body = body.replace(b"__TUNESBACK_TOKEN__", self.server.token.encode())
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, body, content_type)

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        if (not self._host_ok() or not url.path.startswith("/api/")
                or not secrets.compare_digest(self.headers.get(TOKEN_HEADER, ""), self.server.token)):
            return self._json(HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Request too large"})
        try:
            args = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
        if not isinstance(args, dict):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "Arguments must be an object"})
        self._json(HTTPStatus.OK, self.server.api.call(url.path[len("/api/"):], args))
