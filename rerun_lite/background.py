"""The video background.

How it works (Tk cannot make a widget see-through, so the window shows the video through a colour key):

  * A second, borderless window sits directly behind the app window and plays the video in a Label. It follows the
    app window when it moves, is resized or maximised, hides when the app is minimised, never takes focus, ignores
    clicks (see `_styles`) and does not appear in the taskbar or Alt-Tab.
  * The app window declares its page background colour (the theme's `bg`) transparent (`-transparentcolor`). Every
    place the page background shows - the gaps between cards, the margins, the space behind text - therefore shows
    the video; cards, buttons, fields and the live view stay solid.
  * Text and rounded buttons drawn straight onto that colour key come out with ragged edges, because Windows cannot
    blend them with the picture behind. So the video is darkened (or lightened, in a light theme) in a soft patch
    behind every label and button ("scrim"): the ragged edge then falls on a calm area and the text stays crisp.

Decoding runs on its own thread; the Tk thread only turns the newest frame into a picture. The video is toned toward the
theme's background colour (the "Dimming" setting) so text stays readable. It pauses while the window is minimised, and
optionally while Crest is running, so it never costs Crest anything it does not have to.

Which video plays: for the Ahri theme the first file in `background/` next to the app (mp4, webm, mkv, avi, mov, gif);
else a file chosen in Settings > General > Background for that theme; else the theme's own animation in assets/
(tools/make_background.py draws them). A small video (under 1280 px wide) is enlarged once and cleaned up
(upscale.py) in the background; until that is done the original plays.
"""
from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageTk

from rerun import errlog, ios
from rerun.ios import C

from . import palettes, theme, upscale

VIDEO_TYPES = (".mp4", ".webm", ".mkv", ".avi", ".mov", ".gif")
DIMS = {"Light": 0.70, "Medium": 0.50, "Strong": 0.36}            # how much of the video is kept (the rest is the theme colour)
SCRIMS = {"Off": 0.0, "Soft": 0.55, "Strong": 0.80}                # how far the video is pulled to the theme colour behind controls
SPEEDS = {"Smooth (30 fps)": 30, "Normal (20 fps)": 20, "Light on the PC (12 fps)": 12}
DEFAULTS = {"bg_dim": "Medium", "bg_fps": 20, "bg_pause_running": False, "bg_scrim": "Soft", "bg_upscale": True}
MAX_RECTS = 400


def app_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def asset_video(root: Path, filename: str) -> Path | None:
    """A built-in video by file name: next to the app (or the project), else inside the exe."""
    if not filename:
        return None
    rel = Path("assets") / filename
    for base in (Path(root), app_dir()):
        if (base / rel).is_file():
            return base / rel
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled and (Path(bundled) / rel).is_file():
        return Path(bundled) / rel
    return None


def pick_video(root: Path, res) -> Path | None:
    """The file that plays for the open appearance `res` (appearance.Resolved), or None (no video, or none found).

    Background "Your own video" -> the file chosen in Settings. Otherwise the look's (or the chosen theme's) own
    animation; for Ahri's, a video dropped into the `background` folder takes its place (the first one found)."""
    a = res.appearance
    if a.background == "custom":
        p = Path(a.custom_video) if a.custom_video else None
        return p if p is not None and p.is_file() else None
    if not res.video:
        return None
    if res.video == palettes.LOOKS["ahri"].video:
        folder = Path(root) / "background"
        if folder.is_dir():
            for p in sorted(folder.iterdir()):
                if p.suffix.lower() in VIDEO_TYPES and p.is_file():
                    return p
    return asset_video(root, res.video)


def find_video(root: Path, chosen: str = "", key: str = "ahri") -> Path | None:
    """(compatibility) the video for look `key`, or the file `chosen` when it exists."""
    from . import appearance
    a = appearance.Appearance(key if key in appearance.LOOKS else "ahri", background="custom" if chosen else "auto",
                              custom_video=chosen)
    p = pick_video(root, appearance.resolve(a))
    return p if p is not None or not chosen else pick_video(root, appearance.resolve(appearance.Appearance(a.look)))


def chosen_path(settings: dict, key: str) -> str:
    return str(settings.get(f"bg_path_{key}") or "")


def cover(frame: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale `frame` to fill w x h (cropping the overflow), like CSS background-size: cover."""
    fh, fw = frame.shape[:2]
    s = max(w / fw, h / fh)
    nw, nh = max(int(round(fw * s)), w), max(int(round(fh * s)), h)
    r = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    x, y = (nw - w) // 2, (nh - h) // 2
    return r[y:y + h, x:x + w]


def _hex_bgr(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[4:6], 16), int(c[2:4], 16), int(c[0:2], 16)


class Player(threading.Thread):
    """Decodes `path` in a loop and keeps the newest toned, window-sized frame in `.frame` (RGB uint8).

    Every frame is `veil + (video - veil) * keep`, where `veil` is the theme's background colour and `keep` is the
    Dimming setting, lowered further at the window's edge (a soft vignette) and behind the controls (the scrim:
    `rects`, set by the window, are the places where labels and buttons sit)."""

    def __init__(self, path: Path, size: tuple[int, int], dim: float, fps: int, veil: str = "#000000",
                 scrim: float = 0.0):
        super().__init__(daemon=True)
        self.path, self.size, self.dim, self.fps = path, size, dim, fps
        self.veil, self.scrim = veil, scrim
        self.rects: tuple = ()
        self.frame: np.ndarray | None = None
        self.stamp = 0
        self.running = threading.Event()
        self.running.set()
        self._quit = False
        self.error = ""
        self._key = None
        self._keep = None
        self._veil32 = None

    def stop(self):
        self._quit = True
        self.running.set()

    def _weights(self, w: int, h: int) -> None:
        """Rebuild the per-pixel 'keep' map when the size, dimming, vignette or scrim changed."""
        key = (w, h, self.dim, self.scrim, self.rects, self.veil)
        if key == self._key:
            return
        d = np.sqrt(((np.arange(w) - w / 2) / (w / 2)) ** 2 + ((np.arange(h)[:, None] - h / 2) / (h / 2)) ** 2)
        pull = 0.35 * np.clip(d - 0.5, 0, 1)                                    # toward the veil at the edges
        if self.scrim > 0 and self.rects:
            m = np.zeros((h, w), np.float32)
            for x0, y0, x1, y1 in self.rects:
                cv2.rectangle(m, (int(x0) - 5, int(y0) - 4), (int(x1) + 5, int(y1) + 4), 1.0, -1)
            m = cv2.GaussianBlur(m, (0, 0), 7) * self.scrim
            pull = np.clip(pull + m, 0, 0.92)
        self._keep = (self.dim * (1.0 - pull)).astype(np.float32)[..., None]
        self._veil32 = np.array(_hex_bgr(self.veil), np.float32)
        self._key = key

    def run(self):
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            self.error = f"Cannot open {self.path.name}"
            return
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 24
        last = time.monotonic()
        while not self._quit:
            if not self.running.wait(0.25):
                continue
            ok, frame = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
                if not ok:
                    self.error = "The video has no frames"
                    return
            w, h = self.size
            w, h = max(w, 16), max(h, 16)
            out = cover(frame, w, h)
            up = out.shape[1] / max(frame.shape[1], 1)
            if up > 1.4:                                              # a small video blown up: soften it so text stays readable
                out = cv2.GaussianBlur(out, (0, 0), min(2.4, 0.9 * up))
            self._weights(out.shape[1], out.shape[0])
            toned = self._veil32 + (out.astype(np.float32) - self._veil32) * self._keep
            self.frame = cv2.cvtColor(np.clip(toned, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)
            self.stamp += 1
            step = 1.0 / min(self.fps, src_fps)
            now = time.monotonic()
            time.sleep(max(0.0, step - (now - last)))
            last = time.monotonic()
        cap.release()


class Backdrop:
    """The second window and the colour key. `start()` builds it; `stop()` takes it away again."""

    def __init__(self, app: tk.Tk, root: Path, settings: dict, on_status=None):
        self.app, self.root, self.s = app, Path(root), settings
        self.win: tk.Toplevel | None = None
        self.label: tk.Label | None = None
        self.player: Player | None = None
        self.photo = None
        self.shown_stamp = -1
        self._sync_job = None
        self.active = False
        self.path: Path | None = None          # the video the user sees named (the file chosen / dropped / built in)
        self.playing: Path | None = None       # the file actually decoded (the enlarged copy, once it exists)
        self._procs: list = []
        self.hooked = 0
        self._ticks = 0
        self.status = ""                       # "" or e.g. "Enlarging… 40%"
        self._on_status = on_status
        self._upscaled: Path | None = None
        self._cancel = threading.Event()
        self._rects_sig = None
        self.key = theme.ACTIVE

    # ------------------------------------------------------------ start / stop
    def veil(self) -> str:
        return C["bg"]

    def wanted(self) -> bool:
        """A video is wanted here: not in Classic (ReRun's own look), and not when the background is Off."""
        cur = theme.CURRENT
        return cur is not None and theme.is_custom() and cur.appearance.background != "off"

    def start(self) -> bool:
        self.key = theme.ACTIVE
        if self.active or not self.wanted():
            return False
        self.path = pick_video(self.root, theme.CURRENT)
        if self.path is None:
            return False
        self._cancel = threading.Event()
        self._upscaled = None
        self.playing = self._prepare_source(self.path)
        app = self.app
        app.update_idletasks()
        w, h = max(app.winfo_width(), 200), max(app.winfo_height(), 200)
        self.win = tk.Toplevel(app)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.configure(bg=C["bg"])
        self.label = tk.Label(self.win, bd=0, highlightthickness=0, bg=C["bg"])
        self.label.pack(fill="both", expand=True)
        self.player = self._new_player(self.playing, w, h)
        self.player.start()
        try:
            app.attributes("-transparentcolor", C["bg"])
        except tk.TclError as e:
            errlog.note("lite.bg_key", e)
        self.active = True
        self._styles()
        self._sync()
        app.bind("<Configure>", self._on_configure, add="+")
        app.bind("<Map>", lambda e: self._visibility(), add="+")
        app.bind("<Unmap>", lambda e: self._visibility(), add="+")
        self._paint()
        return True

    def _new_player(self, path: Path, w: int, h: int) -> Player:
        p = Player(path, (w, h), DIMS.get(str(self.s.get("bg_dim")), 0.50), int(self.s.get("bg_fps", 20)),
                   veil=self.veil(), scrim=SCRIMS.get(str(self.s.get("bg_scrim")), 0.55))
        p.rects = self._rects_sig or ()
        return p

    # ------------------------------------------------------------ enlarging a small video (once, in the background)
    def _prepare_source(self, src: Path) -> Path:
        """`src` itself, or its enlarged copy when it exists; builds that copy in the background when it is needed."""
        if not self.s.get("bg_upscale", True):
            return src
        try:
            width = upscale.source_size(src)[0]
            if not upscale.needs_upscale(width):
                return src
            cache = self.root / "data" / "lite" / "cache"
            have = upscale.ready(src, cache)
            if have is not None:
                return have
            threading.Thread(target=self._upscale_worker, args=(src, upscale.cache_path(src, cache), self._cancel),
                             daemon=True).start()
        except Exception as e:  # noqa: BLE001 - the original still plays
            errlog.note("lite.bg_upscale", e)
        return src

    def _upscale_worker(self, src: Path, dst: Path, cancel: threading.Event) -> None:
        self._set_status("Enlarging… 0%")
        ok = upscale.build(src, dst, progress=lambda p: self._set_status(f"Enlarging… {p}%"), cancel=cancel)
        if ok and not cancel.is_set():
            self._upscaled = dst
        self._set_status("")

    def _set_status(self, text: str) -> None:
        self.status = text

    def stop(self):
        if not self.active and self.win is None:
            return
        self.active = False
        self._cancel.set()
        if self.player is not None:
            self.player.stop()
            self.player = None
        try:
            self.app.attributes("-transparentcolor", "")
        except tk.TclError:
            pass
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
        self._procs = []

    def restart(self):
        self.stop()
        self.start()

    # ------------------------------------------------------------ keeping the window behind the app
    def _styles(self):
        """No focus, no taskbar button, and - the important part - a click on the video must do nothing.

        Where the page background shows the video, a click lands on the video window, not on the app. Left alone,
        Windows would make the video window the active one and raise it over the app, hiding every widget until the
        app is clicked again. So the video window (and the windows inside it) answer WM_MOUSEACTIVATE with
        MA_NOACTIVATE: the click is simply ignored and the app stays in front and in focus."""
        if sys.platform != "win32" or self.win is None:
            return
        try:
            self.win.update_idletasks()
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            GWL_EXSTYLE, NOACTIVATE, TOOLWINDOW = -20, 0x08000000, 0x00000080
            style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | NOACTIVATE | TOOLWINDOW) & ~0x00040000)   # not APPWINDOW
            self._never_activate(hwnd)
        except Exception as e:  # noqa: BLE001 - cosmetic
            errlog.note("lite.bg_styles", e)

    def _never_activate(self, top: int):
        """Answer WM_MOUSEACTIVATE with MA_NOACTIVATE on `top` and every window inside it."""
        u = ctypes.windll.user32
        lresult = ctypes.c_ssize_t
        wndproc = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u.SetWindowLongPtrW.restype = ctypes.c_void_p
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        u.CallWindowProcW.restype = lresult
        u.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        olds: dict[int, int] = {}

        def hook(h):
            def proc(hwnd, msg, wp, lp):
                if msg == 0x21:                                   # WM_MOUSEACTIVATE
                    return 3                                      # MA_NOACTIVATE
                return u.CallWindowProcW(olds[hwnd], hwnd, msg, wp, lp)
            cb = wndproc(proc)
            self._procs.append(cb)                                # must stay alive as long as the window
            olds[h] = u.SetWindowLongPtrW(h, -4, ctypes.cast(cb, ctypes.c_void_p))          # GWLP_WNDPROC

        kids: list[int] = []
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumChildWindows(top, enum(lambda h, _l: (kids.append(h), True)[1]), 0)
        for h in [top, *kids]:
            hook(h)
        self.hooked = 1 + len(kids)

    def _on_configure(self, e):
        if e.widget is not self.app or not self.active:
            return
        if self._sync_job is None:
            self._sync_job = self.app.after(16, self._sync)

    def _sync(self):
        self._sync_job = None
        if not self.active or self.win is None:
            return
        app = self.app
        try:
            w, h = max(app.winfo_width(), 16), max(app.winfo_height(), 16)
            self.win.geometry(f"{w}x{h}+{app.winfo_rootx()}+{app.winfo_rooty()}")
            self.win.attributes("-topmost", bool(app.attributes("-topmost")))
            if self.player is not None:
                self.player.size = (w, h)
            self._visibility()
            self.win.tk.call("lower", self.win._w, app._w)                 # directly behind the app window
        except tk.TclError as e:
            errlog.note("lite.bg_sync", e)

    def _visibility(self):
        if not self.active or self.win is None:
            return
        try:
            hidden = self.app.state() in ("iconic", "withdrawn") or not self.app.winfo_viewable()
            if hidden and self.win.state() != "withdrawn":
                self.win.withdraw()
            elif not hidden and self.win.state() == "withdrawn":
                self.win.deiconify()
                self.win.tk.call("lower", self.win._w, self.app._w)
            if self.player is not None:
                if hidden or self._paused_for_crest():
                    self.player.running.clear()
                else:
                    self.player.running.set()
        except tk.TclError:
            pass

    def _paused_for_crest(self) -> bool:
        if not self.s.get("bg_pause_running"):
            return False
        try:
            return any(i.status in ("running", "starting") for i in self.app.m.instances.values())
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------ the scrim: where controls sit
    def _collect_rects(self) -> tuple:
        """Boxes (in window pixels) of everything that is drawn straight onto the page background: labels, buttons,
        switches, and the cards' corners. The video is toned down behind them."""
        app = self.app
        ox, oy = app.winfo_rootx(), app.winfo_rooty()
        key = C["bg"].lower()
        out: list[tuple[int, int, int, int]] = []

        def box(w, pad=0):
            x0, y0 = w.winfo_rootx() - ox - pad, w.winfo_rooty() - oy - pad
            return (x0, y0, x0 + w.winfo_width() + 2 * pad, y0 + w.winfo_height() + 2 * pad)

        def visit(parent):
            for c in parent.winfo_children():
                if len(out) >= MAX_RECTS or isinstance(c, tk.Toplevel):
                    continue
                try:
                    if not c.winfo_viewable():
                        continue
                    if isinstance(c, ios.Card):
                        out.append(box(c, 2))
                        continue
                    kids = c.winfo_children()
                    if not kids:
                        if c.winfo_width() <= 700 and c.winfo_height() <= 140 and str(c.cget("bg")).lower() == key:
                            out.append(box(c))
                    else:
                        visit(c)
                except tk.TclError:                                   # a widget with no bg option, or just destroyed
                    continue
        visit(app)
        return tuple(out)

    # ------------------------------------------------------------ showing frames
    def _paint(self):
        if not self.active or self.win is None or self.player is None:
            return
        try:
            pl = self.player
            if pl.error and pl.frame is None:
                errlog.note("lite.bg_video", pl.error)
                self.stop()
                return
            self._visibility()
            self._ticks += 1
            if self._ticks % 40 == 0:                                       # belt and braces: stay directly behind the app
                self.win.tk.call("lower", self.win._w, self.app._w)
            if self._ticks % 8 == 1:                                        # where the controls are, a few times a second
                rects = self._collect_rects()
                if rects != self._rects_sig:
                    self._rects_sig = rects
                    pl.rects = rects
            if self._upscaled is not None:                                  # the enlarged copy is ready: switch to it
                new, self._upscaled = self._upscaled, None
                w, h = pl.size
                nxt = self._new_player(new, w, h)
                nxt.start()
                pl.stop()
                self.player = pl = nxt
                self.playing = new
            if self._on_status is not None and self.status != getattr(self, "_shown_status", None):
                self._shown_status = self.status
                self._on_status()
            if pl.frame is not None and pl.stamp != self.shown_stamp and pl.running.is_set():
                self.shown_stamp = pl.stamp
                self.photo = ImageTk.PhotoImage(Image.fromarray(pl.frame))
                self.label.configure(image=self.photo)
            self.app.after(max(10, int(1000 / max(self.player.fps, 1))), self._paint)
        except tk.TclError:
            pass


# ================================================================== the settings the video keeps (Appearance > Background)
class BackgroundMixin:
    def _bg_settings(self) -> dict:
        saved = self._ui_state()
        return {k: saved.get(k, v) for k, v in DEFAULTS.items()}

    def _bg_save(self, **changes):
        try:
            ui = self._ui_state()
            ui.update(changes)
            self._ui_path.write_text(json.dumps(ui, indent=1), encoding="utf-8")
        except OSError as e:
            errlog.note("lite.bg_save", e)

    def _build_backdrop(self):
        self.backdrop = Backdrop(self, self.m.root, self._bg_settings(), on_status=self._bg_refresh_label)
        self.after(200, self._bg_start)
        if not getattr(self, "_bg_destroy_bound", False):
            self._bg_destroy_bound = True
            self.bind("<Destroy>", lambda e: self.backdrop.stop() if e.widget is self else None, add="+")

    def _bg_start(self):
        if getattr(self, "backdrop", None) is not None:
            self.backdrop.start()
            self._bg_refresh_label()

    def _bg_changed(self, **changes):
        """A video setting (dimming, scrim, smoothness, enlarging, pause) changed: keep it and tell the player."""
        self._bg_save(**changes)
        self.backdrop.s.update(changes)
        pl = self.backdrop.player
        if pl is not None:
            if "bg_fps" in changes:
                pl.fps = int(changes["bg_fps"])
            if "bg_dim" in changes:
                pl.dim = DIMS.get(changes["bg_dim"], 0.50)
            if "bg_scrim" in changes:
                pl.scrim = SCRIMS.get(changes["bg_scrim"], 0.55)
        if "bg_upscale" in changes:
            self.backdrop.restart()
        self._bg_refresh_label()

    def _bg_refresh_label(self):
        bd = getattr(self, "backdrop", None)
        label = getattr(self, "_bg_label", None)
        if label is None or bd is None:
            return
        cur = theme.CURRENT
        if bd.active:
            text = bd.status or ("Playing: " + (bd.path.name if bd.path else "?"))[:38]
        elif cur is None or not bd.wanted():
            text = "Off"
        else:
            text = "No video found"
        try:
            label.configure(text=text)
        except tk.TclError:
            self._bg_label = None

