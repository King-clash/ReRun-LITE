"""The game's own pop-ups that are recognised by their words: 'Date has changed', maintenance, 'please update', and
errors. The screens are drawn here (plain text on a dark picture) and read by the real text reader, so this checks the whole
path from the words on the screen to the right action.   Run:  py tests/test_popups.py   (or under pytest)"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ocr as engine_ocr  # noqa: E402
from rerun.engine import StopRoutine  # noqa: E402
from rerun.scripts import base as engine_base  # noqa: E402
from rerun.scripts import CrestScript  # noqa: E402

OK_CENTRE = (360, 800)


def popup(lines: list[str], button: str = "OK") -> np.ndarray:
    img = np.full((1280, 720, 3), (60, 40, 40), np.uint8)
    y = 520
    for line in lines:
        cv2.putText(img, line, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
        y += 60
    cv2.rectangle(img, (240, 760), (480, 840), (200, 120, 40), -1)
    cv2.putText(img, button, (320, 815), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3, cv2.LINE_AA)
    return img


def reader():
    try:
        return engine_ocr.get_ocr()
    except engine_ocr.OcrUnavailable:
        return None


class Script:
    """A Crest script with only what the text safety net touches, recording what it does."""

    def __init__(self, ocr, mode_247=False, unknown_for=100.0):
        self.s = CrestScript.__new__(CrestScript)
        s = self.s
        s._ocr = ocr
        s.cfg = {"mode_247": mode_247}
        s._unknown_since = time.monotonic() - unknown_for
        s._last_text_check = 0.0
        self.taps, self.notes, self.logs, self.records, self.restarts = [], [], [], [], []
        s.tap = lambda x, y, settle=0.6: self.taps.append((x, y))
        s.notify = lambda msg, **k: self.notes.append(msg)
        s.log = self.logs.append
        s.record = lambda kind, detail, image=None, **k: self.records.append(detail)
        s.count = lambda *a, **k: None
        s.progress = lambda *a, **k: None
        s.sleep = lambda *a, **k: None
        s.restart_game = lambda scheduled=False: self.restarts.append(scheduled)

    def run(self, screen) -> bool:
        return self.s._text_safety_net(screen)


def test_date_has_changed_is_dismissed_by_tapping_its_ok():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    sc = Script(ocr)
    assert sc.run(popup(["Date has changed.", "Returning to title."])) is True
    assert len(sc.taps) == 1 and abs(sc.taps[0][0] - OK_CENTRE[0]) < 60 and abs(sc.taps[0][1] - OK_CENTRE[1]) < 60, sc.taps
    assert any("date has changed" in m.lower() for m in sc.logs), sc.logs


def test_the_screen_is_only_read_after_it_has_stayed_unknown_a_while_and_not_too_often():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    sc = Script(ocr, unknown_for=2.0)                      # unknown for only 2 seconds: not read yet
    assert sc.run(popup(["Date has changed.", "Returning to title."])) is False and not sc.taps
    sc = Script(ocr)
    assert sc.run(popup(["Date has changed.", "Returning to title."])) is True
    assert sc.run(popup(["Date has changed.", "Returning to title."])) is False        # read again at most every 20 seconds


def test_a_screen_with_no_known_words_is_left_alone():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    sc = Script(ocr)
    assert sc.run(popup(["Welcome back, summoner."])) is False and not sc.taps and not sc.notes


def test_maintenance_stops_without_24_7_mode_and_waits_then_relaunches_with_it():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    sc = Script(ocr, mode_247=False)
    try:
        sc.run(popup(["The game is under maintenance."]))
        raise AssertionError("maintenance without 24/7 mode must stop the run")
    except StopRoutine:
        pass
    assert any("under maintenance" in m.lower() or "needs you" in m for m in sc.notes), sc.notes
    sc = Script(ocr, mode_247=True)
    clock = {"t": 1000.0}

    def fake_monotonic():
        clock["t"] += 400.0                                # each look at the clock is 400 s later: the 10 minutes pass at once
        return clock["t"]
    real = engine_base.time.monotonic
    engine_base.time.monotonic = fake_monotonic
    try:
        sc.s._unknown_since = fake_monotonic() - 100
        assert sc.run(popup(["The game is under maintenance."])) is True
    finally:
        engine_base.time.monotonic = real
    assert sc.restarts == [True], sc.restarts              # relaunched, counted as an expected restart (not a failure)
    assert any("Waiting 10 minutes" in m for m in sc.notes), sc.notes


def test_please_update_the_app_stops_and_says_it_needs_you():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    sc = Script(ocr, mode_247=True)
    try:
        sc.run(popup(["Please update the app", "to the new version."]))
        raise AssertionError("an update screen must stop the run")
    except StopRoutine:
        pass
    assert any("needs you" in m for m in sc.notes) and not sc.restarts, sc.notes


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, repr(e))
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
