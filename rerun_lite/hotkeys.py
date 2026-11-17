"""System-wide hotkey text: check what you typed ("ctrl+alt+s", "f12") and turn it into what pynput wants.

A key by itself is only allowed for F1-F24 and a few non-typing keys, so a letter can never be hijacked from every
other program. Pure logic; the window starts and stops the listener."""
from __future__ import annotations

MODIFIERS = ("ctrl", "alt", "shift", "cmd")
ALIASES = {"control": "ctrl", "ctl": "ctrl", "option": "alt", "win": "cmd", "windows": "cmd", "super": "cmd"}
SOLO_OK = {f"f{i}" for i in range(1, 25)} | {"pause", "scroll_lock", "insert", "home", "end", "page_up", "page_down"}
NAMED = SOLO_OK | {"delete", "space", "tab", "enter", "esc", "backspace", "print_screen", "up", "down", "left", "right"}
SLOTS = (("stop_all", "Stop everything", "f12"), ("pause_all", "Pause or resume everything", "f11"),
         ("compact", "Show or hide the compact window", ""))


def parse(text: str) -> tuple[str, str]:
    """(canonical text, pynput spec) for what was typed; ('', '') for empty = no hotkey. Raises ValueError (with a
    message you can show) if it is not usable."""
    raw = (text or "").strip().lower().replace(" ", "")
    if not raw:
        return "", ""
    parts = [ALIASES.get(p, p) for p in raw.replace("-", "+").split("+") if p]
    if not parts or len(set(parts)) != len(parts):
        raise ValueError("Type keys joined with +, like ctrl+alt+s or f12.")
    *mods, key = parts
    for m in mods:
        if m not in MODIFIERS:
            raise ValueError(f"'{m}' is not a modifier. Use ctrl, alt, shift or cmd, then the key.")
    if key in MODIFIERS:
        raise ValueError("End the hotkey with a normal key, like ctrl+alt+s.")
    single = len(key) == 1 and key.isalnum()
    if not single and key not in NAMED:
        raise ValueError(f"'{key}' is not a key I know. Use a letter, a digit or a name like f12, home or pause.")
    if not mods and key not in SOLO_OK:
        raise ValueError("A plain letter or digit would stop working everywhere. Add ctrl/alt, or use an F-key.")
    ordered = [m for m in MODIFIERS if m in mods]
    canon = "+".join([*ordered, key])
    spec = "+".join([f"<{m}>" for m in ordered] + [key if single else f"<{key}>"])
    return canon, spec


def clashes(values: dict[str, str]) -> str | None:
    """A message if two slots got the same hotkey, else None."""
    seen: dict[str, str] = {}
    for slot, v in values.items():
        try:
            canon = parse(v)[0]
        except ValueError:
            continue
        if canon and canon in seen:
            return f"'{canon}' is used twice. Each hotkey needs its own keys."
        if canon:
            seen[canon] = slot
    return None


def mapping(values: dict[str, str], actions: dict) -> dict:
    """{pynput spec: callable} for the slots that have a valid hotkey and an action."""
    out = {}
    for slot, fn in actions.items():
        try:
            spec = parse(values.get(slot, ""))[1]
        except ValueError:
            continue
        if spec and fn is not None:
            out[spec] = fn
    return out
