"""GS Companion reference data (https://gscompanion.com): Crest Palace schedule, crests,
crest recommendations per unit, and the global unit list.

The JSON lives in <root>/data/gscompanion/ and is built from scraped pages by
tools/gscompanion_build.py (see that file to refresh it). It is fan-site data: use it
for hints, names and lookups; what the game shows on screen always wins.

    from rerun.gsc_data import GSCData
    gsc = GSCData(root)
    gsc.palace_today()                     # stages open this game day
    gsc.stages_dropping("Arts gauge UP")   # where a crest drops
    gsc.match_crest("Arts gauge UP Lv4")   # OCR text -> (crest record, "Lv4")
    gsc.recommended("Clyde")               # ["ATK UP"]
    gsc.match_unit("Mira (Fire")           # fuzzy OCR name -> unit record
"""
from __future__ import annotations

import difflib
import json
import re
import time
from functools import cached_property
from pathlib import Path

from .crest_stats import game_day

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_LEVEL_RE = re.compile(r"\bLv\.?\s*([1-5])\s*(\+)?", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_BASE_RE = re.compile(r"\s*\(.*?\)\s*$")  # "Kane (Earth)" -> "Kane"


class GSCData:
    def __init__(self, root: str | Path):
        self.dir = Path(root) / "data" / "gscompanion"

    def _load(self, name: str) -> dict:
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    @property
    def available(self) -> bool:
        return (self.dir / "crests.json").exists()

    # --- raw data ---------------------------------------------------------------
    @cached_property
    def stages(self) -> list[dict]:
        return self._load("crest_palace.json").get("stages", [])

    @cached_property
    def crests(self) -> list[dict]:
        return self._load("crests.json").get("crests", [])

    @cached_property
    def recommendations(self) -> dict[str, list[str]]:
        return self._load("crest_recommendations.json").get("units", {})

    @cached_property
    def units(self) -> list[dict]:
        return self._load("units.json").get("units", [])

    @cached_property
    def _crest_by_norm(self) -> dict[str, dict]:
        return {_norm(c["name"]): c for c in self.crests}

    @cached_property
    def _unit_by_norm(self) -> dict[str, dict]:
        return {_norm(u["name"]): u for u in self.units}

    # --- Crest Palace -------------------------------------------------------------
    def palace_on(self, day: str, difficulty: str | None = None) -> list[dict]:
        """Stages open on a weekday ("Friday"), optionally one difficulty (NOVA/EXTREME/PRO)."""
        day = day.title()
        return [s for s in self.stages if day in s["days"]
                and (difficulty is None or s["difficulty"] == difficulty.upper())]

    def palace_today(self, t: float | None = None, difficulty: str | None = None) -> list[dict]:
        """Stages open in the current game day (rolls over at ReRun's 06:00 UTC-6 reset)."""
        return self.palace_on(DAYS[game_day(time.time() if t is None else t).weekday()], difficulty)

    def stage(self, name: str) -> dict | None:
        n = _norm(name)
        return next((s for s in self.stages if _norm(s["name"]) == n or s["slug"] == name), None)

    # --- crests -------------------------------------------------------------------
    def crest(self, name: str) -> dict | None:
        return self._crest_by_norm.get(_norm(name))

    def stages_dropping(self, crest_name: str) -> list[dict]:
        """Palace stages a crest drops in, each with its weekdays."""
        c = self.crest(crest_name)
        if not c:
            return []
        slugs = {d["slug"] for d in c.get("drops", [])}
        return [s for s in self.stages if s["slug"] in slugs]

    def match_crest(self, text: str, cutoff: float = 0.8) -> tuple[dict | None, str | None]:
        """Map an OCR'd crest title like "ATK UP Lv4+" to (crest record, "Lv4+").

        The level is read from the text; the name is matched exactly, then fuzzily."""
        lv = None
        m = _LEVEL_RE.search(text or "")
        if m:
            lv = f"Lv{m.group(1)}{'+' if m.group(2) else ''}"
            name = (text[:m.start()] + text[m.end():]).strip()
        else:
            name = text or ""
        n = _norm(name)
        if n in self._crest_by_norm:
            return self._crest_by_norm[n], lv
        close = difflib.get_close_matches(n, list(self._crest_by_norm), n=1, cutoff=cutoff)
        return (self._crest_by_norm[close[0]] if close else None), lv

    def recommended(self, unit_name: str) -> list[str]:
        """Best crests for a unit, best first (CrestRec via GS Companion)."""
        if unit_name in self.recommendations:
            return self.recommendations[unit_name]
        u = self.match_unit(unit_name)
        return self.recommendations.get(u["name"], []) if u else []

    def units_wanting(self, crest_name: str) -> list[str]:
        """Units whose recommendation list includes this crest."""
        c = self.crest(crest_name)
        name = c["name"] if c else crest_name
        return [u for u, cs in self.recommendations.items() if name in cs]

    # --- units: reference names for scanned units -------------------------------------
    @cached_property
    def _details(self) -> dict:
        return self._load("unit_details.json").get("units", {})

    def best_unit(self, text: str, element: str | None = None,
                  race: str | None = None) -> dict | None:
        """Score every GS Companion unit (of the same element when known) against a name
        read from the game. The game shows titles ("Clyde, the Crimson Sword God",
        "Awoken Priscilla") where the site uses the short name, and OCR runs words
        together, so a unit's name found as the last words, the words before a comma,
        or inside the reading scores high. Returns {"name", "score", "second",
        "second_name"} or None when there is nothing to compare."""
        k = _key(text)
        if not k:
            return None
        words = _norm(text).split()
        comma = text.split(",", 1)[0] if "," in text else None
        pool = [u for u in self.units if not element or u.get("element") == element] or self.units
        scored: dict[str, float] = {}
        for u in pool:
            d = self._details.get(u["name"]) or {}
            names = {u["name"], _BASE_RE.sub("", u["name"])} | set(d.get("aka") or [])
            best = 0.0
            for n in names:
                ck = _key(n)
                if not ck:
                    continue
                cw = _norm(n).split()
                if ck == k:
                    s = 1.0
                elif comma is not None and _key(comma) == ck:
                    s = 0.95                         # "Clyde, the Crimson Sword God"
                elif comma is None and len(cw) <= len(words) and words[-len(cw):] == cw:
                    s = 0.95                         # "Awoken Priscilla", "Holy Knight Goddess Feena"
                elif any(words[i:i + len(cw)] == cw for i in range(len(words))):
                    s = 0.85                         # whole words somewhere in the title
                elif len(ck) >= 4 and ck in k:
                    s = min(0.9, 0.75 + 0.25 * len(ck) / len(k))   # inside run-together OCR
                else:
                    s = difflib.SequenceMatcher(None, k, ck).ratio()
                best = max(best, s)
            if race and d.get("race") and race.lower() == str(d["race"]).lower():
                best += 0.03
            scored[u["name"]] = best
        if not scored:
            return None
        ranked = sorted(scored.items(), key=lambda x: -x[1])
        (n1, s1), (n2, s2) = ranked[0], (ranked[1] if len(ranked) > 1 else ("", 0.0))
        return {"name": n1, "score": round(s1, 3), "second": round(s2, 3), "second_name": n2}

    def unit_facts(self, name: str) -> dict:
        """Element and race GS Companion lists for a unit (by its exact name)."""
        u = next((x for x in self.units if x["name"] == name), None)
        if not u:
            return {}
        out = {"element": u.get("element")}
        race = (self._details.get(name) or {}).get("race")
        if race:
            out["race"] = race
        return {k: v for k, v in out.items() if v}

    REF_MIN = 0.78      # best score needed to take GS Companion's name
    REF_MARGIN = 0.05   # ...and how far ahead of the next unit it must be

    def reference_name(self, text: str, element: str | None = None,
                       race: str | None = None) -> str | None:
        """GS Companion's name for a scanned unit, only when one unit clearly matches
        (e.g. "Rimuru" matches two units equally: no answer)."""
        b = self.best_unit(text, element, race)
        if not b or b["score"] < self.REF_MIN:
            return None
        if b["score"] - b["second"] >= self.REF_MARGIN:
            return b["name"]
        # Close call between a full name and a shorter one inside it ("Godspeed Crusader
        # Platina" vs "Platina"): the more specific name wins when it reads well.
        k1, k2 = _key(_BASE_RE.sub("", b["name"])), _key(_BASE_RE.sub("", b["second_name"]))
        if b["score"] >= 0.9 and b["score"] > b["second"] and k2 and k2 in k1 and k1 != k2:
            return b["name"]
        return None

    # --- units --------------------------------------------------------------------
    def match_unit(self, text: str, cutoff: float = 0.86) -> dict | None:
        n = _norm(text)
        if n in self._unit_by_norm:
            return self._unit_by_norm[n]
        close = difflib.get_close_matches(n, list(self._unit_by_norm), n=1, cutoff=cutoff)
        return self._unit_by_norm[close[0]] if close else None
