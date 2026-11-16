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

from rerun.manager import Instance, Manager
from rerun.scripts import SCRIPTS

from . import LITE_SCRIPTS, MAIN_SCRIPT, crest


class LiteManager(Manager):

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        crest.install()                         # 'crest' is Crest plus the daily palace selector (rerun_lite/crest.py)
        crest.LiteCrest.PALACE_ROOT = self.root

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
