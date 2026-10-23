"""Version numbers: TunesBack's own (PEP 440, like "2.0.0b1") and GitHub release tags.

Release tags have been written several ways over the years ("1.2.0", "1.2.0-b1",
"1.2.0-RC", "v2.0.0-beta.1"); `parse` reads all of them so they can be compared.
Packages for each platform spell pre-releases their own way (`spellings`).
"""
import re
from typing import NamedTuple, Optional

_PATTERN = re.compile(
    r"^\s*v?(?P<release>\d+(?:\.\d+)*)"
    r"(?:[-_.]?(?P<stage>a|alpha|b|beta|c|rc|pre|preview)[-_.]?(?P<num>\d*))?"
    r"(?:[-_.]?dev[-_.]?(?P<dev>\d*))?\s*$",
    re.IGNORECASE,
)
_STAGES = {"a": "a", "alpha": "a", "b": "b", "beta": "b", "c": "rc", "rc": "rc", "pre": "rc", "preview": "rc"}
_RANK = {"a": 0, "b": 1, "rc": 2}
_NAMES = {"a": "Alpha", "b": "Beta", "rc": "Release Candidate"}


class Version(NamedTuple):
    release: tuple[int, ...]
    stage: Optional[str] = None  # "a", "b" or "rc"; None for a final release
    num: int = 0
    dev: Optional[int] = None

    @property
    def prerelease(self) -> bool:
        return self.stage is not None or self.dev is not None

    def key(self) -> tuple:
        release = self.release + (0,) * (4 - len(self.release))
        if self.stage is not None:
            stage = (_RANK[self.stage], self.num)
        elif self.dev is not None:
            stage = (-1, 0)  # "2.0.0.dev0" comes before 2.0.0's alphas and betas
        else:
            stage = (3, 0)
        return release, stage, -1 if self.dev is None else self.dev

    def __str__(self) -> str:  # PEP 440
        text = ".".join(map(str, self.release))
        if self.stage:
            text += f"{self.stage}{self.num}"
        if self.dev is not None:
            text += f".dev{self.dev}"
        return text

    def display(self) -> str:
        """For people: "2.0.0 Beta 1"."""
        text = ".".join(map(str, self.release))
        if self.stage:
            text += f" {_NAMES[self.stage]}" + (f" {self.num}" if self.num else "")
        if self.dev is not None:
            text += " (development build)"
        return text


def parse(text: str) -> Optional[Version]:
    match = _PATTERN.match(text or "")
    if not match:
        return None
    stage = _STAGES[match["stage"].lower()] if match["stage"] else None
    return Version(
        tuple(int(p) for p in match["release"].split(".")),
        stage,
        int(match["num"] or 0) if stage else 0,
        int(match["dev"] or 0) if match["dev"] is not None else None,
    )


def newer(candidate: Version, current: Version) -> bool:
    return candidate.key() > current.key()


def spellings(text: str) -> dict[str, str]:
    """The same version as each kind of package wants it."""
    v = parse(text)
    if v is None:
        raise ValueError(f"not a version: {text!r}")
    base = ".".join(map(str, v.release))
    word = {"a": "alpha", "b": "beta", "rc": "rc"}.get(v.stage or "", "")
    pre = f"{word}{v.num}" if v.stage else ""
    if v.dev is not None:
        pre += f"dev{v.dev}"
    return {
        "pep440": str(v),
        "display": v.display(),
        "tag": f"v{base}" + (f"-{word}.{v.num}" if v.stage else "") + (f"-dev.{v.dev}" if v.dev is not None else ""),
        "deb": f"{base}~{pre}" if pre else base,  # "~" sorts before the final release
        "rpm": f"{base}~{pre}" if pre else base,
        "pacman": f"{base}{pre}",  # pacman puts "2.0.0beta1" before "2.0.0"
        "windows": ".".join(map(str, (v.release + (0, 0, 0))[:3])) + f".{_RANK.get(v.stage, 3) * 100 + v.num if v.stage else 999}",
        "prerelease": "true" if v.prerelease else "false",
    }


if __name__ == "__main__":
    # python -m tunesback.version [VERSION]: every spelling, as KEY=value lines (for CI).
    import sys
    from . import __version__

    for key, value in spellings(sys.argv[1] if len(sys.argv) > 1 else __version__).items():
        print(f"{key}={value}")
