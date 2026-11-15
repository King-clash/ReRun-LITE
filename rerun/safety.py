"""Account safety: limits, dry run, and the Terms-of-Service warning.

Nothing here hides automation from the game or varies timing to avoid detection. The limits only cap how
much Rerun runs, and dry run shows what it WOULD tap while tapping nothing.
"""
from __future__ import annotations

import time

from .accounts import AccountStore
from .checklist import period_start
from .engine import StopRoutine

TOS_WARNING = ("IMPORTANT: Grand Summoners may prohibit third-party automation, macros, bots, or unattended "
               "gameplay under its Terms of Service. Using these features may result in account restrictions, "
               "suspension, or permanent bans. Use at your own discretion. You are responsible for understanding "
               "and complying with the game's current rules.")
SAFETY_NOTE = ("The limits below only cap how much Rerun runs. They do not make automation safe or undetectable, "
               "and they do not remove the risk described above.")

DRY_MAX_ACTIONS = 40      # a dry run ends after this many planned actions...
DRY_MAX_DISTINCT = 12     # ...or this many different ones...
DRY_MAX_SECONDS = 90      # ...or this long
_READ_ONLY_SHELL = ("pm list", "dumpsys", "getprop", "wm size", "wm density", "echo", "pidof", "cat ")


class DryRunDevice:
    """Wraps a real Device: screenshots and read-only queries pass through; every tap, swipe, key press and
    app start/stop is recorded in `plan` instead of being sent. Ends the run when the plan is long enough."""

    def __init__(self, real, log=None):
        self._real = real
        self.plan: list[dict] = []
        self._log = log or (lambda m: None)
        self._t0 = time.time()
        self._seen: set[tuple] = set()

    def __getattr__(self, name):           # screencap, connect, serial, package, is_game_foreground ...
        return getattr(self._real, name)

    def _plan(self, kind: str, **args) -> None:
        key = (kind, tuple(sorted(args.items())))
        self.plan.append({"t": round(time.time() - self._t0, 1), "action": kind, **args})
        if key not in self._seen:
            self._seen.add(key)
            self._log("DRY RUN: would " + describe(kind, args))
        if len(self.plan) >= DRY_MAX_ACTIONS or len(self._seen) >= DRY_MAX_DISTINCT \
                or time.time() - self._t0 > DRY_MAX_SECONDS:
            raise StopRoutine(f"dry run complete - {len(self.plan)} actions planned, none sent")

    def tap(self, x, y):
        self._plan("tap", x=int(x), y=int(y))

    def tap_many(self, x, y, n, chunk=10):
        self._plan("tap", x=int(x), y=int(y), times=int(n))

    def swipe(self, x1, y1, x2, y2, ms=300):
        self._plan("swipe", x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2))

    def back(self):
        self._plan("press Back")

    def launch_game(self):
        self._plan("start the game")

    def stop_game(self):
        self._plan("close the game")

    def shell(self, command: str, timeout: float = 20) -> str:
        if command.strip().startswith(_READ_ONLY_SHELL):
            return self._real.shell(command, timeout=timeout)
        self._plan("run shell command", command=command[:60])
        return ""


def describe(kind: str, a: dict) -> str:
    if kind == "tap":
        return f"tap ({a['x']}, {a['y']})" + (f" x{a['times']}" if a.get("times") else "")
    if kind == "swipe":
        return f"swipe ({a['x1']}, {a['y1']}) -> ({a['x2']}, {a['y2']})"
    if kind == "run shell command":
        return f"run '{a.get('command', '')}'"
    return kind


def plan_summary(plan: list[dict]) -> str:
    """Distinct planned actions with counts - what a dry run shows the user."""
    if not plan:
        return "Nothing was planned: the script did not try to touch the game."
    counts: dict[str, int] = {}
    for p in plan:
        label = describe(p["action"], p)
        counts[label] = counts.get(label, 0) + 1
    lines = [f"{n}x {label}" for label, n in counts.items()]
    return f"{len(plan)} planned action(s), none sent:\n" + "\n".join(lines)


def minutes_today(store: AccountStore, aid: str, now: float | None = None) -> float:
    """Real (non dry-run) farming minutes in the current game day, including a session still running."""
    now = now or time.time()
    start = period_start(now, "daily")
    total = 0.0
    for s in store.sessions(aid):
        if s.get("dry_run"):
            continue
        a, b = max(s["start"], start), min(s["end"] or now, now)
        if b > a:
            total += (b - a) / 60
    return total


def check_start(store: AccountStore, aid: str, script: str, now: float | None = None) -> str | None:
    """None when this account may start `script`, else the reason it may not (shown to the user)."""
    a = store.get(aid)
    s = a["safety"]
    if not s["automation_allowed"]:
        return f"Automation is switched off for '{a['name']}' (Account Manager > Safety)."
    if s["allowed_scripts"] and script not in s["allowed_scripts"]:
        return f"'{a['name']}' is only allowed to run: {', '.join(s['allowed_scripts'])}."
    lim = int(s["daily_minutes_limit"])
    if lim and minutes_today(store, aid, now) >= lim:
        return f"'{a['name']}' has used its {lim} minute limit for today (the game day resets at 6 AM UTC-6)."
    return None
