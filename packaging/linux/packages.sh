#!/usr/bin/env bash
# Packages the PyInstaller build in dist/TunesBack for Linux distributions:
# .deb (Debian, Ubuntu, Mint), .rpm (Fedora, RHEL-likes), .pkg.tar.zst (Arch,
# Manjaro), AppImage and a plain .tar.gz. Run from the repository root after
# `pyinstaller packaging/tunesback.spec`. Needs fpm, rpm, zstd, libarchive-tools,
# ImageMagick and desktop-file-utils; the Flatpak is made separately
# (packaging/linux/io.github.mooseses.tunesback.yml).
#
# usage: packaging/linux/packages.sh OUTPUT_DIR
set -euo pipefail
OUT=$(realpath "${1:-.}")
ID=io.github.mooseses.tunesback
LINUX=packaging/linux
eval "$(python3 -m tunesback.version --shell)"
BASE="TunesBack-Linux-v${V_PEP440}-x86_64"
mkdir -p "$OUT"

desktop-file-validate "$LINUX/$ID.desktop"

# ---------- tarball ----------
tar -C dist -czf "$OUT/$BASE.tar.gz" TunesBack

# ---------- one file tree for deb, rpm and pacman ----------
ROOT=$(mktemp -d)
mkdir -p "$ROOT/opt" "$ROOT/usr/bin" "$ROOT/usr/share/applications" "$ROOT/usr/share/metainfo" \
  "$ROOT/usr/share/licenses/tunesback"
cp -a dist/TunesBack "$ROOT/opt/tunesback"
ln -s /opt/tunesback/tunesback "$ROOT/usr/bin/tunesback"
cp "$LINUX/$ID.desktop" "$ROOT/usr/share/applications/"
cp "$LINUX/$ID.metainfo.xml" "$ROOT/usr/share/metainfo/"
cp LICENSE "$ROOT/usr/share/licenses/tunesback/"
for size in 48 64 128 256 512; do
  dir="$ROOT/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$dir"
  convert packaging/icons/linux.png -resize "${size}x${size}" "$dir/$ID.png"
done

COMMON=(
  -s dir -C "$ROOT" -n tunesback
  --license GPL-3.0-only --vendor "Peter Jin" --maintainer "Peter Jin <noreply@github.com>"
  --url https://github.com/mooseses/TunesBack
  --description "Year-in-review statistics for your music library"
  --after-install "$LINUX/after-install.sh" --after-remove "$LINUX/after-install.sh"
)
# Qt and its web engine come with the app; these are the system libraries they load.
fpm "${COMMON[@]}" -t deb -v "$V_DEB" -a amd64 --category sound -p "$OUT/$BASE.deb" \
  -d libegl1 -d libgl1 -d libxkbcommon-x11-0 -d libxcb-cursor0 -d libxcb-icccm4 -d libxcb-image0 \
  -d libxcb-keysyms1 -d libxcb-randr0 -d libxcb-render-util0 -d libxcb-shape0 -d libxcb-xinerama0 \
  -d libxcb-xkb1 -d libnss3 -d libxcomposite1 -d libxdamage1 -d libxrandr2 -d libxtst6 -d libxkbfile1 \
  -d "libasound2t64 | libasound2" -d libdbus-1-3 \
  -d libwayland-client0 -d libwayland-cursor0 -d libwayland-egl1 -d libwayland-server0 \
  opt usr
fpm "${COMMON[@]}" -t rpm -v "$V_RPM" -a x86_64 --rpm-os linux -p "$OUT/$BASE.rpm" \
  -d mesa-libEGL -d mesa-libGL -d libxkbcommon-x11 -d xcb-util-cursor -d xcb-util-wm -d xcb-util-image \
  -d xcb-util-keysyms -d xcb-util-renderutil -d nss -d libXcomposite -d libXdamage -d libXrandr -d libXtst \
  -d libxkbfile -d alsa-lib -d dbus-libs \
  -d libwayland-client -d libwayland-cursor -d libwayland-egl -d libwayland-server \
  opt usr
fpm "${COMMON[@]}" -t pacman -v "$V_PACMAN" -a x86_64 --pacman-compression zstd -p "$OUT/$BASE.pkg.tar.zst" \
  -d libglvnd -d libxkbcommon-x11 -d xcb-util-cursor -d xcb-util-wm -d xcb-util-image -d xcb-util-keysyms \
  -d xcb-util-renderutil -d nss -d libxcomposite -d libxdamage -d libxrandr -d libxtst -d libxkbfile \
  -d alsa-lib -d dbus -d wayland \
  opt usr

# ---------- AppImage ----------
APPDIR=$(mktemp -d)/AppDir
mkdir -p "$APPDIR"
cp -a dist/TunesBack "$APPDIR/TunesBack"
cp -a "$ROOT/usr" "$APPDIR/usr"
rm "$APPDIR/usr/bin/tunesback"
cp "$LINUX/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp "$LINUX/$ID.desktop" "$APPDIR/"
cp packaging/icons/linux.png "$APPDIR/$ID.png"
cp packaging/icons/linux.png "$APPDIR/.DirIcon"
if [ ! -x appimagetool ]; then
  wget -q -O appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x appimagetool
fi
ARCH=x86_64 ./appimagetool --appimage-extract-and-run "$APPDIR" "$OUT/$BASE.AppImage"
chmod +x "$OUT/$BASE.AppImage"

ls -la "$OUT"
