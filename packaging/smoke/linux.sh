#!/usr/bin/env bash
# Smoke test for the packaged Linux app.
# Starts it on a virtual display with a window manager, drives the custom title
# bar with real X input and reports what happened. Fails only if the app
# crashes or never shows a window.
#
# usage: linux.sh PATH/TO/tunesback [true|false]   (needs Xvfb, openbox, xdotool, ImageMagick)
set -u
EXE=$1
SCREENSHOTS=${2:-false}
WORK=$(mktemp -d)
export DISPLAY=:99
export XDG_CONFIG_HOME=$WORK/config XDG_CACHE_HOME=$WORK/cache XDG_DATA_HOME=$WORK/data XDG_STATE_HOME=$WORK/state
# Fresh profile, so the app opens on its first-run set-up.
mkdir -p "$XDG_CONFIG_HOME/TunesBack"
echo '{"debug_logging": true, "theme": "dark"}' > "$XDG_CONFIG_HOME/TunesBack/settings.json"

Xvfb :99 -screen 0 1600x1000x24 >/dev/null 2>&1 &
XVFB=$!
sleep 1
openbox >/dev/null 2>&1 &
WM=$!
sleep 1

shot() {
  [ "$SCREENSHOTS" = "true" ] || return 0
  import -window root -resize 50% -quality 60 "$WORK/$1.jpg"
  base64 -w 4000 "$WORK/$1.jpg" | sed "s/^/SHOT $1 /"
  echo "SHOT $1 END"
}
geom() { xdotool getwindowgeometry --shell "$WID" | tr '\n' ' '; echo; }
show_log() {
  local file
  file=$(find "$WORK" -name tunesback.log | head -1)
  [ -n "$file" ] && { echo "--- app log ---"; tail -n 40 "$file"; }
}

"$EXE" > "$WORK/stdout.txt" 2>&1 &
APP=$!
WID=""
for _ in $(seq 1 120); do
  kill -0 $APP 2>/dev/null || break
  WID=$(xdotool search --name '^TunesBack$' 2>/dev/null | tail -1)
  [ -n "$WID" ] && break
  sleep 0.5
done
if [ -z "$WID" ]; then
  echo "FAIL: no window"
  cat "$WORK/stdout.txt"
  show_log
  kill $WM $XVFB 2>/dev/null
  exit 1
fi

sleep 10
echo "start    $(geom)"; shot start
eval "$(xdotool getwindowgeometry --shell "$WID")"
# Drag the title bar from an empty spot.
xdotool mousemove $((X + 700)) $((Y + 19)) mousedown 1; sleep 0.3
for _ in 1 2 3 4 5 6 7 8 9 10; do xdotool mousemove_relative -- 8 5; sleep 0.05; done
xdotool mouseup 1; sleep 1
echo "dragged  $(geom)"
eval "$(xdotool getwindowgeometry --shell "$WID")"
# Resize from the bottom-right corner.
xdotool mousemove $((X + WIDTH - 3)) $((Y + HEIGHT - 3)) mousedown 1; sleep 0.3
for _ in 1 2 3 4 5 6 7 8 9 10; do xdotool mousemove_relative -- -10 -6; sleep 0.05; done
xdotool mouseup 1; sleep 1
echo "resized  $(geom)"
eval "$(xdotool getwindowgeometry --shell "$WID")"
# Open the File menu in the title bar, then close it.
xdotool mousemove $((X + 152)) $((Y + 19)) click 1; sleep 0.8; shot menu
xdotool key Escape; sleep 0.4
# Double-click the title bar to maximise.
xdotool mousemove $((X + 700)) $((Y + 19)) click --repeat 2 --delay 120 1; sleep 1.5
echo "dblclick $(geom)"; shot maximized
eval "$(xdotool getwindowgeometry --shell "$WID")"
xdotool mousemove $((X + WIDTH - 23)) $((Y + 19)) click 1
for _ in $(seq 1 16); do kill -0 $APP 2>/dev/null || break; sleep 0.5; done
if kill -0 $APP 2>/dev/null; then echo "closed by close button: False"; kill $APP; else echo "closed by close button: True"; fi
show_log
kill $WM $XVFB 2>/dev/null
exit 0
