"""Read the game's own Crest Palace schedule (Exploring > Schedule) from a running game.

Used by tools/palace_schedule.py and by Settings > Palace Selector > "Read the game's schedule".

What it does to the game, in full: from the Home screen it taps Exploring, then Schedule; it unticks the schedule's other filter
buttons so only Crest Palace is listed; it scrolls a short way at a time and reads each page; then it ticks the filters back exactly
as they were found and taps Close. It starts nothing, buys nothing and changes nothing on the account. If anything goes wrong in
the middle, the filters are still put back and the window closed (it is all in a `finally`).

`dev` is any object with screencap() -> BGR image, tap(x, y) and swipe(x1, y1, x2, y2, ms) (rerun.adb.Device has them).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from . import palaces

EXPLORING_BUTTON = (590, 940)            # Home screen
SCHEDULE_BUTTON = (650, 1220)            # bottom bar of the Exploring screen
CLOSE_BUTTON = (360, 1218)
# the eight filter buttons, in the order they appear: the centre of each tick box
FILTERS = ["Epic Event", "Trial Event", "Assault Event", "Daily Quest", "Giant Boss", "Rotating Boss", "Crest Palace", "S. Road"]
FILTER_POINTS = [(48, 195), (215, 195), (383, 195), (550, 195), (48, 260), (215, 260), (383, 260), (550, 260)]


class ScheduleError(Exception):
    """Something the user can act on (the game is not on Home, the window did not open...). The message says what."""


@dataclass
class ScheduleResult:
    entries: list = field(default_factory=list)       # palaces.SchedEntry, in the order read
    gaps: int = 0                                     # places where two pages shared nothing (an entry may have been missed)
    pages: int = 0


def ticked(img: np.ndarray, pt: tuple[int, int]) -> bool:
    """Is the filter button's tick box showing the orange tick? (An empty box is dark.)"""
    x, y = pt
    box = img[max(0, y - 22):y + 22, max(0, x - 22):x + 22].astype(int)
    if box.size == 0:
        return False
    b, g, r = box[..., 0], box[..., 1], box[..., 2]
    orange = (r > 200) & (g > 70) & (g < 190) & (b < 90)
    return float(orange.mean()) > 0.04


def on_schedule(ocr, img: np.ndarray) -> bool:
    return any(w.y < 140 and "schedule" in w.text.lower() for w in ocr.screen_words(img, min_conf=40))


def _same(a: np.ndarray | None, b: np.ndarray) -> bool:
    return a is not None and a.shape == b.shape and float(np.abs(a.astype(np.int16) - b).mean()) < 1.0


def read_schedule(dev, ocr, vision, names: list[str], pages: int = 24, pause=None, log=lambda m: None) -> ScheduleResult:
    """Open the schedule, read up to `pages` pages of Crest Palace entries, and leave the game as it was found."""
    pause = pause or time.sleep
    img = dev.screencap()
    if vision.find(img, "exploring_button"):
        log("Opening Exploring")
        dev.tap(*EXPLORING_BUTTON)
        pause(4)
        img = dev.screencap()
    if not vision.find(img, "crest_palace_icon") and not vision.find(img, "crest_palace_icon2"):
        raise ScheduleError("Start with the game on the Home screen (or the Exploring screen).")
    dev.tap(*SCHEDULE_BUTTON)
    pause(4)
    img = dev.screencap()
    if not on_schedule(ocr, img):
        raise ScheduleError("The Schedule window did not open. Close any pop-up in the game and try again.")
    before = [ticked(img, p) for p in FILTER_POINTS]
    result = ScheduleResult()
    try:
        for i, p in enumerate(FILTER_POINTS):
            if before[i] != (FILTERS[i] == "Crest Palace"):
                dev.tap(*p)
                pause(0.8)
        pause(1.5)
        last, prev = None, []
        for _page in range(pages):
            img = dev.screencap()
            if _same(last, img):
                break                                                # the list stopped moving: the end of it
            last = img
            now = palaces.parse_schedule(ocr.screen_words(img, min_conf=40), names)
            result.pages += 1
            if result.pages > 1 and now and prev and not any(e in prev for e in now):
                result.gaps += 1                                     # nothing shared with the page before: something may be skipped
            for e in now:
                if e not in result.entries:
                    result.entries.append(e)
            prev = now
            dev.swipe(360, 900, 360, 540, 1100)                      # a short, slow swipe: a fast long one flings past entries
            pause(1.5)
    finally:
        try:
            now_img = dev.screencap()
            for i, p in enumerate(FILTER_POINTS):                    # put the filters back exactly as they were
                if ticked(now_img, p) != before[i]:
                    dev.tap(*p)
                    pause(0.8)
        finally:
            dev.tap(*CLOSE_BUTTON)
            pause(2)
    return result


def describe(result: ScheduleResult, root) -> list[str]:
    """Plain-language lines for a window or a console: what was read, then the selector's choice for each day against it."""
    lines = []
    if not result.entries:
        return ["No palace entries were read from the game's schedule."]
    unknown = sorted({e.name for e in result.entries if not e.known})
    lines.append(f"Read {len(result.entries)} palace entries over {result.pages} page(s) of the game's schedule."
                 + (f" ({result.gaps} place(s) where the pages did not overlap: an entry may have been missed.)" if result.gaps else ""))
    for row in palaces.plan_vs_schedule(result.entries, root):
        if row["chosen"] is None:
            verdict = f"nothing chosen ({row['note']})"
        else:
            verdict = "open that day" if row["ok"] else "NOT OPEN that day"
        lines.append(f"  {row['date']} {row['day'][:3]}: chooses {row['chosen'] or '-'} - {verdict}")
    if unknown:
        lines.append("In the game's schedule but not in palaces.yaml: " + ", ".join(unknown) + ". Add them (Add from screen...) when they are on the Crest Palace screen.")
    return lines
