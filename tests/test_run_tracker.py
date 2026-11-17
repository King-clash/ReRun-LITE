"""Run phases, the run tracker / session store and the activity categories. No window, no emulator.
Run:  py tests/test_run_tracker.py"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun_lite import feedcat, phases, runs  # noqa: E402


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, s):
        self.t += s


def tracker(**kw):
    d = Path(tempfile.mkdtemp(prefix="lite_runs_"))
    clk = Clock()
    return runs.RunTracker(d / "sessions.jsonl", clock=clk, **kw), clk, d


def test_phases_keep_the_old_status_words_and_add_the_new_ones():
    assert phases.phase_of("idle") == "idle" and phases.phase_of("starting") == "initializing"
    assert phases.phase_of("running") == "running" and phases.phase_of("paused") == "paused"
    assert phases.phase_of("running", script_state="unknown") == "waiting"
    assert phases.phase_of("running", script_state="drop_info") == "running"
    assert phases.phase_of("running", recovering="restarting the game") == "recovering"
    assert phases.phase_of("paused", recovering="x") == "paused"                    # your pause always wins
    assert phases.phase_of("error") == "failed"
    assert phases.phase_of("idle", ended="completed") == "completed"
    assert phases.phase_of("idle", ended="nonsense") == "idle"
    assert set(phases.LABEL) == set(phases.COLOR) == set(phases.PHASES)


def test_how_a_run_ended_is_read_from_the_reason():
    e = phases.end_phase
    assert e("idle", "finished") == "completed" and e("idle", "dry run complete - 5 actions planned, none sent") == "completed"
    assert e("idle", "stopped by user") == "stopped" and e("idle", "stopped") == "stopped"
    assert e("idle", "Session limit of 60 minutes reached") == "stopped"
    for bad in ("stuck on drop_info", "no progress", "game not running", "restart limit reached (3 per game day)",
                "game shows 'maintenance'"):
        assert e("idle", bad) == "failed", bad
    assert e("error", "adb offline") == "failed" and e("idle", "") == "idle"


def test_cycle_times_exclude_the_first_run_and_your_pauses():
    t, clk, d = tracker()
    try:
        t.start_session("A")
        clk.tick(300); t.on_count("A", "crest.runs")                  # first run: 300 s, includes getting to the quest
        clk.tick(100); t.on_count("A", "crest.runs")                  # 100 s
        clk.tick(50); t.pause("A"); clk.tick(1000); t.resume("A")     # paused for 1000 s: not counted
        clk.tick(70); t.on_count("A", "crest.runs")                   # 50 + 70 = 120 s
        live = t.live("A")
        assert live["runs"] == 3 and live["first_run_s"] == 300.0
        assert live["fastest_s"] == 100.0 and live["slowest_s"] == 120.0 and live["avg_s"] == 110.0
        assert live["active_s"] == 300 + 100 + 50 + 70               # the 1000 s pause is not farming time
        assert live["runs_per_hour"] == round(3 / (520 / 3600), 1)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_an_unfinished_cycle_is_interrupted_and_nothing_is_guessed_to_be_a_success():
    t, clk, d = tracker()
    try:
        t.start_session("A")
        clk.tick(200); t.on_count("A", "crest.runs")
        clk.tick(90)                                                  # a cycle is 90 s in when the session is stopped
        rec = t.end_session("A", "stopped: stopped by user")
        assert rec["runs"] == 1 and rec["ended"] == "stopped" and rec["interrupted"] is True and rec["unfinished_s"] == 90
        t.start_session("A")
        clk.tick(10)
        rec2 = t.end_session("A", "finished: all done")
        assert rec2["ended"] == "completed" and rec2["interrupted"] is False and rec2["runs"] == 0
        assert rec2["success_rate"] is None and rec2["avg_s"] is None and rec2["runs_per_hour"] is None   # unknown, not 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_failures_interruptions_and_recoveries_are_counted_apart():
    t, clk, d = tracker()
    try:
        t.start_session("A")
        for key in ("crest.text_popups", "crest.text_popups", "crest.failures", "game_restarts", "crest.unknown"):
            t.on_count("A", key)
        clk.tick(60); t.on_count("A", "crest.runs")                   # a run after the restart: the recovery worked
        t.on_count("A", "game_restarts")                              # a second restart, never followed by a run
        live = t.live("A")
        assert (live["interruptions"], live["failures"], live["recoveries"], live["recovered"]) == (2, 1, 2, 1)
        assert live["recovery_rate"] == 0.5 and live["success_rate"] == 0.5          # 1 run, 1 failure
        rec = t.end_session("A", "error: adb offline")
        assert rec["ended"] == "failed" and rec["unresolved_recoveries"] == 1
        t.on_count("A", "crest.runs")                                 # counts after the session ended are ignored
        assert t.live("A") is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sessions_are_saved_newest_first_trimmed_and_a_damaged_line_is_skipped():
    t, clk, d = tracker(keep=10)
    try:
        for i in range(5):
            t.start_session("A"); clk.tick(10 + i); t.on_count("A", "crest.runs"); t.end_session("A", "finished")
        t.start_session("B"); clk.tick(5); t.end_session("B", "stopped: stopped by user")
        with t.path.open("a", encoding="utf-8") as f:
            f.write("{not json\n")
        got = t.sessions(3)
        assert [r["instance"] for r in got] == ["B", "A", "A"] and got[0]["ended"] == "stopped"
        assert len(t.sessions(100)) == 6 and len(t.sessions(100, "A")) == 5
        assert t.clear() == 6 and t.sessions() == [] and not t.path.exists()
        # retention: far more than `keep` sessions keeps the newest ones only
        t.keep = 10
        for i in range(400):
            t.start_session("A"); clk.tick(1); t.on_count("A", "crest.runs"); t.end_session("A", "finished")
        rows = t.sessions(1000)
        assert 10 <= len(rows) <= 400 and rows[0]["id"] == f"{int(clk.t - 1)}-A"
        t._trim()
        assert len(t.sessions(1000)) <= 30 or t.path.stat().st_size < 64 * 1024
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_dry_run_is_not_saved_as_farming_history():
    t, clk, d = tracker()
    try:
        t.start_session("A", dry_run=True); clk.tick(30)
        assert t.end_session("A", "stopped: dry run complete - 5 actions planned, none sent") is None
        assert t.sessions() == []
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_saved_records_hold_numbers_only_and_stay_small():
    t, clk, d = tracker()
    try:
        t.start_session("A")
        for _ in range(500):
            clk.tick(30); t.on_count("A", "crest.runs")
        rec = t.end_session("A", "finished")
        assert len(rec["cycles"]) == runs.MAX_CYCLES and rec["runs"] == 500
        line = t.path.read_text(encoding="utf-8").splitlines()[0]
        assert len(line) < 4000 and json.loads(line)["instance"] == "A"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_activity_categories():
    c = feedcat.categorize
    assert c("Instance 1", "[Crest] State: drop_info") == "Automation"
    assert c("Instance 1", "[Crest] Game is not running - relaunching") == "Recovery"
    assert c("Instance 1", "[Crest] Read a 'x' popup - tapping OK") == "Recovery"
    assert c("Instance 1", "Unexpected error:\nTraceback", "error") == "Error"
    assert c("Instance 1", "[Crest] could not find the button", "warn") == "Warning"
    assert c("app", "Stats reset") == "System" and c("discord", "Discord connected") == "System"
    assert c("Instance 1", "Started Crest on Instance 1") == "Automation"
    assert c("Instance 1", "something plain") == "Information"
    assert c("Instance 1", "Session ended after 5 min (Crest): finished | 3 run(s), 1 game restart(s)") == "Information"
    assert c("Instance 1", "Recovery started: restarting the game") == "Recovery"
    assert feedcat.collapsed("a\nb\nc") == ("a", 2) and feedcat.collapsed("one") == ("one", 0) and feedcat.collapsed("") == ("", 0)
    assert set(feedcat.CATEGORIES) == {"Information", "Automation", "Warning", "Error", "Recovery", "System"}


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
