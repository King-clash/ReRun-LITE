"""The compact window's decisions, with no window in them (so they can be tested anywhere)."""
from __future__ import annotations

from . import phases, readiness
from .runs import fmt_secs

PAUSABLE = {"running", "waiting", "recovering", "paused"}


def runs_text(live: dict | None) -> str:
    """'12 runs  ·  1h 04m  ·  11.2/h  ·  avg 4m 55s' for a session's live numbers (or why there are none)."""
    if not live:
        return "No session running"
    bits = [f"{live['runs']} run{'s' if live['runs'] != 1 else ''}", fmt_secs(live["active_s"])]
    if live.get("runs_per_hour") is not None:
        bits.append(f"{live['runs_per_hour']}/h")
    if live.get("avg_s") is not None:
        bits.append(f"avg {fmt_secs(live['avg_s'])}")
    if live.get("failures"):
        bits.append(f"{live['failures']} failed")
    return "  ·  ".join(bits)


def pick_emulator(m, selected: str | None) -> str | None:
    """The emulator the compact window shows: one that is running, else the one selected, else the first."""
    run, paused = readiness.running(m)
    for group in (run, paused):
        if group:
            return group[0]
    return selected if selected in m.instances else next(iter(m.instances), None)


def compact_summary(m, name: str | None, problems: list | None = None) -> dict:
    """Everything the compact window shows, from the Manager alone (so it can be tested without a window)."""
    if not name or name not in m.instances:
        return {"phase": "idle", "label": "No emulator", "color": "gray", "detail": "Add an emulator in the full window.",
                "stats": "", "warning": "", "can_start": False, "can_pause": False, "can_stop": False,
                "pause_text": "Pause", "start_text": "Start", "more": ""}
    ph, detail = m.phase(name)
    inst = m.instances[name]
    active = ph in phases.ACTIVE
    run, paused = readiness.running(m)
    others = [n for n in run + paused if n != name]
    if active and ph not in ("completed", "stopped", "failed"):
        doing = detail or (inst.detail or "")[:90]
    else:
        doing = detail or "Ready"
    warning = ""
    stuck = getattr(m, "stuck_for", lambda n: None)(name)
    if stuck:
        warning = f"No progress for {int(stuck // 60)} min - check the emulator."
    elif ph == "failed":
        warning = detail or "The last run failed - see the Log."
    elif ph == "waiting":
        warning = "The game screen is not recognised yet."
    elif not active and problems:
        warning = problems[0].text
    return {"phase": ph, "label": phases.LABEL[ph], "color": phases.COLOR[ph], "detail": doing,
            "stats": runs_text(m.runs.live(name)), "warning": warning,
            "can_start": not active, "can_pause": ph in PAUSABLE, "can_stop": active,
            "pause_text": "Resume" if ph == "paused" else "Pause", "start_text": "Start",
            "more": f"+{len(others)} more emulator{'s' if len(others) != 1 else ''} running" if others else ""}
