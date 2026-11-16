"""Quick, local "is it ready?" checks behind the status chip, the tab badges and the Auto Crest notice.

Nothing here touches the emulator or starts anything: it only looks at settings and captured template pictures,
so it is cheap enough to repeat every few seconds.
"""
from __future__ import annotations

from typing import NamedTuple

from . import MAIN_SCRIPT, palaces

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class Problem(NamedTuple):
    text: str
    fix: str          # "emulator" | "templates" | "settings" | "palaces": where the Fix button goes


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
    choice = palaces.choose(m.root)
    if choice.mode != "off":                      # the daily palace selector decides the palace
        if not choice.ok:
            out.append(Problem(f"Palace selector: {choice.problem}", "palaces"))
        return out
    if cfg.get("start_home", True):
        tiles = {n for n, _, _, have in m.template_checklist(MAIN_SCRIPT)
                 if have and (n == "crest_palace_target" or n.rsplit("_", 1)[-1] in DAYS)
                 and n.startswith("crest_palace_")}
        if not tiles and not str(cfg.get("palace_name") or "").strip() and not str(cfg.get("palace_by_day") or "").strip():
            out.append(Problem("Crest does not know which palace to open. Capture the palace tile in Templates "
                               "or type the palace name in Crest settings.", "settings"))
    return out


def running(m) -> tuple[list[str], list[str]]:
    """(emulators running, emulators paused)."""
    run = [n for n, i in m.instances.items() if i.status in ("running", "starting")]
    paused = [n for n, i in m.instances.items() if i.status == "paused"]
    return run, paused
