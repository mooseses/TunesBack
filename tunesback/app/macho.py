"""The macOS SDK an executable was built with, read from its Mach-O load commands.

macOS 26 draws an app in Liquid Glass only when its executable was built with
the macOS 26 SDK or later; older ones run in the previous look. CI stamps the
packaged app's launcher (see the build workflow); Python run from source
usually names an older SDK.
"""
from __future__ import annotations

import platform
import struct
import sys
from pathlib import Path
from typing import Optional

LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
CPU_TYPES = {"arm64": 0x0100000C, "x86_64": 0x01000007}


def sdk_version(path: str | Path) -> Optional[tuple[int, int]]:
    """(major, minor) of the SDK the executable names, or None if it can't be read."""
    try:
        data = Path(path).read_bytes()[:1 << 20]
    except OSError:
        return None
    if len(data) < 32:
        return None
    magic = struct.unpack_from(">I", data)[0]
    if magic in (0xCAFEBABE, 0xCAFEBABF):  # universal: use this machine's slice
        wide = magic == 0xCAFEBABF
        count = struct.unpack_from(">I", data, 4)[0]
        want = CPU_TYPES.get(platform.machine())
        size = 32 if wide else 20
        for i in range(min(count, 8)):
            cpu = struct.unpack_from(">i", data, 8 + i * size)[0]
            offset = (struct.unpack_from(">Q", data, 8 + i * size + 8)[0] if wide
                      else struct.unpack_from(">I", data, 8 + i * size + 8)[0])
            if want is None or cpu == want:
                try:
                    data = Path(path).read_bytes()[offset:offset + (1 << 20)]
                except OSError:
                    return None
                break
        else:
            return None
    if struct.unpack_from("<I", data)[0] != 0xFEEDFACF:  # 64-bit, little-endian
        return None
    ncmds = struct.unpack_from("<I", data, 16)[0]
    at = 32
    for _ in range(ncmds):
        if at + 8 > len(data):
            return None
        cmd, size = struct.unpack_from("<II", data, at)
        if cmd == LC_BUILD_VERSION:
            return _unpack(struct.unpack_from("<I", data, at + 16)[0])
        if cmd == LC_VERSION_MIN_MACOSX:
            return _unpack(struct.unpack_from("<I", data, at + 12)[0])
        if size < 8:
            return None
        at += size
    return None


def _unpack(value: int) -> tuple[int, int]:
    return value >> 16, (value >> 8) & 0xFF


def liquid_glass() -> bool:
    """Whether this process draws in Liquid Glass: macOS 26 or later, and built with its SDK."""
    if sys.platform != "darwin":
        return False
    try:
        major = int(platform.mac_ver()[0].split(".")[0])
    except ValueError:
        return False
    sdk = sdk_version(sys.executable)
    return major >= 26 and sdk is not None and sdk[0] >= 26
