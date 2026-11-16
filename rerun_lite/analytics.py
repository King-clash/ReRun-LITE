"""Numbers and CSV for the Sessions page, from the saved session summaries (no window, no tkinter).

Everything here only adds up what the sessions recorded; nothing is estimated. A day is the local calendar day of the
session's start, so the graphs line up with the clock you see."""
from __future__ import annotations

import csv
import io
import statistics
import time
from datetime import datetime, timedelta

from .runs import fmt_secs

RANGES = (("Last 7 days", 7), ("Last 30 days", 30), ("All saved", 0))


def in_range(sessions: list[dict], days: int, now: float | None = None, instance: str | None = None) -> list[dict]:
    """Sessions that started in the last `days` days (0 = all), optionally only one emulator. Oldest first."""
    now = time.time() if now is None else now
    cutoff = now - days * 86400 if days else 0
    rows = [s for s in sessions if float(s.get("start") or 0) >= cutoff and instance in (None, "", s.get("instance"))]
    return sorted(rows, key=lambda s: float(s.get("start") or 0))


def totals(rows: list[dict]) -> dict:
    """Sums and averages over the sessions given."""
    runs = sum(int(s.get("runs") or 0) for s in rows)
    fails = sum(int(s.get("failures") or 0) for s in rows)
    active = sum(int(s.get("active_s") or 0) for s in rows)
    cycles = [c for s in rows for c in (s.get("cycles") or []) if isinstance(c, (int, float)) and c > 0]
    ended: dict[str, int] = {}
    for s in rows:
        ended[s.get("ended", "stopped")] = ended.get(s.get("ended", "stopped"), 0) + 1
    return {
        "sessions": len(rows), "runs": runs, "failures": fails, "active_s": active,
        "restarts": sum(int(s.get("recoveries") or 0) for s in rows),
        "recovered": sum(int(s.get("recovered") or 0) for s in rows),
        "avg_cycle_s": round(statistics.fmean(cycles), 1) if cycles else None,
        "median_cycle_s": round(statistics.median(cycles), 1) if cycles else None,
        "fastest_s": round(min(cycles), 1) if cycles else None,
        "slowest_s": round(max(cycles), 1) if cycles else None,
        "runs_per_hour": round(runs / (active / 3600), 1) if active >= 60 and runs else None,
        "ended": ended,
    }


def per_day(rows: list[dict], days: int, now: float | None = None) -> list[tuple[str, int]]:
    """[(YYYY-MM-DD, runs)] for each of the last `days` local days, zero where nothing ran (so the bars are even)."""
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).date()
    if days <= 0:
        days = max(1, (today - datetime.fromtimestamp(float(rows[0].get("start") or now)).date()).days + 1) if rows else 7
        days = min(days, 90)
    keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    acc = dict.fromkeys(keys, 0)
    for s in rows:
        k = datetime.fromtimestamp(float(s.get("start") or 0)).date().isoformat()
        if k in acc:
            acc[k] += int(s.get("runs") or 0)
    return list(acc.items())


def cycle_series(rows: list[dict], limit: int = 120) -> list[float]:
    """Cycle times of the newest sessions in order (oldest first), for the line graph; capped at `limit` points."""
    out: list[float] = []
    for s in rows:
        out.extend(float(c) for c in (s.get("cycles") or []) if isinstance(c, (int, float)))
    return out[-limit:]


def session_line(s: dict) -> tuple[str, str, str]:
    """(title, detail, state) for one row of the list."""
    when = datetime.fromtimestamp(float(s.get("start") or 0)).strftime("%a %d %b  %H:%M")
    title = f"{when}  ·  {s.get('instance', '?')}"
    bits = [f"{s.get('runs', 0)} runs", fmt_secs(s.get("active_s"))]
    if s.get("avg_s"):
        bits.append(f"avg {fmt_secs(s['avg_s'])}")
    if s.get("failures"):
        bits.append(f"{s['failures']} failed")
    if s.get("recoveries"):
        bits.append(f"{s['recoveries']} game restart(s)")
    detail = "  ·  ".join(bits) + f"  ·  {s.get('reason', '')}"
    return title, detail, s.get("ended", "stopped")


CSV_COLUMNS = ("start", "instance", "account", "runs", "failures", "duration_s", "active_s", "avg_s", "runs_per_hour",
               "recoveries", "recovered", "interruptions", "ended", "reason")


def to_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for s in rows:
        row = []
        for c in CSV_COLUMNS:
            v = s.get(c, "")
            if c == "start" and v != "":
                v = datetime.fromtimestamp(float(v)).strftime("%Y-%m-%d %H:%M:%S")
            row.append(v)
        w.writerow(row)
    return out.getvalue()
