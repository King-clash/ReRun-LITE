"""Account Manager data: the single source of truth for everything about one game account.

Layout (all under <root>/accounts/, none of it touches stats.json / history / units of the legacy install):
  index.json                 {"active": id, "order": [ids]}
  events.json                game-wide event list (start/end/description); completion is per account
  <id>/account.json          profile, fields with provenance, tasks, goals, safety + notification settings
  <id>/activity.jsonl        append-only: what happened to this account (edits, scans, tasks, sessions)
  <id>/resources.jsonl       append-only: one line each time a numeric field really changes (charts)
  <id>/sessions.jsonl        farming sessions started for this account
  <id>/vault.json            per-crest annotations (substats you typed in) and keep/discard rules
  <id>/units/                this account's own unit roster (the migrated account keeps the legacy one)

Rules the code enforces:
  * every method takes an account id and refuses an unknown one - nothing is ever written "to the active account"
    by accident;
  * a field keeps WHERE its value came from: manual > verified > ocr > unverified;
  * a scan never overwrites with an uncertain reading: a low-confidence value is parked as `pending`
    and the last reliable value stays;
  * a field can be locked to "I maintain this by hand" - scans then only park their reading;
  * writes are atomic (temp file + replace) and the previous file is kept as `.bak`.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from . import errlog

STATUS_RANK = {"unverified": 1, "ocr": 2, "verified": 3, "manual": 4}
MIN_CONFIDENCE = 60.0          # an OCR reading below this is parked, never applied

# key -> (label, kind, (min, max), group)
FIELDS: dict[str, tuple[str, str, tuple | None, str]] = {
    "player_name":   ("Player name", "text", None, "Identity"),
    "player_level":  ("Player level", "int", (1, 9999), "Identity"),
    "energy":        ("Energy", "int", (0, 99999), "Energy"),
    "energy_max":    ("Max energy", "int", (1, 99999), "Energy"),
    "gems":          ("Gems", "int", (0, 10_000_000), "Currency"),
    "gold":          ("Gold", "int", (0, 10**12), "Currency"),
    "tickets":       ("Alch", "int", (0, 1_000_000), "Currency"),
    "summon_tickets": ("Summon tickets", "int", (0, 1_000_000), "Currency"),
    "raid_tickets":  ("Raid tickets", "int", (0, 1_000_000), "Currency"),
}
NUMERIC = [k for k, v in FIELDS.items() if v[1] == "int"]

# What the scanner can really read today. Everything else is manual until its screen has been captured.
SCAN_SUPPORT = {
    "energy": ("supported", "Energy bar on the quest screens (text reader, verified on real screens)."),
    "energy_max": ("supported", "Read together with energy."),
    "units": ("beta", "Compendium Counter reads the unit list; not verified on every unit."),
    "player_level": ("beta", "Rank in the top bar. Voting reader, never wrong on the 26 real screens it was checked on (one account); skips a dimmed bar."),
    "player_name": ("unsupported", "No reader yet - needs a screenshot of the profile screen."),
    "gems": ("beta", "Top bar. Voting reader, never wrong on the real screens it was checked on (one account); sometimes unsure."),
    "gold": ("beta", "Top bar. Checked only against a capped 999,999,999 balance, so small amounts are untested."),
    "tickets": ("unsupported", "No reader yet - needs a screenshot of the screen that shows Alch."),
    "summon_tickets": ("unsupported", "No reader yet."),
    "raid_tickets": ("unsupported", "No reader yet."),
    "inventory": ("unsupported", "No inventory reader. Crests found while farming are logged; the rest is manual."),
    "tasks": ("unsupported", "Daily/weekly task screens are not read; mark them done by hand or by a finished script."),
}

DEFAULT_SAFETY = {
    "automation_allowed": True,      # False: Rerun refuses to start any script for this account
    "daily_minutes_limit": 0,        # 0 = no limit (game day, counted from finished + running sessions)
    "session_minutes_limit": 0,      # 0 = no limit: a session is stopped after this many minutes
    "allowed_scripts": [],           # empty = every script; otherwise only these script ids
    "dry_run": False,                # plan only: log what would be tapped, tap nothing
}
DEFAULT_NOTIFY = {
    "enabled": True, "daily_report": True, "failures": True, "low_energy": True,
    "low_energy_below": 0,           # 0 = off
    "event_warnings": True, "event_warn_hours": 24, "ping": True,
}
DEFAULT_PREFS = {"energy_regen_minutes": 0,      # minutes per energy point; 0 = unknown -> no refill estimate
                 "week_reset_weekday": 0,        # 0 = Monday (an assumption - set it to the game's real day)
                 "stale_scan_hours": 24}

SCAN_HISTORY_KEEP = 100


class AccountError(ValueError):
    """Bad input for an account operation (the message is meant to be shown to the user)."""


def _now() -> float:
    return time.time()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if path.exists():
        try:
            os.replace(path, path.with_suffix(path.suffix + ".bak"))
        except OSError as e:  # noqa: BLE001 - a missing backup must not block the save
            errlog.note("accounts.bak", e)
    os.replace(tmp, path)


def _load(path: Path, default):
    """Read JSON; a damaged file is set aside (never deleted) and the default is used."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as e:
        try:
            path.replace(path.with_suffix(path.suffix + f".corrupt-{int(_now())}"))
        except OSError:
            pass
        errlog.note("accounts.load", e)
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            return json.loads(bak.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default


def validate_value(key: str, value):
    """Return the cleaned value or raise AccountError with a message fit for the user."""
    if key not in FIELDS:
        raise AccountError(f"Unknown field '{key}'.")
    label, kind, rng, _ = FIELDS[key]
    if kind == "text":
        s = str(value).strip()
        if not s:
            raise AccountError(f"{label} cannot be empty.")
        return s[:60]
    if isinstance(value, bool):
        raise AccountError(f"{label} must be a number.")
    if isinstance(value, str):
        s = value.replace(",", "").replace(" ", "").strip()
        if not s.lstrip("-").isdigit():
            raise AccountError(f"{label} must be a whole number (got '{value}').")
        value = int(s)
    elif isinstance(value, float):
        if value != int(value):
            raise AccountError(f"{label} must be a whole number (got {value}).")
        value = int(value)
    elif not isinstance(value, int):
        raise AccountError(f"{label} must be a number.")
    lo, hi = rng
    if not lo <= value <= hi:
        raise AccountError(f"{label} must be between {lo:,} and {hi:,} (got {value:,}).")
    return value


def _blank(aid: str, name: str, label: str = "", notes: str = "", instance: str = "") -> dict:
    t = _now()
    return {"id": aid, "name": name, "label": label, "notes": notes, "instance": instance,
            "created": t, "modified": t, "fields": {}, "pending": {}, "locked": [],
            "tasks": {}, "custom_tasks": [], "goals": [], "event_done": {}, "event_reminded": {}, "alerts_sent": {},
            "scan_history": [], "last_scan_ok": None, "legacy_units": False,
            "safety": dict(DEFAULT_SAFETY), "notify": dict(DEFAULT_NOTIFY), "prefs": dict(DEFAULT_PREFS),
            "schema": 1}


class AccountStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.dir = self.root / "accounts"
        self._lock = threading.RLock()
        self._cache: dict[str, dict] = {}
        self.index: dict = _load(self.dir / "index.json", {"active": "", "order": []})
        self.listeners: list = []      # callables(kind, account_id, detail) - the GUI refreshes on these
        self.index["order"] = [a for a in self.index.get("order", []) if (self.dir / a / "account.json").exists()]
        if self.index["active"] not in self.index["order"]:
            self.index["active"] = self.index["order"][0] if self.index["order"] else ""

    # ------------------------------------------------------------------ storage
    def _path(self, aid: str, name: str = "account.json") -> Path:
        return self.dir / aid / name

    def _save_index(self) -> None:
        _atomic_write(self.dir / "index.json", json.dumps(self.index, indent=1))

    def _get(self, aid: str) -> dict:
        with self._lock:
            if aid not in self.index["order"]:
                raise AccountError(f"No account with id '{aid}'.")
            if aid not in self._cache:
                data = _load(self._path(aid), None)
                if data is None:
                    raise AccountError(f"Account '{aid}' could not be read.")
                base = _blank(aid, data.get("name", aid))
                for k, v in base.items():           # fill keys added by newer versions, keep everything else
                    data.setdefault(k, v)
                for k in ("safety", "notify", "prefs"):
                    data[k] = {**base[k], **(data.get(k) or {})}
                self._cache[aid] = data
            return self._cache[aid]

    def _save(self, a: dict) -> None:
        a["modified"] = _now()
        _atomic_write(self._path(a["id"]), json.dumps(a, indent=1, ensure_ascii=False))

    def _emit(self, kind: str, aid: str, detail: str = "") -> None:
        for fn in list(self.listeners):
            try:
                fn(kind, aid, detail)
            except Exception as e:  # noqa: BLE001 - a broken listener must not break the data layer
                errlog.note("accounts.listener", e)

    def log_activity(self, aid: str, kind: str, detail: str, **extra) -> None:
        self._get(aid)
        rec = {"t": _now(), "kind": kind, "detail": detail, **extra}
        with self._lock:
            p = self._path(aid, "activity.jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def read_log(self, aid: str, name: str, limit: int = 0) -> list[dict]:
        self._get(aid)
        out = []
        try:
            with self._path(aid, name).open(encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue           # one damaged line never hides the rest
        except FileNotFoundError:
            pass
        return out[-limit:] if limit else out

    def activity(self, aid: str, limit: int = 200) -> list[dict]:
        return self.read_log(aid, "activity.jsonl", limit)

    # ------------------------------------------------------------------ accounts
    def ids(self) -> list[str]:
        return list(self.index["order"])

    def all(self) -> list[dict]:
        return [self._get(a) for a in self.index["order"]]

    @property
    def active_id(self) -> str:
        return self.index["active"]

    def active(self) -> dict | None:
        return self._get(self.index["active"]) if self.index["active"] else None

    def get(self, aid: str) -> dict:
        return self._get(aid)

    def create(self, name: str, label: str = "", notes: str = "", instance: str = "",
               legacy_units: bool = False) -> str:
        name = (name or "").strip()
        if not name:
            raise AccountError("Give the account a name.")
        with self._lock:
            if any(a["name"].lower() == name.lower() for a in self.all()):
                raise AccountError(f"An account named '{name}' already exists.")
            aid = uuid.uuid4().hex[:8]
            a = _blank(aid, name[:40], label.strip()[:30], notes, instance)
            a["legacy_units"] = legacy_units
            self._cache[aid] = a
            self.index["order"].append(aid)
            if not self.index["active"]:
                self.index["active"] = aid
            self._save(a)
            self._save_index()
        self.log_activity(aid, "account", "Account created")
        self._emit("created", aid)
        return aid

    def update(self, aid: str, **changes) -> dict:
        with self._lock:
            a = self._get(aid)
            for k, v in changes.items():
                if k == "name":
                    v = (v or "").strip()
                    if not v:
                        raise AccountError("Give the account a name.")
                    if any(o["id"] != aid and o["name"].lower() == v.lower() for o in self.all()):
                        raise AccountError(f"An account named '{v}' already exists.")
                    a["name"] = v[:40]
                elif k in ("label", "notes", "instance"):
                    a[k] = str(v)[:2000 if k == "notes" else 60]
                else:
                    raise AccountError(f"'{k}' cannot be changed this way.")
            self._save(a)
        self.log_activity(aid, "account", "Details edited: " + ", ".join(changes))
        self._emit("updated", aid)
        return a

    def remove(self, aid: str, keep_files: bool = True) -> None:
        """Remove an account. Its folder is MOVED to accounts/_removed/ (recoverable), not deleted."""
        with self._lock:
            self._get(aid)
            src = self.dir / aid
            if keep_files and src.exists():
                dst = self.dir / "_removed" / f"{aid}-{int(_now())}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(src, dst)
            self.index["order"].remove(aid)
            self._cache.pop(aid, None)
            if self.index["active"] == aid:
                self.index["active"] = self.index["order"][0] if self.index["order"] else ""
            self._save_index()
        self._emit("removed", aid)

    def set_active(self, aid: str) -> None:
        with self._lock:
            self._get(aid)
            self.index["active"] = aid
            self._save_index()
        self._emit("active", aid)

    def accounts_for_instance(self, instance: str) -> list[dict]:
        return [a for a in self.all() if a["instance"] == instance]

    def units_dir(self, aid: str) -> Path | None:
        """Where this account's unit roster lives: None means 'the legacy root' (migrated account)."""
        a = self._get(aid)
        return None if a["legacy_units"] else self.dir / aid

    # ------------------------------------------------------------------ fields
    def field(self, aid: str, key: str) -> dict | None:
        return self._get(aid)["fields"].get(key)

    def value(self, aid: str, key: str, default=None):
        f = self.field(aid, key)
        return f["value"] if f else default

    def set_locked(self, aid: str, key: str, locked: bool) -> None:
        with self._lock:
            a = self._get(aid)
            if key not in FIELDS:
                raise AccountError(f"Unknown field '{key}'.")
            s = set(a["locked"])
            (s.add if locked else s.discard)(key)
            a["locked"] = sorted(s)
            self._save(a)

    def set_field(self, aid: str, key: str, value, status: str = "manual", source: str = "",
                  confidence: float | None = None, scan: str | None = None) -> dict:
        """Store one value. Returns {"applied": bool, "reason": str}. Raises AccountError on bad input."""
        if status not in STATUS_RANK:
            raise AccountError(f"Unknown status '{status}'.")
        value = validate_value(key, value)
        with self._lock:
            a = self._get(aid)
            cur = a["fields"].get(key)
            if status != "manual":
                if key in a["locked"]:
                    return self._park(a, key, value, status, confidence, "field is maintained by hand")
                if status == "ocr" and (confidence is None or confidence < MIN_CONFIDENCE):
                    return self._park(a, key, value, "unverified", confidence, "reading too uncertain")
                if cur and STATUS_RANK.get(cur["status"], 0) > STATUS_RANK[status] and status == "unverified":
                    return self._park(a, key, value, status, confidence, "an unverified value never replaces a better one")
            if key == "energy" and a["fields"].get("energy_max"):
                mx = a["fields"]["energy_max"]["value"]
                if value > mx and status != "manual":
                    return self._park(a, key, value, status, confidence, f"energy {value} is above max {mx}")
            rec = {"value": value, "status": status, "t": _now(), "source": source}
            if confidence is not None:
                rec["confidence"] = round(float(confidence), 1)
            if scan:
                rec["scan"] = scan
            old = cur["value"] if cur else None
            a["fields"][key] = rec
            a["pending"].pop(key, None)
            self._save(a)
        if key in NUMERIC and old != value:
            self._append_resource(aid, key, value, status)
        if old != value or (cur and cur["status"] != status):
            self.log_activity(aid, "field", f"{FIELDS[key][0]}: {old if old is not None else '-'} -> {value} ({status})")
        self._emit("field", aid, key)
        return {"applied": True, "reason": ""}

    def _park(self, a: dict, key: str, value, status: str, confidence, reason: str) -> dict:
        a["pending"][key] = {"value": value, "status": status, "t": _now(), "reason": reason,
                             **({"confidence": round(float(confidence), 1)} if confidence is not None else {})}
        self._save(a)
        return {"applied": False, "reason": reason}

    def accept_pending(self, aid: str, key: str) -> None:
        with self._lock:
            p = self._get(aid)["pending"].get(key)
        if not p:
            raise AccountError("Nothing is waiting for that field.")
        self.set_field(aid, key, p["value"], status="manual", source="accepted scan reading")

    def clear_field(self, aid: str, key: str) -> None:
        with self._lock:
            a = self._get(aid)
            a["fields"].pop(key, None)
            a["pending"].pop(key, None)
            self._save(a)
        self.log_activity(aid, "field", f"{FIELDS[key][0]} cleared")
        self._emit("field", aid, key)

    def _append_resource(self, aid: str, key: str, value: int, status: str) -> None:
        with self._lock:
            p = self._path(aid, "resources.jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": _now(), "key": key, "value": value, "status": status}) + "\n")

    def resource_history(self, aid: str, key: str) -> list[tuple[float, int]]:
        return [(r["t"], r["value"]) for r in self.read_log(aid, "resources.jsonl") if r.get("key") == key]

    # ------------------------------------------------------------------ scans
    def record_scan(self, aid: str, readings: dict, source: str, expected: list[str] | None = None,
                    unsupported: list[str] | None = None) -> dict:
        """Apply a scan's readings ({key: (value, confidence)}) and keep a report of what happened.
        Nothing the scan could not read is touched."""
        scan_id = uuid.uuid4().hex[:8]
        detected, uncertain, rejected = [], [], []
        for key, (value, conf) in readings.items():
            try:
                res = self.set_field(aid, key, value, status="ocr", source=source, confidence=conf, scan=scan_id)
            except AccountError as e:
                rejected.append({"key": key, "reason": str(e)})
                continue
            (detected if res["applied"] else uncertain).append(
                {"key": key, "value": value, "confidence": conf, "reason": res["reason"]})
        missing = [k for k in (expected or []) if k not in readings]
        report = {"id": scan_id, "t": _now(), "source": source, "detected": detected, "uncertain": uncertain,
                  "rejected": rejected, "missing": missing, "unsupported": unsupported or []}
        with self._lock:
            a = self._get(aid)
            a["scan_history"] = (a["scan_history"] + [report])[-SCAN_HISTORY_KEEP:]
            if detected:
                a["last_scan_ok"] = report["t"]
            self._save(a)
        self.log_activity(aid, "scan", f"{source}: {len(detected)} read, {len(uncertain)} uncertain, "
                                       f"{len(missing)} not found", scan=scan_id)
        self._emit("scan", aid, scan_id)
        return report

    # ------------------------------------------------------------------ sessions
    def begin_session(self, aid: str, instance: str, script: str, dry_run: bool = False) -> str:
        sid = uuid.uuid4().hex[:8]
        rec = {"id": sid, "account": aid, "instance": instance, "script": script, "start": _now(),
               "end": None, "status": "running", "dry_run": dry_run, "results": {}, "error": ""}
        with self._lock:
            p = self._path(aid, "sessions.jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        self.log_activity(aid, "session", f"Started {script} on {instance}" + (" (dry run)" if dry_run else ""))
        self._emit("session", aid, sid)
        return sid

    def end_session(self, aid: str, sid: str, status: str, results: dict | None = None, error: str = "") -> None:
        """Sessions are append-only: finishing writes a second line with the same id (latest wins)."""
        recs = self.sessions(aid)
        base = next((r for r in recs if r["id"] == sid), None)
        if base is None:
            raise AccountError("Unknown session.")
        done = {**base, "end": _now(), "status": status, "results": results or {}, "error": error}
        with self._lock:
            with self._path(aid, "sessions.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(done) + "\n")
        self.log_activity(aid, "session", f"{base['script']} {status}" + (f": {error}" if error else ""))
        self._emit("session", aid, sid)

    def sessions(self, aid: str) -> list[dict]:
        latest: dict[str, dict] = {}
        for r in self.read_log(aid, "sessions.jsonl"):
            latest[r["id"]] = r
        return sorted(latest.values(), key=lambda r: r["start"])

    # ------------------------------------------------------------------ settings
    def update_settings(self, aid: str, section: str, **values) -> dict:
        defaults = {"safety": DEFAULT_SAFETY, "notify": DEFAULT_NOTIFY, "prefs": DEFAULT_PREFS}
        if section not in defaults:
            raise AccountError(f"Unknown settings section '{section}'.")
        with self._lock:
            a = self._get(aid)
            for k, v in values.items():
                if k not in defaults[section]:
                    raise AccountError(f"Unknown setting '{k}'.")
                want = defaults[section][k]
                if isinstance(want, bool):
                    v = bool(v)
                elif isinstance(want, int):
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        raise AccountError(f"'{k}' must be a whole number.") from None
                    if v < 0 or (k == "week_reset_weekday" and v > 6):
                        raise AccountError(f"'{k}' is out of range.")
                elif isinstance(want, list):
                    v = [str(x) for x in v]
                a[section][k] = v
            self._save(a)
        self.log_activity(aid, "settings", f"{section}: " + ", ".join(f"{k}={v}" for k, v in values.items()))
        self._emit("settings", aid, section)
        return a[section]

    # ------------------------------------------------------------------ events (game-wide)
    def events(self) -> list[dict]:
        return _load(self.dir / "events.json", [])

    def save_event(self, title: str, start: float, end: float, description: str = "",
                   goal: str = "", event_id: str = "") -> str:
        title = (title or "").strip()
        if not title:
            raise AccountError("Give the event a title.")
        if end <= start:
            raise AccountError("The event must end after it starts.")
        with self._lock:
            evs = self.events()
            if event_id:
                ev = next((e for e in evs if e["id"] == event_id), None)
                if ev is None:
                    raise AccountError("Unknown event.")
                ev.update(title=title, start=start, end=end, description=description, goal=goal)
            else:
                event_id = uuid.uuid4().hex[:8]
                evs.append({"id": event_id, "title": title, "start": start, "end": end,
                            "description": description, "goal": goal, "source": "manual"})
            _atomic_write(self.dir / "events.json", json.dumps(evs, indent=1, ensure_ascii=False))
        self._emit("events", "", event_id)
        return event_id

    def delete_event(self, event_id: str) -> None:
        with self._lock:
            evs = [e for e in self.events() if e["id"] != event_id]
            _atomic_write(self.dir / "events.json", json.dumps(evs, indent=1, ensure_ascii=False))
        self._emit("events", "", event_id)

    def set_event_done(self, aid: str, event_id: str, done: bool) -> None:
        with self._lock:
            a = self._get(aid)
            if done:
                a["event_done"][event_id] = _now()
            else:
                a["event_done"].pop(event_id, None)
            self._save(a)
        self._emit("events", aid, event_id)
