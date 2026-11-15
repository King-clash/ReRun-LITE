"""Daily / weekly checklist engine.

Resets follow the GAME clock (06:00 UTC-6), never the computer's midnight - the same rule Crest uses
(`crest_stats.game_day`). A weekly task resets on the account's `week_reset_weekday` at that same hour
(default Monday - an assumption, change it per account in Safety & settings).

A task's state this period is one of:
  completed   done (by you, or by a script and then confirmed by you)
  unverified  a script says it finished it but nothing has confirmed that on screen yet
  in_progress a script is running it right now
  failed      a script tried this period and failed
  available   due now and not done
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from .accounts import AccountError, AccountStore

GAME_TZ = timezone(timedelta(hours=-6))
RESET_HOUR = 6

STATES = ("completed", "unverified", "in_progress", "failed", "available")

# id, name, period, priority (1 = most important), script that can do it (None = manual), note
BUILTIN_TASKS = [
    {"id": "login_reward", "name": "Login reward + mail", "period": "daily", "priority": 1,
     "script": "login_mail", "note": "Automated by 'Login & Mail' (live-verified)."},
    {"id": "daily_missions", "name": "Daily missions", "period": "daily", "priority": 2,
     "script": None, "note": "Manual - no reliable automation yet."},
    {"id": "free_summon", "name": "Free summon", "period": "daily", "priority": 3,
     "script": None, "note": "Manual. Rerun never spends summons by itself."},
    {"id": "raid_tickets", "name": "Raid tickets", "period": "daily", "priority": 4,
     "script": "raid_tickets", "note": "'Raid Tickets' script is BETA (not yet run on a real game)."},
    {"id": "weekly_shop", "name": "Weekly shop items", "period": "weekly", "priority": 2,
     "script": None, "note": "Manual. Rerun never buys anything."},
    {"id": "weekly_missions", "name": "Weekly missions", "period": "weekly", "priority": 3,
     "script": None, "note": "Manual."},
]


def period_start(t: float, period: str, week_weekday: int = 0) -> float:
    """Timestamp when the daily/weekly period containing `t` began (game clock)."""
    dt = datetime.fromtimestamp(t, GAME_TZ)
    day = dt.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
    if dt < day:
        day -= timedelta(days=1)
    if period == "weekly":
        day -= timedelta(days=(day.weekday() - week_weekday) % 7)
    elif period != "daily":
        raise AccountError(f"Unknown period '{period}'.")
    return day.timestamp()


def next_reset(t: float, period: str, week_weekday: int = 0) -> float:
    start = datetime.fromtimestamp(period_start(t, period, week_weekday), GAME_TZ)
    return (start + timedelta(days=7 if period == "weekly" else 1)).timestamp()


def fmt_until(seconds: float) -> str:
    s = max(0, int(seconds))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return (f"{d}d {h}h" if d else f"{h}h {m:02d}m")


class Checklist:
    def __init__(self, store: AccountStore):
        self.s = store

    # ------------------------------------------------------------------ definitions
    def definitions(self, aid: str) -> list[dict]:
        a = self.s.get(aid)
        hidden = {k for k, v in a["tasks"].items() if v.get("hidden")}
        overrides = {k: v.get("priority") for k, v in a["tasks"].items() if v.get("priority")}
        defs = [dict(t, builtin=True) for t in BUILTIN_TASKS if t["id"] not in hidden]
        defs += [dict(t, builtin=False) for t in a["custom_tasks"] if t["id"] not in hidden]
        for d in defs:
            if d["id"] in overrides:
                d["priority"] = overrides[d["id"]]
        return sorted(defs, key=lambda d: (d["priority"], d["name"].lower()))

    def add_task(self, aid: str, name: str, period: str = "daily", priority: int = 5, script: str | None = None) -> str:
        name = (name or "").strip()
        if not name:
            raise AccountError("Give the task a name.")
        if period not in ("daily", "weekly"):
            raise AccountError("A task is either daily or weekly.")
        a = self.s.get(aid)
        if any(t["name"].lower() == name.lower() for t in self.definitions(aid)):
            raise AccountError(f"There is already a task called '{name}'.")
        tid = "c" + uuid.uuid4().hex[:6]
        with self.s._lock:
            a["custom_tasks"].append({"id": tid, "name": name[:60], "period": period,
                                      "priority": max(1, min(9, int(priority))), "script": script or None,
                                      "note": "Custom task."})
            self.s._save(a)
        self.s.log_activity(aid, "task", f"Task added: {name}")
        return tid

    def remove_task(self, aid: str, tid: str) -> None:
        """Custom tasks are deleted; built-in ones are hidden (they come back with 'reset to defaults')."""
        a = self.s.get(aid)
        with self.s._lock:
            if any(t["id"] == tid for t in a["custom_tasks"]):
                a["custom_tasks"] = [t for t in a["custom_tasks"] if t["id"] != tid]
            elif any(t["id"] == tid for t in BUILTIN_TASKS):
                a["tasks"].setdefault(tid, {})["hidden"] = True
            else:
                raise AccountError("Unknown task.")
            self.s._save(a)
        self.s.log_activity(aid, "task", f"Task removed: {tid}")

    def set_priority(self, aid: str, tid: str, priority: int) -> None:
        a = self.s.get(aid)
        if not any(d["id"] == tid for d in self.definitions(aid)):
            raise AccountError("Unknown task.")
        with self.s._lock:
            a["tasks"].setdefault(tid, {})["priority"] = max(1, min(9, int(priority)))
            self.s._save(a)

    # ------------------------------------------------------------------ state
    def _weekday(self, aid: str) -> int:
        return int(self.s.get(aid)["prefs"].get("week_reset_weekday", 0))

    def state_of(self, aid: str, tdef: dict, now: float | None = None) -> str:
        now = now or time.time()
        rec = self.s.get(aid)["tasks"].get(tdef["id"], {})
        start = period_start(now, tdef["period"], self._weekday(aid))
        last = rec.get("last_done")
        if last and last >= start:
            return "completed" if rec.get("verified", True) else "unverified"
        st = rec.get("run_state")
        if st and rec.get("run_t", 0) >= start:
            if st in ("in_progress", "failed"):
                return st
        return "available"

    def rows(self, aid: str, now: float | None = None) -> list[dict]:
        now = now or time.time()
        wd = self._weekday(aid)
        out = []
        for d in self.definitions(aid):
            rec = self.s.get(aid)["tasks"].get(d["id"], {})
            out.append({**d, "state": self.state_of(aid, d, now), "last_done": rec.get("last_done"),
                        "resets_in": next_reset(now, d["period"], wd) - now,
                        "history": rec.get("history", [])[-10:]})
        return out

    def summary(self, aid: str, now: float | None = None) -> dict:
        rows = self.rows(aid, now)
        res = {}
        for per in ("daily", "weekly"):
            rs = [r for r in rows if r["period"] == per]
            done = sum(1 for r in rs if r["state"] == "completed")
            res[per] = {"done": done, "total": len(rs),
                        "unverified": sum(1 for r in rs if r["state"] == "unverified"),
                        "failed": sum(1 for r in rs if r["state"] == "failed"),
                        "remaining": [r["name"] for r in rs if r["state"] not in ("completed",)],
                        "resets_in": next_reset(now or time.time(), per, self._weekday(aid)) - (now or time.time())}
        return res

    # ------------------------------------------------------------------ changes
    def _rec(self, aid: str, tid: str) -> tuple[dict, dict]:
        a = self.s.get(aid)
        tdef = next((d for d in self.definitions(aid) if d["id"] == tid), None)
        if tdef is None:
            raise AccountError("Unknown task.")
        return a, tdef

    def mark_done(self, aid: str, tid: str, by: str = "manual", now: float | None = None) -> None:
        """by='manual' is confirmed; by='script' is 'unverified' until you confirm it."""
        now = now or time.time()
        a, tdef = self._rec(aid, tid)
        with self.s._lock:
            rec = a["tasks"].setdefault(tid, {})
            rec.update(last_done=now, verified=(by == "manual"), run_state="", run_t=now)
            rec.setdefault("history", []).append({"t": now, "by": by, "event": "done"})
            rec["history"] = rec["history"][-60:]
            self.s._save(a)
        self.s.log_activity(aid, "task", f"{tdef['name']} done ({by})", task=tid)
        self.s._emit("task", aid, tid)

    def confirm(self, aid: str, tid: str) -> None:
        a, tdef = self._rec(aid, tid)
        with self.s._lock:
            rec = a["tasks"].setdefault(tid, {})
            if not rec.get("last_done"):
                raise AccountError("That task has not been done yet.")
            rec["verified"] = True
            self.s._save(a)
        self.s._emit("task", aid, tid)

    def undo(self, aid: str, tid: str) -> None:
        a, tdef = self._rec(aid, tid)
        with self.s._lock:
            rec = a["tasks"].setdefault(tid, {})
            rec.update(last_done=None, verified=True, run_state="")
            rec.setdefault("history", []).append({"t": time.time(), "by": "manual", "event": "undone"})
            self.s._save(a)
        self.s.log_activity(aid, "task", f"{tdef['name']} marked not done", task=tid)
        self.s._emit("task", aid, tid)

    def begin_run(self, aid: str, tid: str, now: float | None = None) -> None:
        """A script is about to do this task. Refuses if it is already done this period (no duplicates)."""
        now = now or time.time()
        a, tdef = self._rec(aid, tid)
        st = self.state_of(aid, tdef, now)
        if st in ("completed", "unverified"):
            raise AccountError(f"'{tdef['name']}' is already done this period.")
        if st == "in_progress":
            raise AccountError(f"'{tdef['name']}' is already running.")
        with self.s._lock:
            a["tasks"].setdefault(tid, {}).update(run_state="in_progress", run_t=now)
            self.s._save(a)
        self.s._emit("task", aid, tid)

    def cancel_run(self, aid: str, tid: str) -> None:
        """A run that never really started (refused, or a dry run) leaves the task as it was."""
        a, _ = self._rec(aid, tid)
        with self.s._lock:
            a["tasks"].setdefault(tid, {}).update(run_state="")
            self.s._save(a)
        self.s._emit("task", aid, tid)

    def end_run(self, aid: str, tid: str, ok: bool, now: float | None = None) -> None:
        now = now or time.time()
        if ok:
            self.mark_done(aid, tid, by="script", now=now)
            return
        a, tdef = self._rec(aid, tid)
        with self.s._lock:
            rec = a["tasks"].setdefault(tid, {})
            rec.update(run_state="failed", run_t=now)
            rec.setdefault("history", []).append({"t": now, "by": "script", "event": "failed"})
            self.s._save(a)
        self.s.log_activity(aid, "task", f"{tdef['name']} failed", task=tid)
        self.s._emit("task", aid, tid)

    def due_automatable(self, aid: str, scripts_available: dict[str, str]) -> list[dict]:
        """Tasks that are due AND have a script Rerun really has - the only ones that may be started."""
        return [r for r in self.rows(aid) if r["state"] in ("available", "failed")
                and r.get("script") and r["script"] in scripts_available]
