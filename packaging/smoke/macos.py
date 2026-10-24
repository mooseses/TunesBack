"""Smoke test for the packaged macOS app.

Starts it on its first-run set-up, drives the title bar with real mouse events
and reports what happened; then sets it up with a library and starts it again
on the main window. Fails if the app crashes, never shows a window, or can't be
dragged by its title bar.

usage: python macos.py PATH/TO/TunesBack.app/Contents/MacOS/tunesback FIXTURES_DIR [true|false]
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import Quartz

exe, fixtures = sys.argv[1], sys.argv[2]
screenshots = len(sys.argv) > 3 and sys.argv[3] == "true"

config = Path.home() / "Library" / "Application Support" / "TunesBack"
config.mkdir(parents=True, exist_ok=True)
# Fresh profile, so the app opens on its first-run set-up.
(config / "settings.json").write_text(json.dumps({"debug_logging": True, "theme": "dark"}))
log = Path.home() / "Library" / "Logs" / "TunesBack" / "tunesback.log"


def window_bounds():
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    for w in windows:
        if w.get("kCGWindowOwnerPID") == proc.pid and w.get("kCGWindowLayer") == 0:
            b = w["kCGWindowBounds"]
            return int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])
    return None


def post(kind, x, y, clicks=1, delta=(0, 0)):
    event = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, clicks)
    # Window dragging follows the deltas carried by each event, not just positions.
    Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventDeltaX, int(delta[0]))
    Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventDeltaY, int(delta[1]))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def drag(x, y, dx, dy):
    post(Quartz.kCGEventMouseMoved, x, y); time.sleep(0.2)
    post(Quartz.kCGEventLeftMouseDown, x, y); time.sleep(0.2)
    for i in range(1, 11):
        post(Quartz.kCGEventLeftMouseDragged, x + dx * i / 10, y + dy * i / 10, delta=(dx / 10, dy / 10)); time.sleep(0.04)
    post(Quartz.kCGEventLeftMouseUp, x + dx, y + dy); time.sleep(0.8)


def click(x, y, clicks=1):
    post(Quartz.kCGEventMouseMoved, x, y); time.sleep(0.15)
    for n in range(1, clicks + 1):
        post(Quartz.kCGEventLeftMouseDown, x, y, n); post(Quartz.kCGEventLeftMouseUp, x, y, n); time.sleep(0.1)


def shot(name):
    if not screenshots:
        return
    path = Path(tempfile.gettempdir()) / f"{name}.jpg"
    subprocess.run(["screencapture", "-x", "-t", "jpg", str(path)], check=False)
    subprocess.run(["sips", "-Z", "1280", "-s", "formatOptions", "60", str(path)], capture_output=True, check=False)
    if path.exists():
        data = base64.b64encode(path.read_bytes()).decode()
        for i in range(0, len(data), 4000):
            print(f"SHOT {name} {data[i:i + 4000]}")
        print(f"SHOT {name} END", flush=True)


def show(label, b):
    print(f"{label:<10} " + (f"x={b[0]} y={b[1]} w={b[2]} h={b[3]}" if b else "no window"), flush=True)


def launch():
    global proc
    proc = subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        if window_bounds():
            return
    print(f"FAIL: no window (exit code {proc.poll()})")
    if log.exists():
        print(log.read_text()[-6000:])
    sys.exit(1)


def moved(before, after):
    return before[:2] != after[:2]


failures = []
launch()
time.sleep(12)
x, y, w, h = window_bounds()
click(x + w // 2, y + h // 2)  # bring the app to the front; the first click only activates it
time.sleep(1)
show("start", (x, y, w, h)); shot("start")
drag(x + 600, y + 12, 80, 40)
b = window_bounds(); show("dragged", b)
if not moved((x, y, w, h), b):
    failures.append("set-up: dragging the title strip didn't move the window")
x, y, w, h = b
drag(x + w - 2, y + h - 2, 60, 30)
b = window_bounds(); show("resized", b)
x, y, w, h = b
click(x + 600, y + 12, clicks=2); time.sleep(1.5)
show("dblclick", window_bounds()); shot("zoomed")
proc.terminate()
proc.wait(10)

# Second run: set up with a library, so the app opens on the main window.
seeded = subprocess.run([exe, "--add-library", str(Path(fixtures) / "Test Library.xml")], capture_output=True, text=True)
print("seed:", (seeded.stdout or seeded.stderr).strip()[-300:])
launch()
time.sleep(15)
x, y, w, h = window_bounds()
click(x + w - 40, y + h - 40)  # activate, away from anything clickable
time.sleep(1.5)
show("main", (x, y, w, h)); shot("main")
drag(x + 600, y + 12, 60, 30)
b = window_bounds(); show("strip drag", b)
if not moved((x, y, w, h), b):
    failures.append("main window: dragging the title strip didn't move the window")
x, y, w, h = b
drag(x + w - 70, y + 48, -50, -20)  # the empty end of the page's title row
b = window_bounds(); show("bar drag", b)
print("top bar drag moved the window:", moved((x, y, w, h), b))
proc.terminate()
proc.wait(10)
if log.exists():
    print("--- app log ---")
    print("\n".join(log.read_text().splitlines()[-60:]))
for failure in failures:
    print("FAIL:", failure)
sys.exit(1 if failures else 0)
