"""Read the game's own Crest Palace schedule and compare it with what ReRun LITE's palace selector would choose.

It opens Exploring > Schedule in the running game, reads the pages (scrolling down), and prints, for each day the game
lists, which palaces are open and whether the selector's choice for that day is one of them. It is read-only for your
account: the only taps are menu navigation and the schedule's own filter buttons, which are put back as they were, and
then the Schedule window is closed. Nothing is started, bought or changed. (The same reader is behind the button
Settings > Palace Selector > "Read the game's schedule".)

Start it with the game on the Home screen or the Exploring screen:
    py tools/palace_schedule.py            # reads about a week
    py tools/palace_schedule.py --pages 6  # fewer pages

Needs BlueStacks open with ADB on (it uses BlueStacks' own HD-Adb.exe) and the text reader that ReRun LITE already uses.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rerun.ocr import get_ocr  # noqa: E402
from rerun.vision import TemplateStore, Vision  # noqa: E402
from rerun_lite import palaces, schedule_reader  # noqa: E402


def adb_path() -> str:
    for cand in (shutil.which("adb"), r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
                 r"C:\Program Files (x86)\BlueStacks_nxt\HD-Adb.exe"):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("No adb found (BlueStacks' HD-Adb.exe or adb on PATH).")


class Phone:
    """The three calls the reader needs, over adb."""

    def __init__(self):
        self.adb = adb_path()
        out = subprocess.run([self.adb, "devices"], capture_output=True, text=True, timeout=30).stdout
        serials = [ln.split()[0] for ln in out.splitlines()[1:] if ln.strip().endswith("device")]
        if not serials:
            raise SystemExit("No device connected (is BlueStacks open with ADB on?).")
        self.serial = serials[0]

    def run(self, *args: str, timeout: float = 60) -> bytes:
        return subprocess.run([self.adb, "-s", self.serial, *args], capture_output=True, timeout=timeout).stdout

    def screencap(self) -> np.ndarray:
        img = cv2.imdecode(np.frombuffer(self.run("exec-out", "screencap", "-p"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit("Could not read a screenshot.")
        return img

    def tap(self, x: int, y: int) -> None:
        self.run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self.run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", type=int, default=24, help="how many pages to read at most (default 24, about a week)")
    args = ap.parse_args(argv)
    names = [p.name for p in palaces.read_list(ROOT)]
    try:
        result = schedule_reader.read_schedule(Phone(), get_ocr(), Vision(TemplateStore(ROOT / "templates")), names, args.pages,
                                               log=print)
    except schedule_reader.ScheduleError as e:
        raise SystemExit(str(e)) from e
    for e in result.entries:
        print(f"  {e.date}  {e.name:30s} {e.start} to {e.end}" + ("" if e.known else "   <- NOT in palaces.yaml"))
    print()
    print("\n".join(schedule_reader.describe(result, ROOT)))
    print("\nThe game labels these times PST and starts each day at 0:00, four hours before the 06:00 UTC-6 reset the selector uses.")
    return 0 if result.entries else 1


if __name__ == "__main__":
    raise SystemExit(main())
