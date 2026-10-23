# PyInstaller spec for TunesBack. Build from the repository root:
#   pyinstaller packaging/tunesback.spec
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
ICON_PNG = str(ROOT / "tunesback" / "assets" / "icon.png")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "tunesback" / "assets"), "tunesback/assets"),
        (str(ROOT / "tunesback" / "web"), "tunesback/web"),
    ],
    hiddenimports=collect_submodules("tunesback"),
    excludes=["tkinter", "numpy", "pandas", "matplotlib"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tunesback",
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico") if sys.platform == "win32" else ICON_PNG,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TunesBack")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="TunesBack.app",
        icon=ICON_PNG,
        bundle_identifier="io.github.mooseses.tunesback",
        version=VERSION,
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": VERSION},
    )
