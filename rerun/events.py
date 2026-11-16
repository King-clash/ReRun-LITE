"""The events Manager.emit sends to listeners (GUI, Discord), written down as types.

Events are plain dicts at run time (so every existing listener keeps working); these TypedDicts
document and type-check their shape. The GUI's own queue also carries private events whose type
starts with an underscore (`_preview`, `_error`...) - those never leave the GUI."""
from __future__ import annotations

from typing import Any, TypedDict, Union


class LogEvent(TypedDict):
    type: str          # "log"
    instance: str
    message: str
    line: str          # "HH:MM:SS [instance] message"
    level: str         # info | warn | error
    category: str      # Information | Automation | Warning | Error | Recovery | System (ReRun LITE adds it)


class StatusEvent(TypedDict):
    type: str          # "status"
    instance: str
    status: str        # idle | starting | running | paused | error
    detail: str


class PhaseEvent(TypedDict):
    type: str          # "phase" (ReRun LITE): the richer run phase changed; `status` events are unchanged
    instance: str
    phase: str         # idle | initializing | running | waiting | recovering | paused | completed | stopped | failed
    detail: str


class NotifyEvent(TypedDict):
    type: str          # "notify"
    instance: str
    message: str


class HistoryEvent(TypedDict):
    type: str          # "history"
    entry: dict[str, Any]   # the History entry (t, instance, script, kind, detail, ...)


Event = Union[LogEvent, StatusEvent, PhaseEvent, NotifyEvent, HistoryEvent]

# event type -> the keys it must carry (used by tests so a listener can rely on them)
REQUIRED_KEYS: dict[str, set[str]] = {
    "log": {"type", "instance", "message", "line", "level"},
    "status": {"type", "instance", "status", "detail"},
    "phase": {"type", "instance", "phase", "detail"},
    "notify": {"type", "instance", "message"},
    "history": {"type", "entry"},
}


def problems(event: dict) -> list[str]:
    """What is wrong with an event dict (empty = well formed)."""
    need = REQUIRED_KEYS.get(str(event.get("type")))
    if need is None:
        return [f"unknown event type {event.get('type')!r}"]
    missing = sorted(need - set(event))
    return [f"{event['type']} event is missing {', '.join(missing)}"] if missing else []
