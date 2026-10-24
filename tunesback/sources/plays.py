"""Listens from sources that log every play (scrobblers, streaming exports)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..model import clean_text


@dataclass(frozen=True, slots=True)
class Play:
    """One listen."""

    name: str
    artist: str
    album: str
    played_at: int  # when it started, Unix time (UTC)
    ms_played: Optional[int] = None  # how long it was listened to, when known
    skipped: bool = False
    album_artist: Optional[str] = None
    duration_ms: Optional[int] = None  # the track's full length, when known
    art_url: Optional[str] = None

    @classmethod
    def make(cls, name, artist, album, played_at, **kw) -> Optional["Play"]:
        """A Play with cleaned-up text, or None when there's no title or artist."""
        name, artist = clean_text(name), clean_text(artist)
        if not name or not artist:
            return None
        return cls(name, artist, clean_text(album) or "", int(played_at), **kw)


class SourceError(Exception):
    """A problem with a source that the user should see (wrong user name, no connection...)."""


class Stopped(Exception):
    """The user cancelled a sync; what was fetched so far is kept."""


def sync_history(store, source_id: int, newer, older, progress=lambda text: None,
                 stop=lambda: False) -> int:
    """Bring a play source up to date. Returns how many new listens were stored.

    `newer(after)` yields batches of plays newer than `after`; `older(before)`
    yields batches going back in time from `before` (or from now, when None).
    The first sync fetches the whole history, newest first, and remembers how
    far back it got after every batch, so an interrupted import carries on
    where it stopped. Later syncs fetch what's new, then keep going back if
    the history isn't complete yet.
    """
    state = dict((store.source(source_id) or {}).get("options", {}).get("sync", {}))
    new = 0

    def save() -> None:
        store.set_options(source_id, sync=state)

    if state.get("newest") is not None:
        progress("Checking for new listens…")
        newest = state["newest"]
        for batch in newer(state["newest"]):
            if stop():
                raise Stopped
            new += store.add_plays(source_id, batch)
            newest = max(newest, max(p.played_at for p in batch))
            progress(f"{new:,} new listens…")
        # Only now: a catch-up that stopped half way must start over next time.
        state["newest"] = newest
        save()

    if not state.get("complete") or state.get("newest") is None:
        for batch in older(state.get("oldest")):
            if stop():
                raise Stopped
            new += store.add_plays(source_id, batch)
            low, high = min(p.played_at for p in batch), max(p.played_at for p in batch)
            state["oldest"] = low if state.get("oldest") is None else min(state["oldest"], low)
            state["newest"] = high if state.get("newest") is None else max(state["newest"], high)
            save()
            progress(f"{new:,} listens so far, back to {_month(state['oldest'])}…")
        state["complete"] = True
        save()
    return new


def _month(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%B %Y")
