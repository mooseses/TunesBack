"""Last.fm: every scrobble, from user.getRecentTracks.

Reading someone's scrobbles needs only their user name and an API key (free,
from https://www.last.fm/api/account/create). Builds can ship a key; without
one, set-up asks for it.
"""
from __future__ import annotations

import os
import time
from typing import Iterator, Optional

from .http import Client
from .plays import Play, SourceError

API = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 200  # the most Last.fm returns per page
KEY_URL = "https://www.last.fm/api/account/create"
_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"  # Last.fm's grey "no artwork" star
_RETRY_CODES = {8, 11, 16, 29}  # operation failed, offline, temporarily unavailable, rate limited


def bundled_key() -> Optional[str]:
    """An API key that came with this copy of TunesBack, if any."""
    key = os.environ.get("TUNESBACK_LASTFM_API_KEY")
    if key:
        return key.strip()
    try:
        from .. import _build  # written by the release build
        return getattr(_build, "LASTFM_API_KEY", None) or None
    except ImportError:
        return None


class LastFm:
    def __init__(self, username: str, api_key: str, base_url: Optional[str] = None, stop=lambda: False):
        self.username = username.strip()
        self.api_key = api_key.strip()
        self.client = Client(base_url or API, "Last.fm", min_interval=0.25, stop=stop)

    def call(self, method: str, **params) -> dict:
        status, body = self.client.get("", {"method": method, "api_key": self.api_key, "format": "json", **params},
                                       retry_if=lambda s, b: isinstance(b, dict) and b.get("error") in _RETRY_CODES)
        if isinstance(body, dict) and "error" in body:
            raise SourceError(self._message(body.get("error"), body.get("message")))
        if status != 200 or not isinstance(body, dict):
            raise SourceError(f"Last.fm sent an unexpected answer (error {status}).")
        return body

    def _message(self, code, text) -> str:
        if code == 6:
            return f"There's no Last.fm user called “{self.username}”."
        if code in (10, 26):
            return "Last.fm didn't accept that API key. Check it was copied completely."
        if code == 17:
            return (f"{self.username} keeps their listening history private. Turn off “Hide recent listening "
                    "information” in Last.fm's privacy settings, then try again.")
        return f"Last.fm said: {text or 'something went wrong'} (error {code})."

    def check(self) -> dict:
        """The account's name, scrobble count and sign-up time; raises SourceError if it can't be read."""
        user = self.call("user.getInfo", user=self.username).get("user", {})
        # Private profiles still show their info, so also read one page of scrobbles.
        self.call("user.getRecentTracks", user=self.username, limit=1)
        return {"name": user.get("name") or self.username, "plays": int(user.get("playcount") or 0),
                "registered": int((user.get("registered") or {}).get("unixtime") or 0) or None}

    def _pages(self, **bounds) -> Iterator[list[Play]]:
        page, pages = 1, 1
        while page <= pages:
            body = self.call("user.getRecentTracks", user=self.username, limit=PAGE_SIZE, page=page,
                             extended=1, **bounds)
            recent = body.get("recenttracks") or {}
            attr = recent.get("@attr") or {}
            pages = int(attr.get("totalPages") or 0)
            tracks = recent.get("track") or []
            if isinstance(tracks, dict):  # a single scrobble comes back without the list
                tracks = [tracks]
            plays = [p for p in map(_play, tracks) if p is not None]
            if plays:
                yield plays
            page += 1

    def newer(self, after: int) -> Iterator[list[Play]]:
        # A fixed upper bound keeps the pages from shifting while new scrobbles arrive.
        yield from self._pages(**{"from": after + 1, "to": int(time.time())})

    def older(self, before: Optional[int]) -> Iterator[list[Play]]:
        yield from self._pages(to=before if before is not None else int(time.time()))


def _text(value) -> str:
    if isinstance(value, dict):
        return value.get("#text") or value.get("name") or ""
    return value or ""


def _play(track: dict) -> Optional[Play]:
    if not isinstance(track, dict) or (track.get("@attr") or {}).get("nowplaying"):
        return None
    when = (track.get("date") or {}).get("uts")
    if not when:
        return None
    art = None
    for image in track.get("image") or []:
        url = image.get("#text") if isinstance(image, dict) else None
        if url and _PLACEHOLDER not in url:
            art = url  # the list goes from small to large; keep the largest
    return Play.make(track.get("name"), _text(track.get("artist")), _text(track.get("album")), int(when), art_url=art)
