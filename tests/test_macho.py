"""Reading the SDK version from a Mach-O executable (for Liquid Glass on macOS)."""
import struct

from tunesback.app import macho


def thin(sdk: int, cmd: int = macho.LC_BUILD_VERSION) -> bytes:
    other = struct.pack("<II", 0x19, 72) + b"\0" * 64  # an LC_SEGMENT_64 first
    if cmd == macho.LC_BUILD_VERSION:
        version = struct.pack("<IIIIII", cmd, 24, 1, 0x000B0000, sdk, 0)
    else:
        version = struct.pack("<IIII", cmd, 16, 0x000B0000, sdk)
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 2, len(other) + len(version), 0, 0)
    return header + other + version


def test_sdk_version(tmp_path):
    new, old, legacy, junk = (tmp_path / n for n in ("new", "old", "legacy", "junk"))
    new.write_bytes(thin(0x001A0500))  # 26.5
    old.write_bytes(thin(0x000C0100))  # 12.1
    legacy.write_bytes(thin(0x000A0F00, macho.LC_VERSION_MIN_MACOSX))  # 10.15
    junk.write_bytes(b"#!/bin/sh\necho hi\n" * 4)
    assert macho.sdk_version(new) == (26, 5)
    assert macho.sdk_version(old) == (12, 1)
    assert macho.sdk_version(legacy) == (10, 15)
    assert macho.sdk_version(junk) is None and macho.sdk_version(tmp_path / "missing") is None


def test_no_liquid_glass_off_macos():
    assert macho.liquid_glass() is False
