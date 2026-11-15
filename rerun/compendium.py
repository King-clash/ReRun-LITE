"""Compendium: quest clear targets and progress per unit, from the Unit Roster's scans.

Every scan stays in units/scans.jsonl (nothing here edits it). Targets live in
units/targets.json:
  {"global": 100 | null,          target for every unit without its own
   "near_pct": 90,                "near target" = at least this % done
   "units": {"Unit name": 500}}   individual targets (win over the global one)

Clear counts come from the roster (the best reading so far); the change column
compares the latest reading with the previous scan that read the same unit,
e.g. "+12 since 14 Nov". Readings made under a name later corrected in the Units
tab are mapped to the corrected name through the roster's aliases.
"""
from __future__ import annotations

import json
import threading
import time

from .units import UnitRoster

NEAR_PCT = 90
UNREAD = "Unread or uncertain"
FILTERS = ("All units", UNREAD, "With a target", "Near target", "At target")


def bar(pct: float | None, width: int = 10) -> str:
    """Text progress bar for tables and Discord: '██████░░░░ 60%'."""
    if pct is None:
        return ""
    full = max(0, min(width, int(round(pct / 100 * width))))
    return "█" * full + "░" * (width - full) + f" {pct:.0f}%"


def day(t: float) -> str:
    return time.strftime("%d %b", time.localtime(t)).lstrip("0")


class Compendium:
    def __init__(self, roster: UnitRoster, history=None):
        self.r = roster
        self.history = history
        self.path = roster.dir / "targets.json"
        self._lock = threading.Lock()
        self.targets = self._load()

    def _load(self) -> dict:
        data = {"global": None, "near_pct": NEAR_PCT, "units": {}}
        try:
            data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
        return data

    def _save(self) -> None:
        self.r.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.targets, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------ targets
    def set_target(self, name: str, n: int | None) -> None:
        """Individual target; None (or 0) removes it so the global one applies."""
        with self._lock:
            if n:
                self.targets["units"][name] = int(n)
            else:
                self.targets["units"].pop(name, None)
            self._save()

    def rename(self, old: str, new: str) -> None:
        """A name corrected in the Units tab keeps its target (unless the new name has one)."""
        with self._lock:
            t = self.targets["units"].pop(old, None)
            if t and new not in self.targets["units"]:
                self.targets["units"][new] = t
            if t:
                self._save()

    def set_global(self, n: int | None) -> None:
        with self._lock:
            self.targets["global"] = int(n) if n else None
            self._save()

    def set_near(self, pct: int) -> None:
        with self._lock:
            self.targets["near_pct"] = max(1, min(99, int(pct)))
            self._save()

    def target_of(self, name: str) -> tuple[int | None, str]:
        """(target, 'unit' | 'global' | '')"""
        own = self.targets["units"].get(name)
        if own:
            return int(own), "unit"
        g = self.targets.get("global")
        return (int(g), "global") if g else (None, "")

    # ------------------------------------------------------------ scan history
    def _canon(self, name: str) -> str:
        seen = set()
        while name in self.r.aliases and name not in seen:  # follow chains of renames
            seen.add(name)
            name = self.r.aliases[name]
        return name

    def readings(self) -> dict[str, list[tuple[float, int]]]:
        """{unit: [(scan time, quest clears), ...]} oldest first, one per scan."""
        out: dict[str, list[tuple[float, int]]] = {}
        for s in self.r.scans():
            for n, f in (s.get("observed") or {}).items():
                v = f.get("quest_clears")
                if isinstance(v, int):
                    out.setdefault(self._canon(n), []).append((s["t"], v))
        for v in out.values():
            v.sort()
        return out

    def last_scan(self) -> dict | None:
        scans = self.r.scans()
        return scans[-1] if scans else None

    def last_complete_scan(self) -> dict | None:
        """Newest scan that reached the end of the list. Scans saved before the flag
        existed are checked against their History entry ("Reached the end of the list")."""
        ended = []
        if self.history is not None:
            ended = [e["t"] for e in self.history.recent(500, kind="compendium")
                     if "Reached the end of the list" in e.get("detail", "")]
        for s in reversed(self.r.scans()):
            if s.get("complete") or (s.get("complete") is None
                                     and any(abs(t - s["t"]) < 30 for t in ended)):
                return s
        return None

    # ------------------------------------------------------------ rows
    def rows(self, search: str = "", sort: str = "name", desc: bool = False,
             show: str = "All units", element: str | None = None) -> list[dict]:
        """One row per roster unit: its roster fields plus target progress."""
        hist = self.readings()
        near = self.targets.get("near_pct") or NEAR_PCT
        out = []
        for u in self.r.rows(search=search, element=element, only_incomplete=(show == UNREAD)):
            name = u["name"]
            clears = self.r.value(u, "quest_clears")
            target, kind = self.target_of(name)
            pct = remaining = None
            if target and clears is not None:
                pct = min(100.0, clears / target * 100)
                remaining = max(0, target - clears)
            delta = since = None
            h = hist.get(name, [])
            if len(h) >= 2:
                delta, since = h[-1][1] - h[-2][1], h[-2][0]
            state = ("done" if remaining == 0 else "near" if pct is not None and pct >= near
                     else "" if pct is None else "open")
            if show == "With a target" and not target:
                continue
            if show == "Near target" and state != "near":
                continue
            if show == "At target" and state != "done":
                continue
            out.append({"name": name, "element": self.r.value(u, "element"),
                        "element_unsure": (u["fields"].get("element") or {}).get("status") == "uncertain",
                        "race": self.r.value(u, "race"), "last_seen": u.get("last_seen"),
                        "clears": clears, "target": target, "target_kind": kind,
                        "pct": pct, "remaining": remaining, "delta": delta, "since": since,
                        "state": state, "uncertain": u.get("name_status") == "uncertain",
                        "status": (u["fields"].get("quest_clears") or {}).get("status")})

        def v(r):
            return r["name"].lower() if sort == "name" else r.get(sort)
        have = sorted((r for r in out if v(r) is not None), key=v, reverse=desc)
        return have + sorted((r for r in out if v(r) is None), key=lambda r: r["name"].lower())

    def unit_line(self, name: str) -> str | None:
        """One line about a roster unit for other views (GS Companion): clears, target,
        progress, change. None when the unit is not in the roster."""
        rows = [r for r in self.rows() if r["name"] == name]
        if not rows:
            return None
        r = rows[0]
        parts = ["clears not read" if r["clears"] is None else f"{r['clears']:,} quest clears"]
        if r["target"]:
            parts.append(f"target {r['target']:,}" + (" (global)" if r["target_kind"] == "global" else ""))
            if r["pct"] is not None:
                parts.append("reached" if r["state"] == "done" else f"{r['remaining']:,} to go ({r['pct']:.0f}%)")
        ch = self.change_text(r)
        if ch:
            parts.append(ch)
        return "  ·  ".join(parts)

    @staticmethod
    def change_text(row: dict) -> str:
        if row["delta"] is None:
            return ""
        return f"{row['delta']:+,} since {day(row['since'])}"

    # ------------------------------------------------------------ summaries
    def summary(self) -> dict:
        rows = self.rows()
        last = self.last_scan()
        full = self.last_complete_scan()
        return {"units": len(rows),
                "with_target": sum(1 for r in rows if r["target"]),
                "near": sum(1 for r in rows if r["state"] == "near"),
                "done": sum(1 for r in rows if r["state"] == "done"),
                "last_scan": last["t"] if last else None,
                "last_scan_complete": bool(full and last and full["t"] == last["t"]),
                "last_complete": full["t"] if full else None,
                "global": self.targets.get("global"),
                "near_pct": self.targets.get("near_pct") or NEAR_PCT}

    def summary_text(self) -> str:
        s = self.summary()
        if not s["units"]:
            return "No units scanned yet."
        when = (time.strftime("%d %b %H:%M", time.localtime(s["last_complete"]))
                if s["last_complete"] else "none yet")
        text = f"Last full scan: **{when}** · {s['units']} units"
        if s["last_scan"] and not s["last_scan_complete"]:
            text += f" (newest scan {day(s['last_scan'])} stopped early)"
        if s["with_target"]:
            text += (f"\nTargets: {s['with_target']} · near (≥{s['near_pct']}%): **{s['near']}** · "
                     f"reached: **{s['done']}**")
        else:
            text += "\nNo targets set yet."
        return text


__all__ = ["Compendium", "FILTERS", "UNREAD", "bar", "day"]
