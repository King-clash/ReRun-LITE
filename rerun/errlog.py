"""Quiet-failure log: errors that must not stop a script (a broken listener, OCR hiccup)
are written to error.log next to the app instead of vanishing. The same error from the
same place is written at most once per RATE_S seconds so a per-tick failure cannot flood it."""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

RATE_S = 600
MAX_BYTES = 512 * 1024

_path: Path | None = None
_last: dict[tuple[str, str], float] = {}
_lock = threading.Lock()


def init(root: str | Path) -> None:
    global _path
    _path = Path(root) / "error.log"


def note(where: str, exc: BaseException) -> None:
    """Record exc (called from inside an except block). Never raises."""
    try:
        if _path is None:
            return
        key = (where, repr(exc))
        now = time.time()
        with _lock:
            if now - _last.get(key, 0.0) < RATE_S:
                return
            _last[key] = now
            if _path.exists() and _path.stat().st_size > MAX_BYTES:
                _path.replace(_path.with_suffix(".log.old"))
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            with _path.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{where}]\n{tb}\n")
    except Exception:  # noqa: BLE001 - the error log itself must never cause an error
        pass
