"""Desktop notifications: which events may pop one up, and when. Pure logic - the window only shows the result.

Saved in data/lite/ui.json as "notify_desktop". Off by default: nothing new appears until you turn it on."""
from __future__ import annotations

KINDS = (("failed", "A session failed or crashed"),
         ("finished", "A session finished (stopped by its own limit)"),
         ("stuck", "Crest looks stuck"),
         ("recovery", "The game was restarted or logged back in"))
DEFAULTS = {"enabled": False, "only_hidden": True, "failed": True, "finished": False, "stuck": True, "recovery": False}
COOLDOWN_S = 60.0           # the same kind for the same emulator is shown at most once a minute


def load(raw) -> dict:
    """The saved dict with every key present and a real true/false; anything odd falls back to the default."""
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        for k in DEFAULTS:
            if isinstance(raw.get(k), bool):
                out[k] = raw[k]
    return out


def decide(prefs: dict, kind: str, window_visible: bool) -> bool:
    if not prefs.get("enabled") or not prefs.get(kind, False):
        return False
    return not (prefs.get("only_hidden") and window_visible)


class Throttle:
    def __init__(self, cooldown: float = COOLDOWN_S):
        self.cooldown = cooldown
        self._seen: dict[tuple[str, str], float] = {}

    def allow(self, kind: str, instance: str, now: float) -> bool:
        key = (kind, instance)
        last = self._seen.get(key)
        if last is not None and now - last < self.cooldown:
            return False
        self._seen[key] = now
        return True


def message(kind: str, instance: str, detail: str = "") -> tuple[str, str]:
    """(title, text) for the pop-up."""
    detail = (detail or "").strip()
    head = {"failed": "Session failed", "finished": "Session finished", "stuck": "Crest looks stuck",
            "recovery": "Game restarted"}.get(kind, "ReRun LITE")
    return f"{head} - {instance}", detail[:200] if detail else head
