"""Fetching JSON from web services: polite (one request at a time, spaced out),
patient with hiccups (retries with backoff) and clear when it gives up."""
from __future__ import annotations

import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from .. import __version__
from .plays import SourceError, Stopped

log = logging.getLogger(__name__)

USER_AGENT = f"TunesBack/{__version__} (+https://github.com/mooseses/TunesBack)"
RETRY_STATUS = {429, 500, 502, 503, 504}


def ssl_context() -> ssl.SSLContext:
    """The system's certificates, plus certifi's when it's installed (packaged
    Python builds don't always find the system ones)."""
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except (ImportError, OSError):
        pass
    return context


class Client:
    def __init__(self, base_url: str, name: str, min_interval: float = 0.25, timeout: float = 25,
                 retries: int = 5, stop: Callable[[], bool] = lambda: False):
        self.base_url = base_url
        self.name = name  # for messages: "Couldn't reach Last.fm"
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.stop = stop
        self._last = 0.0
        self._lock = threading.Lock()
        self._context = ssl_context() if base_url.startswith("https") else None

    def _wait(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stop():
                raise Stopped
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def get(self, path: str, params: Optional[dict] = None,
            retry_if: Callable[[int, object], bool] = lambda status, body: False) -> tuple[int, object]:
        """GET base_url + path. Returns (status, parsed JSON or None). Network errors and
        5xx/429 answers (or ones `retry_if` flags) are retried; then SourceError."""
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = self.base_url + path + ("?" + query if query else "")
        delay = 1.0
        offline = 0
        for attempt in range(self.retries + 1):
            with self._lock:
                self._wait(self._last + self.min_interval - time.monotonic())
                self._last = time.monotonic()
            status, body, wait = self._fetch(url)
            if status is not None and status not in RETRY_STATUS and not retry_if(status, body):
                return status, body
            # No connection at all rarely fixes itself in seconds: give up sooner than on a busy server.
            offline = offline + 1 if status is None else 0
            if attempt == self.retries or offline > 2:
                break
            log.debug("%s: retrying %s (status %s)", self.name, path, status)
            self._wait(max(delay, wait or 0))
            delay = min(delay * 2, 30)
        if status is None:
            raise SourceError(f"Couldn't reach {self.name}. Check your internet connection and try again.")
        raise SourceError(f"{self.name} isn't answering properly right now (error {status}). Try again later.")

    def _fetch(self, url: str) -> tuple[Optional[int], object, Optional[float]]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context) as response:
                return response.status, _json(response.read()), None
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After") or e.headers.get("X-RateLimit-Reset-In")
            try:
                wait = float(retry_after) if retry_after else None
            except ValueError:
                wait = None
            return e.code, _json(e.read()), wait
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            log.info("%s: %s", self.name, e)
            return None, None, None


def _json(data: bytes) -> object:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
