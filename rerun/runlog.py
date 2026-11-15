"""Persistent run log: every Log-tab line is also appended to rerun.log next to the app, so what
happened is still known after a crash or restart (the Log tab itself lives in memory).

The file is opened per line and closed again (no handle is held, so temp folders can be deleted
on Windows) and is rotated by size: rerun.log -> rerun.log.1 -> .2 -> .3. Never raises."""
from __future__ import annotations

import threading
import time
from pathlib import Path

MAX_BYTES = 1_000_000
KEEP = 3

LEVELS = {"info": 0, "warn": 1, "error": 2}
FILE_LEVELS = {"all": 0, "warnings": 1, "errors": 2}      # config logging.file_level -> minimum level

_path: Path | None = None
_lock = threading.Lock()
_min_level = 0


def configure(file_mb: float = 1.0, file_count: int = 3, file_level: str = "all") -> None:
    """Apply the Logging settings: size of each file, how many old files to keep, and the lowest
    level written ('all' | 'warnings' | 'errors'). Out-of-range values are clamped, never rejected."""
    global MAX_BYTES, KEEP, _min_level
    MAX_BYTES = int(max(0.1, min(float(file_mb), 100.0)) * 1_000_000)
    KEEP = int(max(1, min(int(file_count), 20)))
    _min_level = FILE_LEVELS.get(str(file_level).lower(), 0)


def init(root: str | Path) -> None:
    global _path
    _path = Path(root) / "rerun.log"


def _rotate(path: Path) -> None:
    for i in range(KEEP, 0, -1):
        src = path if i == 1 else path.with_name(f"{path.name}.{i - 1}")
        dst = path.with_name(f"{path.name}.{i}")
        if src.exists():
            dst.unlink(missing_ok=True)
            src.replace(dst)


def write(instance: str, msg: str, level: str = "info") -> None:
    try:
        if _path is None or LEVELS.get(level, 0) < _min_level:
            return
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {level.upper():5s} [{instance}] " \
               + msg.replace("\r", "").replace("\n", "\n    ")
        with _lock:
            if _path.exists() and _path.stat().st_size > MAX_BYTES:
                _rotate(_path)
            with _path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001 - logging must never break a script
        pass
