"""Goals and what to farm next.

Goal types (each reads real numbers; nothing is invented):
  resource    reach N of a currency field            current = the account's field (manual or scanned)
  unit_level  get unit X to level N                  current = the account's unit roster
  crest       collect N crests (rarity / palace)     current = crests logged since the goal was created
  custom      anything else, tracked by hand         current = the progress you enter

Recommendations name the routine that supports a goal and say WHY, using only what is known. A run
estimate appears only when the ledger holds enough data (>= MIN_RUNS runs and >= 1 matching drop).
Nothing here starts a script or spends a resource.
"""
from __future__ import annotations

import time
import uuid

from .accounts import FIELDS, AccountError, AccountStore
from .crest_stats import RARITIES
from .vault import Vault, attribute

GOAL_TYPES = ("resource", "unit_level", "crest", "custom")
MIN_RUNS = 20


class Goals:
    def __init__(self, store: AccountStore, vault: Vault, roster_for, ledger):
        self.s, self.vault, self.roster_for, self.ledger = store, vault, roster_for, ledger

    # ------------------------------------------------------------------ crud
    def add(self, aid: str, gtype: str, title: str, target: int = 1, priority: int = 5, **spec) -> str:
        if gtype not in GOAL_TYPES:
            raise AccountError(f"Goal type must be one of {', '.join(GOAL_TYPES)}.")
        title = (title or "").strip()
        if not title:
            raise AccountError("Give the goal a title.")
        try:
            target = int(target)
        except (TypeError, ValueError):
            raise AccountError("The target must be a whole number.") from None
        if target < 1:
            raise AccountError("The target must be at least 1.")
        if gtype == "resource":
            key = spec.get("key")
            if key not in FIELDS or FIELDS[key][1] != "int":
                raise AccountError("Pick a currency or number field for a resource goal.")
        elif gtype == "unit_level":
            if not (spec.get("unit") or "").strip():
                raise AccountError("Name the unit.")
        elif gtype == "crest":
            r = spec.get("rarity", "")
            if r and r not in RARITIES:
                raise AccountError(f"Rarity must be one of {', '.join(RARITIES)}.")
        a = self.s.get(aid)
        gid = uuid.uuid4().hex[:8]
        with self.s._lock:
            a["goals"].append({"id": gid, "type": gtype, "title": title[:80], "target": target,
                               "priority": max(1, min(9, int(priority))), "created": time.time(),
                               "status": "active", "done_at": None, "manual": 0,
                               "history": [{"t": time.time(), "event": "created"}],
                               **{k: v for k, v in spec.items() if k in ("key", "unit", "rarity", "palace")}})
            self.s._save(a)
        self.s.log_activity(aid, "goal", f"Goal added: {title}")
        self.s._emit("goal", aid, gid)
        return gid

    def _goal(self, aid, gid) -> dict:
        g = next((x for x in self.s.get(aid)["goals"] if x["id"] == gid), None)
        if g is None:
            raise AccountError("Unknown goal.")
        return g

    def edit(self, aid: str, gid: str, **changes) -> None:
        g = self._goal(aid, gid)
        with self.s._lock:
            for k, v in changes.items():
                if k == "target":
                    v = int(v)
                    if v < 1:
                        raise AccountError("The target must be at least 1.")
                elif k == "priority":
                    v = max(1, min(9, int(v)))
                elif k == "manual":
                    v = max(0, int(v))
                elif k not in ("title", "unit", "key", "rarity", "palace"):
                    raise AccountError(f"'{k}' cannot be edited.")
                g[k] = v
            g["history"].append({"t": time.time(), "event": "edited: " + ", ".join(changes)})
            self.s._save(self.s.get(aid))
        self.s._emit("goal", aid, gid)

    def remove(self, aid: str, gid: str) -> None:
        a = self.s.get(aid)
        g = self._goal(aid, gid)
        with self.s._lock:
            g["status"] = "archived"          # kept for goal history, hidden from the active list
            g["history"].append({"t": time.time(), "event": "removed"})
            self.s._save(a)
        self.s.log_activity(aid, "goal", f"Goal removed: {g['title']}")
        self.s._emit("goal", aid, gid)

    # ------------------------------------------------------------------ progress
    def current(self, aid: str, g: dict) -> tuple[int | None, str]:
        """(current value or None when unknown, where it came from)."""
        t = g["type"]
        if t == "resource":
            f = self.s.field(aid, g["key"])
            return (f["value"], f"{FIELDS[g['key']][0]} ({f['status']})") if f else (None, "no value recorded yet")
        if t == "unit_level":
            roster = self.roster_for(aid)
            u = roster.units.get(g["unit"]) if roster else None
            lv = roster.value(u, "level") if u else None
            return (int(lv), "unit roster") if lv is not None else (None, "unit not in this account's roster")
        if t == "crest":
            n = 0
            for r in self.vault.ledger_records(aid):
                if float(r["t"]) < g["created"]:
                    continue
                if g.get("rarity") and r.get("rarity") != g["rarity"]:
                    continue
                if g.get("palace") and g["palace"].lower() not in (r.get("palace") or "").lower():
                    continue
                n += 1
            return n, "crests logged since the goal was created"
        return int(g.get("manual", 0)), "entered by hand"

    def progress(self, aid: str, g: dict) -> dict:
        cur, src = self.current(aid, g)
        target = g["target"]
        frac = 0.0 if cur is None else min(1.0, cur / target)
        done = cur is not None and cur >= target
        return {"goal": g, "current": cur, "target": target, "fraction": frac, "done": done,
                "remaining": None if cur is None else max(0, target - cur), "source": src}

    def refresh(self, aid: str) -> list[dict]:
        """Progress for every active/done goal; marks newly reached ones done (and logs it once)."""
        out = []
        a = self.s.get(aid)
        for g in sorted((x for x in a["goals"] if x["status"] in ("active", "done")),
                        key=lambda x: (x["status"] != "active", x["priority"], x["created"])):
            p = self.progress(aid, g)
            if p["done"] and g["status"] == "active":
                with self.s._lock:
                    g["status"], g["done_at"] = "done", time.time()
                    g["history"].append({"t": g["done_at"], "event": "reached"})
                    self.s._save(a)
                self.s.log_activity(aid, "goal", f"Goal reached: {g['title']}")
                self.s._emit("goal", aid, g["id"])
            out.append(p)
        return out

    # ------------------------------------------------------------------ advice
    def _crest_rate(self, aid: str, g: dict) -> tuple[float | None, int]:
        """(matching drops per run, runs counted) from this account's attributed ledger records."""
        runs = drops = 0
        for r in getattr(self.ledger, "records", []):
            if r.get("type") not in ("run", "drop") or attribute(self.s, r) != aid:
                continue
            if r["type"] == "run":
                runs += 1
            elif (not g.get("rarity") or r.get("rarity") == g["rarity"]) and \
                    (not g.get("palace") or g["palace"].lower() in (r.get("palace") or "").lower()):
                drops += 1
        return (drops / runs if runs >= MIN_RUNS and drops else None), runs

    def recommend(self, aid: str, scripts_available: dict[str, str]) -> list[dict]:
        """One entry per active, unfinished goal, most important first: what to do and why."""
        recs = []
        for p in self.refresh(aid):
            g = p["goal"]
            if g["status"] != "active":
                continue
            rem = p["remaining"]
            if g["type"] == "crest":
                rate, runs = self._crest_rate(aid, g)
                script = "crest" if "crest" in scripts_available else None
                why = f"{rem} more needed ({p['current']} of {g['target']})."
                if rate:
                    why += f" Your ledger shows about 1 in {round(1 / rate)} runs matches, so roughly {round(rem / rate)} runs."
                else:
                    why += f" Not enough data to estimate runs ({runs} counted; needs {MIN_RUNS}+ runs and a match)."
                recs.append({"goal": g["title"], "goal_id": g["id"], "script": script,
                             "action": "Run the Crest farm" if script else "Crest script unavailable", "why": why})
            elif g["type"] == "resource":
                recs.append({"goal": g["title"], "goal_id": g["id"], "script": None,
                             "action": "No farm is linked to this currency",
                             "why": (f"{rem:,} to go." if rem is not None else "No value recorded - enter or scan it.")
                                    + " Rerun does not know which activity earns it, so it makes no suggestion."})
            elif g["type"] == "unit_level":
                recs.append({"goal": g["title"], "goal_id": g["id"], "script": None,
                             "action": "Level it in the game",
                             "why": (f"{rem} level(s) to go." if rem is not None else p["source"])
                                    + " Unit material requirements are not available to Rerun."})
            else:
                recs.append({"goal": g["title"], "goal_id": g["id"], "script": None,
                             "action": "Tracked by hand", "why": f"{p['current']} of {g['target']} entered."})
        return recs
