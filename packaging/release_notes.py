"""Print a release's notes: its section of CHANGELOG.md, then what to download.

    python packaging/release_notes.py 2.0.0b1
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tunesback.version import parse  # noqa: E402

DOWNLOADS = """
### Which file do I need?

| | |
|---|---|
| Windows 10/11 | `TunesBack-Windows-v{v}-x64.exe` (installer) or `-portable.zip` |
| Mac with Apple silicon (M1 and later) | `TunesBack-macOS-v{v}-arm64.dmg` |
| Mac with an Intel processor | `TunesBack-macOS-v{v}-x86_64.dmg` |
| Debian, Ubuntu, Mint | `TunesBack-Linux-v{v}-x86_64.deb` |
| Fedora and other RPM distributions | `TunesBack-Linux-v{v}-x86_64.rpm` |
| Arch, Manjaro | `TunesBack-Linux-v{v}-x86_64.pkg.tar.zst` |
| Any Linux | `.flatpak`, `.AppImage` or `.tar.gz` |

macOS: the first time, you may need **System Settings → Privacy & Security → Open Anyway**. Checksums are in `SHA256SUMS.txt`.
"""


def notes(version: str, changelog: str) -> str:
    wanted = parse(version)
    sections = re.split(r"^## ", changelog, flags=re.M)[1:]
    for section in sections:
        heading, _, body = section.partition("\n")
        if parse(heading.strip()) == wanted:
            return body.strip() + "\n" + DOWNLOADS.format(v=str(wanted))
    raise SystemExit(f"CHANGELOG.md has no section for {version}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    print(notes(sys.argv[1], (root / "CHANGELOG.md").read_text(encoding="utf-8")))
