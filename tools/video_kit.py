"""A tiny screen-recording kit for how-to videos of the real ReRun LITE window.

It does not film the screen. It asks Windows to draw only the app's own window (and its pop-ups) into a bitmap
(PrintWindow), so nothing else on the desktop can appear, and it can run while the window sits off-screen. A
"scenario" is a generator: every `yield` is one video frame, and the helpers (move, click, type, hold, ...) are
generators too, used with `yield from`. A fake mouse pointer, a click ripple, a highlight ring, numbered steps and a
caption are drawn on top. Output: MP4 (mpeg4) and WebM (VP9), 15 frames a second, no sound.
"""
from __future__ import annotations

import ctypes
import math
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 15
OUT_W, OUT_H = 1600, 900
SIDE_W = 420
BG = (11, 14, 20)
CARD = (19, 24, 36)
LINE = (35, 43, 60)
TEXT = (242, 244, 248)
MUTED = (142, 151, 170)
ACCENT = (115, 129, 255)
GREEN = (52, 211, 153)
GOLD = (227, 177, 92)
FONTS = Path("C:/Windows/Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(str(FONTS / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=fnt) <= width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- window capture (the app's own windows only)
def _printwindow(widget: tk.Misc) -> Image.Image:
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = u.GetParent(widget.winfo_id()) or widget.winfo_id()
    r = wintypes.RECT()
    u.GetClientRect(hwnd, ctypes.byref(r))
    w, h = max(r.right, 1), max(r.bottom, 1)
    hdc = u.GetDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mdc, bmp)
    u.PrintWindow(hwnd, mdc, 3)

    class BI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("a", wintypes.LONG), ("b", wintypes.LONG),
                    ("c", wintypes.DWORD), ("d", wintypes.DWORD)]
    bi = BI(ctypes.sizeof(BI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


class Film:
    """One video. `scenes` is a list of (title, caption) shown in the side panel; `run(scenario)` records it."""

    def __init__(self, app: tk.Tk, title: str, steps: list[str], out_stem: Path, number: str = ""):
        self.app, self.title, self.steps, self.out = app, title, steps, Path(out_stem)
        self.number = number
        self.step = -1
        self.caption = ""
        self.cx = self.cy = 0.0
        self.show_cursor = False
        self.ripple = 0
        self.ring: tuple | None = None
        self.frames = 0
        self._writers: list[cv2.VideoWriter] = []
        self._gen = None
        self._pending = None
        self._done = False
        self._error: BaseException | None = None
        self.scene: Image.Image | None = None      # a full-frame slide instead of the window (title / text cards)

    # ------------------------------------------------------------ capture
    def window_image(self) -> Image.Image:
        app = self.app
        app.update_idletasks()
        img = _printwindow(app)
        ox, oy = app.winfo_rootx(), app.winfo_rooty()
        for tl in app.winfo_children():
            if not isinstance(tl, tk.Toplevel) or not tl.winfo_ismapped():
                continue
            if tl.winfo_width() >= app.winfo_width() - 2 and tl.winfo_height() >= app.winfo_height() - 2:
                img = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.5)       # the dim layer of a dialog
                continue
            sub = _printwindow(tl).convert("RGBA")
            try:
                key = str(tl.attributes("-transparentcolor"))
            except tk.TclError:
                key = ""
            if key:
                kc = _hex(key)
                a = np.asarray(sub)
                mask = (a[..., 0] == kc[0]) & (a[..., 1] == kc[1]) & (a[..., 2] == kc[2])
                a = a.copy()
                a[..., 3] = np.where(mask, 0, 255)
                sub = Image.fromarray(a, "RGBA")
            img.paste(sub, (tl.winfo_rootx() - ox, tl.winfo_rooty() - oy), sub)
        return img

    def widget_box(self, w: tk.Misc) -> tuple[int, int, int, int]:
        ox, oy = self.app.winfo_rootx(), self.app.winfo_rooty()
        x, y = w.winfo_rootx() - ox, w.winfo_rooty() - oy
        return x, y, x + w.winfo_width(), y + w.winfo_height()

    # ------------------------------------------------------------ drawing
    def _compose(self) -> np.ndarray:
        canvas = Image.new("RGB", (OUT_W, OUT_H), BG)
        d = ImageDraw.Draw(canvas)
        if self.scene is not None:
            canvas.paste(self.scene, (0, 0))
            return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)
        win = self.window_image()
        avail_w, avail_h = OUT_W - SIDE_W - 40, OUT_H - 40
        s = min(avail_w / win.width, avail_h / win.height)
        if abs(s - 1) > 0.01:
            win = win.resize((int(win.width * s), int(win.height * s)), Image.LANCZOS)
        wx, wy = 20, (OUT_H - win.height) // 2
        # soft shadow, then the window
        key = (win.width, win.height)
        if getattr(self, "_shadow_key", None) != key:
            sh = Image.new("RGBA", (win.width + 60, win.height + 60), (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle((30, 36, win.width + 30, win.height + 36), 14, fill=(0, 0, 0, 150))
            self._shadow, self._shadow_key = sh.filter(ImageFilter.GaussianBlur(14)), key
        canvas.paste(self._shadow, (wx - 30, wy - 30), self._shadow)
        canvas.paste(win, (wx, wy))
        ov = ImageDraw.Draw(canvas, "RGBA")
        # highlight ring
        if self.ring is not None:
            x0, y0, x1, y1 = self.ring
            pulse = 0.5 + 0.5 * math.sin(self.frames / 3.0)
            pad = 4 + 3 * pulse
            ov.rounded_rectangle((wx + x0 * s - pad, wy + y0 * s - pad, wx + x1 * s + pad, wy + y1 * s + pad), 10,
                                 outline=GOLD + (int(170 + 85 * pulse),), width=3)
        # click ripple
        if self.ripple:
            r = 8 + (14 - self.ripple) * 2.4
            ov.ellipse((wx + self.cx * s - r, wy + self.cy * s - r, wx + self.cx * s + r, wy + self.cy * s + r),
                       outline=ACCENT + (int(40 + 14 * self.ripple),), width=3)
        # pointer
        if self.show_cursor:
            px_, py_ = wx + self.cx * s, wy + self.cy * s
            pts = [(0, 0), (0, 17), (4.2, 13.2), (7, 19.5), (9.6, 18.4), (6.8, 12.3), (12, 12.3)]
            ov.polygon([(px_ + x + 1.5, py_ + y + 2) for x, y in pts], fill=(0, 0, 0, 110))
            ov.polygon([(px_ + x, py_ + y) for x, y in pts], fill=(255, 255, 255, 255), outline=(20, 20, 20, 255))
        self._sidebar(canvas, d)
        return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)

    def _sidebar(self, canvas: Image.Image, d: ImageDraw.ImageDraw) -> None:
        x0 = OUT_W - SIDE_W
        d.rectangle((x0, 0, OUT_W, OUT_H), fill=(14, 18, 27))
        d.line((x0, 0, x0, OUT_H), fill=LINE, width=1)
        x, y = x0 + 30, 34
        d.rounded_rectangle((x, y, x + 52, y + 22), 5, fill=GOLD)
        d.text((x + 26, y + 11), "LITE", font=font(12, True), fill=(27, 20, 5), anchor="mm")
        d.text((x + 64, y + 11), "ReRun  ·  setup guide" + (f"  ·  {self.number}" if self.number else ""),
               font=font(14), fill=MUTED, anchor="lm")
        y += 48
        for line in wrap(d, self.title, font(30, True), SIDE_W - 60):
            d.text((x, y), line, font=font(30, True), fill=TEXT)
            y += 38
        y += 14
        n_font, t_font = font(15, True), font(16)
        for i, label in enumerate(self.steps):
            done, cur = i < self.step, i == self.step
            cy = y + 14
            if cur:
                d.rounded_rectangle((x - 10, y - 5, OUT_W - 24, y + 33 + 20 * (len(wrap(d, label, t_font, SIDE_W - 110)) - 1)),
                                    10, fill=(28, 35, 54))
            d.ellipse((x, cy - 13, x + 26, cy + 13), fill=ACCENT if cur else (GREEN if done else (33, 40, 58)))
            if done:
                d.line([(x + 7, cy), (x + 11.5, cy + 5), (x + 20, cy - 5)], fill=(255, 255, 255), width=3)
            else:
                d.text((x + 13, cy), str(i + 1), font=n_font, anchor="mm", fill=(255, 255, 255) if cur else MUTED)
            lines = wrap(d, label, t_font, SIDE_W - 110)
            for j, ln in enumerate(lines):
                d.text((x + 40, y + 4 + j * 21), ln, font=font(16, cur), fill=TEXT if cur else (MUTED if not done else (170, 178, 195)))
            y += 36 + 21 * (len(lines) - 1) + 8
        # caption box at the bottom
        if self.caption:
            cf = font(17)
            lines = wrap(d, self.caption, cf, SIDE_W - 84)
            h = 28 + 25 * len(lines)
            by = OUT_H - 50 - h
            d.rounded_rectangle((x - 10, by, OUT_W - 24, by + h), 12, fill=CARD, outline=LINE)
            d.rectangle((x - 10, by + 14, x - 7, by + h - 14), fill=GOLD)
            for j, ln in enumerate(lines):
                d.text((x + 12, by + 14 + j * 25), ln, font=cf, fill=TEXT)
        # progress along the bottom
        total = max(len(self.steps), 1)
        d.rounded_rectangle((x, OUT_H - 28, OUT_W - 30, OUT_H - 22), 3, fill=(33, 40, 58))
        d.rounded_rectangle((x, OUT_H - 28, x + (SIDE_W - 60) * max(self.step + 1, 0) / total, OUT_H - 22), 3, fill=ACCENT)

    # ------------------------------------------------------------ scenario helpers (all generators)
    def say(self, step: int | None, caption: str = ""):
        """Move to step `step` (0-based; None keeps it) and set the caption."""
        if step is not None:
            self.step = step
        self.caption = caption
        yield

    def hold(self, seconds: float):
        for _ in range(max(1, int(seconds * FPS))):
            yield

    def wait_for(self, cond, timeout: float = 8.0, what: str = ""):
        t0 = time.time()
        while not cond():
            if time.time() - t0 > timeout:
                raise TimeoutError(f"waiting for {what or cond}")
            yield

    def highlight(self, w: tk.Misc | None, pad: int = 0):
        if w is None:
            self.ring = None
        else:
            x0, y0, x1, y1 = self.widget_box(w)
            self.ring = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        yield

    def move(self, x: float, y: float, seconds: float = 0.7):
        if not self.show_cursor:
            self.cx, self.cy, self.show_cursor = x + 120, y + 90, True
        sx, sy = self.cx, self.cy
        n = max(2, int(seconds * FPS))
        bow = min(40.0, math.hypot(x - sx, y - sy) * 0.12)
        for i in range(1, n + 1):
            t = ease(i / n)
            self.cx = sx + (x - sx) * t + bow * math.sin(math.pi * t) * 0.6
            self.cy = sy + (y - sy) * t - bow * math.sin(math.pi * t)
            yield
        self.cx, self.cy = x, y

    def move_to(self, w: tk.Misc, fx: float = 0.5, fy: float = 0.5, seconds: float = 0.7):
        x0, y0, x1, y1 = self.widget_box(w)
        yield from self.move(x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy, seconds)

    def click(self, w: tk.Misc, fx: float = 0.5, fy: float = 0.5, seconds: float = 0.7, wait: float = 0.5):
        """Pointer to `w`, a ripple, then the real click. The click runs from its own callback so that a modal dialog
        it opens does not freeze the recording."""
        yield from self.move_to(w, fx, fy, seconds)
        self.ripple = 14
        yield
        ex, ey = int(w.winfo_width() * fx), int(w.winfo_height() * fy)

        def fire():
            if not w.winfo_exists():
                return
            for ev in ("<Enter>", "<ButtonPress-1>", "<ButtonRelease-1>"):
                w.event_generate(ev, x=ex, y=ey)
        self.app.after(1, fire)
        yield from self.hold(wait)

    def type_into(self, entry: tk.Entry, text: str, per_char: float = 0.07, clear: bool = True):
        entry.focus_force()
        if clear:
            entry.delete(0, "end")
        for ch in text:
            entry.insert("end", ch)
            yield from self.hold(per_char)

    def scroll_into_view(self, w: tk.Misc, seconds: float = 0.8):
        """Scroll the ScrollFrame that holds `w` until `w` is comfortably inside it."""
        cv = w
        while cv is not None and not (isinstance(cv, tk.Canvas) and cv.cget("yscrollcommand")):
            cv = cv.master
        if cv is None:
            return
        self.app.update_idletasks()
        bbox = cv.bbox("all")
        if not bbox:
            return
        total = bbox[3] - bbox[1]
        view_h = cv.winfo_height()
        wy = w.winfo_rooty() - cv.winfo_rooty() + cv.canvasy(0)
        target = max(0.0, min(1.0, (wy - view_h * 0.35) / max(total - view_h, 1)))
        start = cv.yview()[0] * 1.0
        n = max(2, int(seconds * FPS))
        for i in range(1, n + 1):
            cv.yview_moveto((start + (target - start) * ease(i / n)) * 1.0 if total > view_h else 0)
            yield

    def slide(self, heading: str, lines: list[str], seconds: float, kicker: str = ""):
        """A full-frame text card (no app window), used for things that happen outside the app."""
        img = Image.new("RGB", (OUT_W, OUT_H), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((120, 110, OUT_W - 120, OUT_H - 110), 24, fill=CARD, outline=LINE)
        d.rounded_rectangle((170, 160, 230, 186), 6, fill=GOLD)
        d.text((200, 173), "LITE", font=font(14, True), fill=(27, 20, 5), anchor="mm")
        d.text((250, 173), kicker or f"ReRun LITE  ·  {self.title}", font=font(18), fill=MUTED, anchor="lm")
        y = 240
        for ln in wrap(d, heading, font(44, True), OUT_W - 400):
            d.text((170, y), ln, font=font(44, True), fill=TEXT)
            y += 56
        y += 24
        for item in lines:
            wrapped = wrap(d, item, font(26), OUT_W - 470)
            d.ellipse((172, y + 11, 184, y + 23), fill=ACCENT)
            for ln in wrapped:
                d.text((206, y), ln, font=font(26), fill=(214, 220, 232))
                y += 38
            y += 14
        self.scene = img
        yield from self.hold(seconds)
        self.scene = None

    # ------------------------------------------------------------ driver
    def _open_writers(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        for ext, codec in (("mp4", "mp4v"), ("webm", "VP90")):
            w = cv2.VideoWriter(str(self.out.with_suffix("." + ext)), cv2.VideoWriter_fourcc(*codec), FPS, (OUT_W, OUT_H))
            if w.isOpened():
                self._writers.append(w)

    def _frame(self):
        if self.ripple:
            self.ripple -= 1
        img = self._compose()
        for w in self._writers:
            w.write(img)
        self.frames += 1
        if self.frames % 100 == 0:
            print(f"  ... {self.frames} frames ({time.time() - self._t0:.0f}s)", flush=True)

    def _fail(self, e: BaseException) -> None:
        """Stop for good: show why, and close any open dialog so a modal wait cannot keep the process alive."""
        import traceback
        traceback.print_exception(e)
        self._error, self._done = e, True
        for tl in list(self.app.winfo_children()):
            if isinstance(tl, tk.Toplevel):
                tl.destroy()
        self.app.quit()

    def _tick(self):
        try:
            next(self._gen)
        except StopIteration:
            self._done = True
            self.app.quit()
            return
        except BaseException as e:  # noqa: BLE001 - reported by run()
            self._fail(e)
            return
        # let Tk repaint / animate for about a frame's worth of real time, then capture
        self.app.after(35, self._capture)

    def _capture(self):
        try:
            self.app.update_idletasks()
            self._frame()
        except BaseException as e:  # noqa: BLE001
            self._fail(e)
            return
        self.app.after(1, self._tick)

    def run(self, scenario) -> int:
        self._t0 = time.time()
        self._open_writers()
        self._gen = scenario(self)
        self.app.after(300, self._tick)
        self.app.mainloop()
        for w in self._writers:
            w.release()
        if self._error is not None:
            raise self._error
        return self.frames
