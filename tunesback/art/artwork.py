"""Read album artwork from audio files, with a small thumbnail cache."""
from __future__ import annotations

import base64
import logging
import os
import threading
from io import BytesIO
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


def load_artwork(location: Optional[str]) -> Optional[Image.Image]:
    """Full-size artwork for a library location, or None."""
    path = resolve_location(location)
    if not path:
        return None
    try:
        data = _embedded_art(path)
    except Exception as e:  # unreadable tags: fall back to a cover image next to the file
        log.debug("No readable tags in %s: %s", path, e)
        data = None
    try:
        data = data or _folder_art(path)
        if data:
            image = Image.open(BytesIO(data))
            image.load()
            return image.convert("RGB")
    except Exception as e:  # corrupt tags or images should never break a run
        log.warning("Artwork unreadable for %s: %s", path, e)
    return None


class ThumbnailCache:
    """Thread-safe cache of small JPEG thumbnails as data URIs."""

    def __init__(self, size: int = 160):
        self._size = size
        self._cache: dict[str, Optional[str]] = {}
        self._lock = threading.Lock()

    def get(self, location: str) -> Optional[str]:
        with self._lock:
            if location in self._cache:
                return self._cache[location]
        image = load_artwork(location)
        uri = None
        if image is not None:
            image.thumbnail((self._size, self._size))
            buf = BytesIO()
            image.save(buf, format="JPEG", quality=85)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        with self._lock:
            self._cache[location] = uri
        return uri

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
