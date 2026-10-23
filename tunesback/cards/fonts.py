"""Fonts for the cards: the bundled ones, measuring text, and fallbacks.

Cards are drawn with the fonts in assets/fonts. Song titles can be in any
script, so characters those fonts don't have are drawn with a system font
that has them. Finding one means reading the character map of installed
fonts, which is done once, and only when such a character shows up.
"""
from __future__ import annotations

import bisect
import logging
import os
import platform
import struct
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import ImageFont

log = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
# Text is measured at this size and scaled, so one font object serves every size.
_REF_SIZE = 256


# ---------- reading font files ----------

def _tables(data: bytes, offset: int) -> dict[str, tuple[int, int]]:
    count = struct.unpack_from(">H", data, offset + 4)[0]
    tables = {}
    for i in range(count):
        tag, _checksum, start, length = struct.unpack_from(">4sIII", data, offset + 12 + 16 * i)
        tables[tag.decode("latin-1")] = (start, length)
    return tables


def _face_offsets(data: bytes) -> list[int]:
    """Where each face starts: one for a .ttf/.otf, several for a .ttc collection."""
    if data[:4] == b"ttcf":
        count = struct.unpack_from(">I", data, 8)[0]
        return list(struct.unpack_from(f">{count}I", data, 12))
    return [0]


def _cmap_ranges(data: bytes, tables: dict) -> list[tuple[int, int]]:
    """Code point ranges the face has glyphs for (format 4 and 12 subtables)."""
    if "cmap" not in tables:
        return []
    base = tables["cmap"][0]
    count = struct.unpack_from(">H", data, base + 2)[0]
    subtables = {}
    for i in range(count):
        pid, eid, off = struct.unpack_from(">HHI", data, base + 4 + 8 * i)
        subtables[(pid, eid)] = base + off
    for key in ((3, 10), (0, 6), (0, 4), (3, 1), (0, 3), (0, 2), (0, 1), (0, 0)):
        if key not in subtables:
            continue
        at = subtables[key]
        fmt = struct.unpack_from(">H", data, at)[0]
        if fmt == 12:
            groups = struct.unpack_from(">I", data, at + 12)[0]
            return [struct.unpack_from(">II", data, at + 16 + 12 * g) for g in range(groups)]
        if fmt == 4:
            segs = struct.unpack_from(">H", data, at + 6)[0] // 2
            ends = struct.unpack_from(f">{segs}H", data, at + 14)
            starts = struct.unpack_from(f">{segs}H", data, at + 16 + 2 * segs)
            return [(s, e) for s, e in zip(starts, ends) if s != 0xFFFF]
    return []


def _names(data: bytes, tables: dict) -> tuple[Optional[str], int, bool]:
    """(family, weight, italic) as font renderers look them up."""
    family = None
    if "name" in tables:
        base = tables["name"][0]
        _fmt, count, strings = struct.unpack_from(">HHH", data, base)
        found = {}
        for i in range(count):
            pid, eid, _lang, nid, length, off = struct.unpack_from(">6H", data, base + 6 + 12 * i)
            if nid == 1 and pid in (0, 3) and nid not in found:
                raw = data[base + strings + off: base + strings + off + length]
                try:
                    found[nid] = raw.decode("utf-16-be")
                except UnicodeDecodeError:
                    continue
        family = found.get(1)
    weight, italic = 400, False
    if "OS/2" in tables:
        base = tables["OS/2"][0]
        weight = struct.unpack_from(">H", data, base + 4)[0] or 400
        italic = bool(struct.unpack_from(">H", data, base + 62)[0] & 1)
    return family, weight, italic


@dataclass
class Face:
    """One font face in a file (a .ttc collection holds several)."""

    path: str
    index: int
    family: str
    weight: int
    italic: bool
    ranges: list[tuple[int, int]]

    def __post_init__(self) -> None:
        self._starts = [r[0] for r in self.ranges]

    def covers(self, char: str) -> bool:
        cp = ord(char)
        i = bisect.bisect_right(self._starts, cp) - 1
        return i >= 0 and self.ranges[i][0] <= cp <= self.ranges[i][1]


def read_faces(path: str) -> list[Face]:
    """Every face in a font file. Unreadable files give an empty list."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        faces = []
        for index, offset in enumerate(_face_offsets(data)):
            tables = _tables(data, offset)
            family, weight, italic = _names(data, tables)
            if family:
                faces.append(Face(path, index, family, weight, italic, sorted(_cmap_ranges(data, tables))))
        return faces
    except (OSError, struct.error, ValueError, IndexError):
        return []


# ---------- bundled fonts ----------

@dataclass(frozen=True)
class FontSpec:
    """A font as designs ask for it: a family and a weight."""

    family: str
    weight: int = 400
    italic: bool = False


@lru_cache(maxsize=None)
def _bundled() -> tuple[Face, ...]:
    faces = []
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        faces.extend(read_faces(str(path)))
    return tuple(faces)


def _family_root(face: Face) -> str:
    """"Figtree ExtraBold" -> "Figtree": the files name each weight as its own family."""
    for suffix in (" Thin", " ExtraLight", " Light", " Medium", " SemiBold", " ExtraBold", " Black"):
        if face.family.endswith(suffix):
            return face.family[: -len(suffix)]
    return face.family


def bundled_face(spec: FontSpec) -> Face:
    """The bundled face closest to `spec` (same family, nearest weight)."""
    faces = [f for f in _bundled() if _family_root(f) == spec.family] or [f for f in _bundled() if _family_root(f) == "Figtree"]
    return min(faces, key=lambda f: (f.italic != spec.italic, abs(f.weight - spec.weight)))


@lru_cache(maxsize=None)
def bundled_files() -> frozenset[str]:
    return frozenset(f.path for f in _bundled())


# ---------- fallback fonts for other scripts ----------

# Fonts that read well next to the bundled ones, in order of preference. Matched
# against lower-cased file names; anything else installed is tried after these.
_PREFERRED = (
    "notosans-regular", "notosanscjk", "notosansjp", "notosanskr", "notosanssc", "notosanstc", "notosans",
    "sourcehansans", "segoeui.ttf", "yugothm", "yugothr", "msyh.", "msjh.", "malgun.", "meiryo", "hiragino",
    "pingfang", "applesdgothicneo", "arial unicode", "arialuni", "dejavusans.ttf", "wqy-zenhei", "droidsansfallback",
    "nirmala", "tahoma", "geezapro", "kohinoor", "thonburi", "seguisym", "seguiemj", "notocoloremoji",
    "apple color emoji",
)
_AVOID = ("bold", "italic", "oblique", "light", "thin", "black", "heavy", "condensed", "narrow", "mono", "serif",
          "unifont", "lastresort")


def _font_dirs() -> list[Path]:
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
        return dirs
    if system == "Darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts",
                Path("/System/Library/AssetsV2")]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".local" / "share" / "fonts",
            home / ".fonts"]


def _rank(path: str) -> tuple[int, int, str]:
    name = os.path.basename(path).lower()
    preferred = next((i for i, p in enumerate(_PREFERRED) if p in name), len(_PREFERRED))
    avoid = sum(word in name for word in _AVOID)
    return (avoid, preferred, name)


class _Fallbacks:
    """Finds an installed font for characters the bundled fonts don't have."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: Optional[list[str]] = None
        self._faces: dict[str, list[Face]] = {}
        self._by_char: dict[str, Optional[Face]] = {}

    def _candidates(self) -> list[str]:
        if self._files is None:
            found = []
            for root in _font_dirs():
                for dirpath, _dirs, files in os.walk(root):
                    found.extend(os.path.join(dirpath, f) for f in files
                                 if f.lower().endswith((".ttf", ".otf", ".ttc")))
            self._files = sorted(found, key=_rank)
        return self._files

    def face_for(self, char: str) -> Optional[Face]:
        with self._lock:
            if char not in self._by_char:
                self._by_char[char] = self._search(char)
            return self._by_char[char]

    def _search(self, char: str) -> Optional[Face]:
        for path in self._candidates():
            if path not in self._faces:
                self._faces[path] = read_faces(path)
            for face in self._faces[path]:
                if face.covers(char):
                    log.debug("Using %s for U+%04X", face.family, ord(char))
                    return face
        return None


FALLBACKS = _Fallbacks()


# ---------- measuring ----------

@lru_cache(maxsize=64)
def _pil_font(path: str, index: int) -> Optional[ImageFont.FreeTypeFont]:
    try:
        return ImageFont.truetype(path, _REF_SIZE, index=index)
    except OSError:
        return None  # e.g. bitmap-only colour emoji fonts


def _ignorable(char: str) -> bool:
    return unicodedata.category(char) in ("Mn", "Me", "Cf")


def runs(text: str, face: Face) -> list[tuple[Optional[Face], str]]:
    """Split text into pieces drawn by the same face (the design's, or a fallback)."""
    pieces: list[tuple[Optional[Face], str]] = []
    for char in text:
        if face.covers(char) or char.isspace() or _ignorable(char):
            chosen: Optional[Face] = face
        else:
            chosen = FALLBACKS.face_for(char)
        if pieces and (pieces[-1][0] is chosen or _ignorable(char)):
            pieces[-1] = (pieces[-1][0], pieces[-1][1] + char)
        else:
            pieces.append((chosen, char))
    return pieces


def text_width(text: str, spec: FontSpec, size: float, letter_spacing: float = 0.0) -> float:
    """Width of one line of text, in pixels at `size`."""
    face = bundled_face(spec)
    width = 0.0
    for piece_face, piece in runs(text, face):
        font = _pil_font(piece_face.path, piece_face.index) if piece_face else None
        if font is None:
            # No font has it (or it's a bitmap emoji font): assume a square glyph.
            width += _REF_SIZE * sum(0 if _ignorable(c) else 1.1 for c in piece)
        else:
            width += font.getlength(piece)
    return width * size / _REF_SIZE + letter_spacing * size * max(len(text) - 1, 0)


@lru_cache(maxsize=None)
def vertical_metrics(spec: FontSpec) -> tuple[float, float, float]:
    """(ascent, descent, cap height) as fractions of the font size."""
    face = bundled_face(spec)
    font = _pil_font(face.path, face.index)
    ascent, descent = font.getmetrics()
    cap_top = font.getbbox("H", anchor="ls")[1]  # negative: above the baseline
    return ascent / _REF_SIZE, descent / _REF_SIZE, -cap_top / _REF_SIZE



