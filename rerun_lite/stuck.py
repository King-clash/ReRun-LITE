"""Stuck detection: notice - and say so - when Crest has not advanced for a while.

This only WATCHES. The engine already restarts or stops by its own rules (24/7 mode restarts the game after 20 minutes
without progress, 'Max game restarts per day' caps that, and 25 identical screens in a row stops the script). This
adds an earlier, softer signal: after `warn_s` seconds without progress it writes one Warning to the Log, raises a
"stuck" alert (desktop notification if you enabled it) and shows a note in the compact window and on the Health page.
It never taps, presses keys or restarts anything.

An episode ends when progress resumes; each episode is reported once. Paused time and recoveries never count."""
from __future__ import annotations

from typing import Callable

DEFAULT_MINUTES = 8
CHOICES = (0, 5, 8, 12, 15)          # 0 = off


class StuckWatch:
    def __init__(self, minutes: int = DEFAULT_MINUTES, clock: Callable[[], float] | None = None):
        self.minutes = minutes
        self._open: dict[str, float] = {}        # emulator -> when the open episode was reported
        self.episodes: dict[str, int] = {}

    @property
    def warn_s(self) -> float:
        return self.minutes * 60.0

    def set_minutes(self, minutes) -> None:
        try:
            m = int(minutes)
        except (TypeError, ValueError):
            m = DEFAULT_MINUTES
        self.minutes = m if m in CHOICES else DEFAULT_MINUTES

    def check(self, name: str, idle_s: float | None, active: bool, now: float) -> str | None:
        """Call about once a second per emulator. `idle_s` = seconds since the script last advanced (None = unknown),
        `active` = running and not paused and not recovering. Returns 'start' the moment an episode begins, 'end' when
        it ends, else None."""
        if not self.minutes or idle_s is None or not active:
            if name in self._open and (not active or not self.minutes):
                self._open.pop(name, None)       # paused/stopped/recovering or switched off: close quietly
            return None
        if idle_s >= self.warn_s:
            if name not in self._open:
                self._open[name] = now
                self.episodes[name] = self.episodes.get(name, 0) + 1
                return "start"
            return None
        if name in self._open:
            del self._open[name]
            return "end"
        return None

    def stuck_for(self, name: str, idle_s: float | None) -> float | None:
        """Seconds without progress while an episode is open, else None."""
        return idle_s if name in self._open and idle_s is not None else None

    def forget(self, name: str) -> None:
        self._open.pop(name, None)
        self.episodes.pop(name, None)
