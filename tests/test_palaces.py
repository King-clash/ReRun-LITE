"""The daily Crest Palace selector: the game-day clock, the list, weekday and cycle choices, the import from GS
Companion (never overwrites), Crest opening only today's palace (and stopping instead of running another), and the
Settings page.   Run:  py tests/test_palaces.py"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun.scripts.base import Finished  # noqa: E402
from rerun_lite import palaces  # noqa: E402
from rerun_lite.crest import LiteCrest, find_tile  # noqa: E402
from tests.test_lite import close, lite_root, open_lite, texts  # noqa: E402

TZ = timezone(timedelta(hours=-6))
TILES = {"Shrine of Cursed Claw": (44, 338, 682, 488), "Shrine of Whirlwind": (44, 520, 682, 668)}


def palace_root():
    """A throw-away app folder with two palace pictures cut from a real Crest Palace screenshot (at 90% size, so
    they are not the game's own pixels) and one palace whose picture file is missing."""
    root = lite_root()
    shot = cv2.imread(str(ROOT / "tests" / "fixtures" / "crest_palace_list.png"))
    (root / "images").mkdir()
    lines = []
    for name, (x0, y0, x1, y1) in TILES.items():
        cv2.imwrite(str(root / "images" / f"{palaces.slug(name)}.png"), cv2.resize(shot[y0:y1, x0:x1], None, fx=0.9, fy=0.9))
        lines.append(f"{name}: images/{palaces.slug(name)}.png\n")
    lines.append("Shrine of Perdition: images/shrine_of_perdition.png\n")
    (root / "palaces.yaml").write_text("".join(lines), encoding="utf-8")
    return root, shot


def at(day: int) -> datetime:
    return datetime(2026, 11, day, 12, 0, tzinfo=TZ)


def test_the_palace_day_changes_at_the_game_reset_not_at_midnight():
    assert palaces.game_date(datetime(2026, 11, 17, 5, 59, tzinfo=TZ)).isoformat() == "2026-11-16"   # Tuesday 05:59: still Monday
    assert palaces.game_date(datetime(2026, 11, 17, 6, 0, tzinfo=TZ)).isoformat() == "2026-11-17"
    assert palaces.game_date(datetime(2026, 11, 17, 0, 30, tzinfo=TZ)).strftime("%A") == "Monday"
    # the same instant seen on a phone or PC in another time zone is the same game day
    assert palaces.game_date(datetime(2026, 11, 17, 11, 59, tzinfo=timezone.utc)) == \
        palaces.game_date(datetime(2026, 11, 17, 5, 59, tzinfo=TZ))


def test_weekday_cycle_off_and_the_missing_picture_stop():
    root, _ = palace_root()
    try:
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Saturday": "Shrine of Cursed Claw", "Sunday": "Shrine of Perdition"}))
        c = palaces.choose(root, at(14))                                  # a Saturday
        assert c.ok and c.palace.name == "Shrine of Cursed Claw" and c.path.name == "shrine_of_cursed_claw.png" and c.day == "Saturday"
        c = palaces.choose(root, at(15))                                  # Sunday: listed, but the picture is not there
        assert not c.ok and c.palace.name == "Shrine of Perdition" and "images/shrine_of_perdition.png" in c.problem
        c = palaces.choose(root, at(16))                                  # Monday: nothing chosen: stop, no default palace
        assert not c.ok and "Monday" in c.problem and c.palace is None
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Monday": "No Such Palace"}))
        assert "not in palaces.yaml" in palaces.choose(root, at(16)).problem
        # cycle: one palace per game day, in list order, wrapping; it starts where it was told to
        palaces.save_schedule(root, palaces.Schedule("cycle", {}, "Shrine of Whirlwind", "2026-11-14", []))
        assert [palaces.choose(root, at(d)).palace.name for d in (14, 15, 16, 17)] == \
            ["Shrine of Whirlwind", "Shrine of Perdition", "Shrine of Cursed Claw", "Shrine of Whirlwind"]
        palaces.save_schedule(root, palaces.Schedule("cycle", {}, "", "2026-11-14", ["Shrine of Cursed Claw", "Shrine of Whirlwind"]))
        assert [palaces.choose(root, at(d)).palace.name for d in (14, 15, 16)] == \
            ["Shrine of Cursed Claw", "Shrine of Whirlwind", "Shrine of Cursed Claw"]
        palaces.save_schedule(root, palaces.Schedule("off"))
        assert palaces.choose(root, at(14)).mode == "off" and palaces.choose(root, at(14)).palace is None
        (root / "palaces.yaml").write_text("", encoding="utf-8")
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Saturday": "Shrine of Cursed Claw"}))
        assert "empty" in palaces.choose(root, at(14)).problem
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_import_names_files_after_palaces_and_never_overwrites_or_edits_lines():
    src, root = lite_root(), lite_root()
    try:
        (src / "images" / "stages").mkdir(parents=True)
        stages = [{"name": "Ember Palace", "stage_id": "1", "days": ["Monday"]}, {"name": "Frost Palace", "stage_id": "2", "days": ["Tuesday"]},
                  {"name": "Ghost Palace", "stage_id": "3", "days": ["Friday"]}]            # Ghost has no picture
        (src / "crest_palace.json").write_text(json.dumps({"stages": stages}), encoding="utf-8")
        for sid in ("1", "2"):
            cv2.imwrite(str(src / "images" / "stages" / f"banner_{sid}.png"), np.full((20, 40, 3), int(sid) * 60, np.uint8))
            (src / "images" / "stages" / f"banner_{sid}.png").replace(src / "images" / "stages" / f"banner_{sid}.webp")
        (root / "images").mkdir()
        mine = root / "images" / "frost_palace.png"
        cv2.imwrite(str(mine), np.zeros((9, 9, 3), np.uint8))                              # an existing, different picture
        before = mine.read_bytes()
        (root / "palaces.yaml").write_text("Ember Palace: images/ember_palace.png\n", encoding="utf-8")     # an existing line
        rep = palaces.import_from_gscompanion(src, root)
        assert [n for n, _ in rep.copied] == ["Ember Palace"] and [n for n, _ in rep.kept] == ["Frost Palace"]
        assert rep.no_source == ["Ghost Palace"] and rep.listed == ["Frost Palace"] and rep.already_listed == ["Ember Palace"]
        assert mine.read_bytes() == before                                                  # not overwritten
        assert (root / "images" / "ember_palace.png").is_file()
        assert (root / "palaces.yaml").read_text(encoding="utf-8").splitlines() == \
            ["Ember Palace: images/ember_palace.png", "Frost Palace: images/frost_palace.png"]
        assert [(p.name, p.image) for p in palaces.read_list(root)] == \
            [("Ember Palace", "images/ember_palace.png"), ("Frost Palace", "images/frost_palace.png")]
        again = palaces.import_from_gscompanion(src, root)                                  # a second import changes nothing
        assert not again.copied and not again.listed
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Monday": "Ember Palace"}))
        assert "images/" not in (root / palaces.SCHEDULE_FILE).read_text(encoding="utf-8")  # paths only in the list
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


class Rec:
    """Stand-in for the few things a running Crest touches while it opens a palace."""

    def __init__(self, root):
        self.crest = LiteCrest.__new__(LiteCrest)
        self.crest.cfg = {"mode_247": True}
        self.crest.nav_active = True
        self.crest.PALACE_ROOT = root
        self.taps, self.notes, self.logs = [], [], []
        self.crest.tap = lambda x, y, settle=0.6: self.taps.append((x, y))
        self.crest.notify = lambda msg, **k: self.notes.append(msg)
        self.crest.log = lambda msg: self.logs.append(msg)

    def run(self, screen) -> bool:
        try:
            self.crest.handle_crest_palace_screen(screen)
            return True
        except Finished:
            return False


def test_crest_opens_only_todays_palace_and_stops_instead_of_running_another():
    root, shot = palace_root()
    try:
        r = Rec(root)
        today = palaces.DAYS[palaces.game_date().weekday()]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        assert r.run(shot) and len(r.taps) == 1 and 520 < r.taps[0][1] < 680 and 40 < r.taps[0][0] < 690, r.taps
        assert "Whirlwind" in r.logs[-1] and "images/shrine_of_whirlwind.png" in r.logs[-1]
        r.taps.clear()
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Cursed Claw"}))
        assert r.run(shot) and 330 < r.taps[0][1] < 490                                    # the first tile, not another
        blank = shot.copy()
        blank[300:720] = 40                                                                 # today's palace is not on this screen
        r.taps.clear()
        assert not r.run(blank) and not r.taps
        assert "Shrine of Cursed Claw" in r.notes[-1] and "images/shrine_of_cursed_claw.png" in r.notes[-1] and "no other palace" in r.notes[-1]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Perdition"}))
        assert not r.run(shot) and not r.taps                                               # its picture file is missing
        assert "Shrine of Perdition" in r.notes[-1] and "images/shrine_of_perdition.png" in r.notes[-1]
        palaces.save_schedule(root, palaces.Schedule("weekday", {}))
        assert not r.run(shot) and not r.taps and today in r.notes[-1]                      # nothing chosen for today
        palaces.save_schedule(root, palaces.Schedule("off"))
        assert r.crest.selector_on() is False                                               # the original handler takes over
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_tile_is_found_at_another_size_and_a_different_palace_is_not():
    root, shot = palace_root()
    try:
        pic = cv2.imread(str(root / "images" / "shrine_of_cursed_claw.png"))
        score, x, y, scale = find_tile(shot, pic)
        assert score > 0.8 and 330 < y < 490 and 1.05 < scale < 1.2, (score, x, y, scale)
        other = cv2.imread(str(root / "images" / "shrine_of_whirlwind.png"))
        score2, _, y2, _ = find_tile(shot, other)
        assert score2 > 0.8 and y2 > 520                                                    # each picture finds its own tile
        stranger = np.random.RandomState(1).randint(0, 255, pic.shape, np.uint8)
        assert find_tile(shot, stranger)[0] < 0.4
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_settings_page_lists_palaces_saves_choices_and_feeds_the_status_chip():
    root, m, inst, app = open_lite()
    try:
        extra, _ = palace_root()
        shutil.copytree(extra / "images", root / "images")
        (root / "palaces.yaml").write_text("Shrine of Cursed Claw: images/shrine_of_cursed_claw.png\n"
                                           "Shrine of Perdition: images/shrine_of_perdition.png\n", encoding="utf-8")
        shutil.rmtree(extra, ignore_errors=True)
        app._set_nav.select("palaces")
        app.update()
        words = " ".join(texts(app._set_pages["palaces"]))
        assert "Shrine of Cursed Claw" in words and "picture found" in words and "picture MISSING" in words
        today = palaces.DAYS[palaces.game_date().weekday()]
        app._pal_mode.set(palaces.MODES["weekday"])
        app._pal_week[today].set("Shrine of Perdition")                                    # its picture is missing
        app._pal_save()
        s = palaces.load_schedule(root)
        assert s.mode == "weekday" and s.week[today] == "Shrine of Perdition"
        assert "picture is missing" in app._pal_today.cget("text")
        app._status_sig = None
        app._refresh_status()
        assert any(p.fix == "palaces" for p in app._problems) and "Needs setup" in app.nb.chip.cget("text")
        app._pal_week[today].set("Shrine of Cursed Claw")
        app._pal_save()
        app._status_sig = None
        app._refresh_status()
        assert not any(p.fix in ("palaces", "settings") for p in app._problems)
        assert not app.errors, app.errors
    finally:
        close(app, root)


def test_quest_list_takes_the_top_quest_when_no_picture_or_name_applies():
    from types import SimpleNamespace

    from rerun import textnav
    from rerun_lite.crest import LiteCrest
    from rerun.scripts import crest as engine

    def make(cfg, found=False, rows=2):
        class Fake(LiteCrest):
            ocr = SimpleNamespace(screen_words=lambda *a, **k: ["w"])
        c = Fake.__new__(Fake)
        c.cfg, c.taps, c.logs, c.parties = cfg, [], [], []
        c.has_template, c.find = (lambda n: found), (lambda n, s=None: found)
        c.target_reached, c.tap = (lambda: False), (lambda x, y, settle=0: c.taps.append((x, y)))
        c.log, c.reset_party = c.logs.append, c.parties.append
        textnav.quest_rows = lambda words, y_min=560: [{"y": 663, "title": "The Subject in Trance [PRO]"}, {"y": 850, "title": "[ADV]"}][:rows]
        return c

    real_rows, real_super = textnav.quest_rows, engine.CrestScript.handle_quest_list
    called = []
    engine.CrestScript.handle_quest_list = lambda self, screen: called.append(1)
    try:
        c = make({})                                   # nothing set: the top quest (the first row) is opened
        c.handle_quest_list(None)
        assert c.taps == [(300, 663)] and c.parties == ["new quest entry"] and not called and "top quest" in c.logs[0]
        c = make({"quest_name": "ADV"})                # a name set: the original decides
        c.handle_quest_list(None)
        assert not c.taps and called == [1]
        called.clear()
        c = make({}, found=True)                       # a captured row picture matches: the original decides
        c.handle_quest_list(None)
        assert not c.taps and called == [1]
        called.clear()
        c = make({}, rows=1)                           # a single quest: the original handles it
        c.handle_quest_list(None)
        assert not c.taps and called == [1]
    finally:
        textnav.quest_rows, engine.CrestScript.handle_quest_list = real_rows, real_super


def test_a_crest_screen_that_will_not_clear_is_retried_loosely_then_stopped():
    from types import SimpleNamespace

    from rerun.scripts import crest as engine
    from rerun.scripts.base import Finished
    from rerun_lite.crest import LiteCrest

    c = LiteCrest.__new__(LiteCrest)
    c.events, c.cfg = [], {}
    c.log, c.notify = (lambda m: c.events.append(("log", m))), (lambda m, **k: c.events.append(("notify", m)))
    c.save_frame = lambda tag, screen=None: "debug/x.png"
    c.confirm_word = lambda screen: None
    c.find = lambda name, screen=None, threshold=None, region=None: SimpleNamespace(score=0.55) if threshold else None
    c.tap_match = lambda m, settle=0: c.events.append(("tap", m.score))
    c.wait_for = lambda names, t: None
    original = engine.CrestScript.scrap
    engine.CrestScript.scrap = lambda self, screen: self.events.append(("original", 0))
    try:
        c.scrap(None)
        c.scrap(None)
        assert [e for e in c.events if e[0] == "original"] == [("original", 0)] * 2          # the first tries are the original's
        c.scrap(None)                                                                          # third: a looser OK, and a saved picture
        assert ("tap", 0.55) in c.events and any("did not clear" in e[1] for e in c.events if e[0] == "log")
        c.scrap(None)
        try:
            c.scrap(None)                                                                      # fifth: stop and say why
            raise AssertionError("it should have stopped")
        except Finished as e:
            assert "stuck" in str(e)
        assert any(e[0] == "notify" and "debug/x.png" in e[1] for e in c.events)
        c._scrap_last -= 100                                                                   # a long quiet spell starts over
        c.events.clear()
        c.scrap(None)
        assert c.events == [("original", 0)]
    finally:
        engine.CrestScript.scrap = original


def test_a_confirm_button_is_found_by_its_text_and_tapped_when_there_is_no_ok():
    from types import SimpleNamespace

    import cv2

    from rerun.ocr import OcrUnavailable, get_ocr
    from rerun.scripts import crest as engine
    from rerun_lite.crest import LiteCrest

    base = cv2.imread(str(ROOT / "tests" / "fixtures" / "equip_crest_lv3.png"))

    def screen_with(label):                       # the Equip Crest screen with its bottom bar replaced by one orange button
        im = base.copy()
        cv2.rectangle(im, (40, 1060), (680, 1150), (20, 20, 20), -1)
        cv2.rectangle(im, (230, 1062), (490, 1135), (25, 90, 175), -1)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 1.2, 2)
        org = (360 - tw // 2, 1098 + th // 2)
        cv2.putText(im, label, org, cv2.FONT_HERSHEY_DUPLEX, 1.2, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(im, label, org, cv2.FONT_HERSHEY_DUPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
        return im

    try:
        reader = get_ocr(None)
    except OcrUnavailable:
        reader = None
    if reader is not None:                        # the real text reader on a picture of the screen
        class Real(LiteCrest):
            ocr = reader
        c = Real.__new__(Real)
        x, y = c.confirm_word(screen_with("Confirm"))
        assert abs(x - 360) < 40 and abs(y - 1100) < 30, (x, y)
        assert c.confirm_word(screen_with("OK")) is None and c.confirm_word(screen_with("Redeploy")) is None

    class Fake(LiteCrest):
        ocr = SimpleNamespace()

    def make(has_ok):
        c = Fake.__new__(Fake)
        c.events, c.cfg = [], {}
        c.log = c.events.append
        c.find = lambda name, screen=None, threshold=None, region=None: SimpleNamespace(score=1.0) if (has_ok and name == "select_crest_ok") else None
        c.confirm_word = lambda screen: (359, 1100)
        c.target_reached = lambda: False
        c.tap = lambda x, y, settle=0: c.events.append(("tap", x, y))
        c.wait_for = lambda names, t: SimpleNamespace(score=1.0)
        c.tap_match = lambda m, settle=0: c.events.append("tap ok2")
        return c

    original = engine.CrestScript.scrap
    engine.CrestScript.scrap = lambda self, screen: self.events.append("original scrap")
    try:
        c = make(has_ok=False)                    # no OK, no Redeploy: the Confirm button is tapped, then the confirmation
        c.scrap(None)
        assert ("tap", 359, 1100) in c.events and "tap ok2" in c.events and "original scrap" not in c.events
        c = make(has_ok=True)                     # the usual OK is there: the original code runs untouched
        c.scrap(None)
        assert c.events == ["original scrap"]
    finally:
        engine.CrestScript.scrap = original



class ScrollDevice:
    """A device whose Crest Palace list scrolls: `pages` are the screens, each swipe moves one page."""

    def __init__(self, pages):
        self.pages, self.i, self.swipes = pages, 0, []

    def swipe(self, x1, y1, x2, y2, ms=300):
        self.swipes.append("down" if y2 < y1 else "up")
        self.i = max(0, min(len(self.pages) - 1, self.i + (1 if y2 < y1 else -1)))


def scrolling_rec(root, pages):
    from types import SimpleNamespace
    r = Rec(root)
    dev = ScrollDevice(pages)
    r.crest.ctx = SimpleNamespace(device=dev)
    r.crest.sleep = lambda *a, **k: None
    r.crest.grab = lambda: dev.pages[dev.i].copy()
    r.tap_pages = []
    r.crest.tap = lambda x, y, settle=0.6: (r.taps.append((x, y)), r.tap_pages.append(dev.i))
    return r, dev


def test_a_palace_below_the_fold_is_found_by_scrolling_and_tapped_where_it_was_found():
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        top = shot.copy()
        top[500:700] = 40                                                    # Whirlwind is not visible yet
        r, dev = scrolling_rec(root, [top, shot])
        assert r.run(top) and len(r.taps) == 1 and 520 < r.taps[0][1] < 680, r.taps
        assert dev.swipes == ["down"] and r.tap_pages == [1], (dev.swipes, r.tap_pages)       # tapped while still scrolled
        assert "scrolling 1 page" in r.logs[-1], r.logs
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_list_that_does_not_move_ends_the_search_and_runs_no_other_palace():
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        top = shot.copy()
        top[500:700] = 40
        r, dev = scrolling_rec(root, [top])                                  # a swipe changes nothing: end of the list
        assert not r.run(top) and not r.taps and dev.swipes == ["down"], (r.taps, dev.swipes)
        assert "no other palace" in r.notes[-1] and "scrolled the list" in r.notes[-1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_missing_picture_falls_back_to_the_palace_name_read_from_the_screen():
    from rerun import ocr as engine_ocr
    try:
        reader = engine_ocr.get_ocr()
    except engine_ocr.OcrUnavailable:
        print("skip: no text reader here")
        return
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        (root / "images" / "shrine_of_whirlwind.png").unlink()               # no picture for today's palace
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        r = Rec(root)
        assert not r.run(shot) and not r.taps                                # without a reader: stops, as before
        assert "picture is missing" in r.notes[-1]
        r.crest._ocr = reader
        assert r.run(shot) and len(r.taps) == 1 and 520 < r.taps[0][1] < 680, (r.taps, r.notes)
        assert "name read from the screen" in r.logs[-1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_in_the_hours_the_clocks_disagree_the_schedule_days_palace_is_a_second_choice_only():
    from rerun.checklist import GAME_TZ
    root, shot = palace_root()
    try:
        # 03:00 on the game clock = 09:00 UTC = 01:00 PST: the schedule screen is already on the next day.
        in_window = datetime(2026, 11, 17, 3, 0, tzinfo=GAME_TZ)            # game day Monday, schedule screen Tuesday
        outside = datetime(2026, 11, 16, 12, 0, tzinfo=GAME_TZ)             # Monday midday: both clocks say Monday
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Monday": "Shrine of Cursed Claw",
                                                                  "Tuesday": "Shrine of Whirlwind"}))
        alt = palaces.alt_choice(root, in_window)
        assert alt is not None and alt.palace.name == "Shrine of Whirlwind" and alt.day == "Tuesday"
        assert palaces.alt_choice(root, outside) is None                     # the two clocks agree: no second choice
        assert palaces.alt_choice(root, datetime(2026, 11, 17, 6, 0, tzinfo=GAME_TZ)) is None  # the game day has turned over: they agree
        assert palaces.choose(root, in_window).palace.name == "Shrine of Cursed Claw"   # the game day is still Monday
        cut = shot.copy()
        cut[330:490] = 40                                                    # Monday's palace is gone from the screen
        r = Rec(root)
        r.crest.CLOCK_NOW = lambda: in_window
        assert r.run(cut) and len(r.taps) == 1 and 520 < r.taps[0][1] < 680, (r.taps, r.notes)
        assert "next day" in r.logs[-1] and "Whirlwind" in r.logs[-1]
        r.taps.clear()
        r.crest._tile_taps = 0
        r.crest.CLOCK_NOW = lambda: outside                                  # outside the window: stop, as before
        assert not r.run(cut) and not r.taps and "no other palace" in r.notes[-1]
        palaces.save_schedule(root, palaces.Schedule("off"))
        assert palaces.alt_choice(root, in_window) is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_tile_that_never_opens_is_tapped_a_few_times_and_then_the_run_stops():
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        r = Rec(root)
        for _ in range(LiteCrest.TILE_TAP_LIMIT):
            assert r.run(shot)                                               # the game keeps showing the same list
        assert len(r.taps) == LiteCrest.TILE_TAP_LIMIT
        assert not r.run(shot) and len(r.taps) == LiteCrest.TILE_TAP_LIMIT   # the next one stops instead of tapping again
        assert "never left the Crest Palace screen" in r.notes[-1]
        r.crest._tile_taps = 0                                               # reaching the quest list starts the count again
        assert r.run(shot)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_banner_that_matches_no_palace_picture_is_found_by_its_place_in_the_stack():
    from rerun_lite.crest import unknown_banners
    root, shot = palace_root()                                       # pictures for Cursed Claw (y~410) and Whirlwind (y~600)
    try:
        def pics(*names):
            return [(n, cv2.imread(str(root / "images" / f"{palaces.slug(n)}.png"))) for n in names]
        both = unknown_banners(shot, pics("Shrine of Cursed Claw", "Shrine of Whirlwind"))
        assert both and all(abs(y - 410) > 80 and abs(y - 600) > 80 for y in both), both          # only banners that are in neither
        only_whirl = unknown_banners(shot, pics("Shrine of Whirlwind"))
        assert any(abs(y - 410) < 50 for y in only_whirl) and not any(abs(y - 600) < 80 for y in only_whirl), only_whirl
        assert unknown_banners(shot, pics()) == []                   # nothing known on the screen: no anchor, no guess
        home = cv2.imread(str(ROOT / "tests" / "fixtures" / "home.png"))
        assert unknown_banners(home, pics("Shrine of Cursed Claw", "Shrine of Whirlwind")) == []   # not the Crest Palace screen
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_crest_warns_once_in_the_log_about_a_banner_missing_from_the_list_and_still_opens_today():
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        r = Rec(root)
        assert r.run(shot) and len(r.taps) == 1, (r.taps, r.notes)                                # today's palace still opens
        warned = [m for m in r.logs if "matches none of the pictures" in m]
        assert warned, r.logs                                                                      # the other banners are not in this list
        n = len(warned)
        r.crest._tile_taps = 0
        r.run(shot)
        assert len([m for m in r.logs if "matches none of the pictures" in m]) == n               # said once each, not every time
    finally:
        shutil.rmtree(root, ignore_errors=True)

def test_a_palace_that_is_nowhere_on_the_list_leaves_the_list_scrolled_back_to_the_top():
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        top = shot.copy()
        top[500:700] = 40
        other = top.copy()
        other[330:490] = 90                                                  # a different page, still without Whirlwind
        r, dev = scrolling_rec(root, [top, other])
        assert not r.run(top) and not r.taps and dev.i == 0, (r.taps, dev.i)
        assert dev.swipes == ["down", "down", "up"], dev.swipes               # down, found the end, back up
        assert "no other palace" in r.notes[-1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_second_choice_is_used_only_when_todays_palace_is_nowhere_on_the_list():
    from rerun.checklist import GAME_TZ
    root, shot = palace_root()
    try:
        in_window = datetime(2026, 11, 17, 3, 0, tzinfo=GAME_TZ)             # game day Monday, schedule screen already Tuesday
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Monday": "Shrine of Cursed Claw",
                                                                  "Tuesday": "Shrine of Whirlwind"}))
        page1 = shot.copy()
        page1[330:490] = 40                                                  # Monday's palace is further down the list
        page2 = shot.copy()
        page2[520:680] = 40                                                  # (and the second choice is on the first page only)
        r, dev = scrolling_rec(root, [page1, page2])
        r.crest.CLOCK_NOW = lambda: in_window
        assert r.run(page1) and len(r.taps) == 1, (r.taps, r.notes)
        assert r.tap_pages == [1] and 330 < r.taps[0][1] < 490, (r.tap_pages, r.taps)   # Monday's palace, on the lower page
        assert "next day" not in r.logs[-1]
        r2, dev2 = scrolling_rec(root, [page1])                              # Monday's palace is nowhere: now the second choice
        r2.crest.CLOCK_NOW = lambda: in_window
        assert r2.run(page1) and 520 < r2.taps[0][1] < 680 and "next day" in r2.logs[-1], (r2.taps, r2.logs)
    finally:
        shutil.rmtree(root, ignore_errors=True)



def test_times_playable_is_read_from_the_real_temple_screen_and_not_from_other_screens():
    from rerun import ocr as engine_ocr
    from rerun_lite import palace_find as lc
    try:
        reader = engine_ocr.get_ocr()
    except engine_ocr.OcrUnavailable:
        print("skip: no text reader here")
        return
    fx = ROOT / "tests" / "fixtures"
    assert lc.times_playable(reader, cv2.imread(str(fx / "live_temple_quest_list.png"))) == 3     # 'Times playable x3'
    for other in ("live_frigidity_quest_list", "live_crest_palace_top", "live_schedule_crest_palace"):
        assert lc.times_playable(reader, cv2.imread(str(fx / f"{other}.png"))) is None, other


def test_a_palace_with_no_plays_left_stops_with_a_clear_message_and_otherwise_just_logs():
    from rerun_lite import palace_find as lc
    r = Rec(palace_root()[0])
    r.crest._ocr = object()                                         # only its presence matters: the reading is replaced below
    real = lc.times_playable
    try:
        lc.times_playable = lambda ocr, screen: 0
        try:
            r.crest._check_plays_left(None)
            raise AssertionError("x0 must stop the run")
        except Finished:
            pass
        assert "no plays left today" in r.notes[-1] and "4:00 AM PST" in r.notes[-1]
        lc.times_playable = lambda ocr, screen: 2
        r.crest._check_plays_left(None)
        r.crest._check_plays_left(None)
        assert [m for m in r.logs if "Plays left today" in m] == ["Plays left today in this palace: 2 (it resets at 4:00 AM PST)"]
        n = len(r.notes)
        lc.times_playable = lambda ocr, screen: None                # not read clearly: nothing happens
        r.crest._check_plays_left(None)
        lc.times_playable = lambda ocr, screen: (_ for _ in ()).throw(ValueError("bad frame"))
        r.crest._check_plays_left(None)                             # a reading error never stops a run
        assert len(r.notes) == n
    finally:
        lc.times_playable = real

def test_a_stop_for_a_palace_not_found_keeps_a_picture_of_the_screen():
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        palaces.save_schedule(root, palaces.Schedule("weekday", {today: "Shrine of Whirlwind"}))
        blank = shot.copy()
        blank[300:720] = 40
        r = Rec(root)
        saved = []
        r.crest.save_frame = lambda tag, screen=None: (saved.append(tag), "C:/debug/x_palace_not_found.png")[1]
        assert not r.run(blank) and saved == ["palace_not_found"]
        assert "saved to C:/debug/x_palace_not_found.png" in r.notes[-1] and "no other palace" in r.notes[-1]
        r.crest.save_frame = lambda tag, screen=None: (_ for _ in ()).throw(OSError("disk full"))
        assert not r.run(blank) and "no other palace" in r.notes[-1] and "saved to" not in r.notes[-1]   # a save problem never hides the stop
        r.crest._tile_taps = LiteCrest.TILE_TAP_LIMIT
        r.crest.save_frame = lambda tag, screen=None: (saved.append(tag), "C:/debug/y.png")[1]
        assert not r.run(shot) and saved[-1] == "palace_tile_stuck" and "saved to C:/debug/y.png" in r.notes[-1]
    finally:
        shutil.rmtree(root, ignore_errors=True)



def test_the_games_schedule_screen_is_read_into_dated_palace_entries():
    from rerun import ocr as engine_ocr
    try:
        reader = engine_ocr.get_ocr()
    except engine_ocr.OcrUnavailable:
        print("skip: no text reader here")
        return
    names = [p.name for p in palaces.read_list(ROOT)]
    fx = ROOT / "tests" / "fixtures"

    def entries(n):
        img = cv2.imread(str(fx / n))
        return palaces.parse_schedule(reader.screen_words(img, min_conf=40), names, 2026, today=date(2026, 11, 19))
    first = entries("live_schedule_crest_palace.png")
    got = [(str(e.date), e.name) for e in first]
    assert ("2026-11-18", "Shrine of the Azul Knight") in got and ("2026-11-18", "Shrine of Frigidity") in got, got
    assert ("2026-11-18", "Shrine of Diamond Dust") in got and ("2026-11-18", "Shrine of Effulgence") in got, got
    azul = next(e for e in first if e.name == "Shrine of the Azul Knight")
    assert azul.known and azul.start == "11/18 0:00" and azul.end == "11/18 23:59"           # a one-day slot, as the game shows it
    eff = next(e for e in first if e.name == "Shrine of Effulgence")
    assert eff.start == "11/17 18:00" and eff.end == "11/30 17:59"                            # the limited palace runs for days
    second = {(str(e.date), e.name) for e in entries("live_schedule_crest_palace_2.png")}
    assert {("2026-11-20", "Shrine of Adamantine"), ("2026-11-20", "Shrine of Caliginosity")} <= second, second
    third = {(str(e.date), e.name) for e in entries("live_schedule_crest_palace_3.png")}      # the heading is on an earlier page:
    assert {("2026-11-22", "Shrine of Discordia"), ("2026-11-22", "Shrine of Sagacity")} <= third, third   # the slot dates itself
    odd = palaces.parse_schedule([], names, 2026, today=date(2026, 11, 19))
    assert odd == []


def test_a_palace_the_game_lists_but_the_list_lacks_is_marked_unknown_and_the_plan_is_checked_day_by_day():
    from rerun.ocr import Word
    names = ["Shrine of Perdition", "Shrine of Crimson Sea", "Shrine of Whirlwind"]

    def row(y, text):
        return [Word(t, 90.0, x, y, 70, 20) for t, x in zip(text.split(), (248, 323, 352, 420))]
    words = [Word("11/23(MON)", 90.0, 5, 359, 130, 24), Word("Crest", 90.0, 140, 434, 40, 12), Word("Palace", 90.0, 188, 434, 50, 13)]
    words += row(432, "Shrine of Subspace")
    words += [Word("11/23", 90.0, 220, 468, 40, 14), Word("0:00", 90.0, 285, 465, 40, 25),
              Word("11/23", 90.0, 220, 502, 40, 14), Word("23:59", 90.0, 285, 502, 40, 14)]
    e = palaces.parse_schedule(words, names, 2026, today=date(2026, 11, 19))
    assert len(e) == 1 and e[0].name == "Shrine of Subspace" and not e[0].known and e[0].date == date(2026, 11, 23), e
    root, _shot = palace_root()
    try:
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Monday": "Shrine of Whirlwind", "Tuesday": "Shrine of Whirlwind"}))
        plan = palaces.plan_vs_schedule([e[0], palaces.SchedEntry(date(2026, 11, 24), "Shrine of Whirlwind", True, "11/24 0:00", "11/24 23:59")], root)
        assert [(r["day"], r["ok"]) for r in plan] == [("Monday", False), ("Tuesday", True)], plan
        palaces.save_schedule(root, palaces.Schedule("off"))
        assert all(not r["ok"] and r["chosen"] is None for r in palaces.plan_vs_schedule(e, root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_backup_palace_is_off_by_default_ordered_and_saved_with_the_schedule():
    root, shot = palace_root()
    try:
        assert palaces.load_schedule(root).backup_on is False and palaces.load_schedule(root).backup == []
        palaces.save_schedule(root, palaces.Schedule("weekday", {"Monday": "Shrine of Whirlwind"}, backup=["Shrine of Cursed Claw"]))
        s = palaces.load_schedule(root)
        assert s.backup == ["Shrine of Cursed Claw"] and s.backup_on is False
        assert palaces.backup_choices(root) == []                               # a list alone does nothing: the switch is off
        palaces.save_schedule(root, palaces.Schedule("weekday", {}, backup_on=True,
                                                     backup=["Shrine of Cursed Claw", "No Such Palace", "Shrine of Whirlwind", "shrine of cursed claw"]))
        got = [c.palace.name for c in palaces.backup_choices(root, {"Shrine of Whirlwind"})]
        assert got == ["Shrine of Cursed Claw"], got                           # unknown names, the skipped one and repeats are dropped
        assert all(c.day == "backup" for c in palaces.backup_choices(root))
        palaces.save_schedule(root, palaces.Schedule("off", {}, backup_on=True, backup=["Shrine of Cursed Claw"]))
        assert palaces.backup_choices(root) == []                               # selector off: no backups either
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_crest_runs_a_backup_palace_only_when_the_user_turned_it_on_and_says_so():
    root, shot = palace_root()
    try:
        today = palaces.DAYS[palaces.game_date().weekday()]
        gone = shot.copy()
        gone[520:680] = 40                                                      # today's palace (Whirlwind) is not on the screen
        week = {today: "Shrine of Whirlwind"}
        palaces.save_schedule(root, palaces.Schedule("weekday", week, backup_on=False, backup=["Shrine of Cursed Claw"]))
        r = Rec(root)
        assert not r.run(gone) and not r.taps and "no other palace" in r.notes[-1]        # off: it stops, as always
        palaces.save_schedule(root, palaces.Schedule("weekday", week, backup_on=True, backup=["Shrine of Perdition", "Shrine of Cursed Claw"]))
        r = Rec(root)
        assert r.run(gone) and len(r.taps) == 1 and 330 < r.taps[0][1] < 490, (r.taps, r.notes)   # Perdition has no picture: skipped
        assert "BACKUP palace" in r.logs[-1] and "Shrine of Whirlwind" in r.logs[-1] and "Cursed Claw" in r.logs[-1]
        assert any("backup palace" in n and "Cursed Claw" in n for n in r.notes)                  # and it tells you
        r = Rec(root)
        assert r.run(shot) and "BACKUP" not in r.logs[-1] and 520 < r.taps[0][1] < 680            # today's palace is on: no backup
        nothing = shot.copy()
        nothing[300:720] = 40
        r = Rec(root)
        assert not r.run(nothing) and not r.taps and "no other palace" in r.notes[-1]             # backups missing too: still stops
        assert "also tried" in r.notes[-1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_settings_page_saves_the_backup_switch_and_names_and_flags_unknown_ones():
    root, m, inst, app = open_lite()
    try:
        extra, _ = palace_root()
        shutil.copytree(extra / "images", root / "images")
        (root / "palaces.yaml").write_text("Shrine of Cursed Claw: images/shrine_of_cursed_claw.png\n"
                                           "Shrine of Whirlwind: images/shrine_of_whirlwind.png\n", encoding="utf-8")
        shutil.rmtree(extra, ignore_errors=True)
        app._set_nav.select("palaces")
        app.update()
        assert "Run a backup palace" in " ".join(texts(app._set_pages["palaces"]))
        assert app._pal_backup_on.get() is False
        app._pal_mode.set(palaces.MODES["weekday"])
        app._pal_backup_on.set(True)
        app._pal_backup_var.set("Shrine of Whirlwind, Typo Palace")
        app._pal_save()
        s = palaces.load_schedule(root)
        assert s.backup_on is True and s.backup == ["Shrine of Whirlwind", "Typo Palace"]
        app._pal_save()                                                         # saving again from the page keeps them
        assert palaces.load_schedule(root).backup_on is True
        assert not app.errors, app.errors
    finally:
        close(app, root)


def test_a_palace_is_added_with_its_picture_and_never_replaces_anything():
    root, shot = palace_root()
    try:
        before = (root / "palaces.yaml").read_bytes()
        pic = palaces.cut_banner(shot, 410)
        assert pic.shape[0] > 100 and pic.shape[1] > 600                      # the banner, inside its frame
        p = palaces.add_palace(root, "  Shrine   of Subspace ", pic)
        assert p.name == "Shrine of Subspace" and p.image == "images/shrine_of_subspace.png"
        assert (root / p.image).is_file() and palaces.find(palaces.read_list(root), "shrine of subspace") is not None
        assert (root / "palaces.yaml").read_bytes().startswith(before)         # lines already there are untouched
        for bad, why in (("Shrine of Subspace", "already in"), ("", "Give the palace a name"), ("Bad: name", "cannot contain"),
                         ("# note", "cannot contain")):
            try:
                palaces.add_palace(root, bad, pic)
                raise AssertionError(bad)
            except ValueError as e:
                assert why in str(e), (bad, str(e))
        (root / "images" / "shrine_of_new.png").write_bytes(b"keep me")        # a picture of that name already exists
        try:
            palaces.add_palace(root, "Shrine of New", pic)
            raise AssertionError("must not replace a picture")
        except ValueError as e:
            assert "already exists" in str(e)
        assert (root / "images" / "shrine_of_new.png").read_bytes() == b"keep me"
        assert palaces.find(palaces.read_list(root), "Shrine of New") is None   # and no line was added for it
        try:
            palaces.add_palace(root, "Shrine of Nothing", None)
            raise AssertionError("no picture")
        except ValueError:
            pass
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_added_palaces_follow_the_files_line_endings_and_a_missing_list_is_started():
    root, shot = palace_root()
    try:
        crlf = chr(13) + chr(10)
        (root / "palaces.yaml").write_bytes(("Shrine of Whirlwind: images/shrine_of_whirlwind.png" + crlf).encode())
        palaces.add_palace(root, "Shrine of Subspace", palaces.cut_banner(shot, 410))
        raw = (root / "palaces.yaml").read_bytes().decode()
        assert raw == ("Shrine of Whirlwind: images/shrine_of_whirlwind.png" + crlf + "Shrine of Subspace: images/shrine_of_subspace.png" + crlf)
        (root / "palaces.yaml").write_bytes(b"Shrine of Whirlwind: images/shrine_of_whirlwind.png")       # no line ending at the end
        palaces.add_palace(root, "Shrine of Oblivion", palaces.cut_banner(shot, 410))
        assert [p.name for p in palaces.read_list(root)] == ["Shrine of Whirlwind", "Shrine of Oblivion"]
        (root / "palaces.yaml").unlink()
        palaces.add_palace(root, "Shrine of Eternity", palaces.cut_banner(shot, 410))
        assert [p.name for p in palaces.read_list(root)] == ["Shrine of Eternity"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_settings_buttons_check_the_screen_and_add_the_missing_palace_from_it():
    import cv2
    from rerun import ios
    root, m, inst, app = open_lite()
    shown, asked = [], []
    real_alert, real_ask = ios.alert, ios.ask_string
    try:
        fx = ROOT / "tests" / "fixtures"
        screen = cv2.imread(str(fx / "live_crest_palace_top.png"))               # Effulgence, Frigidity, Diamond Dust, Azul Knight
        (root / "images").mkdir(exist_ok=True)
        lines = []
        for name in ("Shrine of Frigidity", "Shrine of Diamond Dust", "Shrine of the Azul Knight"):
            slug = palaces.slug(name)
            shutil.copy(ROOT / "images" / f"{slug}.png", root / "images" / f"{slug}.png")
            lines.append(f"{name}: images/{slug}.png")
        (root / "palaces.yaml").write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        ios.alert = lambda parent, message, title="Rerun": shown.append(message)
        ios.ask_string = lambda parent, title, message, initial="": (asked.append(message), "Shrine of Effulgence")[1]
        app._pal_sync = True
        m.screenshot = lambda name: screen
        app._set_nav.select("palaces")
        app.update()
        assert "Check the Crest Palace screen" in " ".join(texts(app._set_pages["palaces"]))
        app._pal_check_now()
        assert "Shrine of Frigidity" in shown[-1] and "Shrine of Diamond Dust" in shown[-1] and "1 banner(s) match none" in shown[-1], shown
        shown.clear()
        app._pal_add_from_screen()
        assert asked and "matches none of your palaces" in asked[-1], asked
        assert (root / "images" / "shrine_of_effulgence.png").is_file()
        assert palaces.find(palaces.read_list(root), "Shrine of Effulgence") is not None
        app.update()
        app._pal_check_now()
        assert "Shrine of Effulgence" in shown[-1] and "match none" not in shown[-1], shown      # now it is recognised
        n = len(asked)
        app._pal_add_from_screen()
        assert len(asked) == n and "matches a picture in your list" in shown[-1], shown[-1]      # nothing left to add
        m.screenshot = lambda name: (_ for _ in ()).throw(OSError("device offline"))
        app._pal_check_now()
        assert "Could not get a screenshot" in shown[-1] and "device offline" in shown[-1]
        m.screenshot = lambda name: np.full((1280, 720, 3), 30, np.uint8)
        app._pal_check_now()
        assert "None of your palaces is on this screen" in shown[-1]
        assert not app.errors, app.errors
    finally:
        ios.alert, ios.ask_string = real_alert, real_ask
        close(app, root)


def test_the_fast_two_pass_search_gives_the_same_answer_as_the_exact_one():
    from rerun_lite.crest import MATCH_MIN, find_tile, find_tile_exact
    fx = ROOT / "tests" / "fixtures"
    names = ["Shrine of Frigidity", "Shrine of the Azul Knight", "Temple of Heavenly Light", "Shrine of Effulgence", "Shrine of Whirlwind"]
    pics = {n: cv2.imread(str(ROOT / "images" / f"{palaces.slug(n)}.png")) for n in names}
    for f in ("live_crest_palace_top.png", "live_crest_palace_scrolled.png", "crest_palace_list.png"):
        screen = cv2.imread(str(fx / f))
        for n, pic in pics.items():
            exact, fast = find_tile_exact(screen, pic), find_tile(screen, pic)
            assert abs(exact[0] - fast[0]) < 0.03, (f, n, exact, fast)
            assert (exact[0] >= MATCH_MIN) == (fast[0] >= MATCH_MIN), (f, n, exact, fast)       # the same yes or no
            if exact[0] >= MATCH_MIN:
                assert abs(exact[1] - fast[1]) <= 3 and abs(exact[2] - fast[2]) <= 3, (f, n, exact, fast)   # on the same spot
    assert find_tile(np.zeros((100, 100, 3), np.uint8), pics["Shrine of Frigidity"])[0] == 0.0   # a picture that cannot fit


def test_a_misread_heading_does_not_misdate_a_one_day_slot_and_an_implausible_one_is_ignored():
    from rerun.ocr import Word
    names = ["Shrine of Eternity", "Shrine of Effulgence"]

    def entry(y, name, start, end, sh, eh):
        w = [Word("Crest", 90.0, 140, y, 40, 12), Word("Palace", 90.0, 188, y, 50, 13)]
        w += [Word(t, 90.0, 248 + 60 * i, y - 2, 60, 18) for i, t in enumerate(name.split())]
        w += [Word(start.split()[0], 90.0, 220, y + 34, 40, 14), Word(sh, 90.0, 285, y + 32, 40, 25),
              Word(end.split()[0], 90.0, 220, y + 68, 40, 14), Word(eh, 90.0, 285, y + 68, 40, 14)]
        return w
    words = [Word("1/19(THU)", 90.0, 5, 359, 130, 24)]                                 # the big heading lost a digit: 11/19 read as 1/19
    words += entry(432, "Shrine of Eternity", "11/19 0:00", "11/19 23:59", "0:00", "23:59")
    words += entry(573, "Shrine of Effulgence", "11/17 18:00", "11/30 17:59", "18:00", "17:59")   # a long slot: only the heading dates it
    got = palaces.parse_schedule(words, names, today=date(2026, 11, 19))
    eternity = next(e for e in got if e.name == "Shrine of Eternity")
    assert eternity.date == date(2026, 11, 19), eternity                                # dated by its own start and end, not the heading
    eff = next(e for e in got if e.name == "Shrine of Effulgence")
    assert eff.date is None, eff                                                         # a heading of 1/19 is not a believable date
    words[0] = Word("11/19(THU)", 90.0, 5, 359, 130, 24)
    eff = next(e for e in palaces.parse_schedule(words, names, today=date(2026, 11, 19)) if e.name == "Shrine of Effulgence")
    assert eff.date == date(2026, 11, 19)                                                # a good heading dates the long slot

if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
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
