"""A demo music library for screenshots and the website's cards.

    python packaging/demo/build_demo.py OUT_DIR

Takes the test library (tests/fixtures/Test Library.xml, real songs and albums), gives every
album a folder with its real cover (from Apple's iTunes Search API; albums it can't find keep
TunesBack's placeholder) and an empty file per song, so TunesBack finds the covers the way it
does on your computer. It also writes a year of listening, as a Spotify-style history, so the
recap has listening times. The covers are only used for these pictures and aren't committed.

Writes OUT_DIR/Library.xml, OUT_DIR/Music/..., OUT_DIR/Streaming_History_Audio_2024.json and _2025.json.
"""
import json
import plistlib
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tunesback.sources.itunes_xml import _is_music  # noqa: E402  the same songs TunesBack counts
SOURCE = ROOT / "tests" / "fixtures" / "Test Library.xml"
YEAR = 2025
PLAYS = 3200  # listens in the year


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "Unknown"


def fetch_cover(artist: str, album: str) -> bytes | None:
    """The album's cover from the iTunes Search API, at 600 px; None if it isn't found."""
    query = urllib.parse.urlencode({"term": f"{artist} {album}", "entity": "album", "limit": 5, "media": "music"})
    try:
        with urllib.request.urlopen(f"https://itunes.apple.com/search?{query}", timeout=20) as response:
            results = json.load(response).get("results", [])
    except Exception as e:  # offline, rate limited: the album keeps its placeholder
        print(f"  no cover for {artist} – {album}: {e}", file=sys.stderr)
        return None
    wanted = album.lower().split(" (")[0]
    results.sort(key=lambda r: (wanted not in r.get("collectionName", "").lower(),
                                artist.lower() not in r.get("artistName", "").lower()))
    for result in results:
        url = result.get("artworkUrl100")
        if url:
            try:
                with urllib.request.urlopen(url.replace("100x100bb", "600x600bb"), timeout=20) as response:
                    return response.read()
            except Exception:
                continue
    return None


def main(out: Path) -> None:
    out = out.resolve()  # file URIs need an absolute path
    out.mkdir(parents=True, exist_ok=True)
    music = out / "Music"
    with SOURCE.open("rb") as f:
        library = plistlib.load(f)
    library["Date"] = datetime(YEAR, 12, 31, 20, 0, tzinfo=timezone.utc)

    covers: dict[tuple[str, str], bool] = {}
    songs = []
    for track_id, track in library["Tracks"].items():
        if "Name" not in track or not _is_music(track):
            continue
        artist = track.get("Album Artist") or track.get("Artist") or "Unknown Artist"
        album = track.get("Album") or "Unknown Album"
        folder = music / safe(artist) / safe(album)
        folder.mkdir(parents=True, exist_ok=True)
        song = folder / f"{track_id}.m4a"
        song.touch()
        track["Location"] = song.as_uri()
        key = (artist, album)
        if key not in covers and album != "Unknown Album":
            cover = fetch_cover(artist, album)
            if cover:
                (folder / "cover.jpg").write_bytes(cover)
            covers[key] = bool(cover)
            time.sleep(0.4)  # the iTunes API allows about 20 requests a minute
        songs.append(track)
    with (out / "Library.xml").open("wb") as f:
        plistlib.dump(library, f)
    print(f"{len(songs)} songs, covers for {sum(covers.values())} of {len(covers)} albums")

    # A year of listening: songs you played more in iTunes come up more, with an evening peak,
    # busier weekends and the odd skip. A lighter year before it, with only some of the artists,
    # so the recap has new finds.
    rng = random.Random(YEAR)
    artists = sorted({t.get("Artist") or t.get("Album Artist") or "" for t in songs})
    known = set(rng.sample(artists, int(len(artists) * 0.6)))
    write_history(out, YEAR - 1, [t for t in songs if (t.get("Artist") or t.get("Album Artist") or "") in known],
                  PLAYS // 4, rng)
    write_history(out, YEAR, songs, PLAYS, rng)


def write_history(out: Path, year: int, songs: list, plays: int, rng: random.Random) -> None:
    weights = [max(1, t.get("Play Count", 0)) ** 1.15 for t in songs]
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    hours = [1, 1, 0, 0, 0, 0, 1, 3, 5, 4, 3, 3, 4, 3, 3, 4, 5, 6, 8, 9, 10, 9, 6, 3]
    history = []
    for _ in range(plays):
        track = rng.choices(songs, weights)[0]
        day = start + timedelta(days=rng.randrange(365))
        if day.weekday() >= 5 and rng.random() < 0.3:
            day = start + timedelta(days=rng.randrange(365))
        hour = rng.choices(range(24), hours)[0]
        ended = day + timedelta(hours=hour, minutes=rng.randrange(60), seconds=rng.randrange(60))
        length = int(track.get("Total Time") or 210_000)
        played = length if rng.random() > 0.08 else rng.randrange(4_000, 25_000)
        history.append({
            "ts": ended.strftime("%Y-%m-%dT%H:%M:%SZ"), "platform": "demo", "ms_played": played,
            "master_metadata_track_name": track["Name"],
            "master_metadata_album_artist_name": track.get("Artist") or track.get("Album Artist"),
            "master_metadata_album_album_name": track.get("Album"),
            "spotify_track_uri": f"spotify:track:demo{track['Track ID']}",
            "reason_end": "trackdone" if played == length else "fwdbtn",
        })
    history.sort(key=lambda e: e["ts"])
    (out / f"Streaming_History_Audio_{year}.json").write_text(json.dumps(history))
    print(f"{len(history)} listens in {year}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
