#!/bin/sh
# Lists the shared libraries a TunesBack bundle needs that this system doesn't have,
# with the bundled file that needs each one. Doesn't fail: some are only used by
# Qt plugins TunesBack never loads (printing, for one).
# usage: ldd-scan.sh BUNDLE_DIR
find "$1" -type f -name '*.so*' | while read -r f; do
  ldd "$f" 2>/dev/null | awk -v f="${f#$1/}" '/not found/ {print "MISSING " $1 "  (needed by " f ")"}'
done | sort -u
exit 0
