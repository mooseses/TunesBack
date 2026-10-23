"""ListenBrainz: every listen, from its public API (no key needed)."""
from __future__ import annotations

from typing import Iterator, Optional
from urllib.parse import quote

from .http import Client
from .plays import Play, SourceError

API = "https://api.listenbrainz.org/1/"
PAGE_SIZE = 1000  # the most ListenBrainz returns per request


class ListenBrainz:
    def __init__(self, username: str, base_url: Optional[str] = None, stop=lambda: False):
        self.username = username.strip()
        self.client = Client(base_url or API, "ListenBrainz", min_interval=0.2, stop=stop)

    def _get(self, path: str, **params) -> dict:
        status, body = self.client.get(f"user/{quote(self.username, safe='')}/{path}", params)
        if status == 404:
            raise SourceError(f"There's no ListenBrainz user called “{self.username}”.")
        if status != 200 or not isinstance(body, dict):
            message = body.get("error") if isinstance(body, dict) else None
            raise SourceError(f"ListenBrainz said: {message or 'something went wrong'} (error {status}).")
        return body.get("payload") or {}

    def check(self) -> dict:
        count = self._get("listen-count").get("count", 0)
        return {"name": self.username, "plays": int(count or 0), "registered": None}

    def newer(self, after: int) -> Iterator[list[Play]]:
        # With min_ts, ListenBrainz returns the listens right after it: walk forward.
        while True:
            plays = self._batch(min_ts=after)
            if not plays:
                return
            yield plays
            newest = max(p.played_at for p in plays)
            if newest <= after:
                return
            after = newest

    def older(self, before: Optional[int]) -> Iterator[list[Play]]:
        while True:
            # max_ts is exclusive; include the boundary second so nothing at it is missed.
            plays = self._batch(max_ts=before + 1 if before is not None else None)
            if not plays:
                return
            yield plays
            oldest = min(p.played_at for p in plays)
            if before is not None and oldest >= before:
                if len(plays) < PAGE_SIZE:
                    return
                oldest = before - 1  # a whole page within one second: step past it
            before = oldest

    def _batch(self, **bounds) -> list[Play]:
        listens = self._get("listens", count=PAGE_SIZE, **bounds).get("listens") or []
        return [p for p in map(_play, listens) if p is not None]


def _play(listen: dict) -> Optional[Play]:
    if not isinstance(listen, dict) or not listen.get("listened_at"):
        return None
    meta = listen.get("track_metadata") or {}
    info = meta.get("additional_info") or {}
    duration = info.get("duration_ms")
    if not isinstance(duration, int) and isinstance(info.get("duration"), (int, float)):
        duration = int(info["duration"] * 1000)
    mapping = meta.get("mbid_mapping") or {}
    art = None
    if mapping.get("caa_release_mbid") and mapping.get("caa_id"):
        art = f"https://coverartarchive.org/release/{mapping['caa_release_mbid']}/{mapping['caa_id']}-250.jpg"
    return Play.make(meta.get("track_name"), meta.get("artist_name"), meta.get("release_name"),
                     int(listen["listened_at"]), duration_ms=duration if isinstance(duration, int) else None,
                     art_url=art)
