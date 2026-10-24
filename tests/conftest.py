import plistlib
from datetime import datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_LIBRARY = FIXTURES / "Test Library.xml"


def track(track_id, name, artist="Artist", album="Album", plays=0, skips=0, **extra):
    attrs = {
        "Track ID": track_id,
        "Name": name,
        "Artist": artist,
        "Album": album,
        "Total Time": 180_000,
        "Persistent ID": f"PID{track_id:04d}",
        "Kind": "MPEG audio file",
    }
    if plays:
        attrs["Play Count"] = plays
    if skips:
        attrs["Skip Count"] = skips
    attrs.update(extra)
    return attrs


def write_library(path: Path, tracks: list[dict], date: datetime | None = datetime(2025, 1, 1)) -> Path:
    data = {"Major Version": 1, "Minor Version": 1, "Application Version": "12.13", "Tracks": {}}
    if date:
        data["Date"] = date
    data["Library Persistent ID"] = "LIB0001"
    for t in tracks:
        data["Tracks"][str(t["Track ID"])] = t
    with open(path, "wb") as f:
        plistlib.dump(data, f)
    return path


@pytest.fixture
def library(tmp_path):
    """Write a library export: library("name.xml", [tracks], date=...)."""
    def make(name, tracks, date=datetime(2025, 1, 1)):
        return write_library(tmp_path / name, tracks, date)
    return make
