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
"""
from __future__ import annotations

import time

from rerun import errlog
from rerun.manager import Instance, Manager
from rerun.scripts import SCRIPTS

from . import LITE_SCRIPTS, MAIN_SCRIPT, crest, phases
from .runs import RunTracker
from .stuck import StuckWatch


class LiteManager(Manager):

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        crest.install()                         # 'crest' is Crest plus the daily palace selector (rerun_lite/crest.py)
        crest.LiteCrest.PALACE_ROOT = self.root
        # run states, session tracking and the stuck watch (rerun_lite/phases.py, runs.py, stuck.py). They only read what
        # the manager and Crest already do; nothing here taps, presses a key or restarts anything.
        self.alert_listeners: list = []                 # fn(kind, instance, detail); a listener that raises is ignored
        self.runs = RunTracker(self.root / "data" / "lite" / "sessions.jsonl")
        self.stuck = StuckWatch()
        self._ended: dict[str, str] = {}                # instance -> how its last run ended (phases.end_phase)
        self._stuck_idle: dict[str, float] = {}
        stats, original = self.stats, self.stats.incr

        def incr(instance, key, n=1, *a, **k):
            result = original(instance, key, n, *a, **k)
            try:
                self.runs.on_count(instance, key, n)
                if key.rsplit(".", 1)[-1] == "game_restarts":
                    self.fire_alert("recovery", instance, "The game was restarted or logged back in")
            except Exception as e:  # noqa: BLE001 - tracking must never break a run
                errlog.note("lite.on_count", e)
            return result
        stats.incr = incr

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


    # ------------------------------------------------------------ alerts
    def fire_alert(self, kind: str, instance: str, detail: str = "") -> None:
        """Tell the listeners (the window's desktop notifications) that something happened. A listener that raises is
        skipped; the others still hear it."""
        for fn in list(self.alert_listeners):
            try:
                fn(kind, instance, detail)
            except Exception as e:  # noqa: BLE001
                errlog.note("lite.alert_listener", e)

    # ------------------------------------------------------------ phases and the session record
    def _set_status(self, inst: Instance, status: str, detail: str = "") -> None:
        before = inst.status
        super()._set_status(inst, status, detail)
        try:
            if status == "starting":
                self._ended.pop(inst.name, None)
                self.runs.start_session(inst.name, inst.dry_run)
            elif status == "paused":
                self.runs.pause(inst.name)
            elif status == "running" and before == "paused":
                self.runs.resume(inst.name)
            elif status in ("idle", "error") and before in ("starting", "running", "paused"):
                ended = phases.end_phase(status, detail)
                self._ended[inst.name] = ended
                self.stuck.forget(inst.name)
                if ended == "failed":
                    self.fire_alert("failed", inst.name, detail)
                elif ended == "completed" and not inst.dry_run:
                    self.fire_alert("finished", inst.name, detail)
        except Exception as e:  # noqa: BLE001
            errlog.note("lite.set_status", e)

    def _record_session(self, inst: Instance, started_at: float, before: dict, reason: str) -> None:
        super()._record_session(inst, started_at, before, reason)
        try:
            self.runs.end_session(inst.name, reason, inst.account, inst.script)
        except Exception as e:  # noqa: BLE001
            errlog.note("lite.end_session", e)

    def phase(self, name: str) -> tuple[str, str]:
        """(phase, a short line about it) for an emulator, see rerun_lite/phases.py."""
        inst = self.instances.get(name)
        if inst is None:
            return "idle", ""
        params = inst.ctx.params if inst.ctx is not None else {}
        script_state, recovering = params.get("script_state", ""), params.get("recovering", "")
        ph = phases.phase_of(inst.status, script_state, recovering, self._ended.get(name, "idle"))
        return ph, phases.describe(ph, script_state, recovering, inst.detail)

    def _idle_seconds(self, inst: Instance) -> float | None:
        last = (inst.ctx.params.get("last_progress") if inst.ctx is not None else None)
        return None if not last else max(0.0, time.monotonic() - float(last))

    def refresh_phases(self) -> None:
        """Called about once a second by the window: watch for Crest not advancing. One warning per episode."""
        now = time.monotonic()
        for name, inst in list(self.instances.items()):
            idle = self._idle_seconds(inst)
            params = inst.ctx.params if inst.ctx is not None else {}
            active = inst.status == "running" and not params.get("recovering")
            event = self.stuck.check(name, idle, active, now)
            if event == "start":
                minutes = int((idle or 0) // 60)
                msg = f"Crest has not advanced for {minutes} minutes - the game may be stuck. Nothing was done; it keeps trying by its own rules."
                self.log(name, msg, "warn")
                self.fire_alert("stuck", name, msg)

    def stuck_for(self, name: str) -> float | None:
        """Seconds Crest has gone without progress while a stuck warning is open, else None."""
        inst = self.instances.get(name)
        return self.stuck.stuck_for(name, self._idle_seconds(inst)) if inst is not None else None

    def _worker(self, inst: Instance) -> None:
        try:
            super()._worker(inst)
        finally:
            inst.script = MAIN_SCRIPT           # afterwards the emulator is a Crest emulator again
            if self.runs.live(inst.name) is not None:          # a start that failed before the session record was written
                self.runs.end_session(inst.name, f"error: {inst.detail}" if inst.status == "error" else f"stopped: {inst.detail}",
                                      inst.account, inst.script)
