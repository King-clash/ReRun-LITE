"""Activity categories for the Log tab: Information, Automation, Warning, Error, Recovery, System.

One pure function, so the same line gets the same category everywhere (the window, the saved log, Discord)."""
from __future__ import annotations

CATEGORIES = ("Information", "Automation", "Warning", "Error", "Recovery", "System")
RECOVERY_WORDS = ("restart", "relaunch", "recover", "logging back in", "popup", "pop-up", "dismiss", "maintenance",
                  "log back in", "game is not running")
SYSTEM_INSTANCES = {"app", "discord", "scheduler", "update", "updates"}


def categorize(instance: str, message: str, level: str = "info") -> str:
    low = (message or "").lower()
    body = low.split("] ", 1)[-1] if low.startswith("[") else low          # the script's own words, without '[Crest]'
    if body.startswith(("session ended", "recovery step finished")):        # summaries mention restarts but are not one
        return "Information"
    if any(w in body for w in RECOVERY_WORDS):
        return "Recovery"
    if level == "error":
        return "Error"
    if level == "warn":
        return "Warning"
    if instance in SYSTEM_INSTANCES:
        return "System"
    if low.startswith("[") or low.startswith(("state:", "dry run", "started", "resumed", "paused", "stopping")):
        return "Automation"
    return "Information"


def collapsed(message: str) -> tuple[str, int]:
    """(first line, number of further lines) so a traceback can be shown folded."""
    lines = (message or "").splitlines() or [""]
    return lines[0], len(lines) - 1
