"""Crest ledger and statistics (4+, Burst, Lv4 ... tracked separately).

History (history/history.jsonl) is capped and deletes its oldest entries, so
all-time crest numbers can't come from it. The ledger is a separate append-only
file, crest_log.jsonl, that is never compacted:

  {"type": "run",  "t", "instance", "session", "script"}               one completed run
  {"type": "drop", "t", "instance", "session", "script", "rarity",      one crest seen on the
   "action", "palace", "shot", "source", "confidence", "key"}           Equip Crest screen / burst
  {"type": "baseline", "t", "instance", "runs", "source", "key"}       runs counted before the
                                                                      ledger existed (no dates)

Rarity classes: lv3, lv3+, lv4, 4+, burst, ? (unidentified). "4+" never includes
Lv4. source: "live" (seen by a script) or "history" (rebuilt from History).
confidence: "verified" (icon + title agreed, or icon only), "assumed" (an
unidentified crest the user allowed to be scrapped as Lv3), "uncertain".

"Today" is the game day: it starts at the daily reset (06:00 UTC-6), the same
clock the Crest Palace rotation and 24/7 relogin use.
"""
from __future__ import annotations

import json
import shutil
from bisect import bisect_left
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

GAME_TZ = timezone(timedelta(hours=-6))
RESET_HOUR = 6
RARITIES = ["lv3", "lv3+", "lv4", "4+", "burst", "?"]
NOTABLE = ("4+", "burst")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# History's rarity names -> ledger classes
_HISTORY_RARITY = {"lv3": "lv3", "lv3+": "lv3+", "lv4": "lv4", "4+": "4+", "5+": "burst", "?": "?"}


SAME_EVENT_S = 3.0  # a script writes History and the ledger within milliseconds of each other


def _live_times(records: list[dict]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in records:
        if r.get("type") == "drop" and r.get("source", "live") == "live":
            out.setdefault(r.get("instance"), []).append(float(r["t"]))
    for v in out.values():
        v.sort()
    return out


def _seen_live(index: dict[str, list[float]], instance: str, t: float) -> bool:
    """True when a live drop was logged for this instance at (almost) the same moment."""
    times = index.get(instance) or []
    i = bisect_left(times, t - SAME_EVENT_S)
    return i < len(times) and times[i] <= t + SAME_EVENT_S


def game_day(t: float) -> datetime.date:
    """The game day a timestamp belongs to (days roll over at 06:00 UTC-6)."""
    return (datetime.fromtimestamp(t, GAME_TZ) - timedelta(hours=RESET_HOUR)).date()


def rate_text(drops: int, runs: int) -> str:
    """'1 drop per 140 runs' - plain wording for an observed rate."""
    if runs <= 0:
        return "no runs recorded"
    if drops <= 0:
        return f"none in {runs:,} run{'s' if runs != 1 else ''}"
    per = runs / drops
    return f"1 drop per {per:,.0f} runs" if per >= 10 else f"1 drop per {per:,.1f} runs"


class CrestLedger:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "crest_log.jsonl"
        self.shots = self.root / "crest_shots"
        self._lock = threading.Lock()
        self.records: list[dict] = []
        self._keys: set[str] = set()
        if self.path.exists():
            raw = self.path.read_text(encoding="utf-8")
            if raw and not raw.endswith("\n"):
                # A crash mid-write left a torn last line: end it so the next
                # record starts on a fresh line instead of being glued onto it.
                with self.path.open("a", encoding="utf-8") as f:
                    f.write("\n")
            for line in raw.splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn last line after a crash; keep everything else
                self.records.append(r)
                if r.get("key"):
                    self._keys.add(r["key"])

    # ------------------------------------------------------------ writing
    def _append(self, rec: dict) -> dict:
        with self._lock:
            if rec.get("key") and rec["key"] in self._keys:
                return rec  # already recorded (reconstruction is repeatable)
            self.records.append(rec)
            if rec.get("key"):
                self._keys.add(rec["key"])
            self.root.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        return rec

    def add_run(self, instance: str, session: str, script: str = "crest",
                t: float | None = None) -> dict:
        return self._append({"type": "run", "t": t or time.time(), "instance": instance,
                             "session": session, "script": script})

    def add_drop(self, instance: str, session: str, rarity: str, action: str,
                 script: str = "crest", image: np.ndarray | None = None,
                 palace: str | None = None, confidence: str = "verified",
                 title: str | None = None, t: float | None = None) -> dict:
        t = t or time.time()
        rec = {"type": "drop", "t": t, "instance": instance, "session": session,
               "script": script, "rarity": rarity if rarity in RARITIES else "?",
               "action": action, "source": "live", "confidence": confidence}
        if palace:
            rec["palace"] = palace
        if title:
            rec["title"] = title
        if image is not None and getattr(image, "size", 0):
            rec["shot"] = self._save_shot(image, t, rec["rarity"])
        return self._append(rec)

    def _save_shot(self, image: np.ndarray, t: float, rarity: str) -> str | None:
        """Notable drops keep a full screenshot; others none (History has a thumb)."""
        if rarity not in NOTABLE + ("lv4",):
            return None
        self.shots.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(t))}_{rarity.replace('+', 'plus')}.png"
        ok, buf = cv2.imencode(".png", image)
        if not ok:
            return None
        buf.tofile(str(self.shots / name))
        return name

    def shot_path(self, rec: dict | None) -> Path | None:
        if not rec or not rec.get("shot"):
            return None
        p = self.shots / rec["shot"]
        return p if p.exists() else None

    # ------------------------------------------------------------ reconstruction
    def reconstruct(self, history_entries: list[dict], stats_all: dict | None = None,
                    history_thumbs: Path | None = None) -> dict:
        """Rebuild drops from History crest entries and record pre-ledger run
        counts from stats.json. Repeatable: every record has a stable key, so a
        second call adds nothing. Returns {"drops": n, "baselines": n}."""
        added = {"drops": 0, "baselines": 0}
        live = _live_times(self.records)
        for e in history_entries:
            if e.get("kind") != "crest":
                continue
            key = f"h:{e.get('instance')}:{e.get('t')}"
            if key in self._keys:
                continue
            if _seen_live(live, e.get("instance"), float(e.get("t", 0))):
                continue  # the script already logged this crest live

            raw = e.get("rarity")
            rarity = _HISTORY_RARITY.get(raw or "", "?")
            rec = {"type": "drop", "t": float(e.get("t", 0)), "instance": e.get("instance", "?"),
                   "session": "history", "script": e.get("script", "crest"), "rarity": rarity,
                   "action": e.get("action") or "unknown", "source": "history",
                   "confidence": "verified" if raw in _HISTORY_RARITY and raw != "?" else "uncertain",
                   "key": key}
            # Notable drops: copy their History thumbnail, which History may delete later.
            if rarity in NOTABLE + ("lv4",) and history_thumbs and e.get("thumb"):
                src = history_thumbs / e["thumb"]
                if src.exists():
                    self.shots.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, self.shots / e["thumb"])
                    rec["shot"] = e["thumb"]
            self._append(rec)
            added["drops"] += 1
        for inst, counters in (stats_all or {}).items():
            key = f"baseline:{inst}"
            if key in self._keys:
                continue
            runs = int(counters.get("crest.runs", 0)) + int(counters.get("multi_farm.runs", 0))
            if not runs and not any(r.get("instance") == inst for r in self.records):
                continue
            self._append({"type": "baseline", "t": time.time(), "instance": inst, "runs": runs,
                          "source": "stats.json", "key": key,
                          "note": "crest runs counted before the ledger existed; dates unknown"})
            added["baselines"] += 1
        return added

    # ------------------------------------------------------------ reading
    def summary(self, instance: str | None = None, now: float | None = None,
                session: str | None = None) -> dict:
        return crest_summary(self.records, instance, now, session)


def crest_summary(records: list[dict], instance: str | None = None, now: float | None = None,
                  session: str | None = None) -> dict:
    """All crest numbers the dashboard, Discord and History need, from ledger records."""
    now = now or time.time()
    today = game_day(now)
    recs = [r for r in records if instance is None or r.get("instance") == instance]
    runs = [r for r in recs if r["type"] == "run"]
    live = _live_times(recs)
    # Rebuilt-from-History copies of crests that were also logged live (written by
    # an early Phase 1 build on restart) are ignored, not deleted: the file stays append-only.
    drops = sorted((r for r in recs if r["type"] == "drop" and not (
        r.get("source") == "history" and _seen_live(live, r.get("instance"), float(r["t"])))),
        key=lambda r: r["t"])
    baseline = sum(int(r.get("runs", 0)) for r in recs if r["type"] == "baseline")
    if session is None:  # latest live session
        live = [r for r in recs if r["type"] in ("run", "drop") and r.get("source", "live") == "live"]
        session = max(live, key=lambda r: r["t"])["session"] if live else None

    def counts(items):
        out = {k: 0 for k in RARITIES}
        for r in items:
            out[r["rarity"]] = out.get(r["rarity"], 0) + 1
        return out

    def window(pred):
        d = [r for r in drops if pred(r)]
        n = len([r for r in runs if pred(r)])
        return {"drops": counts(d), "runs": n}

    out = {
        "today": window(lambda r: game_day(r["t"]) == today),
        "session": window(lambda r: session is not None and r.get("session") == session),
        "all": {"drops": counts(drops), "runs": len(runs) + baseline},
        "session_id": session,
        "baseline_runs": baseline,
        "ledger_runs": len(runs),
    }
    total_runs = out["all"]["runs"]
    for cls in ("4+", "burst", "lv4"):
        n = out["all"]["drops"][cls]
        out[f"rate_{cls}"] = rate_text(n, total_runs)
        out[f"avg_runs_{cls}"] = round(total_runs / n, 1) if n else None
        last = next((r for r in reversed(drops) if r["rarity"] == cls), None)
        out[f"last_{cls}"] = last
        # Runs since: only dated runs can be compared with the drop's time.
        if last:
            out[f"since_{cls}"] = len([r for r in runs if r["t"] > last["t"]])
        else:
            out[f"since_{cls}"] = total_runs
    notable = [r for r in drops if r["rarity"] in NOTABLE]
    out["last_notable"] = notable[-1] if notable else None
    out["last_drop"] = drops[-1] if drops else None
    by_palace: dict[str, dict] = {}
    by_weekday = {d: {"drops": 0, "4+": 0, "burst": 0, "runs": 0} for d in WEEKDAYS}
    for r in drops:
        p = by_palace.setdefault(r.get("palace") or "Unknown palace", {"drops": 0, "4+": 0, "burst": 0})
        p["drops"] += 1
        wd = by_weekday[WEEKDAYS[game_day(r["t"]).weekday()]]
        wd["drops"] += 1
        if r["rarity"] in NOTABLE:
            p[r["rarity"]] += 1
            wd[r["rarity"]] += 1
    for r in runs:
        by_weekday[WEEKDAYS[game_day(r["t"]).weekday()]]["runs"] += 1
    out["by_palace"] = by_palace
    out["by_weekday"] = by_weekday
    out["uncertain"] = len([r for r in drops if r.get("confidence") != "verified"])
    out["reconstructed"] = len([r for r in drops if r.get("source") == "history"])
    return out


def format_summary(s: dict, title: str = "Crests") -> str:
    """Plain-text block for Discord /crests and the daily summary."""
    def line(label, w):
        d = w["drops"]
        return (f"{label}: 4+ **{d['4+']}** · Burst **{d['burst']}** · Lv4 {d['lv4']} · "
                f"runs {w['runs']:,}")

    def when(r):
        return time.strftime("%m-%d %H:%M", time.localtime(r["t"])) if r else "never"

    rows = [f"**{title}**",
            line("Today", s["today"]), line("Session", s["session"]), line("All-time", s["all"]),
            f"4+ observed rate: {s['rate_4+']} · runs since last 4+: {s['since_4+']:,}",
            f"Burst observed rate: {s['rate_burst']} · runs since last Burst: {s['since_burst']:,}",
            f"Last 4+/Burst: {when(s['last_notable'])}"
            + (f" ({s['last_notable']['rarity']})" if s["last_notable"] else "")]
    if s["baseline_runs"]:
        rows.append(f"_{s['baseline_runs']:,} runs from before tracking have no dates; "
                    "'runs since' only counts dated runs._")
    if s["uncertain"]:
        rows.append(f"_{s['uncertain']} crest(s) have an uncertain classification._")
    rows.append("_Observed history only - not a prediction of future drops._")
    return "\n".join(rows)
