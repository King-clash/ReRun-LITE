"""Smooth Live View: the emulator's own screen recorder streamed as H.264 video.

A screenshot over ADB (`screencap`) takes ~180 ms on BlueStacks (measured 2026-11-14:
5.6 fps at most, and every one competes with the running script for ADB). Android's
`screenrecord --output-format=h264 -` instead streams the screen as video: Rerun relays it
through a local socket to OpenCV's bundled FFmpeg decoder (no extra install) and keeps only
the newest frame. Measured on the same emulator: first frame after 0.5 s, 60-120 frames/s
decoded (the Live View draws 30 of them per second).

Read-only: it records the screen and never taps. screenrecord stops by itself after its
time limit (3 minutes on older Android), so the stream restarts with a short gap. After
repeated failures it gives up (`failed`) and the Live View falls back to screenshots.
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time

import cv2
import numpy as np

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
# Low-latency decoding: tiny probe, no buffering (OpenCV passes these to FFmpeg).
_FFMPEG_OPTS = "probesize;2048|analyzeduration;0|fflags;nobuffer|flags;low_delay"
TIME_LIMIT_S = 180      # screenrecord's maximum on older Android; restart after it
MAX_FAILS = 3           # sessions in a row that produced no frame -> give up


class LiveStream:
    # 800 px tall (sharper than the Live View panel) at 4 Mbit/s: the lightest setting
    # measured; while it runs a script's screenshot takes ~10-20% longer (encoder load).
    def __init__(self, adb_path: str, serial: str, portrait: bool = True,
                 long_side: int = 800, bitrate: int = 4_000_000):
        self.adb, self.serial = adb_path, serial
        w, h = (long_side * 9 // 16, long_side)
        self.size = (w, h) if portrait else (h, w)
        self.bitrate = bitrate
        self.frame: np.ndarray | None = None
        self.seq = 0                 # increases with every decoded frame
        self.failed = False          # gave up: use screenshots instead
        self.error = ""
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._times: list[float] = []  # recent frame times, for fps()

    # ---------------------------------------------------------------- control
    def start(self) -> "LiveStream":
        self._thread = threading.Thread(target=self._run, name=f"live-{self.serial}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._kill()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive()) and not self._stop.is_set()

    def fps(self) -> float:
        """Frames decoded per second over the last two seconds."""
        now = time.monotonic()
        recent = [t for t in self._times if now - t <= 2.0]
        return len(recent) / 2.0

    # ---------------------------------------------------------------- worker
    def _kill(self) -> None:
        p = self._proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def _run(self) -> None:
        fails = 0
        while not self._stop.is_set():
            got = self._session()
            if self._stop.is_set():
                break
            fails = 0 if got else fails + 1
            if fails >= MAX_FAILS:
                self.failed = True
                break
            time.sleep(0.3 if got else 1.0)

    def _cmd(self) -> list[str]:
        w, h = self.size
        return [self.adb, "-s", self.serial, "exec-out", "screenrecord", "--output-format=h264",
                "--size", f"{w}x{h}", "--bit-rate", str(self.bitrate),
                "--time-limit", str(TIME_LIMIT_S), "-"]

    def _session(self) -> bool:
        """One screenrecord run. True if it produced at least one frame."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        srv.settimeout(10)
        port = srv.getsockname()[1]
        try:
            self._proc = subprocess.Popen(self._cmd(), stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        except OSError as e:
            self.error = f"screenrecord could not start: {e}"
            srv.close()
            return False
        proc = self._proc

        def pump():
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                while not self._stop.is_set():
                    b = proc.stdout.read1(65536)
                    if not b:
                        break
                    conn.sendall(b)
            except OSError:
                pass
            finally:
                conn.close()

        threading.Thread(target=pump, daemon=True).start()
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _FFMPEG_OPTS
        cap = cv2.VideoCapture(f"tcp://127.0.0.1:{port}", cv2.CAP_FFMPEG)
        got = False
        try:
            while not self._stop.is_set() and cap.isOpened():
                ok, f = cap.read()
                if not ok:
                    break
                got = True
                self.frame = f
                self.seq += 1
                now = time.monotonic()
                self._times.append(now)
                if len(self._times) > 400:
                    self._times = [t for t in self._times if now - t <= 2.0]
        except cv2.error as e:
            self.error = str(e)
        finally:
            cap.release()
            self._kill()
            srv.close()
        if not got and not self.error:
            self.error = "no video from screenrecord"
        return got


__all__ = ["LiveStream"]
