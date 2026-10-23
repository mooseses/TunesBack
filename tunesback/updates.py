"""Checking GitHub releases for a newer TunesBack.

Betas see newer betas and releases; releases see only releases, unless you ask
for betas. The download offered is the one for this computer: the right Mac
architecture, the Windows installer, or the same kind of Linux package.
"""
import logging
import os
import platform
import sys
from pathlib import Path
from typing import Optional

from . import REPOSITORY, __version__
from .sources import http
from .version import newer, parse

log = logging.getLogger(__name__)

API = "https://api.github.com"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
NOTES_LIMIT = 4000


def install_kind() -> Optional[str]:
    """How this copy was installed, as the file ending of its download. None when run from source."""
    if not getattr(sys, "frozen", False):
        return None
    system = platform.system()
    if system == "Darwin":
        return "arm64.dmg" if platform.machine() == "arm64" else "x86_64.dmg"
    if system == "Windows":
        return "x64.exe"
    if os.environ.get("APPIMAGE"):
        return ".AppImage"
    if Path("/.flatpak-info").exists():
        return ".flatpak"
    if Path(sys.executable).resolve().is_relative_to("/opt/tunesback"):
        family = _os_family()
        return {"debian": ".deb", "fedora": ".rpm", "arch": ".pkg.tar.zst"}.get(family, ".tar.gz")
    return ".tar.gz"


def _os_family() -> str:
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return ""
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    names = " ".join(fields.get(k, "").strip('"').lower() for k in ("ID", "ID_LIKE")).split()
    for family, members in (("debian", {"debian", "ubuntu"}), ("fedora", {"fedora", "rhel", "centos", "suse", "opensuse"}),
                            ("arch", {"arch", "archlinux", "manjaro", "endeavouros"})):
        if members & set(names):
            return family
    return ""


def check(current: str = __version__, betas: Optional[bool] = None,
          client: Optional[http.Client] = None) -> dict:
    """The newest release worth offering. Raises SourceError when GitHub can't be reached.

    Returns {"current", "available": bool, and when available "version", "tag", "url",
    "download", "published", "notes", "prerelease"}.
    """
    mine = parse(current)
    if betas is None:
        betas = bool(mine and mine.prerelease)
    client = client or http.Client(API, "GitHub", retries=1, timeout=15)
    status, body = client.get(f"/repos/{REPOSITORY}/releases", {"per_page": 30})
    if status != 200 or not isinstance(body, list):
        raise http.SourceError(f"GitHub didn't list TunesBack's releases (error {status}). Try again later.")
    best, best_version = None, None
    for release in body:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        version = parse(release.get("tag_name") or "") or parse(release.get("name") or "")
        if version is None or (version.prerelease and not betas):
            continue
        if best_version is None or newer(version, best_version):
            best, best_version = release, version
    result = {"current": mine.display() if mine else current, "available": False}
    if best is None or mine is None or not newer(best_version, mine):
        return result
    kind = install_kind()
    download = next((a.get("browser_download_url") for a in best.get("assets") or []
                     if kind and str(a.get("name", "")).endswith(kind)), None)
    notes = (best.get("body") or "").replace("\r\n", "\n").strip()
    return {
        **result,
        "available": True,
        "version": best_version.display(),
        "tag": best.get("tag_name"),
        "url": best.get("html_url") or RELEASES,
        "download": download,
        "published": best.get("published_at"),
        "notes": notes[:NOTES_LIMIT] + ("…" if len(notes) > NOTES_LIMIT else ""),
        "prerelease": best_version.prerelease,
    }

