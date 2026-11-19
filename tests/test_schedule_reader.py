"""rerun_lite/schedule_reader.py against a stand-in for the game made from real screenshots: it must read the schedule and, whatever
happens, leave the filter buttons as it found them and close the window.   Run:  py tests/test_schedule_reader.py   (or pytest)"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ocr as engine_ocr  # noqa: E402
from rerun.vision import TemplateStore, Vision  # noqa: E402
from rerun_lite import palaces, schedule_reader as sr  # noqa: E402
from tests.test_lite import close, open_lite, texts  # noqa: E402
from tests.test_palaces import palace_root  # noqa: E402

FX = ROOT / "tests" / "fixtures"


def img(name: str) -> np.ndarray:
    return cv2.imread(str(FX / name))


class FakeGame:
    """Home -> Exploring -> Schedule, with the eight filter buttons and a list that scrolls, drawn from real screenshots."""

    def __init__(self, ticks, start="home", opens=True):
        self.ticks, self.stage, self.page, self.opens = list(ticks), start, 0, opens
        self.home, self.exploring = img("home.png"), img("live_exploring.png")
        self.all_on = img("live_schedule_all_filters.png")
        self.only = [img("live_schedule_crest_palace.png"), img("live_schedule_crest_palace_2.png"), img("live_schedule_crest_palace_3.png")]
        self.on_patch, self.off_patch = {}, {}
        for i, (x, y) in enumerate(sr.FILTER_POINTS):                # a ticked and an empty tick box, cut from the real screens
            self.on_patch[i] = self.all_on[y - 24:y + 24, x - 24:x + 24].copy()
        ex, ey = sr.FILTER_POINTS[0]
        for i in range(8):
            self.off_patch[i] = self.only[0][ey - 24:ey + 24, ex - 24:ex + 24].copy()   # Epic Event is empty here
        self.taps, self.swipes, self.closed = [], [], 0

    def screencap(self):
        if self.stage == "home":
            return self.home.copy()
        if self.stage == "exploring":
            return self.exploring.copy()
        base = (self.only[min(self.page, 2)] if self.ticks.count(True) == 1 and self.ticks[6] else self.all_on).copy()
        for i, (x, y) in enumerate(sr.FILTER_POINTS):
            base[y - 24:y + 24, x - 24:x + 24] = (self.on_patch if self.ticks[i] else self.off_patch)[i]
        return base

    def tap(self, x, y):
        self.taps.append((x, y))
        near = lambda p, r=45: abs(x - p[0]) <= r and abs(y - p[1]) <= r  # noqa: E731
        if self.stage == "home" and near(sr.EXPLORING_BUTTON, 60):
            self.stage = "exploring"
        elif self.stage == "exploring" and near(sr.SCHEDULE_BUTTON, 60) and self.opens:
            self.stage, self.page = "schedule", 0
        elif self.stage == "schedule":
            if near(sr.CLOSE_BUTTON, 60):
                self.stage, self.closed = "exploring", self.closed + 1
            for i, p in enumerate(sr.FILTER_POINTS):
                if near(p, 30):
                    self.ticks[i] = not self.ticks[i]

    def swipe(self, x1, y1, x2, y2, ms=300):
        self.swipes.append((y1, y2))
        if self.stage == "schedule":
            self.page = min(self.page + 1, 2)


def reader():
    try:
        return engine_ocr.get_ocr()
    except engine_ocr.OcrUnavailable:
        return None


def names():
    return [p.name for p in palaces.read_list(ROOT)]


def run(game, ocr, **kw):
    return sr.read_schedule(game, ocr, Vision(TemplateStore(ROOT / "templates")), names(), pause=lambda s: None, **kw)


def test_it_reads_the_week_and_leaves_every_filter_and_the_window_as_it_found_them():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    for start in ([True] * 8, [True, False, True, True, False, True, False, True], [False] * 8):
        g = FakeGame(start)
        res = run(g, ocr)
        got = {(str(e.date), e.name) for e in res.entries}
        assert {("2026-11-18", "Shrine of the Azul Knight"), ("2026-11-20", "Shrine of Adamantine"),
                ("2026-11-22", "Shrine of Discordia")} <= got, got
        assert res.pages == 3                                                 # the list stopped moving on the third page
        assert g.ticks == start, (start, g.ticks)                             # the filters are back exactly as they were
        assert g.stage == "exploring" and g.closed == 1                       # and the window was closed once
        for (y1, y2) in g.swipes:
            assert y1 - y2 <= 400                                             # short swipes only (a long one flings past entries)


def test_a_problem_in_the_middle_still_puts_the_filters_back_and_closes_the_window():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return

    class Breaks:
        def __init__(self, inner):
            self.inner, self.calls = inner, 0

        def screen_words(self, im, min_conf=60):
            self.calls += 1
            if self.calls >= 4:                                               # fine for the window check and page 1, then fails
                raise RuntimeError("reader crashed")
            return self.inner.screen_words(im, min_conf=min_conf)
    start = [True] * 8
    g = FakeGame(start)
    try:
        run(g, Breaks(ocr))
        raise AssertionError("the error must reach the caller")
    except RuntimeError as e:
        assert "reader crashed" in str(e)
    assert g.ticks == start and g.stage == "exploring" and g.closed == 1, (g.ticks, g.stage, g.closed)


def test_it_refuses_politely_when_the_game_is_not_on_home_or_the_window_does_not_open():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    g = FakeGame([True] * 8)
    g.home = img("live_crest_palace_top.png")                                 # some other screen
    try:
        run(g, ocr)
        raise AssertionError("must refuse")
    except sr.ScheduleError as e:
        assert "Home screen" in str(e)
    assert g.taps == []                                                       # it tapped nothing
    g = FakeGame([True] * 8, start="exploring", opens=False)
    try:
        run(g, ocr)
        raise AssertionError("must refuse")
    except sr.ScheduleError as e:
        assert "did not open" in str(e)
    assert len(g.taps) == 1 and g.ticks == [True] * 8                         # one tap at the Schedule button, nothing else


def test_the_summary_says_what_was_read_and_which_chosen_palaces_are_not_open():
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    res = run(FakeGame([True] * 8), ocr)
    root, _shot = palace_root()
    try:
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Wednesday": "Shrine of Whirlwind", "Friday": "Shrine of Whirlwind"}))
        text = "\n".join(sr.describe(res, root))
        assert "palace entries" in text and "NOT OPEN that day" in text and "Wed" in text, text
        assert sr.describe(sr.ScheduleResult(), root) == ["No palace entries were read from the game's schedule."]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_settings_button_asks_first_refuses_while_crest_runs_and_shows_the_result():
    from rerun import ios
    ocr = reader()
    if ocr is None:
        print("skip: no text reader here")
        return
    root, m, inst, app = open_lite()
    shown, asked = [], []
    real_alert, real_confirm, real_sleep = ios.alert, ios.confirm, sr.time.sleep
    try:
        shutil.copytree(ROOT / "images", root / "images", dirs_exist_ok=True)
        shutil.copy(ROOT / "palaces.yaml", root / "palaces.yaml")
        game = FakeGame([True] * 8)
        game.is_connected, game.connect = (lambda: True), (lambda: None)
        m.device = lambda name: game
        ios.alert = lambda parent, message, title="Rerun": shown.append((title, message))
        sr.time.sleep = lambda s: None
        app._pal_sync = True
        app._set_nav.select("palaces")
        app.update()
        assert "Read the game's schedule" in " ".join(texts(app._set_pages["palaces"]))
        m.instances[inst].status = "running"
        app._pal_read_schedule()
        assert "Stop Crest first" in shown[-1][1] and not game.taps                     # not while a run is going
        m.instances[inst].status = "idle"
        ios.confirm = lambda parent, message, title="Rerun", ok="OK", **k: (asked.append(message), False)[1]
        app._pal_read_schedule()
        assert asked and "filter buttons back" in asked[-1] and not game.taps          # declined: nothing tapped
        ios.confirm = lambda parent, message, title="Rerun", ok="OK", **k: (asked.append(message), True)[1]
        app._pal_read_schedule()
        title, text = shown[-1]
        assert title == "The game's palace schedule" and "palace entries" in text, shown[-1]
        assert game.ticks == [True] * 8 and game.stage == "exploring"                  # everything put back
        game2 = FakeGame([True] * 8)
        game2.is_connected, game2.connect = (lambda: True), (lambda: None)
        game2.home = img("live_crest_palace_top.png")
        m.device = lambda name: game2
        app._pal_read_schedule()
        assert "Home screen" in shown[-1][1] and game2.taps == []                       # the wrong screen: refused, nothing tapped
        assert not app.errors, app.errors
    finally:
        ios.alert, ios.confirm, sr.time.sleep = real_alert, real_confirm, real_sleep
        close(app, root)


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
