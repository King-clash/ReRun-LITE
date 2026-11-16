"""The start-up window with a progress bar and "about N s left".

ReRun LITE takes a few seconds to open (the one-file exe unpacks itself, then the image tools and the window have to
load). Without anything on screen that looks like nothing is happening. This window shows how far along it is.

  * Real progress, not a timer: the bar moves when a step really finishes (8% starting, 40% image tools, ...).
  * "About N s left" comes from how long the same step took the last time (kept in data/lite/startup.json); the very
    first start shows the percentage only.
  * Two phases use it: "load" (before the first window: loading the program) and "open" (after sign-in: building
    the window). The one-file exe also shows a static picture while it unpacks (build_lite.py --splash); this window
    closes that picture when it appears.

Nothing here imports cv2, numpy or the rest of ReRun, so it can appear first.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

from . import palettes

W, H = 460, 214


def _dpi_aware() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001 - already set, or not available: harmless
            pass


def close_exe_picture() -> None:
    """The one-file exe's own picture (shown while it unpacks) goes away once this window is up."""
    try:
        import pyi_splash  # type: ignore[import-not-found]
        pyi_splash.close()
    except Exception:  # noqa: BLE001 - not a built exe
        pass


class Marks:
    """How long each step took last time, per phase: {"load": {"total": 4.2, "marks": {"40": 1.9}}}."""

    def __init__(self, root: str | Path | None):
        self.path = Path(root) / "data" / "lite" / "startup.json" if root else None
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
            if not isinstance(self.data, dict):
                self.data = {}
        except (OSError, ValueError):
            self.data = {}

    def last(self, phase: str) -> dict:
        d = self.data.get(phase)
        return d if isinstance(d, dict) else {}

    def save(self, phase: str, total: float, marks: dict) -> None:
        if self.path is None:
            return
        self.data[phase] = {"total": round(total, 2), "marks": {str(k): round(v, 2) for k, v in marks.items()}}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except OSError:
            pass


def remaining(last: dict, pct: float) -> float | None:
    """Seconds left, from the previous run: its total minus when it passed the same step. None when unknown."""
    marks = last.get("marks") or {}
    total = last.get("total")
    if not marks or not isinstance(total, (int, float)):
        return None
    key = str(int(pct))
    if key not in marks:
        earlier = [int(k) for k in marks if int(k) <= pct]
        if not earlier:
            return float(total)
        key = str(max(earlier))
    return max(0.0, float(total) - float(marks[key]))


def left_text(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 1.5:
        return "Almost ready"
    return f"About {int(round(seconds))} s left"


class Splash:
    """A small borderless window with a smooth progress bar. `master=None` makes its own Tk root; a Tk root or
    Toplevel `master` makes it a Toplevel of that."""

    def __init__(self, master: tk.Misc | None, root: str | Path | None, phase: str, title: str = "ReRun LITE",
                 first: str = "Starting…", theme_key: str = palettes.DEFAULT):
        _dpi_aware()
        self.c = palettes.splash_colors(theme_key)            # the colours of the chosen theme
        self.own = master is None
        self.win = tk.Tk() if self.own else tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.configure(bg=self.c["edge"])
        self.k = max(1.0, self.win.winfo_fpixels("1i") / 96.0)
        self.w, self.h = int(W * self.k), int(H * self.k)
        self.cv = tk.Canvas(self.win, width=self.w - 2, height=self.h - 2, bg=self.c["bg"], highlightthickness=0, bd=0)
        self.cv.pack(padx=1, pady=1)
        self.phase, self.marks, self.last = phase, Marks(root), {}
        self.last = self.marks.last(phase)
        self.target = 0.0
        self.shown = 0.0
        self.text = first
        self.t0 = time.monotonic()
        self.done_marks: dict[int, float] = {}
        self.title = title
        self._lock = threading.Lock()
        self._closed = False
        x, y = (self.win.winfo_screenwidth() - self.w) // 2, (self.win.winfo_screenheight() - self.h) // 3
        self.win.geometry(f"{self.w}x{self.h}+{x}+{y}")
        self._draw_static()
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.update()
        close_exe_picture()
        self._draw()
        self.win.update()

    # ------------------------------------------------------------ progress (safe to call from a worker thread)
    def set(self, pct: float, text: str | None = None) -> None:
        with self._lock:
            self.target = max(self.target, min(100.0, float(pct)))
            if text:
                self.text = text
            self.done_marks[int(pct)] = time.monotonic() - self.t0

    # ------------------------------------------------------------ drawing
    def _f(self, size: int, bold: bool = False):
        return ("Segoe UI Semibold" if bold else "Segoe UI", -int(size * self.k))

    def _draw_static(self) -> None:
        k, c = self.k, self.cv
        c.delete("all")
        c.create_rectangle(int(30 * k), int(30 * k), int(84 * k), int(56 * k), fill=self.c["tag"], width=0, tags="s")
        c.create_text(int(57 * k), int(43 * k), text="LITE", fill=self.c["tag_text"], font=self._f(13, True), tags="s")
        c.create_text(int(98 * k), int(43 * k), text="ReRun", fill=self.c["text"], font=self._f(22, True), anchor="w", tags="s")
        c.create_text(int(30 * k), int(82 * k), text=self.title, fill=self.c["muted"], font=self._f(13), anchor="w", tags="s")
        x0, x1, y0, y1 = int(30 * k), int((W - 30) * k), int(136 * k), int(146 * k)
        c.create_rectangle(x0, y0, x1, y1, fill=self.c["track"], width=0, tags="s")
        self.bar = (x0, x1, y0, y1)

    def _draw(self) -> None:
        k, c = self.k, self.cv
        c.delete("d")
        x0, x1, y0, y1 = self.bar
        fx = x0 + int((x1 - x0) * self.shown / 100.0)
        if fx > x0:
            c.create_rectangle(x0, y0, fx, y1, fill=self.c["fill"], width=0, tags="d")
            c.create_rectangle(max(x0, fx - int(26 * k)), y0, fx, y1, fill=self.c["tag"], width=0, tags="d")
        c.create_text(x0, int(112 * k), text=self.text, fill=self.c["text"], font=self._f(14), anchor="w", tags="d")
        c.create_text(x1, int(112 * k), text=f"{int(self.shown)}%", fill=self.c["text"], font=self._f(14, True), anchor="e", tags="d")
        eta = left_text(remaining(self.last, self.target)) if self.shown < 99 else ""
        c.create_text(x0, int(168 * k), text=eta or ("Opening…" if self.shown >= 99 else ""), fill=self.c["muted"],
                      font=self._f(12), anchor="w", tags="d")

    def pump(self) -> None:
        """Ease the bar toward its target and repaint. Call often from the main thread."""
        if self._closed:
            return
        with self._lock:
            tgt = self.target
        self.shown += (tgt - self.shown) * 0.22
        if tgt - self.shown < 0.15:
            self.shown = tgt
        self._draw()
        self.win.update()

    def run_while(self, work, poll: float = 0.016):
        """Run `work()` in a thread while this window keeps animating. Returns its result; re-raises its error."""
        box: dict = {}

        def go():
            try:
                box["r"] = work()
            except BaseException as e:  # noqa: BLE001 - handed to the main thread below
                box["e"] = e
        th = threading.Thread(target=go, daemon=True)
        th.start()
        while th.is_alive():
            self.pump()
            time.sleep(poll)
        self.set(100)
        for _ in range(40):                                       # let the bar reach the end before it goes
            self.pump()
            if self.shown >= 99.9:
                break
            time.sleep(poll)
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def step(self, pct: float, text: str | None = None) -> None:
        """Main-thread progress: set the target and animate for a moment."""
        self.set(pct, text)
        for _ in range(6):
            self.pump()
            time.sleep(0.008)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        total = time.monotonic() - self.t0
        self.marks.save(self.phase, total, self.done_marks)
        try:
            self.win.destroy()
        except tk.TclError:
            pass


__all__ = ["Splash", "Marks", "remaining", "left_text", "close_exe_picture"]
