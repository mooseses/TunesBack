"""Map the file:// URIs stored in a library to paths on this machine.

Libraries often point at network shares, and each OS mounts those somewhere
different, so for remote files we try every plausible mount point.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterator, Optional

log = logging.getLogger(__name__)

SYSTEM = platform.system()


@dataclass(frozen=True, slots=True)
class FileUri:
    host: Optional[str]  # None for local files
    path: str  # decoded, with "/" separators

    @property
    def parts(self) -> list[str]:
        return [p for p in self.path.split("/") if p]


def parse_file_uri(uri: str) -> Optional[FileUri]:
    """Split a library location into host and decoded path.

    The URI must still be percent-encoded: decoding first would turn "%23" into
    "#" and lose everything after it. iTunes on Windows writes network files as
    "file://localhost//server/share/...", so a "//" path also names a host.
    """
    if not uri:
        return None
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme and parsed.scheme != "file":
        return None
    host = parsed.netloc or None
    path = urllib.parse.unquote(parsed.path)
    if host and host.lower() == "localhost":
        host = None
    if host is None and path.startswith("//"):
        server, _, rest = path[2:].partition("/")
        host, path = server or None, "/" + rest
    return FileUri(host=host, path=path)


def _local_path(uri: FileUri) -> str:
    if SYSTEM == "Windows":
        # "/C:/Music/x.mp3" -> "C:\Music\x.mp3"
        path = uri.path[1:] if re.match(r"^/[A-Za-z]:", uri.path) else uri.path
        return path.replace("/", "\\")
    return uri.path


def _windows_candidates(uri: FileUri) -> Iterator[str]:
    yield "\\\\" + uri.host + "\\" + "\\".join(uri.parts)


def _linux_candidates(uri: FileUri) -> Iterator[str]:
    parts = uri.parts
    if not parts:
        return
    share, rest = parts[0], parts[1:]
    share_l = share.casefold()
    runtime = f"/run/user/{os.getuid()}"

    def under(base: str) -> str:
        return os.path.join(base, *rest)

    # GNOME / GVFS: /run/user/<uid>/gvfs/smb-share:server=host,share=name
    gvfs = os.path.join(runtime, "gvfs")
    for mount in _listdir(gvfs):
        decoded = urllib.parse.unquote(mount).casefold()
        if mount.startswith("smb-share:") and f"share={share_l}" in decoded:
            yield under(os.path.join(gvfs, mount))
    yield under(os.path.join(gvfs, f"smb-share:server={uri.host.lower()},share={share_l}"))

    # Legacy GVFS location
    yield under(os.path.expanduser(f"~/.gvfs/{share} on {uri.host}"))

    # KDE / kio-fuse: /run/user/<uid>/kio-fuse-XXXX/smb/<host>/<share>
    for entry in _listdir(runtime):
        if not entry.startswith("kio-fuse-"):
            continue
        smb = os.path.join(runtime, entry, "smb")
        for host in _listdir(smb):
            for mounted_share in _listdir(os.path.join(smb, host)):
                if mounted_share.casefold() == share_l:
                    yield under(os.path.join(smb, host, mounted_share))

    # Manual mounts
    user = os.environ.get("USER", "")
    for base in ("/mnt", "/media", f"/media/{user}", f"/run/media/{user}"):
        yield os.path.join(base, *parts)


def _macos_candidates(uri: FileUri) -> Iterator[str]:
    parts = uri.parts
    if not parts:
        return
    yield os.path.join("/Volumes", *parts)
    if len(parts) > 1:
        yield os.path.join("/Volumes", *parts[1:])
    # Finder adds "-1" etc. when two shares have the same name.
    for volume in _listdir("/Volumes"):
        if volume.startswith(parts[0]):
            yield os.path.join("/Volumes", volume, *parts[1:])


def _listdir(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def resolve_location(uri: Optional[str]) -> Optional[str]:
    """Return an existing local path for a library location, or None."""
    parsed = parse_file_uri(uri) if uri else None
    if parsed is None:
        return None

    if parsed.host is None:
        local = _local_path(parsed)
        candidates: Iterator[str] = iter([local])
        if SYSTEM == "Darwin" and local.startswith("/") and not os.path.exists(local):
            candidates = iter([local, *_macos_candidates(parsed)])
    elif SYSTEM == "Windows":
        candidates = _windows_candidates(parsed)
    elif SYSTEM == "Darwin":
        candidates = _macos_candidates(parsed)
    else:
        candidates = _linux_candidates(parsed)

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    log.debug("No local file for %s", uri)
    return None
