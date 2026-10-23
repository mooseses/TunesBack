"""Read album artwork from audio files, with a small thumbnail cache."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import threading
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


def load_artwork(location: Optional[str], max_size: Optional[int] = None) -> Optional[Image.Image]:
    """Artwork for a library location, or None.

    With `max_size`, JPEGs are decoded at a reduced scale, which is several
    times faster than decoding a large cover and shrinking it afterwards.
    """
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
            image = Image.open(BytesIO(data))
            if max_size:
                image.draft("RGB", (max_size, max_size))
            image.load()
            return image.convert("RGB")
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


def _data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
