"""LiteManager: the original Manager, offering only the scripts ReRun LITE has.

Everything that runs a script - the worker thread, Crest itself, the checklist, sessions, stats, History,
the crest ledger, Discord alerts, dry run, limits - is inherited unchanged from rerun/manager.py. The only
differences are which scripts exist and what "this emulator's script" means:

  * scripts_available() lists Crest, Login & Mail and Raid Tickets and nothing else (no other built-in
    script, no custom routine), so nothing else can be started from the window, a schedule or Discord;
  * an emulator's own script is always Crest. (If a start ever names another script, the emulator is a
    Crest emulator again afterwards;
  * LITE never writes an emulator's script into config.yaml. A full ReRun sharing the same folder keeps
    whatever script it had chosen there.

What LITE adds on top (the original's behaviour is unchanged; nothing here sends a tap):

  * run PHASES (phases.py): `phase(name)` says whether an emulator is waiting, recovering, completed, stopped or
    failed, on top of the five status words; `refresh_phases()` sends a "phase" event when one changes;
  * a RUN TRACKER (runs.py): how long each run took and how each session ended, saved to data/lite/sessions.jsonl;
  * Log CATEGORIES (feedcat.py) on every line, and a line that repeats as a warning or error within a few seconds
    is folded into "repeated N more times" instead of flooding the Log tab.
"""
from __future__ import annotations

import time

from rerun import errlog, runlog
from rerun.manager import Instance, Manager, log_level
from rerun.scripts import SCRIPTS

from . import LITE_SCRIPTS, MAIN_SCRIPT, channel, crest, phases, runs
from .feedcat import categorize
from .stuck import StuckWatch

REPEAT_WINDOW_S = 5.0       # the same warning/error again within this long is folded into a count


class LiteManager(Manager):

    def __init__(self, *a, **k):
        # state that log() and _set_status() use, set before the original __init__ (which already logs)
        self.stuck = StuckWatch()
        self.alert_listeners: list = []          # called as fn(kind, instance, detail): see notifyprefs.KINDS
        self._phases: dict[str, tuple[str, str]] = {}
        self._ended: dict[str, tuple[str, str]] = {}
        self._rep_key: tuple | None = None
        self._rep_t, self._rep_n, self._rep_instance, self._rep_level = 0.0, 0, "", "info"
        self.runs = runs.RunTracker(None)
        super().__init__(*a, **k)
        crest.install()                         # 'crest' is Crest plus the daily palace selector (rerun_lite/crest.py)
        crest.LiteCrest.PALACE_ROOT = self.root
        self.runs = runs.RunTracker(channel.data_dir(self.root) / runs.FILE)
        self._hook_stats()

    # ------------------------------------------------------------ run tracker: fed by the counters Crest already bumps
    def _hook_stats(self) -> None:
        """Every counter the script bumps ('crest.runs', 'crest.failures', 'game_restarts'...) also tells the tracker."""
        original = self.stats.incr

        def incr(instance: str, key: str, n: int = 1) -> None:
            original(instance, key, n)
            try:
                self.runs.on_count(instance, key, n)
            except Exception as e:  # noqa: BLE001 - tracking must never break a script
                errlog.note("lite.runs.on_count", e)
        self.stats.incr = incr

    def _record_session(self, inst, started_at, before, reason) -> None:
        try:
            super()._record_session(inst, started_at, before, reason)
        finally:
            try:
                rec = self.runs.end_session(inst.name, reason, account=inst.account, script=inst.script)
                if rec and rec.get("ended") in ("failed", "completed"):
                    self.fire_alert("failed" if rec["ended"] == "failed" else "finished", inst.name, reason)
            except Exception as e:  # noqa: BLE001
                errlog.note("lite.runs.end_session", e)

    def pause(self, name: str) -> str:
        msg = super().pause(name)
        inst = self.instances.get(name)
        if inst is not None and inst.status == "paused":
            self.runs.pause(name)
        return msg

    def resume(self, name: str) -> str:
        msg = super().resume(name)
        inst = self.instances.get(name)
        if inst is not None and inst.status == "running":
            self.runs.resume(name)
        return msg

    # ------------------------------------------------------------ phases
    def _set_status(self, inst: Instance, status: str, detail: str = "") -> None:
        prev = inst.status
        super()._set_status(inst, status, detail)
        try:
            if status in ("starting", "running"):
                self._ended.pop(inst.name, None)
            if status == "running" and prev == "starting":
                self.runs.start_session(inst.name, inst.dry_run)
            if status in ("idle", "error"):
                self._ended[inst.name] = (phases.end_phase(status, detail), detail)
            self.refresh_phases()
        except Exception as e:  # noqa: BLE001 - a status helper must never break the worker
            errlog.note("lite.set_status", e)

    def phase(self, name: str) -> tuple[str, str]:
        """(phase, short detail) for an emulator: see phases.py."""
        inst = self.instances.get(name)
        if inst is None:
            return "idle", ""
        params = inst.ctx.params if inst.ctx is not None else {}
        ended, text = self._ended.get(name, ("idle", ""))
        state, recovering = str(params.get("script_state") or ""), str(params.get("recovering") or "")
        ph = phases.phase_of(inst.status, state, recovering, ended)
        return ph, phases.describe(ph, state, recovering, text)

    def stuck_for(self, name: str) -> float | None:
        """Seconds Crest has gone without advancing, while a stuck episode is open for this emulator (else None)."""
        inst = self.instances.get(name)
        lp = inst.ctx.params.get("last_progress") if inst is not None and inst.ctx is not None else None
        return self.stuck.stuck_for(name, None if lp is None else time.monotonic() - lp)

    def _check_stuck(self) -> None:
        now = time.monotonic()
        for name, inst in list(self.instances.items()):
            params = inst.ctx.params if inst.ctx is not None else {}
            lp = params.get("last_progress")
            active = inst.status == "running" and not params.get("recovering") and lp is not None
            idle = None if lp is None else now - lp
            what = self.stuck.check(name, idle, active, now)
            if what == "start":
                mins = int(idle // 60)
                self.log(name, f"Crest has not advanced for {mins} minutes (screen: {params.get('script_state') or 'unknown'}). "
                               "Nothing was changed - check the emulator.", level="warn")
                self.fire_alert("stuck", name, f"No progress for {mins} minutes")
            elif what == "end":
                self.log(name, "Crest is moving again.")

    def refresh_phases(self) -> None:
        """Send a 'phase' event for every emulator whose phase changed since the last call (cheap; the window calls it
        every second), and write the start and end of a recovery to the Log."""
        try:
            self._check_stuck()
        except Exception as e:  # noqa: BLE001 - a watcher must never break the window's loop
            errlog.note("lite.stuck", e)
        changes = []
        with self._lock:
            for name in list(self.instances):
                now = self.phase(name)
                before = self._phases.get(name)
                if before is None or before[0] != now[0]:
                    self._phases[name] = now
                    changes.append((name, before[0] if before else "idle", now))
                else:
                    self._phases[name] = now
        for name, was, (ph, detail) in changes:
            self.emit({"type": "phase", "instance": name, "phase": ph, "detail": detail})
            if ph == "recovering":
                self.log(name, f"Recovery started: {detail}")
                self.fire_alert("recovery", name, detail)
            elif was == "recovering":
                self.log(name, f"Recovery step finished - Crest is now {phases.LABEL[ph].lower()}")

    def fire_alert(self, kind: str, instance: str, detail: str = "") -> None:
        """Tell whoever listens (the window's desktop notifications) that something worth a pop-up happened."""
        for fn in list(self.alert_listeners):
            try:
                fn(kind, instance, detail)
            except Exception as e:  # noqa: BLE001 - a listener must never break the worker
                errlog.note("lite.alert", e)

    # ------------------------------------------------------------ Log lines: categories, and folding a repeated problem
    def log(self, instance: str, msg: str, level: str | None = None) -> None:
        level = level or log_level(msg)
        key, now = (instance, msg), time.monotonic()
        pending = None
        with self._lock:
            problem = level in ("warn", "error")
            if problem and key == self._rep_key and now - self._rep_t < REPEAT_WINDOW_S:
                self._rep_n += 1
                self._rep_t = now
                return
            if self._rep_n:
                pending = (self._rep_instance, self._rep_n, self._rep_level)
            self._rep_n = 0
            self._rep_key = key if problem else None
            self._rep_t, self._rep_instance, self._rep_level = now, instance, level
        if pending:
            self._write_log(pending[0], f"(the line above repeated {pending[1]} more time(s))", pending[2])
        self._write_log(instance, msg, level)

    def _write_log(self, instance: str, msg: str, level: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} [{instance}] {msg}"
        entry = {"instance": instance, "message": msg, "line": line, "level": level,
                 "category": categorize(instance, msg, level)}
        with self._lock:
            self.log_lines.append(line)
            self.log_entries.append(entry)
            keep = self.log_keep()
            if len(self.log_lines) > keep + 500:     # trim in batches, not on every line
                del self.log_lines[:-keep]
                del self.log_entries[:-keep]
        self.emit({"type": "log", **entry})
        runlog.write(instance, msg, level)

    def scripts_available(self) -> dict[str, str]:
        """id -> display name of the scripts LITE has (Crest first)."""
        return {k: SCRIPTS[k].display_name() for k in LITE_SCRIPTS if k in SCRIPTS}

    # ------------------------------------------------------------ an emulator's script is Crest
    def reload(self) -> list[str]:
        problems = super().reload()
        for inst in self.instances.values():
            if inst.status in ("idle", "error"):
                inst.script = MAIN_SCRIPT       # whatever config.yaml says (a full ReRun may share it)
        return problems

    def set_instance_script(self, name: str, script: str) -> None:
        """In memory only - config.yaml keeps the script a full ReRun saved for this emulator."""
        inst = self.instances.get(name)
        if inst is not None and inst.status in ("idle", "error"):
            inst.script = script

    def start(self, name: str, script: str | None = None, confirm_account: str | None = None,
              dry_run: bool = False, task: str = "") -> str:
        """Same as the original; a start that names no script (Start, Start All, a schedule, autostart,
        Discord /start) is a Crest start."""
        return super().start(name, script or MAIN_SCRIPT, confirm_account=confirm_account,
                             dry_run=dry_run, task=task)

    def _worker(self, inst: Instance) -> None:
        try:
            super()._worker(inst)
        finally:
            inst.script = MAIN_SCRIPT           # afterwards the emulator is a Crest emulator again
