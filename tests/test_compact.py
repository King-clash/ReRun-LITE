"""Compact-mode summary and the activity feed's pure parts (no window needed)."""
import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rerun_lite import compact_logic as compact, phases
from rerun_lite.feedcat import categorize, collapsed


class Inst:
    def __init__(self, status="idle", detail=""):
        self.status, self.detail = status, detail


class Runs:
    def __init__(self, live=None): self._l = live
    def live(self, name): return self._l


class M:
    def __init__(self, insts, ph, live=None):
        self.instances, self._ph, self.runs = insts, ph, Runs(live)
    def phase(self, name): return self._ph.get(name, ("idle", ""))


def test_no_emulator():
    s = compact.compact_summary(M({}, {}), None)
    assert not s["can_start"] and not s["can_stop"]


def test_running_buttons_and_stats():
    m = M({"A": Inst("running")}, {"A": ("running", "Entering the palace")},
          {"runs": 3, "active_s": 900, "runs_per_hour": 12.0, "avg_s": 300, "failures": 0})
    s = compact.compact_summary(m, "A")
    assert s["label"] == phases.LABEL["running"] and s["can_pause"] and s["can_stop"] and not s["can_start"]
    assert "3 runs" in s["stats"] and "12.0/h" in s["stats"]


def test_paused_says_resume_and_waiting_warns():
    m = M({"A": Inst("paused")}, {"A": ("paused", "")})
    assert compact.compact_summary(m, "A")["pause_text"] == "Resume"
    m = M({"A": Inst("running")}, {"A": ("waiting", "")})
    assert compact.compact_summary(m, "A")["warning"]


def test_failed_shows_warning_and_can_restart():
    m = M({"A": Inst("error")}, {"A": ("failed", "Could not find the palace")})
    s = compact.compact_summary(m, "A")
    assert "palace" in s["warning"] and s["can_start"]


def test_other_emulators_mentioned_and_picks_running():
    m = M({"A": Inst("idle"), "B": Inst("running"), "C": Inst("running")}, {})
    assert compact.pick_emulator(m, "A") == "B"
    assert "1 more" in compact.compact_summary(m, "B")["more"]


def test_feed_categories_and_fold():
    assert categorize("A", "Session ended after 5 min (Crest): ok | 1 game restart(s)", "info") == "Information"
    first, more = collapsed("Traceback\n  a\n  b")
    assert first == "Traceback" and more == 2
