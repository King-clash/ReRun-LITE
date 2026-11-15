"""Quick, local "is it ready?" checks behind the status chip, the tab badges and the Auto Crest notice.

Nothing here touches the emulator or starts anything: it only looks at settings and captured template pictures,
so it is cheap enough to repeat every few seconds.
"""
from __future__ import annotations

from typing import NamedTuple

from . import MAIN_SCRIPT

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class Problem(NamedTuple):
    text: str
    fix: str          # "emulator" | "templates" | "settings": where the Fix button goes


def crest_problems(m, instance: str | None) -> list[Problem]:
    """What would stop Crest from starting on `instance`, in the order to fix it."""
    out: list[Problem] = []
    if not m.instances:
        return [Problem("No emulator added yet. Press Detect BlueStacks or Add.", "emulator")]
    missing = m.missing_templates(MAIN_SCRIPT)
    if missing:
        shown = ", ".join(missing[:3]) + ("..." if len(missing) > 3 else "")
        out.append(Problem(f"{len(missing)} Crest template picture(s) missing: {shown}.", "templates"))
    inst = instance if instance in m.instances else next(iter(m.instances))
    cfg = m.script_settings(inst, MAIN_SCRIPT)
    if cfg.get("start_home", True):
        tiles = {n for n, _, _, have in m.template_checklist(MAIN_SCRIPT)
                 if have and (n == "crest_palace_target" or n.rsplit("_", 1)[-1] in DAYS)
                 and n.startswith("crest_palace_")}
        if not tiles and not str(cfg.get("palace_name") or "").strip() and not str(cfg.get("palace_by_day") or "").strip():
            out.append(Problem("Crest does not know which palace to open. Capture the palace tile in Templates "
                               "or type the palace name in Crest settings.", "settings"))
    return out


def dailies_left(ops) -> int | None:
    """Daily tasks not yet completed for the active account (None when there is no account)."""
    aid = ops.store.active_id
    if not aid:
        return None
    return len(ops.checklist.summary(aid)["daily"]["remaining"])


def running(m) -> tuple[list[str], list[str]]:
    """(emulators running, emulators paused)."""
    run = [n for n, i in m.instances.items() if i.status in ("running", "starting")]
    paused = [n for n, i in m.instances.items() if i.status == "paused"]
    return run, paused
