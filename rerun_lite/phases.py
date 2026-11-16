"""The run phase of an emulator: a richer view of what it is doing than the manager's five status words.

The manager's status stays exactly as it was (idle | starting | running | paused | error) - Discord, the schedule,
the tests and the window all read it. A PHASE is worked out from that status plus two small facts the Crest script
leaves for us (ctx.params["script_state"] and ctx.params["recovering"]) and how the last run ended:

    idle          nothing has run since ReRun LITE opened
    initializing  starting up (connecting, reading settings)
    running       Crest is working normally
    waiting       Crest is running but the game's screen is not recognised yet
    recovering    Crest is restarting the game or logging back in
    paused        paused by you
    completed     the last run finished normally
    stopped       the last run was stopped (by you, a limit, a schedule)
    failed        the last run ended on a problem (error, stuck, game closed)

Nothing here touches the emulator; it only reads. Pure functions so every rule can be tested alone.
"""
from __future__ import annotations

PHASES = ("idle", "initializing", "running", "waiting", "recovering", "paused", "completed", "stopped", "failed")
LABEL = {"idle": "Idle", "initializing": "Starting", "running": "Running", "waiting": "Waiting for the game",
         "recovering": "Recovering", "paused": "Paused", "completed": "Completed", "stopped": "Stopped",
         "failed": "Failed"}
COLOR = {"idle": "gray", "initializing": "blue", "running": "green", "waiting": "orange", "recovering": "orange",
         "paused": "orange", "completed": "green", "stopped": "gray", "failed": "red"}
ACTIVE = {"initializing", "running", "waiting", "recovering", "paused"}      # a script is alive in these

# a stop reason containing one of these means the run ended on a problem, not because someone stopped it
FAILURE_WORDS = ("stuck", "no progress", "game not running", "restart limit", "game shows", "needs you",
                 "missing template", "crashed", "error")
USER_STOPS = ("stopped by user", "stopped")


def end_phase(status: str, detail: str) -> str:
    """How a run ended, from the status the manager set when it finished and the reason it gave."""
    low = (detail or "").lower().strip()
    if status == "error":
        return "failed"
    if status != "idle" or not low:
        return "idle"
    if low == "finished" or low.startswith("dry run complete"):
        return "completed"
    if any(w in low for w in FAILURE_WORDS):
        return "failed"
    return "stopped"


def phase_of(status: str, script_state: str = "", recovering: str = "", ended: str = "idle") -> str:
    """The phase for a manager status, what the script reports, and how the last run ended."""
    if status == "starting":
        return "initializing"
    if status == "paused":
        return "paused"
    if status == "running":
        if recovering:
            return "recovering"
        if script_state == "unknown":
            return "waiting"
        return "running"
    if status == "error":
        return "failed"
    return ended if ended in PHASES else "idle"


def describe(phase: str, script_state: str = "", recovering: str = "", ended_text: str = "") -> str:
    """A short line to show beside the phase."""
    if phase == "recovering":
        return recovering or "restarting the game"
    if phase == "waiting":
        return "the screen is not recognised yet"
    if phase in ("completed", "stopped", "failed"):
        return ended_text
    if phase == "running" and script_state and script_state != "unknown":
        return script_state.replace("_", " ")
    return ""
