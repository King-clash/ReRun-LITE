import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rerun_lite.stuck import StuckWatch


def test_one_report_per_episode_and_end():
    w = StuckWatch(8)
    assert w.check("A", 100, True, 0) is None
    assert w.check("A", 481, True, 1) == "start" and w.check("A", 500, True, 2) is None
    assert w.stuck_for("A", 500) == 500
    assert w.check("A", 3, True, 3) == "end" and w.stuck_for("A", 3) is None
    assert w.check("A", 600, True, 4) == "start" and w.episodes["A"] == 2


def test_paused_recovering_or_off_never_count():
    w = StuckWatch(8)
    assert w.check("A", 9999, False, 0) is None                # paused / recovering
    w.set_minutes(0)
    assert w.check("A", 9999, True, 0) is None
    w.set_minutes("junk")
    assert w.minutes == 8 and w.check("A", None, True, 0) is None


def test_open_episode_closed_quietly_when_paused():
    w = StuckWatch(5)
    assert w.check("A", 400, True, 0) == "start"
    assert w.check("A", 400, False, 1) is None and w.stuck_for("A", 400) is None
    assert w.check("A", 400, True, 2) == "start"               # a new episode after the pause, if still idle
