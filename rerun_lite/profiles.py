"""Profiles: named copies of an emulator's Crest settings that you can save and apply again.

Stored in data/lite/profiles.json:
    {"version": 1, "profiles": {"<name>": {"script": "crest", "saved": <unix time>, "app": "<version>",
                                              "values": {<setting key>: <value>, ...}}}}

Rules that keep this safe:
* A profile is only the script's own settings (what Settings > Auto Crest holds). The palace schedule, accounts and
  Discord are separate and are NOT in a profile.
* Applying checks every value against the script's setting definitions: unknown keys, wrong types and choices that no
  longer exist are skipped and reported, never written.
* A file written by a NEWER version of the app is read but never overwritten (you would lose what you can't see).
* Writes go to a temporary file first, so a crash can't leave a half-written profiles.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from rerun import errlog

FILE = "profiles.json"
SCHEMA_VERSION = 1
MAX_NAME = 40


class ProfileError(ValueError):
    """A problem with a message that can be shown as it is."""


def clean_name(name: str) -> str:
    n = " ".join(str(name or "").split())
    if not n:
        raise ProfileError("Give the profile a name.")
    return n[:MAX_NAME]


def coerce(setting, value: Any) -> tuple[bool, Any]:
    """(ok, value) for one setting; `setting` has .type, .choices (see rerun.scripts.base.Setting)."""
    t = setting.type
    if t == "bool":
        return (isinstance(value, bool), value)
    if t == "int":
        if isinstance(value, bool):
            return False, value
        if isinstance(value, int):
            return True, value
        if isinstance(value, float) and value.is_integer():
            return True, int(value)
        return False, value
    if t == "choice":
        return (value in (setting.choices or []), value)
    if t == "text":
        return (isinstance(value, str), value)
    return False, value                       # a setting type this code does not know: never write it blind


def validate(values: dict, spec: Iterable) -> tuple[dict, list[str]]:
    """(values that are fine, problems for the rest)."""
    by_key = {s.key: s for s in spec}
    clean, problems = {}, []
    for k, v in (values or {}).items():
        s = by_key.get(k)
        if s is None:
            problems.append(f"'{k}' is not a setting any more (skipped)")
            continue
        ok, v2 = coerce(s, v)
        if ok:
            clean[k] = v2
        else:
            problems.append(f"'{s.label}': {v!r} is not valid (skipped)")
    return clean, problems


def diff(current: dict, new: dict, spec: Iterable) -> list[tuple[str, Any, Any]]:
    """[(label, old, new)] for the settings a profile would change."""
    out = []
    for s in spec:
        if s.key in new and new[s.key] != current.get(s.key, s.default):
            out.append((s.label, current.get(s.key, s.default), new[s.key]))
    return out


class ProfileStore:
    def __init__(self, path: str | Path, app_version: str = ""):
        self.path = Path(path)
        self.app_version = app_version
        self.profiles: dict[str, dict] = {}
        self.read_only = ""            # why saving is refused (a newer file), else ""
        self.load()

    def load(self) -> None:
        self.profiles, self.read_only = {}, ""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            errlog.note("lite.profiles_load", e)
            self.read_only = "profiles.json could not be read, so it was left alone."
            return
        if not isinstance(raw, dict) or not isinstance(raw.get("profiles"), dict):
            self.read_only = "profiles.json is not in a form this version understands, so it was left alone."
            return
        ver = raw.get("version", 1)
        if not isinstance(ver, int) or ver > SCHEMA_VERSION:
            self.read_only = "profiles.json was written by a newer ReRun LITE, so it is shown but not changed."
        for name, p in raw["profiles"].items():
            if isinstance(p, dict) and isinstance(p.get("values"), dict):
                self.profiles[str(name)] = {"script": str(p.get("script") or "crest"), "saved": p.get("saved"),
                                            "app": p.get("app", ""), "values": dict(p["values"])}

    def names(self) -> list[str]:
        return sorted(self.profiles, key=str.lower)

    def _write(self) -> None:
        if self.read_only:
            raise ProfileError(self.read_only)
        data = {"version": SCHEMA_VERSION, "profiles": self.profiles}
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            raise ProfileError(f"Could not save the profile: {e}") from e

    def save(self, name: str, values: dict, spec: Iterable, script: str = "crest", overwrite: bool = False) -> str:
        name = clean_name(name)
        if name in self.profiles and not overwrite:
            raise ProfileError(f"A profile called '{name}' already exists.")
        clean, _ = validate(values, spec)
        self.profiles[name] = {"script": script, "saved": int(time.time()), "app": self.app_version, "values": clean}
        try:
            self._write()
        except ProfileError:
            self.load()
            raise
        return name

    def delete(self, name: str) -> None:
        if name not in self.profiles:
            raise ProfileError("That profile does not exist.")
        keep = dict(self.profiles)
        del self.profiles[name]
        try:
            self._write()
        except ProfileError:
            self.profiles = keep
            raise

    def rename(self, old: str, new: str) -> str:
        new = clean_name(new)
        if old not in self.profiles:
            raise ProfileError("That profile does not exist.")
        if new != old and new in self.profiles:
            raise ProfileError(f"A profile called '{new}' already exists.")
        keep = dict(self.profiles)
        self.profiles[new] = self.profiles.pop(old)
        try:
            self._write()
        except ProfileError:
            self.profiles = keep
            raise
        return new

    # ---- sharing one profile as text/file
    def export_text(self, name: str) -> str:
        p = self.profiles.get(name)
        if p is None:
            raise ProfileError("That profile does not exist.")
        return json.dumps({"version": SCHEMA_VERSION, "name": name, **p}, indent=1, ensure_ascii=False)

    def import_text(self, text: str, spec: Iterable, name: str | None = None) -> tuple[str, list[str]]:
        """Add a profile from exported text. Returns (name, problems). Values are validated like any other."""
        try:
            raw = json.loads(text)
        except ValueError as e:
            raise ProfileError("That file is not a ReRun LITE profile.") from e
        if not isinstance(raw, dict) or not isinstance(raw.get("values"), dict):
            raise ProfileError("That file is not a ReRun LITE profile.")
        if not isinstance(raw.get("version", 1), int) or raw.get("version", 1) > SCHEMA_VERSION:
            raise ProfileError("That profile was made by a newer ReRun LITE. Update first.")
        base = clean_name(name or raw.get("name") or "Imported")
        final, n = base, 2
        while final in self.profiles:                       # an import never replaces something you already have
            final, n = f"{base[:MAX_NAME - 4]} ({n})", n + 1
        clean, problems = validate(raw["values"], spec)
        self.save(final, clean, spec, script=str(raw.get("script") or "crest"))
        return final, problems
