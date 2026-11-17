"""Crest Palace selector time zones: a zone only changes how each palace's slot is SHOWN (start and end in your local
day and time); which palace runs is still decided by the game day. No window needed.   Run:  py tests/test_palace_timezone.py"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun_lite import palaces  # noqa: E402

GAME = timezone(timedelta(hours=-6))
NAMES = ["Shrine of Perdition", "Shrine of Crimson Sea", "Shrine of Diamond Dust", "Shrine of Eternity",
         "Shrine of Caliginosity", "Shrine of Cursed Claw", "Shrine of Tribulation"]


def make_root(mode: str = "weekday", tz: str | None = None, missing: str = "") -> Path:
    root = Path(tempfile.mkdtemp(prefix="lite_tz_"))
    (root / "images").mkdir()
    lines = []
    for n in NAMES:
        rel = f"images/{palaces.slug(n)}.png"
        lines.append(f"{n}: {rel}\n")
        if n != missing:
            cv2.imwrite(str(root / rel), np.full((20, 20, 3), 90, np.uint8))
    (root / "palaces.yaml").write_text("".join(lines), encoding="utf-8")
    body = {"mode": mode, "week": dict(zip(palaces.DAYS, NAMES)), "cycle": {"start": NAMES[0], "anchor": "2026-11-16", "only": []}}
    if tz is not None:
        body["timezone"] = tz
    (root / "data" / "lite").mkdir(parents=True)
    (root / palaces.SCHEDULE_FILE).write_text(json.dumps(body), encoding="utf-8")
    return root


def at(y, m, d, h, mi=0, tz=GAME) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=tz)


def test_zone_choices_parse_and_bad_values_fall_back_to_the_computer():
    assert palaces.normalize_tz("UTC+10:00") == "UTC+10:00"
    assert palaces.normalize_tz("UTC-6:00") == "UTC-06:00"
    assert palaces.normalize_tz("UTC+5:30") == "UTC+05:30"
    for bad in ("", "Guam", "UTC+15:00", "UTC-13:00", "UTC+10:75", None):
        assert palaces.normalize_tz(bad) == palaces.TZ_COMPUTER, bad
    assert palaces.parse_tz("computer") is None and palaces.parse_tz("UTC+10:00").utcoffset(None) == timedelta(hours=10)
    choices = palaces.tz_choices()
    assert choices[0][0] == palaces.TZ_COMPUTER
    values = [v for v, _ in choices]
    assert len(values) == len(set(values)) and "UTC+10:00" in values and "UTC-06:00" in values and "UTC+05:45" in values
    assert all(palaces.normalize_tz(v) == v for v in values)                     # every choice survives save and load


def test_a_slot_is_the_game_day_written_in_your_zone():
    # Game Monday 16 Nov 2026 runs 06:00 UTC-6 Mon to 06:00 UTC-6 Tue = 12:00 UTC.
    start, end = palaces.slot_times(date(2026, 11, 16))
    assert start == at(2026, 11, 16, 6) and end == at(2026, 11, 17, 6)
    assert palaces.fmt_slot(start, end, "UTC+10:00") == "Mon 22:00 to Tue 22:00 (UTC+10:00)"      # Guam
    assert palaces.fmt_slot(start, end, "UTC-06:00") == "Mon 06:00 to Tue 06:00 (UTC-06:00)"      # the game clock itself
    assert palaces.fmt_slot(start, end, "UTC+09:00") == "Mon 21:00 to Tue 21:00 (UTC+09:00)"      # Tokyo
    assert palaces.fmt_slot(start, end, "UTC+05:30") == "Mon 17:30 to Tue 17:30 (UTC+05:30)"      # India
    assert palaces.fmt_slot(start, end, "UTC-08:00") == "Mon 04:00 to Tue 04:00 (UTC-08:00)"      # US Pacific, standard time
    assert palaces.fmt_slot(start, end, "UTC+14:00") == "Tue 02:00 to Wed 02:00 (UTC+14:00)"      # starts on the NEXT local day


def test_the_palace_of_each_slot_follows_the_game_day_whatever_the_zone():
    root = make_root()
    try:
        now = at(2026, 11, 16, 12)                                                # game Monday
        by_zone = {z: palaces.slots(root, 7, now, z) for z in ("UTC+10:00", "UTC-06:00", "UTC+14:00", "UTC-12:00")}
        for z, week in by_zone.items():
            assert [s.palace.name for s in week] == NAMES, z                    # same palaces, same order, any zone
            assert [s.day for s in week] == list(palaces.DAYS), z
        guam = by_zone["UTC+10:00"]
        assert [s.local_day for s in guam] == list(palaces.DAYS)                  # Guam: each game day starts that evening
        assert guam[0].start == at(2026, 11, 16, 22, tz=timezone(timedelta(hours=10)))
        assert [s.local_day for s in by_zone["UTC+14:00"]] == list(palaces.DAYS[1:]) + ["Monday"]   # a day later
        # a slot is exactly 24 hours long and the slots follow one another with no gap
        for week in by_zone.values():
            assert all(s.end - s.start == timedelta(days=1) for s in week)
            assert all(a.end == b.start for a, b in zip(week, week[1:]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_choosing_a_zone_never_changes_what_crest_runs():
    root = make_root()
    try:
        for hour_utc in range(0, 24):                                              # every hour of a day, around the reset
            now = datetime(2026, 11, 17, hour_utc, 0, tzinfo=timezone.utc)
            baseline = palaces.choose(root, now)
            for z in ("computer", "UTC+10:00", "UTC-12:00", "UTC+14:00"):
                s = palaces.load_schedule(root)
                s.timezone = z
                palaces.save_schedule(root, s)
                c = palaces.choose(root, now)
                assert (c.palace, c.day, c.game_date, c.problem) == (baseline.palace, baseline.day, baseline.game_date, baseline.problem), (hour_utc, z)
        # 11:59 UTC is still game Monday, 12:00 UTC (06:00 UTC-6) is game Tuesday
        assert palaces.choose(root, datetime(2026, 11, 17, 11, 59, tzinfo=timezone.utc)).palace.name == NAMES[0]
        assert palaces.choose(root, datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)).palace.name == NAMES[1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_old_schedule_files_without_a_zone_still_load_and_the_zone_is_saved():
    root = make_root(tz=None)
    try:
        s = palaces.load_schedule(root)
        assert s.timezone == palaces.TZ_COMPUTER and s.mode == "weekday" and s.week["Monday"] == NAMES[0]
        s.timezone = "UTC+10:00"
        palaces.save_schedule(root, s)
        raw = json.loads((root / palaces.SCHEDULE_FILE).read_text(encoding="utf-8"))
        assert raw["timezone"] == "UTC+10:00" and raw["week"]["Monday"] == NAMES[0] and raw["mode"] == "weekday"
        assert palaces.load_schedule(root).timezone == "UTC+10:00"
        raw["timezone"] = "nonsense"                                               # a hand-edited bad value falls back
        (root / palaces.SCHEDULE_FILE).write_text(json.dumps(raw), encoding="utf-8")
        assert palaces.load_schedule(root).timezone == palaces.TZ_COMPUTER
        assert palaces.Schedule("weekday", {"Monday": "x"}).timezone == palaces.TZ_COMPUTER      # old 2-argument calls still work
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cycle_mode_slots_and_problems_are_reported_per_slot():
    root = make_root("cycle", "UTC+10:00", missing="Shrine of Crimson Sea")
    try:
        week = palaces.slots(root, 8, at(2026, 11, 16, 12))
        assert [s.palace.name for s in week[:7]] == NAMES and week[7].palace.name == NAMES[0]       # wraps around
        assert week[1].problem.startswith("picture missing") and not week[0].problem and not week[2].problem
        off = make_root("off")
        try:
            assert all(s.palace is None and s.problem for s in palaces.slots(off, 3, at(2026, 11, 16, 12)))
        finally:
            shutil.rmtree(off, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_weekday_row_label_is_the_next_slot_of_that_weekday():
    root = make_root(tz="UTC+10:00")
    try:
        now = at(2026, 11, 18, 9)                                                  # game Wednesday
        wed = palaces.next_slot_for_day(root, "Wednesday", now)
        assert wed.game_date == date(2026, 11, 18)                                 # today's slot, not next week's
        mon = palaces.next_slot_for_day(root, "Monday", now)
        assert mon.game_date == date(2026, 11, 23) and mon.palace.name == NAMES[0]
        assert palaces.fmt_slot(mon.start, mon.end, "UTC+10:00") == "Mon 22:00 to Tue 22:00 (UTC+10:00)"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_countdown_to_the_switch():
    assert palaces.until_switch(at(2026, 11, 17, 5, 59)) == 60
    assert palaces.until_switch(at(2026, 11, 17, 6, 0)) == 86400
    assert palaces.fmt_left(3 * 3600 + 5 * 60 + 40) == "3h 05m" and palaces.fmt_left(59 * 60) == "59m" and palaces.fmt_left(-5) == "0m"


def test_this_computers_zone_follows_daylight_saving_when_the_pc_does():
    if not hasattr(time, "tzset") or not Path("/usr/share/zoneinfo/America/Los_Angeles").exists():
        print("  (skipped: no time zone database on this machine)")
        return
    old = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        summer, winter = at(2026, 7, 6, 6), at(2026, 12, 7, 6)                      # both game Mondays, reset moment
        assert palaces.fmt_when(summer, "computer") == "Mon 05:00"                  # PDT is UTC-7
        assert palaces.fmt_when(winter, "computer") == "Mon 04:00"                  # PST is UTC-8
        assert palaces.fmt_when(summer, "UTC-08:00") == "Mon 04:00"                 # a fixed offset does not move
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001 - report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {name}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
