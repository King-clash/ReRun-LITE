"""Health checks that need no emulator: quick, local, and honest about what they do not know.

Each check gives a HealthItem. Nothing here taps, starts or changes anything; a few items carry a `fix` name that the
Health page turns into a button which asks before it changes a setting."""
from __future__ import annotations

import shutil
from typing import NamedTuple

from . import MAIN_SCRIPT, readiness

CAP_SUGGESTION = 8        # game restarts per day offered as a safe cap


class HealthItem(NamedTuple):
    title: str
    state: str            # ok | warn | bad | info
    detail: str
    fix: str = ""         # "" | "set_cap:<instance>" | "setup_check" | "templates" | "settings" | "palaces" | "emulator"


def _problems(m) -> list[HealthItem]:
    out = []
    try:
        for p in readiness.crest_problems(m, next(iter(m.instances), None)):
            out.append(HealthItem("Crest is not ready", "warn", p.text, p.fix))
    except Exception as e:  # noqa: BLE001 - a health page must not break on one check
        out.append(HealthItem("Crest readiness", "info", f"Could not check: {e}"))
    return out


def _recovery_cap(m) -> list[HealthItem]:
    out = []
    for name in m.instances:
        cfg = m.script_settings(name, MAIN_SCRIPT)
        if cfg.get("mode_247") and int(cfg.get("max_restarts_per_day") or 0) <= 0:
            out.append(HealthItem(f"{name}: no limit on game restarts", "warn",
                                  "24/7 mode is on and 'Max game restarts per day' is 0 (no limit). A crash loop could "
                                  "restart the game all night. A limit makes it stop and tell you instead.",
                                  f"set_cap:{name}"))
    return out


def run_local(m, sampler=None, stuck=None, now=None) -> list[HealthItem]:
    items: list[HealthItem] = []
    items += _problems(m)
    items += _recovery_cap(m)

    # stuck watch
    if stuck is not None:
        if stuck.minutes:
            open_now = [n for n in m.instances if m.stuck_for(n)]
            items.append(HealthItem("Stuck watch", "warn" if open_now else "ok",
                                    (f"{', '.join(open_now)} has not advanced for a while." if open_now else
                                     f"Warns after {stuck.minutes} minutes without progress. It only warns; it changes nothing.")))
        else:
            items.append(HealthItem("Stuck watch", "info", "Off."))

    # this app and the PC
    if sampler is not None and sampler.latest:
        warns = sampler.warnings()
        items.append(HealthItem("Memory and CPU", "warn" if warns else "ok", " ".join(warns) if warns else sampler.text()))

    # disk space where the app keeps its data
    try:
        free_gb = shutil.disk_usage(m.root).free / 1073741824
        items.append(HealthItem("Disk space", "warn" if free_gb < 2 else "ok",
                                f"{free_gb:.1f} GB free where ReRun LITE keeps its data."
                                + (" Screenshots and logs need room." if free_gb < 2 else "")))
    except OSError:
        pass

    # what the log says
    entries = list(m.log_entries[-500:])
    errors = [e for e in entries if e.get("level") == "error"]
    cfg_warn = [e for e in entries if str(e.get("message", "")).startswith("config.yaml:")]
    if cfg_warn:
        items.append(HealthItem("config.yaml", "warn", f"{len(cfg_warn)} problem(s) found when it was read. "
                                                       f"First: {cfg_warn[0]['message'][:160]}"))
    items.append(HealthItem("Recent errors", "warn" if errors else "ok",
                            f"{len(errors)} error line(s) in the last {len(entries)} log lines." if errors
                            else "No error lines in the recent log."))

    # last sessions
    try:
        last = m.runs.sessions(limit=5)
    except Exception:  # noqa: BLE001
        last = []
    if last:
        fails = 0
        for s in last:
            if s.get("ended") == "failed":
                fails += 1
            else:
                break
        items.append(HealthItem("Recent sessions", "warn" if fails >= 3 else ("info" if fails else "ok"),
                                f"The last {fails} session(s) ended in a failure." if fails
                                else f"Latest: {last[0].get('runs', 0)} runs, ended {last[0].get('ended', 'stopped')}."))
    else:
        items.append(HealthItem("Recent sessions", "info", "No finished sessions saved yet."))
    return items


def worst(items: list[HealthItem]) -> str:
    states = {i.state for i in items}
    return "bad" if "bad" in states else ("warn" if "warn" in states else "ok")


def as_text(items: list[HealthItem]) -> str:
    tag = {"ok": "OK  ", "warn": "WARN", "bad": "FAIL", "info": "INFO"}
    return "\n".join(f"[{tag.get(i.state, i.state)}] {i.title}: {i.detail}" for i in items)
