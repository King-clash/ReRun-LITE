"""Unit Roster: the units on the user's account, as read from their own game.

Data lives in <root>/units/:
  roster.json   {canonical name: unit record}
  scans.jsonl   one line per scan: {"id", "t", "source", "observed": {name: fields}, ...}
  aliases.json  {misread or alternative spelling: canonical name}  (the learned name list)

A unit record keeps every field with its provenance:
  {"name": "...", "first_seen": t, "last_seen": t, "last_scan": id,
   "fields": {"level": {"value": 120, "status": "ocr", "confidence": 91.0,
                        "t": ..., "scan": id, "shot": "..."}, ...}}

Status order (higher wins, never silently replaced by a lower one):
  manual > verified > ocr > estimated > uncertain
A scan that couldn't read a field leaves the stored value alone, so an incomplete
scan never erases good data. No reference data from outside the game is used.
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import re
import threading
import time
from pathlib import Path

from . import errlog

STATUS_RANK = {"uncertain": 0, "estimated": 1, "ocr": 2, "reference": 3, "verified": 4, "manual": 5}
# Unit names: "manual" (you typed it) > "reference" (GS Companion's spelling, clear match)
#             > "ocr" > "uncertain".
FIELDS = ["element", "race", "quest_clears", "level", "rarity", "awakening"]
# What a Units-list scan can read from a unit's page. Level / rarity / awakening are not
# shown there; they stay empty until a screen that shows them is calibrated.
SCANNED_FIELDS = ("element", "race", "quest_clears")
MATCH_RATIO = 0.86          # fuzzy name match needed to map a reading onto a known unit
MIN_NAME_CONF = 60.0        # OCR confidence below this: name kept as "uncertain"
GSC_UNITS_URL = "https://gscompanion.com/units/"


def norm_name(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s.strip(" .,:;|_-")


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm_name(s).lower())


class UnitRoster:
    def __init__(self, root: str | Path):
        self.dir = Path(root) / "units"
        self.roster_path = self.dir / "roster.json"
        self.scans_path = self.dir / "scans.jsonl"
        self.alias_path = self.dir / "aliases.json"
        self._lock = threading.Lock()
        self.units: dict[str, dict] = self._load_json(self.roster_path, {})
        self.aliases: dict[str, str] = self._load_json(self.alias_path, {})
        # reference(name, element, race) -> reference name; set by the Manager when GS
        # Companion data is present. Applied after every scan.
        self.reference = None
        self.reference_facts = None        # name -> {"element", "race"} from GS Companion
        self.rename_listeners: list = []   # (old, new) callbacks, e.g. Compendium targets

    @staticmethod
    def _load_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for path, data in ((self.roster_path, self.units), (self.alias_path, self.aliases)):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)  # atomic: a crash never leaves half a roster

    # ------------------------------------------------------------ names (option 3)
    def resolve_name(self, read: str, confidence: float = 100.0) -> tuple[str, str, float]:
        """Map an OCR reading to a unit name. Returns (name, how, score) where how is
        'alias' (a correction you made), 'exact', 'fuzzy' (close to a known unit),
        'new' (not seen before) or 'uncertain' (low confidence, unknown)."""
        name = norm_name(read)
        k = _key(name)
        for alias, canon in self.aliases.items():
            if _key(alias) == k:
                return canon, "alias", 1.0
        known = {_key(n): n for n in self.units}
        if k in known:
            return known[k], "exact", 1.0
        best, score = None, 0.0
        for kk, n in known.items():
            r = difflib.SequenceMatcher(None, k, kk).ratio()
            if r > score:
                best, score = n, r
        if best and score >= MATCH_RATIO:
            return best, "fuzzy", round(score, 3)
        return name, ("uncertain" if confidence < MIN_NAME_CONF else "new"), round(score, 3)

    def correct_name(self, wrong: str, right: str) -> str:
        """Manual correction: remember the alias and merge a mistaken record into the right one."""
        wrong, right = norm_name(wrong), norm_name(right)
        with self._lock:
            self.aliases[wrong] = right
            bad = self.units.pop(wrong, None)
            if bad:
                good = self.units.setdefault(right, {"name": right, "first_seen": bad["first_seen"],
                                                     "last_seen": bad["last_seen"], "fields": {}})
                for f, v in bad.get("fields", {}).items():
                    cur = good["fields"].get(f)
                    if cur is None or STATUS_RANK[v["status"]] > STATUS_RANK[cur["status"]]:
                        good["fields"][f] = v
                good["first_seen"] = min(good["first_seen"], bad["first_seen"])
            self.units.setdefault(right, {"name": right, "first_seen": time.time(),
                                          "last_seen": time.time(), "fields": {}})
            self.units[right]["name_status"] = "manual"
            self._save()
        return right

    def remove(self, name: str) -> bool:
        """Delete a unit record you don't want (e.g. a misread). Scans in scans.jsonl
        are kept as they were; aliases pointing at it are dropped."""
        with self._lock:
            if self.units.pop(name, None) is None:
                return False
            self.aliases = {a: c for a, c in self.aliases.items() if c != name}
            self._save()
        return True

    # ------------------------------------------------------------ reference names
    def _apply_facts(self, u: dict) -> bool:
        """Race / element of a unit known by its reference name: GS Companion's value
        replaces a misread or uncertain one ('(men' -> Human) and confirms a matching one.
        Values you entered (manual) or verified are never touched. True if changed."""
        if self.reference_facts is None or u.get("name_status") not in ("reference", "manual", "ocr"):
            return False
        try:
            facts = self.reference_facts(u["name"]) or {}
        except Exception as e:  # noqa: BLE001
            errlog.note("units.reference_facts", e)
            return False
        mine = (u["fields"].get("element") or {}).get("value")
        if u.get("name_status") != "reference" and mine and facts.get("element") not in (None, mine):
            return False  # same name, different element: not the same unit - leave it
        changed = False
        for f in ("element", "race"):
            v = facts.get(f)
            if not v:
                continue
            cur = u["fields"].get(f)
            if cur and cur.get("status") in ("manual", "verified"):
                continue
            if cur and cur.get("value") == v:
                if cur.get("status") != "reference":
                    cur["status"] = "reference"
                    changed = True
                continue
            new = {"value": v, "status": "reference", "t": time.time()}
            if cur:
                new["read"] = cur.get("value")
            u["fields"][f] = new
            changed = True
        return changed

    def _reference_for(self, ob: dict) -> str | None:
        if self.reference is None:
            return None
        f = ob.get("fields") or {}
        el = (f.get("element") or {}).get("value")
        race = (f.get("race") or {}).get("value")
        try:
            return norm_name(self.reference(ob.get("name", ""), el, race) or "") or None
        except Exception as e:  # noqa: BLE001 - reference data is optional
            errlog.note("units.reference_name", e)
            return None

    def adopt_reference_names(self, lookup) -> list[tuple[str, str]]:
        """Give scanned units the reference (GS Companion) name when it clearly matches.

        lookup(name, element, race) -> reference name or None. Names you corrected
        yourself (manual) are never changed. The old spelling becomes an alias, so the
        next scan maps straight onto the new name, and every rename is logged in
        units/renames.jsonl (undo: Correct Name back). A reference name already used by
        another unit is left alone (two readings are never merged on a guess)."""
        done: list[tuple[str, str]] = []
        with self._lock:
            for name in list(self.units):
                u = self.units[name]
                if u.get("name_status") == "manual":
                    continue
                f = u.get("fields", {})
                el = (f.get("element") or {}).get("value")
                race = (f.get("race") or {}).get("value")
                try:
                    ref = lookup(name, el, race)
                except Exception as e:  # noqa: BLE001 - reference data is optional
                    errlog.note("units.adopt_reference", e)
                    ref = None
                ref = norm_name(ref or "")
                if not ref or ref == name or ref in self.units:
                    continue
                self.units[ref] = {**self.units.pop(name), "name": ref, "name_status": "reference",
                                   "read_as": u.get("read_as") or name}
                self.aliases[name] = ref
                for a, c in list(self.aliases.items()):
                    if c == name:
                        self.aliases[a] = ref
                done.append((name, ref))
            facts = [n for n, u in self.units.items() if self._apply_facts(u)]
            if done or facts:
                self._save()
                t = time.time()
                with (self.dir / "renames.jsonl").open("a", encoding="utf-8") as fh:
                    for old, new in done:
                        fh.write(json.dumps({"t": t, "from": old, "to": new, "source": "gscompanion"},
                                            ensure_ascii=False) + "\n")
        for old, new in done:
            for cb in self.rename_listeners:
                cb(old, new)
        return done

    # ------------------------------------------------------------ editing
    def set_field(self, name: str, field: str, value, status: str = "manual") -> None:
        with self._lock:
            u = self.units.setdefault(name, {"name": name, "first_seen": time.time(),
                                             "last_seen": time.time(), "fields": {}})
            u["fields"][field] = {"value": value, "status": status, "t": time.time()}
            self._save()

    # ------------------------------------------------------------ scans
    def apply_scan(self, observed: list[dict], source: str, shot_dir: str | None = None,
                   complete: bool | None = None) -> dict:
        """Merge one scan. observed: [{"name", "name_conf", "fields": {f: {"value",
        "confidence"}}, "shot"}]. complete: the scan reached the end of the list
        (False = stopped early). Returns a summary with new units and changes."""
        t = time.time()
        scan_id = time.strftime("%Y%m%d_%H%M%S", time.localtime(t))
        summary = {"scan": scan_id, "seen": 0, "new": [], "changed": [], "uncertain": [],
                   "kept": 0}
        stored_obs: dict[str, dict] = {}
        with self._lock:
            for ob in observed:
                name, how, score = self.resolve_name(ob.get("name", ""), ob.get("name_conf", 100))
                if not name:
                    continue
                ref = self._reference_for(ob) if how in ("new", "uncertain", "fuzzy") else None
                if ref and ref != name and (how != "fuzzy" or ref in self.units):
                    # GS Companion knows this unit: file the reading under its name.
                    read = norm_name(ob.get("name", ""))
                    if read and read != ref:
                        self.aliases[read] = ref
                    name, how = ref, ("exact" if ref in self.units else "reference")
                summary["seen"] += 1
                if how == "uncertain":
                    summary["uncertain"].append(name)
                read = norm_name(ob.get("name", ""))
                cur = self.units.get(name)
                if (how == "fuzzy" and cur is not None and cur.get("name_status") == "uncertain"
                        and ob.get("name_conf", 0) >= MIN_NAME_CONF and read and read != name):
                    # A confident reading replaces an earlier uncertain spelling (never a
                    # manual one); the old spelling is kept as an alias.
                    self.units[read] = {**self.units.pop(name), "name": read, "name_status": "ocr"}
                    self.aliases[name] = read
                    summary.setdefault("renamed", []).append((name, read))
                    name = read
                u = self.units.get(name)
                if u is None:
                    u = self.units[name] = {"name": name, "first_seen": t, "last_seen": t,
                                            "fields": {}, "name_status": "uncertain" if how == "uncertain" else "ocr"}
                    if how == "reference":
                        u["name_status"], u["read_as"] = "reference", norm_name(ob.get("name", ""))
                    summary["new"].append(name)
                u["last_seen"], u["last_scan"] = t, scan_id
                if how == "fuzzy":
                    u.setdefault("readings", [])
                    if ob.get("name") not in u["readings"]:
                        u["readings"] = (u["readings"] + [ob.get("name")])[-5:]
                obs_fields = {}
                for f, fv in (ob.get("fields") or {}).items():
                    if fv is None or fv.get("value") in (None, ""):
                        continue  # unreadable: keep what we have
                    conf = float(fv.get("confidence", 0))
                    status = "ocr" if conf >= MIN_NAME_CONF else "uncertain"
                    new = {"value": fv["value"], "status": status, "confidence": conf, "t": t,
                           "scan": scan_id}
                    if ob.get("shot"):
                        new["shot"] = ob["shot"]
                    obs_fields[f] = fv["value"]
                    cur = u["fields"].get(f)
                    if cur is None:
                        u["fields"][f] = new
                    elif cur["value"] == fv["value"]:
                        if STATUS_RANK[status] >= STATUS_RANK[cur["status"]]:
                            u["fields"][f] = {**cur, "t": t, "scan": scan_id,
                                              "confidence": max(conf, cur.get("confidence", 0))}
                    elif STATUS_RANK[status] >= STATUS_RANK[cur["status"]] and cur["status"] not in ("manual", "verified"):
                        summary["changed"].append((name, f, cur["value"], fv["value"]))
                        u["fields"][f] = new
                    else:
                        summary["kept"] += 1  # lower-trust reading never replaces a better value
                stored_obs[name] = obs_fields
                self._apply_facts(u)
            self._save()
            rec = {"id": scan_id, "t": t, "source": source, "observed": stored_obs,
                   "new": summary["new"]}
            if complete is not None:
                rec["complete"] = bool(complete)
            with self.scans_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return summary

    def scans(self) -> list[dict]:
        out = []
        if self.scans_path.exists():
            for line in self.scans_path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def compare(self, old_id: str, new_id: str) -> dict:
        """Differences between two scans: units added/missing and field changes."""
        s = {x["id"]: x for x in self.scans()}
        a, b = s[old_id]["observed"], s[new_id]["observed"]
        changes = []
        for n in sorted(set(a) & set(b)):
            for f in sorted(set(a[n]) | set(b[n])):
                if f in a[n] and f in b[n] and a[n][f] != b[n][f]:
                    changes.append((n, f, a[n][f], b[n][f]))
        return {"added": sorted(set(b) - set(a)), "not_seen": sorted(set(a) - set(b)),
                "changed": changes}

    # ------------------------------------------------------------ views
    def value(self, u: dict, f: str):
        v = u.get("fields", {}).get(f)
        return v["value"] if v else None

    def rows(self, search: str = "", sort: str = "name", desc: bool = False,
             rarity: str | None = None, element: str | None = None,
             only_incomplete: bool = False) -> list[dict]:
        out = []
        q = search.lower().strip()
        for u in self.units.values():
            if q and q not in u["name"].lower():
                continue
            if rarity and str(self.value(u, "rarity")) != rarity:
                continue
            if element and str(self.value(u, "element")) != element:
                continue
            if only_incomplete and u.get("name_status") != "uncertain" and all(
                    self.value(u, f) is not None and u["fields"][f]["status"] != "uncertain"
                    for f in SCANNED_FIELDS):
                continue
            out.append(u)

        def k(u):
            v = u["name"].lower() if sort == "name" else (
                u.get(sort) if sort in ("first_seen", "last_seen") else self.value(u, sort))
            return (v is None, v if v is not None else 0)
        return sorted(out, key=k, reverse=desc)

    def to_csv(self, rows: list[dict] | None = None) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["name", *FIELDS, "first_seen", "last_seen", "uncertain_fields"])
        for u in rows if rows is not None else self.rows():
            unsure = [f for f, v in u.get("fields", {}).items() if v["status"] == "uncertain"]
            w.writerow([u["name"], *[self.value(u, f) if self.value(u, f) is not None else "" for f in FIELDS],
                        time.strftime("%Y-%m-%d", time.localtime(u["first_seen"])),
                        time.strftime("%Y-%m-%d", time.localtime(u["last_seen"])), " ".join(unsure)])
        return buf.getvalue()

    def summary_text(self) -> str:
        n = len(self.units)
        if not n:
            return "No units scanned yet."
        scans = self.scans()
        last = scans[-1] if scans else None
        incomplete = len(self.rows(only_incomplete=True))
        text = f"**{n}** unit{'s' if n != 1 else ''} on record"
        if last:
            text += (f" · last scan {time.strftime('%d %b %H:%M', time.localtime(last['t']))} "
                     f"({len(last['observed'])} read, {len(last.get('new', []))} new)")
        if incomplete:
            text += f" · {incomplete} unread or uncertain"
        return text
