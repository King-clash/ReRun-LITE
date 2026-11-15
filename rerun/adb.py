"""Talks to BlueStacks instances over ADB: screenshots, taps, swipes, app control.

Using ADB (instead of moving the real mouse) means every instance runs in the
background at the same time and you can keep using your PC.
"""
from __future__ import annotations

import queue
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

BLUESTACKS_ADB_CANDIDATES = [
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\HD-Adb.exe",
    r"C:\Program Files (x86)\BlueStacks\HD-Adb.exe",
]
BLUESTACKS_CONF = r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(RuntimeError):
    pass


def _running_adb_servers() -> list[str]:
    """Paths of adb.exe processes already running (an adb server)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='adb.exe' or Name='HD-Adb.exe'\" "
             "| ForEach-Object { $_.ExecutablePath }"],
            capture_output=True, timeout=15, creationflags=_NO_WINDOW,
        ).stdout.decode(errors="ignore")
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in out.splitlines() if line.strip() and Path(line.strip()).exists()]


def _adb_version(path: str) -> tuple[int, ...]:
    try:
        out = subprocess.run([path, "version"], capture_output=True, timeout=10,
                             creationflags=_NO_WINDOW).stdout.decode(errors="ignore")
    except (OSError, subprocess.TimeoutExpired):
        return ()
    # "Android Debug Bridge version 1.0.41"
    for token in out.split():
        if token.count(".") == 2 and token.replace(".", "").isdigit():
            return tuple(int(x) for x in token.split("."))
    return ()


_ADB_CACHE: dict[str, str] = {}


def find_adb(configured: str | None = None) -> str:
    """Pick the adb to use.

    Two adb versions on one PC kill each other's server on every call
    ("adb server version doesn't match this client"), which breaks any other
    tool using the emulator at the same time. So: use the adb whose server is
    already running if there is one, otherwise the newest adb available.
    """
    if configured and configured != "auto":
        if Path(configured).exists():
            return configured
        raise AdbError(f"adb not found at configured path: {configured}")
    if "auto" in _ADB_CACHE and Path(_ADB_CACHE["auto"]).exists():
        return _ADB_CACHE["auto"]
    running = _running_adb_servers()
    if running:
        _ADB_CACHE["auto"] = running[0]
        return running[0]
    candidates = [c for c in BLUESTACKS_ADB_CANDIDATES if Path(c).exists()]
    for extra in (shutil.which("adb"),
                  str(Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe")):
        if extra and Path(extra).exists():
            candidates.append(extra)
    if not candidates:
        raise AdbError("Could not find adb. Install BlueStacks 5 or set 'adb_path' in config.yaml.")
    best = max(candidates, key=_adb_version)
    _ADB_CACHE["auto"] = best
    return best


def discover_bluestacks_instances(conf_path: str = BLUESTACKS_CONF) -> list[dict]:
    """Read bluestacks.conf and list instances with their ADB ports.

    Returns e.g. [{"id": "Nougat32", "name": "BlueStacks App Player",
    "serial": "127.0.0.1:5555", "adb_enabled": False}]
    """
    path = Path(conf_path)
    if not path.exists():
        return []
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip().strip('"')
    adb_enabled = values.get("bst.enable_adb_access", "0") == "1"
    instances = []
    prefix = "bst.instance."
    ids = sorted({k[len(prefix):].split(".")[0] for k in values if k.startswith(prefix)})
    for inst_id in ids:
        port = values.get(f"{prefix}{inst_id}.status.adb_port")
        if not port:
            continue
        instances.append({
            "id": inst_id,
            "name": values.get(f"{prefix}{inst_id}.display_name", inst_id),
            "serial": f"127.0.0.1:{port}",
            "adb_enabled": adb_enabled,
        })
    return instances


class _Shell:
    """One long-lived `adb shell` for input commands: no new adb process per tap
    (measured 174 -> 138 ms per tap; Android's own `input` command is the rest).
    Each command ends with a marker so we know it finished."""

    def __init__(self, adb: str, serial: str):
        self.proc = subprocess.Popen([adb, "-s", serial, "shell"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=_NO_WINDOW)
        self.lines: queue.Queue = queue.Queue()
        self.n = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in iter(self.proc.stdout.readline, b""):
            self.lines.put(line)
        self.lines.put(None)  # shell ended

    def alive(self) -> bool:
        return self.proc.poll() is None

    def run(self, command: str, timeout: float = 15) -> None:
        self.n += 1
        marker = f"__rerun_done_{self.n}"
        self.proc.stdin.write(f"{command}; echo {marker}\n".encode())
        self.proc.stdin.flush()
        end = time.monotonic() + timeout
        while True:
            line = self.lines.get(timeout=max(0.1, end - time.monotonic()))
            if line is None:
                raise OSError("adb shell closed")
            if marker.encode() in line:
                return

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
        except OSError:
            pass


class Device:
    """One emulator instance reachable through ADB."""

    def __init__(self, adb_path: str, serial: str):
        self.adb = adb_path
        self.serial = serial
        self._lock = threading.Lock()
        self.package: str | None = None
        self._sh: _Shell | None = None

    def _input(self, command: str, timeout: float = 15) -> None:
        """Run an input command on the persistent shell; fall back to a one-off
        `adb shell` if it isn't available or breaks."""
        with self._lock:
            try:
                if self._sh is None or not self._sh.alive():
                    self._sh = _Shell(self.adb, self.serial)
                self._sh.run(command, timeout)
                return
            except queue.Empty:
                # Sent but never confirmed: don't resend (a second tap could
                # press something else). Start a fresh shell next time.
                self._sh.close()
                self._sh = None
                raise AdbError(f"adb input timed out: {command[:40]}")
            except (OSError, ValueError):
                if self._sh:
                    self._sh.close()
                self._sh = None
            self.shell(command, timeout=timeout)

    def close(self) -> None:
        with self._lock:
            if self._sh:
                self._sh.close()
                self._sh = None

    # -- low level -------------------------------------------------------
    def _run(self, *args: str, timeout: float = 20, binary: bool = False):
        cmd = [self.adb, "-s", self.serial, *args]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW
            )
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb timed out: {' '.join(args)}") from e
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="ignore").strip()
            raise AdbError(f"adb {' '.join(args)} failed: {err}")
        return proc.stdout if binary else proc.stdout.decode(errors="ignore")

    def shell(self, command: str, timeout: float = 20) -> str:
        return self._run("shell", command, timeout=timeout)

    # -- connection ------------------------------------------------------
    def connect(self) -> None:
        if ":" in self.serial:
            proc = subprocess.run(
                [self.adb, "connect", self.serial],
                capture_output=True, timeout=15, creationflags=_NO_WINDOW,
            )
            out = proc.stdout.decode(errors="ignore")
            if "connected" not in out:
                raise AdbError(
                    f"Could not connect to {self.serial}: {out.strip()}\n"
                    "In BlueStacks: Settings > Advanced > turn on 'Android Debug Bridge (ADB)'."
                )
        self.shell("echo ok", timeout=10)

    def is_connected(self) -> bool:
        try:
            return self.shell("echo ok", timeout=5).strip() == "ok"
        except AdbError:
            return False

    # -- screen ----------------------------------------------------------
    def screencap(self) -> np.ndarray:
        """Return the current screen as a BGR image.

        Raw frames skip the PNG compression the emulator would otherwise do on
        every capture (about 40% faster, pixel-identical); PNG is the fallback
        for a format this code doesn't know."""
        if self._raw_ok:
            with self._lock:
                data = self._run("exec-out", "screencap", binary=True, timeout=15)
            img = self._decode_raw(data)
            if img is not None:
                return img
            self._raw_ok = False  # unknown format on this device: use PNG from now on
        with self._lock:
            data = self._run("exec-out", "screencap", "-p", binary=True, timeout=15)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError("Screenshot could not be decoded (is the instance running?)")
        return img

    _raw_ok = True

    @staticmethod
    def _decode_raw(data: bytes) -> np.ndarray | None:
        """screencap's raw output: width, height, format (+ colour space on newer
        Android) as little-endian uint32s, then RGBA pixels."""
        if len(data) < 16:
            return None
        w, h, fmt = struct.unpack_from("<III", data)
        hdr = len(data) - w * h * 4
        if fmt != 1 or hdr not in (12, 16) or not (0 < w <= 8192 and 0 < h <= 8192):
            return None  # 1 = RGBA_8888
        rgba = np.frombuffer(data, np.uint8, count=w * h * 4, offset=hdr).reshape(h, w, 4)
        return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)

    def screen_size(self) -> tuple[int, int]:
        img = self.screencap()
        return img.shape[1], img.shape[0]

    # -- input -----------------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        self._input(f"input tap {int(x)} {int(y)}")

    def tap_many(self, x: int, y: int, n: int, chunk: int = 10) -> None:
        """Tap the same point n times, several taps per command (fast)."""
        while n > 0:
            k = min(chunk, n)
            self._input("; ".join([f"input tap {int(x)} {int(y)}"] * k), timeout=30)
            n -= k

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self._input(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}")

    def back(self) -> None:
        self._input("input keyevent 4")

    # -- app control -----------------------------------------------------
    def find_package(self, hint: str = "summoner") -> str | None:
        out = self.shell("pm list packages")
        for line in out.splitlines():
            pkg = line.replace("package:", "").strip()
            if hint.lower() in pkg.lower():
                return pkg
        return None

    def resolve_package(self, configured: str | None) -> str:
        if configured and configured != "auto":
            self.package = configured
        else:
            pkg = self.find_package()
            if not pkg:
                raise AdbError(
                    f"Grand Summoners is not installed on {self.serial} "
                    "(no package containing 'summoner'). Set 'game_package' in config.yaml."
                )
            self.package = pkg
        return self.package

    def foreground_package(self) -> str:
        out = self.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
        return out

    def is_game_foreground(self) -> bool:
        return bool(self.package) and self.package in self.foreground_package()

    def launch_game(self) -> None:
        if not self.package:
            raise AdbError("Game package unknown")
        self.shell(f"monkey -p {self.package} -c android.intent.category.LAUNCHER 1")

    def stop_game(self) -> None:
        if self.package:
            self.shell(f"am force-stop {self.package}")


class FakeDevice(Device):
    """Replays screenshots from a folder. Used for testing routines offline."""

    def __init__(self, frames: list[np.ndarray] | None = None, folder: str | None = None):
        super().__init__(adb_path="fake", serial="fake")
        if folder:
            frames = [cv2.imread(str(p)) for p in sorted(Path(folder).glob("*.png"))]
        self.frames = frames or []
        self.index = 0
        self.taps: list[tuple[int, int]] = []
        self.package = "fake.grandsummoners"
        self.on_tap = None  # optional callback(device, x, y) to advance frames

    def connect(self) -> None:
        return None

    def is_connected(self) -> bool:
        return True

    def screencap(self) -> np.ndarray:
        return self.frames[min(self.index, len(self.frames) - 1)].copy()

    def tap(self, x: int, y: int) -> None:
        self.taps.append((int(x), int(y)))
        if self.on_tap:
            self.on_tap(self, int(x), int(y))

    def tap_many(self, x: int, y: int, n: int, chunk: int = 10) -> None:
        for _ in range(n):
            self.tap(x, y)

    def swipe(self, *a, **k) -> None:
        return None

    def back(self) -> None:
        self.taps.append((-1, -1))

    def is_game_foreground(self) -> bool:
        return True

    def launch_game(self) -> None:
        return None

    def stop_game(self) -> None:
        return None

    def shell(self, command: str, timeout: float = 20) -> str:
        return ""
