"""Turn snapshots (cumulative counters) into listening activity for a period."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from ..model import Snapshot, Track


@dataclass(frozen=True, slots=True)
class TrackActivity:
    """What happened to one track during the period."""

    track: Track
    plays: int
    skips: int
    is_new: bool  # not in the library at the start of the period

    @property
    def ms(self) -> int:
        return self.plays * self.track.duration_ms


class _StartIndex:
    """Looks up a track's state at the start of the period.

    Persistent IDs are authoritative. When a library is rebuilt they change, so
    fall back to name/artist/album, but only when that key is unambiguous.
    """

    def __init__(self, snapshot: Snapshot):
        self.by_id: dict[str, Track] = {}
        by_key: dict[tuple, list[Track]] = defaultdict(list)
        for t in snapshot.tracks:
            if t.persistent_id:
                self.by_id[t.persistent_id] = t
            by_key[t.match_key].append(t)
        self.by_key = {k: v[0] for k, v in by_key.items() if len(v) == 1}

    def find(self, track: Track) -> Optional[Track]:
        if track.persistent_id and track.persistent_id in self.by_id:
            return self.by_id[track.persistent_id]
        return self.by_key.get(track.match_key)


def period_activity(end: Snapshot, start: Optional[Snapshot] = None) -> list[TrackActivity]:
    """Plays and skips per track between two snapshots.

    Without a start snapshot the period is "all time up to `end`". Counters that
    went down (a reset or re-import) count as zero rather than negative.
    """
    index = _StartIndex(start) if start else None
    activity = []
    for track in end.tracks:
        before = index.find(track) if index else None
        plays = track.play_count - (before.play_count if before else 0)
        skips = track.skip_count - (before.skip_count if before else 0)
        plays, skips = max(plays, 0), max(skips, 0)
        if not plays and not skips:
            continue

        is_new = False
        if start is not None and before is None and plays:
            # Not found at the start. If the library says it was added before
            # the start snapshot, it is an existing track we failed to match.
            is_new = track.date_added is None or track.date_added > start.date
        activity.append(TrackActivity(track=track, plays=plays, skips=skips, is_new=is_new))
    return activity
