"""Sanity check of config.yaml against the defaults: unknown keys and wrong value types.

Only warns (Rerun keeps working with what it can read); the messages go to the Log tab so a typo
like `discord: {enable: true}` or `close_to_tray: "yes"` is noticed instead of silently ignored."""
from __future__ import annotations

from typing import Any

# Top-level sections whose inner keys are free-form (per instance / per script / per routine).
FREE_FORM = {"script_settings", "schedules", "instances"}


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "section"
    return "empty" if value is None else type(value).__name__


def _compatible(default: Any, value: Any) -> bool:
    if value is None:
        return True                      # an empty YAML value means "use the default"
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


def check_config(raw: dict, defaults: dict, _path: str = "") -> list[str]:
    out: list[str] = []
    for key, value in (raw or {}).items():
        where = f"{_path}{key}"
        if key not in defaults:
            out.append(f"config.yaml: unknown setting '{where}' (ignored) - check the spelling")
            continue
        default = defaults[key]
        if not _compatible(default, value):
            out.append(f"config.yaml: '{where}' should be {_kind(default)} but is {_kind(value)}")
        elif isinstance(default, dict) and isinstance(value, dict) and key not in FREE_FORM and default:
            out += check_config(value, default, f"{where}.")
    return out
