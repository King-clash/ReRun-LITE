"""A small resource monitor: how much memory and processor this app uses, and how full the PC's memory is.

Standard library only (ctypes on Windows; /proc elsewhere, which is only used when the app is tried on another system).
Every reader is wrapped so a failure gives None - a monitor must never be the thing that breaks the app - and the
numbers are only ever measured, never estimated."""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from typing import Callable

from rerun import errlog

APP_MEM_WARN_MB = 1500        # this app using more than this is worth a look (a leak, or a huge log)
PC_MEM_WARN_PCT = 92          # the PC itself is nearly out of memory


# ---------------------------------------------------------------- readers
def _win_process_mb() -> float | None:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    c = COUNTERS()
    c.cb = ctypes.sizeof(c)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return round(c.WorkingSetSize / 1048576, 1) if ok else None


def _win_cpu_seconds() -> float | None:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    t = [wintypes.FILETIME() for _ in range(4)]
    if not k32.GetProcessTimes(k32.GetCurrentProcess(), *[ctypes.byref(x) for x in t]):
        return None
    ticks = lambda f: (f.dwHighDateTime << 32 | f.dwLowDateTime)  # noqa: E731 - 100 ns units
    return (ticks(t[2]) + ticks(t[3])) / 1e7


def _win_pc_memory() -> tuple[float, float] | None:
    """(used percent, total GB)."""
    import ctypes  # noqa: PLC0415

    class MEM(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

    m = MEM()
    m.dwLength = ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return float(m.dwMemoryLoad), round(m.ullTotalPhys / 1073741824, 1)


def _posix_process_mb() -> float | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            return round(int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)
    except (OSError, ValueError, IndexError):
        return None


def _posix_cpu_seconds() -> float | None:
    t = os.times()
    return t.user + t.system


def _posix_pc_memory() -> tuple[float, float] | None:
    try:
        info = {}
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k] = int(v.split()[0])
        total, avail = info["MemTotal"], info["MemAvailable"]
        return round(100 * (1 - avail / total), 1), round(total / 1048576, 1)
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def default_readers() -> tuple[Callable, Callable, Callable]:
    if sys.platform == "win32":
        return _win_process_mb, _win_cpu_seconds, _win_pc_memory
    return _posix_process_mb, _posix_cpu_seconds, _posix_pc_memory


# ---------------------------------------------------------------- sampler
class Sampler:
    """Take a reading with sample(); history keeps the newest `keep` readings (for a small graph)."""

    def __init__(self, readers=None, clock: Callable[[], float] = time.monotonic, keep: int = 120):
        self._mem, self._cpu, self._pc = readers or default_readers()
        self.clock = clock
        self.cores = os.cpu_count() or 1
        self.history: deque[dict] = deque(maxlen=keep)
        self._last: tuple[float, float] | None = None
        self.latest: dict = {}

    def _safe(self, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - see the module docstring
            errlog.note("lite.resources", e)
            return None

    def sample(self) -> dict:
        now = self.clock()
        mem = self._safe(self._mem)
        cpu_s = self._safe(self._cpu)
        pc = self._safe(self._pc)
        cpu_pct = None
        if cpu_s is not None:
            if self._last is not None and now > self._last[0]:
                cpu_pct = round(max(0.0, (cpu_s - self._last[1]) / (now - self._last[0]) / self.cores * 100), 1)
            self._last = (now, cpu_s)
        out = {"t": now, "app_mb": mem, "app_cpu_pct": cpu_pct,
               "pc_mem_pct": pc[0] if pc else None, "pc_total_gb": pc[1] if pc else None}
        self.latest = out
        self.history.append(out)
        return out

    def warnings(self) -> list[str]:
        s = self.latest
        out = []
        if s.get("app_mb") is not None and s["app_mb"] > APP_MEM_WARN_MB:
            out.append(f"This app is using {s['app_mb']:.0f} MB of memory (more than {APP_MEM_WARN_MB} MB). "
                       "Restarting it clears that.")
        if s.get("pc_mem_pct") is not None and s["pc_mem_pct"] >= PC_MEM_WARN_PCT:
            out.append(f"The PC's memory is {s['pc_mem_pct']:.0f}% full, which can slow the emulator and the bot.")
        return out

    def text(self) -> str:
        s = self.latest
        if not s:
            return "No reading yet"
        f = lambda v, u: "n/a" if v is None else f"{v:g}{u}"  # noqa: E731
        return (f"App memory {f(s['app_mb'], ' MB')}  ·  App CPU {f(s['app_cpu_pct'], '%')}  ·  "
                f"PC memory {f(s['pc_mem_pct'], '%')} of {f(s['pc_total_gb'], ' GB')}")
