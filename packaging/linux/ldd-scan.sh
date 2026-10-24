#!/bin/sh
# Lists the shared libraries a TunesBack bundle needs that neither the bundle nor
# this system has, with the bundled file that needs each one. Like the app's own
# launcher, it looks in the bundle's _internal folder first. Doesn't fail: some
# are only used by Qt plugins TunesBack never loads (multimedia, for one).
# usage: ldd-scan.sh BUNDLE_DIR
export LD_LIBRARY_PATH="$1/_internal:$1/_internal/PyQt6/Qt6/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
find "$1" -type f -name '*.so*' | while read -r f; do
  ldd "$f" 2>/dev/null | awk -v f="${f#$1/}" '/not found/ {print "MISSING " $1 "  (needed by " f ")"}'
done | sort -u
exit 0
