"""Read album artwork from audio files, with a small thumbnail cache."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Optional

import mutagen
from PIL import Image

from .locations import resolve_location

log = logging.getLogger(__name__)

_FOLDER_IMAGES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "albumart.jpg")


def _embedded_art(path: str) -> Optional[bytes]:
    audio = mutagen.File(path)
    if audio is None:
        return None
    tags = getattr(audio, "tags", None)
    if tags:
        for key in tags.keys():
            if key.startswith("APIC"):  # MP3 / ID3
                return tags[key].data
            if key == "covr" and tags["covr"]:  # MP4 / AAC / ALAC
                return bytes(tags["covr"][0])
    pictures = getattr(audio, "pictures", None)  # FLAC
    if pictures:
        return pictures[0].data
    return None


def _folder_art(path: str) -> Optional[bytes]:
    folder = os.path.dirname(path)
    try:
        names = {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return None
    for candidate in _FOLDER_IMAGES:
        if candidate in names:
            with open(os.path.join(folder, names[candidate]), "rb") as f:
                return f.read()
    return None


# Covers from online services (Last.fm, the Cover Art Archive) are kept here once downloaded.
REMOTE_CACHE: Optional[Path] = None


def is_remote(location: Optional[str]) -> bool:
    return bool(location) and location.startswith(("https://", "http://"))


def _remote_bytes(url: str) -> Optional[bytes]:
    """A cover image from the web, cached on disk so it's only downloaded once."""
    cached = REMOTE_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img") if REMOTE_CACHE else None
    if cached is not None and cached.exists():
        try:
            return cached.read_bytes()
        except OSError:
            pass
    from ..sources.http import USER_AGENT, ssl_context
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=10, context=ssl_context()) as response:
            data = response.read(5_000_000)
    except (OSError, ValueError) as e:
        log.debug("Couldn't download artwork %s: %s", url, e)
        return None
    if cached is not None:
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        except OSError:
            pass
    return data


def _decode(data: bytes, max_size: Optional[int]) -> Image.Image:
    image = Image.open(BytesIO(data))
    if max_size:
        image.draft("RGB", (max_size, max_size))
    image.load()
    return image.convert("RGB")


def load_artwork(location: Optional[str], max_size: Optional[int] = None) -> Optional[Image.Image]:
    """Artwork for a library location (or a cover's web address), or None.

    With `max_size`, JPEGs are decoded at a reduced scale, which is several
    times faster than decoding a large cover and shrinking it afterwards.
    """
    if is_remote(location):
        data = _remote_bytes(location)
        try:
            return _decode(data, max_size) if data else None
        except Exception as e:
            log.debug("Artwork unreadable at %s: %s", location, e)
            return None
    path = resolve_location(location)
    if not path:
        return None
    return _load_from_path(path, max_size)


def _load_from_path(path: str, max_size: Optional[int]) -> Optional[Image.Image]:
    try:
        data = _embedded_art(path)
    except Exception as e:  # unreadable tags: fall back to a cover image next to the file
        log.debug("No readable tags in %s: %s", path, e)
        data = None
    try:
        data = data or _folder_art(path)
        if data:
            return _decode(data, max_size)
    except Exception as e:  # corrupt tags or images should never break a run
        log.warning("Artwork unreadable for %s: %s", path, e)
    return None


class ThumbnailCache:
    """Small JPEG thumbnails as data URIs, cached in memory and on disk.

    Disk entries are keyed by file path, size and modification time, so a
    changed file gets a fresh thumbnail and the cache never needs clearing.
    """

    _VERSION = 1

    def __init__(self, size: int = 160, cache_dir: Optional[Path] = None, workers: int = 4):
        self._size = size
        self._dir = cache_dir
        self._memory: dict[str, Optional[str]] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="artwork")
        if cache_dir is not None:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log.warning("Thumbnail cache disabled: %s", e)
                self._dir = None

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()

    def get(self, location: str) -> Optional[str]:
        with self._lock:
            if location in self._memory:
                return self._memory[location]
        uri = self._load(location)
        with self._lock:
            self._memory[location] = uri
        return uri

    def get_many(self, locations: list[str]) -> dict[str, Optional[str]]:
        """Thumbnails for several locations, decoded in parallel."""
        return dict(zip(locations, self._pool.map(self.get, locations)))

    def _disk_path(self, path: str) -> Optional[Path]:
        if self._dir is None:
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = f"{self._VERSION}|{self._size}|{path}|{st.st_size}|{st.st_mtime_ns}"
        return self._dir / (hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest() + ".jpg")

    def _load(self, location: str) -> Optional[str]:
        if is_remote(location):
            image = load_artwork(location, self._size * 2)
            return _thumbnail_uri(image, self._size) if image else None
        path = resolve_location(location)
        if not path:
            return None
        disk = self._disk_path(path)
        if disk is not None:
            try:
                return _data_uri(disk.read_bytes())
            except OSError:
                pass
        image = _load_from_path(path, self._size * 2)
        if image is None:
            return None
        image.thumbnail((self._size, self._size))
        buf = BytesIO()
        image.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
        if disk is not None:
            try:
                disk.write_bytes(data)
            except OSError as e:
                log.debug("Could not cache thumbnail: %s", e)
        return _data_uri(data)


def _thumbnail_uri(image: Image.Image, size: int) -> str:
    image.thumbnail((size, size))
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return _data_uri(buf.getvalue())


def _data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
