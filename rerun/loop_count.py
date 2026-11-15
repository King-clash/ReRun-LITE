"""Read and set the Loops count on Grand Summoners' Auto-Loop Settings screen.

The counter sits right of the "Loops" label; it is read digit by digit with
small digit templates (loopdigit_<digit>_<variant>). It is changed with the
- / + buttons beside the slider, then read back to confirm - the same idea as
ReStart's set_loop_batch, which caps at the dialog's maximum (50 or 100).
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from .vision import Vision

DIGIT_PREFIX = "loopdigit_"
DIGIT_THRESHOLD = 0.80
MAX_GAP = 12  # px between neighbouring digits of one number
MIN_PITCH = 10  # px; closer hits are the same digit
SETTLE_S = 3.0  # how long the counter may take to show the result of the taps


LINE_TOLERANCE = 6  # px a digit's centre may sit off the label's centre line
PEAK_SPAN = 4      # rows above/below a hit that must score clearly lower
PEAK_MARGIN = 0.03


def _peaks_vertically(r: np.ndarray, y: int, x: int) -> bool:
    """A real digit matches best at one height. A plain vertical edge (seen
    live: the counter box's left edge) matches the thin '1' equally well at
    every height - so a lone 1 read as "11". Such a flat column is rejected."""
    s = r[y, x]
    for dy in (-PEAK_SPAN, PEAK_SPAN):
        yy = y + dy
        if 0 <= yy < r.shape[0] and r[yy, x] >= s - PEAK_MARGIN:
            return False
    return True


def read_loops(vision: Vision, screen: np.ndarray) -> int | None:
    label = vision.find(screen, "loops_label")
    if not label:
        return None
    h, w = screen.shape[:2]
    # The value is right-aligned and ends ~120px right of the label; the box's
    # edge just past it reads as a '1', so stop the region before that edge.
    x0, x1 = label.x + label.w, min(w, label.x + label.w + 128)
    y0, y1 = max(0, label.y - 6), min(h, label.y + label.h + 6)
    gray = cv2.cvtColor(screen[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    line_y = label.y + label.h / 2 - y0  # the label's text line, in band coordinates
    hits = []  # (score, x, width, digit)
    for name in vision.store.names():
        if not name.startswith(DIGIT_PREFIX):
            continue
        digit = int(name[len(DIGIT_PREFIX)])
        t = cv2.cvtColor(vision.store.get(name), cv2.COLOR_BGR2GRAY)
        if t.shape[0] > gray.shape[0] or t.shape[1] > gray.shape[1]:
            continue
        r = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(r >= DIGIT_THRESHOLD)
        for y, x in zip(ys, xs):
            # The value is printed on the label's text line; the counter box's
            # edges (top/bottom of the band) are not digits.
            if abs((y + t.shape[0] / 2) - line_y) > LINE_TOLERANCE:
                continue
            if not _peaks_vertically(r, y, x):
                continue
            hits.append((float(r[y, x]), int(x), t.shape[1], digit))
    # Non-maximum suppression along x: best-scoring glyph wins each spot.
    # Digits sit ~16px apart, so any two hits closer than MIN_PITCH are the
    # same digit (a thick '1' otherwise matches twice and 1 reads as "11").
    kept: list[tuple[float, int, int, int]] = []
    for hit in sorted(hits, reverse=True):
        if all(abs(hit[1] - k[1]) >= MIN_PITCH for k in kept):
            kept.append(hit)
    if not kept:
        return None
    kept.sort(key=lambda k: k[1])
    groups: list[list] = [[kept[0]]]
    for k in kept[1:]:
        prev = groups[-1][-1]
        if k[1] - (prev[1] + prev[2]) <= MAX_GAP:
            groups[-1].append(k)
        else:
            groups.append([k])
    best = max(groups, key=lambda g: (len(g), sum(k[0] for k in g) / len(g)))
    return int("".join(str(k[3]) for k in best))


def read_loops_ocr(script, screen: np.ndarray) -> int | None:
    """Fallback when the digit images don't match (e.g. a new game font):
    read the number right of the Loops label with OCR."""
    label = script.ctx.vision.find(screen, "loops_label")
    if not label:
        return None
    return script.read_number(label.x + label.w, label.y - 4, 150, label.h + 8, screen=screen)


def set_loops(script, target: int, max_passes: int = 5) -> int | None:
    """Set the Loops counter to `target` (capped at the game's max).
    Returns the value read back, or None if the counter couldn't be read."""
    v = script.ctx.vision
    last = None
    for _ in range(max_passes):
        img = script.grab()
        cur = read_loops(v, img)
        if cur is None:
            cur = read_loops_ocr(script, img)
        if cur is None:
            script.log("Could not read the Loops counter - leaving it as set")
            return None
        if cur == target or cur == last:  # done, or capped at min/max
            return cur
        button = "loop_plus_button" if target > cur else "loop_minus_button"
        m = v.find(img, button)
        if not m:
            script.log(f"'{button}' not found - leaving Loops at {cur}")
            return cur
        n = abs(target - cur)
        script.log(f"Loops {cur} -> {target}: tapping {'+' if target > cur else '-'} x{n}")
        script.ctx.device.tap_many(*m.center, n)
        # Seen live: the counter updates a moment after the taps, so a single
        # read 0.8 s later still showed the old value and looked like a game
        # limit. Wait for it to change (or give up after SETTLE_S).
        end = time.monotonic() + SETTLE_S
        while True:
            script.sleep(0.4)
            img = script.grab()
            now = read_loops(v, img)
            if now is None:
                now = read_loops_ocr(script, img)
            if now is not None and now != cur or time.monotonic() >= end:
                break
        last = cur
    return read_loops(v, script.grab())
