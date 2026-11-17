"""Run tracker and session store: how long each run took, how each session ended, and what it achieved.

A RUN is counted only when the script counts one (Crest does it when the game's drop screen is seen), so an
uncertain result is never a success. Times are cycle times: the time from one counted run to the next, minus any time
you had paused. The first run of a session is kept apart because it also includes getting to the quest.

  completed   a counted run
  failed      a failure the script itself counted
  interrupted the session ended (stopped, crashed, limit) while a cycle was still under way
  unknown     never inferred: nothing is guessed

Sessions are appended to data/lite/sessions.jsonl when they end (one JSON line each) and trimmed to the newest
`keep`. Only summaries are stored - no screenshots - so the file stays small.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from pathlib import Path
from typing import Callable

from rerun import errlog

FILE = "sessions.jsonl"
MAX_CYCLES = 300            # cycle times kept per session (for graphs); the summary uses all of them
KEEP = 200                  # sessions kept on disk
INTERRUPT_KEYS = ("text_popups",)          # an unexpected screen that was handled
RECOVERY_KEYS = ("game_restarts",)         # the game was restarted / relaunched


def classify_reason(reason: str) -> str:
    """completed | stopped | failed for the reason a session ended ('finished: ...', 'stopped: ...', 'error: ...')."""
    low = (reason or "").lower()
    if low.startswith("finished"):
        if any(w in low for w in ("restart limit",)):
            return "failed"
        return "completed"
    if low.startswith(("error", "crashed", "missing template")):
        return "failed"
    if low.startswith("stopped"):
        body = low[len("stopped"):].lstrip(": ").strip("() ")
        if any(w in body for w in ("stuck", "no progress", "game not running", "game shows", "needs you")):
            return "failed"
        return "stopped"
    return "stopped"


class _Live:
    """What one emulator's current session has done so far."""

    def __init__(self, now: float, dry_run: bool = False):
        self.started = now
        self.dry_run = dry_run
        self.paused_total = 0.0
        self.paused_at: float | None = None
        self.last_run_at = now          # when the current cycle began
        self.cycle_paused = 0.0         # pause time inside the current cycle
        self.cycles: list[float] = []   # completed cycle times, first run excluded
        self.first_run_s: float | None = None
        self.runs = 0
        self.failures = 0
        self.interruptions = 0
        self.recoveries = 0
        self.recovered = 0              # recoveries followed by a counted run
        self.recovery_pending = False

    def active_seconds(self, now: float) -> float:
        paused = self.paused_total + ((now - self.paused_at) if self.paused_at is not None else 0.0)
        return max(0.0, now - self.started - paused)

    def snapshot(self, now: float) -> dict:
        c = self.cycles
        active = self.active_seconds(now)
        rate = round(self.runs / (active / 3600), 1) if active >= 60 and self.runs else None
        done = self.runs + self.failures
        return {
            "started": self.started, "dry_run": self.dry_run, "active_s": int(active),
            "runs": self.runs, "failures": self.failures, "interruptions": self.interruptions,
            "recoveries": self.recoveries, "recovered": self.recovered,
            "recovery_rate": round(self.recovered / self.recoveries, 2) if self.recoveries else None,
            "avg_s": round(sum(c) / len(c), 1) if c else None,
            "fastest_s": round(min(c), 1) if c else None, "slowest_s": round(max(c), 1) if c else None,
            "median_s": round(statistics.median(c), 1) if c else None,
            "first_run_s": round(self.first_run_s, 1) if self.first_run_s is not None else None,
            "runs_per_hour": rate,
            "success_rate": round(self.runs / done, 3) if done else None,
            "paused": self.paused_at is not None,
        }


class RunTracker:
    def __init__(self, path: str | Path | None = None, keep: int = KEEP, clock: Callable[[], float] = time.time):
        self.path = Path(path) if path else None
        self.keep = max(10, int(keep))
        self.clock = clock
        self._live: dict[str, _Live] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ while a session runs
    def start_session(self, instance: str, dry_run: bool = False) -> None:
        with self._lock:
            self._live[instance] = _Live(self.clock(), dry_run)

    def pause(self, instance: str) -> None:
        with self._lock:
            s = self._live.get(instance)
            if s and s.paused_at is None:
                s.paused_at = self.clock()

    def resume(self, instance: str) -> None:
        with self._lock:
            s = self._live.get(instance)
            if s and s.paused_at is not None:
                gone = self.clock() - s.paused_at
                s.paused_total += gone
                s.cycle_paused += gone
                s.paused_at = None

    def on_count(self, instance: str, key: str, n: int = 1) -> None:
        """Called for every counter the script bumps ('crest.runs', 'crest.failures', 'game_restarts', ...)."""
        with self._lock:
            s = self._live.get(instance)
            if s is None or n <= 0:
                return
            tail = key.rsplit(".", 1)[-1]
            if tail == "runs":
                self._run_done(s, n)
            elif tail == "failures":
                s.failures += n
            elif tail in RECOVERY_KEYS:
                s.recoveries += n
                s.recovery_pending = True
            elif tail in INTERRUPT_KEYS:
                s.interruptions += n

    def _run_done(self, s: _Live, n: int) -> None:
        now = self.clock()
        paused_now = (now - s.paused_at) if s.paused_at is not None else 0.0
        cycle = max(0.0, now - s.last_run_at - s.cycle_paused - paused_now)
        for i in range(n):                      # n > 1 only if a counter was bumped by more than one
            if s.runs == 0 and i == 0:
                s.first_run_s = cycle
            elif i == 0:
                s.cycles.append(cycle)
            s.runs += 1
        s.last_run_at, s.cycle_paused = now, 0.0
        if s.recovery_pending:
            s.recovered += 1
            s.recovery_pending = False

    def live(self, instance: str) -> dict | None:
        with self._lock:
            s = self._live.get(instance)
            return s.snapshot(self.clock()) if s else None

    # ------------------------------------------------------------ when it ends
    def end_session(self, instance: str, reason: str, account: str = "", script: str = "crest") -> dict | None:
        """Close the session, save its summary and return it (None if none was open or it was a dry run)."""
        with self._lock:
            s = self._live.pop(instance, None)
            if s is None:
                return None
            now = self.clock()
            snap = s.snapshot(now)
            ended = classify_reason(reason)
            unfinished = now - s.last_run_at - s.cycle_paused - ((now - s.paused_at) if s.paused_at else 0.0)
            rec = {
                "id": f"{int(s.started)}-{instance}", "instance": instance, "script": script, "account": account,
                "start": s.started, "end": now, "duration_s": int(now - s.started), **snap,
                "ended": ended, "reason": reason[:200],
                "interrupted": bool(ended != "completed" and unfinished > 5 and not s.dry_run),
                "unfinished_s": int(max(0, unfinished)),
                "unresolved_recoveries": s.recoveries - s.recovered,
                "cycles": [round(c, 1) for c in s.cycles[-MAX_CYCLES:]],
            }
            rec.pop("paused", None)
        if s.dry_run:                 # a rehearsal taps nothing: it is not farming history
            return None
        self._append(rec)
        return rec

    # ------------------------------------------------------------ the saved sessions
    def _append(self, rec: dict) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._trim()
        except OSError as e:
            errlog.note("runs.append", e)

    def _read_all(self) -> list[dict]:
        if self.path is None or not self.path.is_file():
            return []
        out = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue            # a damaged line is skipped, never fatal
                if isinstance(d, dict):
                    out.append(d)
        except OSError as e:
            errlog.note("runs.read", e)
        return out

    def _trim(self) -> None:
        """Keep the newest `keep` sessions; rewritten only when the file is clearly over (not on every session)."""
        try:
            if self.path.stat().st_size < 64 * 1024:
                return
            rows = self._read_all()
            if len(rows) <= self.keep + 20:
                return
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[-self.keep:]), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            errlog.note("runs.trim", e)

    def sessions(self, limit: int = 50, instance: str | None = None) -> list[dict]:
        """Newest first."""
        rows = [r for r in self._read_all() if instance in (None, r.get("instance"))]
        return rows[::-1][:max(0, limit)]

    def clear(self) -> int:
        """Delete the saved sessions (the window asks first). Returns how many were removed."""
        n = len(self._read_all())
        try:
            if self.path is not None and self.path.is_file():
                self.path.unlink()
        except OSError as e:
            errlog.note("runs.clear", e)
            return 0
        return n


def fmt_secs(s: float | None) -> str:
    if s is None:
        return "-"
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {sec:02d}s" if m else f"{sec}s")
