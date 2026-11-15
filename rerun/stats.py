"""Per-instance counters (runs, crests, errors...), saved to stats.json."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class Stats:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.data: dict[str, dict[str, int]] = {}
        self.started: dict[str, float] = {}
        if self.path and self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.data = {}

    SAVE_EVERY_S = 2.0  # counters change many times a minute; write at most this often

    _last_save = 0.0
    _dirty = False

    def incr(self, instance: str, key: str, n: int = 1) -> None:
        with self._lock:
            d = self.data.setdefault(instance, {})
            d[key] = d.get(key, 0) + n
            self._dirty = True
            if time.monotonic() - self._last_save >= self.SAVE_EVERY_S:
                self._save()

    def flush(self) -> None:
        """Write any unsaved counts (called when a script stops and on exit)."""
        with self._lock:
            if self._dirty:
                self._save()

    def get(self, instance: str) -> dict[str, int]:
        with self._lock:
            return dict(self.data.get(instance, {}))

    def all(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {k: dict(v) for k, v in self.data.items()}

    def reset(self, instance: str | None = None) -> None:
        with self._lock:
            if instance:
                self.data.pop(instance, None)
            else:
                self.data.clear()
            self._save()

    def mark_started(self, instance: str) -> None:
        self.started[instance] = time.time()

    def mark_stopped(self, instance: str) -> None:
        t = self.started.pop(instance, None)
        if t:
            self.incr(instance, "seconds_run", int(time.time() - t))
        self.flush()

    def uptime(self, instance: str) -> int:
        t = self.started.get(instance)
        return int(time.time() - t) if t else 0

    def _save(self) -> None:
        self._dirty = False
        self._last_save = time.monotonic()
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            tmp.replace(self.path)


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"
