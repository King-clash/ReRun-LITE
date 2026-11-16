"""The daily Crest Palace selector: the game-day clock, the list, weekday and cycle choices, the import from GS
Companion (never overwrites), Crest opening only today's palace (and stopping instead of running another), and the
Settings page.   Run:  py tests/test_palaces.py"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
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
