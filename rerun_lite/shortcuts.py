"""Keyboard shortcuts you can change: one registry of actions, their default keys, and the code that turns a key
description ("Ctrl+Shift+K") into a Tk binding and back.

The choices are kept in data/lite/ui.json under "shortcuts" ({action: "Ctrl+Shift+K"}); anything not listed there uses its
default, so a new action never needs a migration. An empty string means "no shortcut". A key can belong to one action only.
"""
from __future__ import annotations

from dataclasses import dataclass

# state bits of a Tk key event
CONTROL, SHIFT, ALT = 0x0004, 0x0001, 0x20000
MODIFIER_KEYS = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Win_L", "Win_R", "Caps_Lock"}
SPECIAL = {"Return": "Enter", "comma": ",", "period": ".", "slash": "/", "minus": "-", "equal": "=", "space": "Space",
           "Prior": "PageUp", "Next": "PageDown", "ISO_Left_Tab": "Tab", "BackSpace": "Backspace"}
TK_SPECIAL = {v: k for k, v in SPECIAL.items() if k not in ("ISO_Left_Tab",)}


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    default: str
    group: str


ACTIONS = (
    Action("palette", "Command palette", "Ctrl+K", "Go"),
    Action("tab_crest", "Auto Crest", "Ctrl+1", "Go"),
    Action("tab_history", "History", "Ctrl+2", "Go"),
    Action("tab_templates", "Templates", "Ctrl+3", "Go"),
    Action("tab_settings", "Settings", "Ctrl+4", "Go"),
    Action("settings", "Open Settings", "Ctrl+,", "Go"),
    Action("next_tab", "Next tab", "Ctrl+Tab", "Go"),
    Action("prev_tab", "Previous tab", "Ctrl+Shift+Tab", "Go"),
    Action("start", "Start / stop Crest", "Ctrl+Enter", "Run"),
    Action("stop", "Stop everything", "Ctrl+.", "Run"),
    Action("dry_run", "Dry run", "Ctrl+D", "Run"),
    Action("pin", "Keep window on top", "Ctrl+T", "Window"),
    Action("copy_status", "Copy a status summary", "Ctrl+Shift+C", "Window"),
    Action("help", "Show the shortcuts", "F1", "Window"),
)
BY_ID = {a.id: a for a in ACTIONS}
GLOBAL_HOTKEYS = ("F11 pauses or resumes everything", "F12 stops everything")      # system-wide, set in config.yaml


def _split(spec: str) -> tuple[list[str], str]:
    spec = (spec or "").strip()
    if not spec:
        return [], ""
    if spec.endswith("+"):
        head, key = spec[:-1].rstrip("+"), "+"
    else:
        head, _, key = spec.rpartition("+")
    mods = {m.strip().lower() for m in head.split("+") if m.strip()}
    return [m for m in ("Ctrl", "Alt", "Shift") if m.lower() in mods], key.strip()


def normalize(spec: str) -> str:
    """'ctrl + shift + k' -> 'Ctrl+Shift+K' (a stable spelling, so two specs can be compared)."""
    mods, key = _split(spec.replace(" ", "") if spec else spec)
    if not key:
        return ""
    if len(key) == 1:
        key = key.upper() if key.isalpha() else key
    else:
        key = SPECIAL.get(key, key)
        key = key[:1].upper() + key[1:] if not (key.startswith("F") and key[1:].isdigit()) else key.upper()
    return "+".join([*mods, key])


def to_tk(spec: str) -> str:
    """'Ctrl+Shift+K' -> '<Control-Shift-Key-K>' (what bind_all wants); '' for no shortcut."""
    mods, key = _split(normalize(spec))
    if not key:
        return ""
    names = {"Ctrl": "Control", "Alt": "Alt", "Shift": "Shift"}
    parts = [names[m] for m in mods]
    if key == "Tab" and "Shift" in mods:
        return "<" + "-".join([p for p in parts if p != "Shift"] + ["ISO_Left_Tab"]) + ">"
    if len(key) == 1 and key.isalnum():
        return "<" + "-".join([*parts, "Key", key.upper() if "Shift" in mods else key.lower()]) + ">"
    name = TK_SPECIAL.get(key, key)
    return "<" + "-".join([*parts, name]) + ">"


def from_event(event) -> str:
    """The spec for a key press, or '' while only a modifier is held."""
    sym = str(event.keysym)
    if sym in MODIFIER_KEYS:
        return ""
    key = SPECIAL.get(sym, sym)
    if len(key) == 1 and key.isalpha():
        key = key.upper()
    mods = []
    if event.state & CONTROL:
        mods.append("Ctrl")
    if event.state & ALT:
        mods.append("Alt")
    if event.state & SHIFT:
        mods.append("Shift")
    return normalize("+".join([*mods, key]))


def describe(spec: str) -> str:
    return normalize(spec) or "None"


class Shortcuts:
    """The keys in force: defaults plus whatever the user changed."""

    def __init__(self, saved: dict | None = None):
        self.keys = {a.id: a.default for a in ACTIONS}
        for aid, spec in (saved or {}).items():
            if aid in BY_ID and isinstance(spec, str):
                self.keys[aid] = normalize(spec)

    def get(self, action: str) -> str:
        return self.keys.get(action, "")

    def owner(self, spec: str, ignore: str = "") -> str:
        """The action that already uses `spec` ('' when it is free)."""
        spec = normalize(spec)
        return next((aid for aid, s in self.keys.items() if s and s == spec and aid != ignore), "")

    def set(self, action: str, spec: str) -> str:
        """Give `action` a key. Returns '' on success, or a sentence saying why not."""
        spec = normalize(spec)
        if action not in BY_ID:
            return "Unknown action."
        if spec and not spec.split("+")[-1]:
            return "That is not a key."
        if spec and "+" not in spec and len(spec) == 1:
            return "Use Ctrl, Alt or a function key, so it does not fire while you type."
        taken = self.owner(spec, ignore=action)
        if taken:
            return f"{spec} is already used by '{BY_ID[taken].label}'."
        self.keys[action] = spec
        return ""

    def reset(self, action: str | None = None) -> None:
        for a in ACTIONS:
            if action in (None, a.id):
                self.keys[a.id] = a.default

    def changed(self) -> dict:
        """Only what differs from the defaults (what is saved)."""
        return {a.id: self.keys[a.id] for a in ACTIONS if self.keys[a.id] != normalize(a.default)}
