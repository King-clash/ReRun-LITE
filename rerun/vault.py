"""Crest Vault: the crests an account found, with the substats you typed in and keep / review advice.

Crests come from Rerun's own crest ledger (crest_log.jsonl: what the Crest script saw and did). The ledger
is per emulator, so a drop is attributed to an account by the farming session that was running then, or,
failing that, by the account bound to that emulator when exactly one is. A drop that cannot be attributed
safely is left out of every vault ("unattributed") rather than guessed.

Substats cannot be read from the screen yet - you enter them. The vault only ever RECOMMENDS: keep,
review, possible duplicate, or consider discarding. It has no way to scrap, sell or discard anything.
"""
from __future__ import annotations

import json
import time
import uuid

from .accounts import AccountError, AccountStore, _atomic_write, _load
from .crest_stats import RARITIES, _live_times, _seen_live

RARITY_ORDER = {r: i for i, r in enumerate(RARITIES)}      # lv3 < lv3+ < lv4 < 4+ < burst < ?
VERDICTS = ("keep", "review", "possible duplicate", "consider discarding")
DEFAULT_RULES = {"keep_rarities": ["4+", "burst"], "discard_rarities": ["lv3"],
                 "wanted_substats": [], "duplicate_limit": 2}


def attribute(store: AccountStore, rec: dict) -> str | None:
    """Account id a ledger record belongs to, or None when that cannot be said safely."""
    inst, t = rec.get("instance"), float(rec.get("t", 0))
    hits = set()
    for a in store.all():
        for s in store.sessions(a["id"]):
            if s["instance"] == inst and s["start"] - 1 <= t <= (s["end"] or time.time()) + 5:
                hits.add(a["id"])
    if len(hits) == 1:
        return hits.pop()
    if hits:
        return None
    bound = store.accounts_for_instance(inst)
    return bound[0]["id"] if len(bound) == 1 else None


class Vault:
    def __init__(self, store: AccountStore, ledger):
        self.s, self.ledger = store, ledger

    def _path(self, aid):
        self.s.get(aid)
        return self.s.dir / aid / "vault.json"

    def _data(self, aid) -> dict:
        d = _load(self._path(aid), {})
        d.setdefault("annotations", {})
        d.setdefault("manual", [])
        d["rules"] = {**DEFAULT_RULES, **(d.get("rules") or {})}
        return d

    def _save(self, aid, d):
        _atomic_write(self._path(aid), json.dumps(d, indent=1, ensure_ascii=False))

    # ------------------------------------------------------------------ items
    def ledger_records(self, aid: str) -> list[dict]:
        recs = list(getattr(self.ledger, "records", []))
        live = _live_times(recs)
        out = []
        for r in recs:
            if r.get("type") != "drop":
                continue
            if r.get("source") == "history" and _seen_live(live, r.get("instance"), float(r["t"])):
                continue
            if attribute(self.s, r) == aid:
                out.append(r)
        return out

    def items(self, aid: str) -> list[dict]:
        d = self._data(aid)
        items = []
        for r in self.ledger_records(aid):
            key = f"L{int(float(r['t']) * 1000)}"
            ann = d["annotations"].get(key, {})
            items.append({"key": key, "t": float(r["t"]), "rarity": r.get("rarity", "?"),
                          "name": ann.get("name") or r.get("title") or "", "palace": r.get("palace", ""),
                          "action": r.get("action", ""), "substats": ann.get("substats", []),
                          "note": ann.get("note", ""), "source": "ledger"})
        for m in d["manual"]:
            items.append({**m, "source": "manual", "action": m.get("action", "kept")})
        items.sort(key=lambda i: i["t"])
        self._judge(items, d["rules"])
        return items

    def add_manual(self, aid: str, rarity: str, name: str, substats: list[str] | None = None,
                   palace: str = "", note: str = "", when: float | None = None) -> str:
        if rarity not in RARITIES:
            raise AccountError(f"Rarity must be one of {', '.join(RARITIES)}.")
        if not (name or "").strip():
            raise AccountError("Give the crest a name.")
        d = self._data(aid)
        key = "M" + uuid.uuid4().hex[:8]
        d["manual"].append({"key": key, "t": when or time.time(), "rarity": rarity, "name": name.strip()[:60],
                            "palace": palace, "substats": [s.strip() for s in (substats or []) if s.strip()],
                            "note": note})
        self._save(aid, d)
        self.s.log_activity(aid, "vault", f"Crest added by hand: {name}")
        return key

    def annotate(self, aid: str, key: str, substats: list[str] | None = None, note: str | None = None,
                 name: str | None = None) -> None:
        d = self._data(aid)
        m = next((x for x in d["manual"] if x["key"] == key), None)
        if m is not None:
            if substats is not None:
                m["substats"] = [s.strip() for s in substats if s.strip()]
            if note is not None:
                m["note"] = note
            if name:
                m["name"] = name
        else:
            if not any(i["key"] == key for i in self.items(aid)):
                raise AccountError("Unknown crest.")
            a = d["annotations"].setdefault(key, {})
            if substats is not None:
                a["substats"] = [s.strip() for s in substats if s.strip()]
            if note is not None:
                a["note"] = note
            if name:
                a["name"] = name
        self._save(aid, d)

    def remove_manual(self, aid: str, key: str) -> None:
        d = self._data(aid)
        d["manual"] = [m for m in d["manual"] if m["key"] != key]
        self._save(aid, d)

    # ------------------------------------------------------------------ rules + advice
    def rules(self, aid: str) -> dict:
        return self._data(aid)["rules"]

    def set_rules(self, aid: str, **rules) -> dict:
        d = self._data(aid)
        for k, v in rules.items():
            if k not in DEFAULT_RULES:
                raise AccountError(f"Unknown rule '{k}'.")
            if k in ("keep_rarities", "discard_rarities"):
                bad = [x for x in v if x not in RARITIES]
                if bad:
                    raise AccountError(f"Unknown rarity: {', '.join(bad)}.")
            if k == "duplicate_limit":
                v = int(v)
                if v < 1:
                    raise AccountError("The duplicate limit must be at least 1.")
            d["rules"][k] = v
        self._save(aid, d)
        return d["rules"]

    @staticmethod
    def _judge(items: list[dict], rules: dict) -> None:
        """Adds 'verdict' and 'why' to each item. Recommendation only - nothing is ever changed."""
        wanted = [w.lower() for w in rules["wanted_substats"]]
        groups: dict[tuple, list[dict]] = {}
        for it in items:
            groups.setdefault((it["rarity"], (it.get("name") or "").lower()), []).append(it)
        for it in items:
            good = [s for s in it.get("substats", []) if any(w in s.lower() for w in wanted)]
            same = groups[(it["rarity"], (it.get("name") or "").lower())]
            n_before = [x for x in same if x["t"] <= it["t"]]
            if it["rarity"] in rules["keep_rarities"] or good:
                v = "keep"
                why = ("wanted substat: " + ", ".join(good)) if good else f"rarity {it['rarity']} is on your keep list"
            elif len(n_before) > int(rules["duplicate_limit"]) and it.get("name"):
                v, why = "possible duplicate", f"{len(n_before)} of the same crest (limit {rules['duplicate_limit']})"
            elif it["rarity"] in rules["discard_rarities"] and not it.get("substats"):
                v, why = "consider discarding", f"rarity {it['rarity']} is on your discard list and no substats are recorded"
            else:
                v, why = "review", "no rule decides this one" + ("" if it.get("substats") else " (substats not entered)")
            it["verdict"], it["why"] = v, why

    @staticmethod
    def search(items: list[dict], text: str = "", rarity: str = "", verdict: str = "", sort: str = "newest") -> list[dict]:
        t = text.lower().strip()
        out = [i for i in items
               if (not t or t in (i["name"] + " " + i["palace"] + " " + " ".join(i["substats"]) + " " + i["note"]).lower())
               and (not rarity or i["rarity"] == rarity) and (not verdict or i["verdict"] == verdict)]
        if sort == "rarity":
            out.sort(key=lambda i: -RARITY_ORDER.get(i["rarity"], -1))
        else:
            out.sort(key=lambda i: i["t"], reverse=(sort == "newest"))
        return out

    def duplicates(self, aid: str) -> list[list[dict]]:
        groups: dict[tuple, list[dict]] = {}
        for it in self.items(aid):
            if it.get("name"):
                groups.setdefault((it["rarity"], it["name"].lower()), []).append(it)
        return [g for g in groups.values() if len(g) > 1]
