"""iOS-style look for the Tk window: palette, fonts and Canvas-drawn controls.

Tk has no rounded corners or anti-aliasing, so rounded shapes are built from
anti-aliased corner bitmaps (drawn with Pillow at 4x, then scaled down) plus
plain rectangles. Switches are pre-rendered Pillow frames.
"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

# iOS system colours (UIKit semantic colours, grouped-table variants).
LIGHT = {
    "bg": "#F2F2F7", "card": "#FFFFFF", "sep": "#C6C6C8", "label": "#000000",
    "secondary": "#8A8A8E", "tertiary": "#C4C4C6", "blue": "#007AFF", "green": "#34C759",
    "red": "#FF3B30", "orange": "#FF9500", "gray": "#8E8E93", "fill": "#E9E9EA",
    "field": "#EEEEEF", "bar": "#F9F9F9", "tab_off": "#999999", "viewer": "#E5E5EA",
    "alert": "#F9F9F9", "menu": "#FFFFFF",
}
DARK = {
    "bg": "#000000", "card": "#1C1C1E", "sep": "#38383A", "label": "#FFFFFF",
    "secondary": "#98989F", "tertiary": "#5A5A5E", "blue": "#0A84FF", "green": "#30D158",
    "red": "#FF453A", "orange": "#FF9F0A", "gray": "#8E8E93", "fill": "#39393D",
    "field": "#2C2C2E", "bar": "#121212", "tab_off": "#7C7C80", "viewer": "#0B0B0C",
    "alert": "#2C2C2E", "menu": "#2C2C2E",
}
C: dict[str, str] = dict(LIGHT)
F: dict[str, tuple] = {}
DARK_MODE = False
SCALE = 1.0
ICON_FONT: str | None = None
ICONS = {
    "home": "", "settings": "", "photo": "", "chat": "",
    "list": "", "play": "", "pause": "", "stop": "",
    "camera": "", "add": "", "edit": "", "delete": "",
    "folder": "", "save": "", "download": "", "search": "",
    "sync": "", "send": "", "chevron_down": "",
    "check": "", "history": "", "refresh": "",
}
ICONS.update({"people": "", "link": ""})  # Segoe Fluent: People, Link
_cache: dict = {}
_fonts: dict = {}


def px(n: float) -> int:
    return int(round(n * SCALE))


def mix(a: str, b: str, t: float) -> str:
    """Colour `a` moved toward `b` by t (0..1)."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def bg_of(w) -> str:
    try:
        return w.cget("bg")
    except tk.TclError:
        return C["bg"]


def measure(font: tuple, text: str) -> int:
    f = _fonts.get(font)
    if f is None:
        f = _fonts[font] = tkfont.Font(font=font)
    return f.measure(text)


def icon_text(name: str | None) -> str:
    return ICONS.get(name, "") if (name and ICON_FONT) else ""


# ------------------------------------------------------------------ setup
def enable_dpi_awareness() -> None:
    """Crisp text on scaled displays (must run before the Tk window exists)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - older Windows: stays bitmap-scaled
            pass


def system_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return False


def init(root: tk.Tk, appearance: str = "auto") -> None:
    """Pick light/dark, fonts and ttk styles. Call once after creating the root."""
    global DARK_MODE, SCALE, ICON_FONT
    _cache.clear()
    _fonts.clear()
    DARK_MODE = appearance == "dark" or (appearance == "auto" and system_dark())
    C.clear()
    C.update(DARK if DARK_MODE else LIGHT)
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    fams = set(tkfont.families(root))

    def first(*names):
        return next((n for n in names if n in fams), None)
    text = first("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "Helvetica") or "TkDefaultFont"
    disp = first("Segoe UI Variable Display", "Segoe UI") or text
    semi = first("Segoe UI Variable Text Semibold", "Segoe UI Semibold")
    mono = first("Cascadia Mono", "Consolas", "Menlo", "Courier New") or "TkFixedFont"
    ICON_FONT = first("Segoe Fluent Icons", "Segoe MDL2 Assets")
    sb = (semi, 11) if semi else (text, 11, "bold")
    F.clear()
    F.update({
        "large": (disp, 22, "bold"), "title": (disp, 14, "bold"),
        "body": (text, 11), "body_semi": sb, "button": (sb[0], 10) + sb[2:],
        "button_small": (sb[0], 9) + sb[2:], "footnote": (text, 9),
        "footnote_semi": (sb[0], 9) + sb[2:], "caption": (text, 8),
        "mono": (mono, 9), "glyph": (text, 15),
        # type scale for dashboards: big numbers, card titles
        "metric": (disp, 24, "bold"), "metric_small": (disp, 15, "bold"), "card_title": (sb[0], 12) + sb[2:],
    })
    if ICON_FONT:
        F.update({"icon": (ICON_FONT, 10), "icon_tab": (ICON_FONT, 15),
                  "icon_small": (ICON_FONT, 7)})
    root.configure(bg=C["bg"])
    _ttk_styles(root)
    root.bind_all("<MouseWheel>", _wheel, add="+")


def _ttk_styles(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("IOS.Treeview", background=C["card"], fieldbackground=C["card"],
                foreground=C["label"], borderwidth=0, relief="flat",
                rowheight=px(34), font=F["body"])
    s.map("IOS.Treeview", background=[("selected", C["blue"])],
          foreground=[("selected", "#FFFFFF")])
    s.layout("IOS.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    # Column headers (Units table): quiet caption style on the card colour, both themes.
    s.configure("IOS.Treeview.Heading", background=C["card"], foreground=C["secondary"],
                font=F["footnote_semi"], relief="flat", borderwidth=0,
                lightcolor=C["card"], darkcolor=C["card"], bordercolor=C["card"], padding=px(6))
    s.map("IOS.Treeview.Heading", background=[("active", C["card"])],
          foreground=[("active", C["label"])])
    for orient in ("Vertical", "Horizontal"):
        name = f"IOS.{orient}.TScrollbar"
        s.layout(name, [(f"{orient}.Scrollbar.trough", {"sticky": "nswe", "children": [
            (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        s.configure(name, troughcolor=C["card"], background=C["tertiary"],
                    bordercolor=C["card"], lightcolor=C["tertiary"], darkcolor=C["tertiary"],
                    arrowsize=px(7), gripcount=0, relief="flat", borderwidth=0)
        s.map(name, background=[("active", C["secondary"])],
              lightcolor=[("active", C["secondary"])], darkcolor=[("active", C["secondary"])])


def style_window(root: tk.Tk) -> None:
    """Windows 11: dark title bar in dark mode, and a caption that blends with the page."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1 if DARK_MODE else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)  # immersive dark mode
        h = C["bg"].lstrip("#")
        colorref = ctypes.c_int(int(h[4:6] + h[2:4] + h[0:2], 16))  # 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), 4)  # caption colour
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


# ------------------------------------------------------------------ drawing
def _corners(r: int, fill: str, bg: str):
    key = ("corner", r, fill, bg)
    if key not in _cache:
        ss = 4
        big = Image.new("RGB", (r * 2 * ss, r * 2 * ss), bg)
        ImageDraw.Draw(big).ellipse((0, 0, r * 2 * ss - 1, r * 2 * ss - 1), fill=fill)
        im = big.resize((r * 2, r * 2), Image.LANCZOS)
        _cache[key] = [ImageTk.PhotoImage(im.crop(b)) for b in
                       ((0, 0, r, r), (r, 0, 2 * r, r), (0, r, r, 2 * r), (r, r, 2 * r, 2 * r))]
    return _cache[key]


def rounded_rect(cv: tk.Canvas, x0, y0, x1, y1, r, fill: str, bg: str, tags=()):
    """Anti-aliased rounded rectangle covering pixels x0..x1-1, y0..y1-1."""
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    r = int(min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    if r < 2:
        cv.create_rectangle(x0, y0, x1 - 1, y1 - 1, fill=fill, outline=fill, tags=tags)
        return
    tl, tr, bl, br = _corners(r, fill, bg)
    for img, x, y in ((tl, x0, y0), (tr, x1 - r, y0), (bl, x0, y1 - r), (br, x1 - r, y1 - r)):
        cv.create_image(x, y, image=img, anchor="nw", tags=tags)
    # Outline-less Tk rectangles stop short of x1/y1, matching the corner tiles.
    cv.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, width=0, tags=tags)
    cv.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, width=0, tags=tags)


# ------------------------------------------------------------------ containers
class Card(tk.Frame):
    """Rounded card. Put children in `.body`; the card sizes to its content like
    a normal frame (stretch=True lets the body fill whatever space it is given).
    The rounded background is a canvas placed behind the body."""

    def __init__(self, parent, pad: int = 4, radius: int = 12, stretch: bool = False,
                 color: str | None = None):
        self._bg = bg_of(parent)
        super().__init__(parent, bg=self._bg)
        self.color = color or C["card"]
        self._r, self._pad = px(radius), px(pad)
        self._cv = tk.Canvas(self, bg=self._bg, highlightthickness=0, bd=0, width=1, height=1)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)
        self._cv.bind("<Configure>", self._layout)
        self.body = tk.Frame(self, bg=self.color)  # created after the canvas, so it sits on top
        self.body.pack(fill="both", expand=stretch, padx=self._pad, pady=self._pad)

    def _layout(self, e):
        self._cv.delete("all")
        rounded_rect(self._cv, 0, 0, e.width, e.height, self._r, self.color, self._bg)


class ScrollFrame(tk.Frame):
    """Vertically scrolling page; put children in `.inner`."""

    def __init__(self, parent):
        bg = bg_of(parent)
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                style="IOS.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=self._sbset)
        self.canvas.pack(side="left", fill="both", expand=True)

    def _sbset(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.sb.pack_forget()
        elif not self.sb.winfo_ismapped():
            self.sb.pack(side="right", fill="y")
        self.sb.set(lo, hi)

    def scroll(self, e):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")


def _wheel(e):
    """Route the mouse wheel to the ScrollFrame under the pointer (Text and
    Treeview scroll themselves)."""
    try:
        w = e.widget.winfo_containing(e.x_root, e.y_root)
    except (tk.TclError, AttributeError, KeyError):
        return
    while w is not None:
        if w.winfo_class() in ("Text", "Treeview", "Listbox"):
            return
        if isinstance(w, ScrollFrame):
            w.scroll(e)
            return
        w = w.master


def page_header(parent, title: str) -> tk.Frame:
    """Large title; returns a frame on the right for buttons."""
    bg = bg_of(parent)
    f = tk.Frame(parent, bg=bg)
    f.pack(fill="x", padx=px(20), pady=(px(16), px(10)))
    tk.Label(f, text=title, bg=bg, fg=C["label"], font=F["large"]).pack(side="left")
    right = tk.Frame(f, bg=bg)
    right.pack(side="right")
    return right


def section_header(parent, text: str, **pack) -> tk.Frame:
    """Small grey caps header above a card; returns a right-hand frame."""
    bg = bg_of(parent)
    f = tk.Frame(parent, bg=bg)
    f.pack(fill="x", **({"padx": px(16), "pady": (px(14), px(6))} | pack))
    tk.Label(f, text=text.upper(), bg=bg, fg=C["secondary"], font=F["footnote"]).pack(side="left", anchor="s")
    right = tk.Frame(f, bg=bg)
    right.pack(side="right")
    return right


class Group(tk.Frame):
    """iOS inset-grouped table: header, a card of rows with inset separators, footer."""

    def __init__(self, parent, header: str | None = None, footer: str | None = None,
                 wrap: int = 640):
        bg = bg_of(parent)
        super().__init__(parent, bg=bg)
        if header:
            tk.Label(self, text=header.upper(), bg=bg, fg=C["secondary"], font=F["footnote"],
                     anchor="w").pack(fill="x", padx=px(16), pady=(0, px(6)))
        self.card = Card(self)
        self.card.pack(fill="x")
        self.footer = None
        if footer:
            self.footer = tk.Label(self, text=footer, bg=bg, fg=C["secondary"], font=F["footnote"],
                                   anchor="w", justify="left", wraplength=px(wrap))
            self.footer.pack(fill="x", padx=px(16), pady=(px(6), 0))
        self._rows = 0

    def row(self, title: str, subtitle: str | None = None, wrap: int = 460) -> tk.Frame:
        """Adds a row with a title (and grey subtitle); returns the right-hand frame."""
        body, card = self.card.body, C["card"]
        if self._rows:
            tk.Frame(body, height=1, bg=C["sep"]).pack(fill="x", padx=(px(12), 0))
        self._rows += 1
        r = tk.Frame(body, bg=card)
        r.pack(fill="x")
        right = tk.Frame(r, bg=card)
        right.pack(side="right", padx=px(12), pady=px(6))
        left = tk.Frame(r, bg=card)
        left.pack(side="left", fill="x", expand=True, padx=(px(12), px(8)), pady=px(9))
        tk.Label(left, text=title, bg=card, fg=C["label"], font=F["body"], anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(left, text=subtitle, bg=card, fg=C["secondary"], font=F["footnote"],
                     anchor="w", justify="left", wraplength=px(wrap)).pack(fill="x")
        return right


def text_box(parent, mono: bool = False, wrap: str = "word", **pack) -> tuple[Card, tk.Text]:
    card = Card(parent, pad=6, stretch=True)
    card.pack(fill="both", expand=True, **pack)
    sb = ttk.Scrollbar(card.body, orient="vertical", style="IOS.Vertical.TScrollbar")
    t = tk.Text(card.body, wrap=wrap, bg=C["card"], fg=C["label"], insertbackground=C["label"],
                selectbackground=C["blue"], selectforeground="#FFFFFF", relief="flat", bd=0,
                highlightthickness=0, padx=px(8), pady=px(6), width=1, height=1,
                font=F["mono"] if mono else F["footnote"], yscrollcommand=sb.set,
                spacing1=px(1), spacing3=px(1))
    sb.configure(command=t.yview)
    sb.pack(side="right", fill="y", pady=px(4))
    t.pack(side="left", fill="both", expand=True)
    return card, t


# ------------------------------------------------------------------ controls
class Button(tk.Canvas):
    """kind: filled | tinted | gray | plain.  color: a palette key (blue, red, ...)."""

    def __init__(self, parent, text: str, command=None, kind: str = "filled",
                 color: str = "blue", icon: str | None = None, small: bool = False):
        self._bg = bg_of(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0, cursor="hand2")
        self._cmd, self._kind, self._color = command, kind, C[color]
        self._icon, self._small = icon_text(icon), small
        self._font = F["button_small" if small else "button"]
        self._bh = px(28 if small else 34)
        self._padx = px(0 if kind == "plain" else (11 if small else 15))
        self._state, self._enabled = "normal", True
        self._focus = False
        self.configure(takefocus=1)              # Tab reaches it; Space / Return press it
        self.bind("<FocusIn>", lambda e=None: self._set_focus(True))
        self.bind("<FocusOut>", lambda e=None: self._set_focus(False))
        for k in ("<space>", "<Return>"):
            self.bind(k, self._key_press)
        self.bind("<Enter>", lambda e=None: self._set_state("hover"))
        self.bind("<Leave>", lambda e=None: self._set_state("normal"))
        self.bind("<ButtonPress-1>", lambda e=None: self._set_state("pressed"))
        self.bind("<ButtonRelease-1>", self._release)
        self.set_text(text)

    def set_text(self, text: str):
        self._text = text
        w = measure(self._font, text) + 2 * self._padx
        if self._icon:
            w += measure(F["icon"], self._icon) + px(6)
        self._bw = w
        self.configure(width=w, height=self._bh)
        self._draw()

    def set_enabled(self, on: bool):
        self._enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _set_state(self, s):
        if not self.winfo_exists():       # a Leave event can arrive just after the page was redrawn
            return
        self._state = s
        self._draw()

    def _set_focus(self, on: bool):
        self._focus = on
        self._draw()

    def _key_press(self, _e=None):
        if self._enabled and self._cmd:
            self._cmd()
        return "break"

    def _release(self, e):
        fire = self._state == "pressed" and 0 <= e.x < self._bw and 0 <= e.y < self._bh
        self._set_state("hover" if fire else "normal")
        if fire and self._enabled and self._cmd:
            self._cmd()

    def _colors(self):
        c, bg = self._color, self._bg
        fill, fg = {
            "filled": (c, "#FFFFFF"),
            "tinted": (mix(bg, c, 0.24 if DARK_MODE else 0.15), c),
            "gray": (C["fill"], C["label"]),
            "plain": (None, c),
        }[self._kind]
        base = fill or bg
        if not self._enabled:
            return (mix(fill, bg, 0.5) if fill else None), mix(fg, base, 0.6)
        if self._state == "pressed":
            return (mix(fill, bg, 0.35) if fill else None), mix(fg, base, 0.4)
        if self._state == "hover":
            if self._kind == "filled":
                return mix(fill, "#FFFFFF", 0.12), fg
            if fill:
                return mix(fill, c, 0.08), fg
            return None, mix(fg, bg, 0.2)
        return fill, fg

    def _draw(self):
        self.delete("all")
        fill, fg = self._colors()
        if fill:
            rounded_rect(self, 0, 0, self._bw, self._bh, px(8 if self._small else 10), fill, self._bg)
        tw = measure(self._font, self._text)
        x = self._padx
        y = self._bh // 2
        if self._icon:
            iw = measure(F["icon"], self._icon)
            self.create_text(x, y, text=self._icon, font=F["icon"], fill=fg, anchor="w")
            x += iw + px(6)
        self.create_text(x + tw // 2, y, text=self._text, font=self._font, fill=fg)
        if self._focus:                                       # visible keyboard focus ring
            if self._kind == "plain":
                self.create_line(self._padx, self._bh - 2, self._bw - self._padx, self._bh - 2,
                                 fill=self._color, width=2)
            else:
                rounded_outline(self, 1, 1, self._bw - 1, self._bh - 1, px(8 if self._small else 10), C["blue"])


class Switch(tk.Canvas):
    """iOS toggle bound to a BooleanVar, with a short slide animation."""
    STEPS = 6

    def __init__(self, parent, variable: tk.BooleanVar, command=None):
        self._bg = bg_of(parent)
        self._W, self._H = px(51), px(31)
        super().__init__(parent, width=self._W, height=self._H, bg=self._bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._var, self._cmd = variable, command
        self._t = 1.0 if variable.get() else 0.0
        self._after = None
        self.bind("<ButtonRelease-1>", self._click)
        self._trace = variable.trace_add("write", lambda *a: self._animate())
        self.bind("<Destroy>", self._untrace)
        self._draw()

    def _untrace(self, e):
        if e.widget is self:
            try:
                self._var.trace_remove("write", self._trace)
            except tk.TclError:
                pass

    def _frame(self, t: float):
        key = ("switch", round(t, 3), self._bg, self._W, self._H, C["fill"], C["green"])
        if key in _cache:
            return _cache[key]
        ss = 4
        W, H = self._W * ss, self._H * ss
        im = Image.new("RGB", (W, H), self._bg)
        pill = Image.new("L", (W, H), 0)
        ImageDraw.Draw(pill).rounded_rectangle((0, 0, W - 1, H - 1), radius=H // 2, fill=255)
        im.paste(Image.new("RGB", (W, H), mix(C["fill"], C["green"], t)), mask=pill)
        m = 2 * ss
        k = H - 2 * m
        kx = m + t * (W - 2 * m - k)
        shadow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shadow).ellipse((kx, m + ss, kx + k, m + k + ss), fill=60)
        shadow = ImageChops.multiply(shadow.filter(ImageFilter.GaussianBlur(ss * 1.5)), pill)
        im.paste(Image.new("RGB", (W, H), "#000000"), mask=shadow)
        ImageDraw.Draw(im).ellipse((kx, m, kx + k, m + k), fill="#FFFFFF")
        photo = ImageTk.PhotoImage(im.resize((self._W, self._H), Image.LANCZOS))
        _cache[key] = photo
        return photo

    def _draw(self):
        self.delete("all")
        self.create_image(0, 0, image=self._frame(self._t), anchor="nw")

    def _click(self, e):
        if 0 <= e.x < self._W and 0 <= e.y < self._H:
            self._var.set(not self._var.get())
            if self._cmd:
                self._cmd()

    def _animate(self):
        target = 1.0 if self._var.get() else 0.0
        if self._after:
            self.after_cancel(self._after)
            self._after = None
        step = 1.0 / self.STEPS
        if abs(self._t - target) <= step + 1e-6:
            self._t = target
            self._draw()
            return
        self._t = round(self._t + (step if target > self._t else -step), 4)
        self._draw()
        self._after = self.after(14, self._animate)


class Field(Card):
    """Rounded text field. `.entry` is the tk.Entry."""

    def __init__(self, parent, variable: tk.Variable, width: int = 20, show: str = "",
                 justify: str = "left", color: str | None = None):
        color = color or C["field"]
        super().__init__(parent, pad=5, radius=8, color=color)
        self.entry = tk.Entry(self.body, textvariable=variable, width=width, show=show,
                              justify=justify, bg=color, fg=C["label"],
                              insertbackground=C["label"], selectbackground=C["blue"],
                              selectforeground="#FFFFFF", relief="flat", bd=0,
                              highlightthickness=0, font=F["body"])
        self.entry.pack(fill="x", padx=px(4), pady=px(1))


class Stepper(tk.Frame):
    """Number field plus an iOS − | + stepper."""

    def __init__(self, parent, variable: tk.StringVar, lo: int = 0, hi: int = 99999):
        bg = bg_of(parent)
        super().__init__(parent, bg=bg)
        self._var, self._lo, self._hi = variable, lo, hi
        Field(self, variable, width=6, justify="right").pack(side="left", padx=(0, px(10)))
        self._W, self._H = px(94), px(32)
        self._cv = tk.Canvas(self, width=self._W, height=self._H, bg=bg, highlightthickness=0,
                             bd=0, cursor="hand2")
        self._cv.pack(side="left")
        self._bg = bg
        self._pressed = None
        self._cv.bind("<ButtonPress-1>", self._press)
        self._cv.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def _draw(self):
        cv, W, H = self._cv, self._W, self._H
        cv.delete("all")
        rounded_rect(cv, 0, 0, W, H, px(8), C["fill"], self._bg)
        if self._pressed is not None:
            x0 = 0 if self._pressed < 0 else W // 2
            cv.create_rectangle(x0 + (px(8) if x0 == 0 else 0), 0,
                                x0 + W // 2 - (0 if x0 == 0 else px(8)) - 1, H - 1,
                                fill=mix(C["fill"], C["label"], 0.12), width=0)
        cv.create_line(W // 2, px(8), W // 2, H - px(8), fill=C["sep"])
        cv.create_text(W // 4, H // 2, text="−", font=F["glyph"], fill=C["label"])
        cv.create_text(3 * W // 4, H // 2, text="+", font=F["glyph"], fill=C["label"])

    def _press(self, e):
        self._pressed = -1 if e.x < self._W // 2 else 1
        self._draw()

    def _release(self, e):
        d, self._pressed = self._pressed, None
        self._draw()
        if d is None or not (0 <= e.x < self._W and 0 <= e.y < self._H):
            return
        try:
            cur = int(str(self._var.get()).strip() or 0)
        except ValueError:
            cur = self._lo
        self._var.set(str(max(self._lo, min(self._hi, cur + d))))


class Select(tk.Frame):
    """iOS pop-up button: shows the value with a chevron and opens a menu of choices.
    Mirrors the bits of ttk.Combobox Rerun uses: get/set/current and ['values']."""

    def __init__(self, parent, values=(), command=None, variable: tk.StringVar | None = None,
                 accent: bool = False):
        bg = bg_of(parent)
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var = variable or tk.StringVar()
        self._values, self._cmd = list(values), command
        fg = C["blue"] if accent else C["secondary"]
        self._lbl = tk.Label(self, textvariable=self.var, bg=bg, fg=fg, cursor="hand2",
                             font=F["body_semi" if accent else "body"])
        self._lbl.pack(side="left")
        widgets = [self, self._lbl]
        if ICON_FONT:
            ch = tk.Label(self, text=ICONS["chevron_down"], bg=bg, fg=fg, font=F["icon_small"],
                          cursor="hand2")
            ch.pack(side="left", padx=(px(6), 0), pady=(px(2), 0))
            widgets.append(ch)
        for w in widgets:
            w.bind("<Button-1>", self._open)

    def _open(self, _e=None):
        if self._values:
            popover(self, self._values, self.var.get(), self._picked)

    def _picked(self, value: str):
        self.var.set(value)
        if self._cmd:
            self._cmd()

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str):
        self.var.set(value)

    def current(self, i: int):
        self.var.set(self._values[i])

    def __setitem__(self, key, value):
        if key == "values":
            self._values = list(value)
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        return self._values if key == "values" else super().__getitem__(key)


def _key(color: str) -> str:
    """A colour one step off `color`: used as the 'transparent' key for pop-up
    corners, so the anti-aliased edge blends with what is behind them while
    nothing inside the pop-up can accidentally match the key."""
    h = color.lstrip("#")
    b = int(h[4:6], 16)
    return f"#{h[:4]}{(b - 1 if b else 1):02X}"


def popover(anchor: tk.Widget, values: list[str], current: str, on_pick) -> None:
    """iOS pull-down menu under `anchor`: rounded, a checkmark on the current
    value; closes on a pick, Escape or a click outside."""
    root = anchor.winfo_toplevel()
    behind = _key(bg_of(anchor))
    color = C["menu"] if DARK_MODE else "#F9F9F9"
    hover = mix(color, C["label"], 0.08)
    top = tk.Toplevel(root)
    top.overrideredirect(True)
    top.configure(bg=behind)
    try:
        top.attributes("-transparentcolor", behind)
    except tk.TclError:
        pass
    r = px(12)
    inset = int(r * 0.3) + 1
    row_h, check_w = px(36), px(30)
    text_w = max(measure(F["body"], v) for v in values)
    W = max(anchor.winfo_width(), text_w + check_w + px(36))
    H = len(values) * row_h + (len(values) - 1) + 2 * inset + px(8)
    cv = tk.Canvas(top, bg=behind, highlightthickness=0, bd=0, width=W, height=H)
    cv.pack()
    rounded_rect(cv, 0, 0, W, H, r, color, behind)
    body = tk.Frame(cv, bg=color)
    cv.create_window(inset, inset + px(4), window=body, anchor="nw", width=W - 2 * inset)

    def close(_e=None):
        try:
            top.grab_release()
        except tk.TclError:
            pass
        top.destroy()

    def pick(v):
        close()
        on_pick(v)

    for i, v in enumerate(values):
        if i:
            tk.Frame(body, height=1, bg=C["sep"]).pack(fill="x", padx=(check_w, 0))
        row = tk.Frame(body, bg=color, height=row_h, cursor="hand2")
        row.pack(fill="x")
        row.pack_propagate(False)
        mark = (ICONS["check"] if ICON_FONT else "✓") if v == current else ""
        ck = tk.Label(row, text=mark, bg=color, fg=C["blue"], width=2,
                      font=F["icon"] if ICON_FONT else F["body"])
        ck.pack(side="left", padx=(px(8), px(2)))
        lb = tk.Label(row, text=v, bg=color, fg=C["label"], font=F["body"], anchor="w")
        lb.pack(side="left", fill="x", expand=True)
        widgets = (row, ck, lb)
        for w in widgets:
            w.bind("<Enter>", lambda e, ws=widgets: [x.configure(bg=hover) for x in ws])
            w.bind("<Leave>", lambda e, ws=widgets: [x.configure(bg=color) for x in ws])
            w.bind("<ButtonRelease-1>", lambda e, v=v: pick(v))
    x = anchor.winfo_rootx() + anchor.winfo_width() - W
    y = anchor.winfo_rooty() + anchor.winfo_height() + px(4)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x = max(0, min(x, sw - W))
    if y + H > sh:  # no room below: open upwards
        y = max(0, anchor.winfo_rooty() - H - px(4))
    top.geometry(f"{W}x{H}+{x}+{y}")

    def outside(e):
        if not (0 <= e.x_root - top.winfo_rootx() < W and 0 <= e.y_root - top.winfo_rooty() < H):
            close()
    top.bind("<ButtonPress>", outside)
    top.bind("<Escape>", close)
    top.focus_force()
    try:
        top.grab_set()
    except tk.TclError:
        pass


class Segmented(tk.Canvas):
    """iOS segmented control bound to a StringVar."""

    def __init__(self, parent, values: list[str], variable: tk.StringVar, command=None):
        self._bg = bg_of(parent)
        self._values, self._var, self._cmd = list(values), variable, command
        self._seg = max(measure(F["footnote_semi"], v) for v in values) + px(28)
        self._W, self._H = self._seg * len(values) + px(4), px(30)
        super().__init__(parent, width=self._W, height=self._H, bg=self._bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _draw(self):
        self.delete("all")
        track = C["field"]
        knob = "#636366" if DARK_MODE else "#FFFFFF"
        rounded_rect(self, 0, 0, self._W, self._H, px(9), track, self._bg)
        cur = self._var.get()
        sel = self._values.index(cur) if cur in self._values else -1
        for i, v in enumerate(self._values):
            x0 = px(2) + i * self._seg
            if i == sel:
                rounded_rect(self, x0, px(2), x0 + self._seg, self._H - px(2), px(7), knob, track)
            elif i and i - 1 != sel:
                self.create_line(x0, px(8), x0, self._H - px(8), fill=C["sep"])
            self.create_text(x0 + self._seg // 2, self._H // 2, text=v, fill=C["label"],
                             font=F["footnote_semi" if i == sel else "footnote"])

    def _click(self, e):
        i = (e.x - px(2)) // self._seg
        if 0 <= i < len(self._values) and 0 <= e.y < self._H:
            self._var.set(self._values[i])
            self._draw()
            if self._cmd:
                self._cmd()


class Toast:
    """Short message capsule that appears above the tab bar and fades away."""

    def __init__(self, parent: tk.Widget):
        self._parent = parent
        self._bg = bg_of(parent)
        self._cv = tk.Canvas(parent, bg=self._bg, highlightthickness=0, bd=0)
        self._after = None

    def show(self, text: str, kind: str = "info", seconds: float = 3.2):
        text = text if len(text) <= 110 else text[:109] + "…"
        color = "#2C2C2E" if DARK_MODE else "#1C1C1E"
        dot = {"info": None, "ok": C["green"], "warn": C["orange"], "error": C["red"]}.get(kind)
        tw = measure(F["footnote_semi"], text)
        W, H = tw + px(40) + (px(16) if dot else 0), px(38)
        cv = self._cv
        cv.delete("all")
        cv.configure(width=W, height=H)
        rounded_rect(cv, 0, 0, W, H, H // 2, color, self._bg)
        x = px(20)
        if dot:
            rounded_rect(cv, x, H // 2 - px(4), x + px(8), H // 2 + px(4), px(4), dot, color)
            x += px(16)
        cv.create_text(x, H // 2, text=text, fill="#FFFFFF", font=F["footnote_semi"], anchor="w")
        cv.place(relx=0.5, rely=1.0, y=-px(10), anchor="s")
        cv.tk.call("raise", cv._w)  # Canvas.lift() raises drawing items, not the widget
        if self._after:
            cv.after_cancel(self._after)
        self._after = cv.after(int(seconds * 1000), self.hide)

    def hide(self):
        self._after = None
        self._cv.place_forget()


def badge(kind: str) -> ImageTk.PhotoImage:
    """Small round status badge for lists: ok (green check), missing (red !),
    optional (grey dash)."""
    d = px(18)
    key = ("badge", kind, d, C["green"], C["red"], C["gray"], C["orange"])
    if key in _cache:
        return _cache[key]
    ss = 4
    D = d * ss
    im = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    g = ImageDraw.Draw(im)
    fill = {"ok": C["green"], "missing": C["red"], "weak": C["orange"]}.get(kind, C["gray"])
    g.ellipse((0, 0, D - 1, D - 1), fill=fill)
    w = max(2, D // 9)
    if kind == "ok":
        g.line([(D * 0.27, D * 0.52), (D * 0.44, D * 0.68), (D * 0.74, D * 0.34)], fill="white",
               width=w, joint="curve")
    elif kind in ("missing", "weak"):
        g.rounded_rectangle((D * 0.45, D * 0.2, D * 0.55, D * 0.6), radius=w // 2, fill="white")
        g.ellipse((D * 0.44, D * 0.68, D * 0.56, D * 0.8), fill="white")
    else:
        g.rounded_rectangle((D * 0.27, D * 0.45, D * 0.73, D * 0.55), radius=w // 2, fill="white")
    photo = ImageTk.PhotoImage(im.resize((d, d), Image.LANCZOS))
    _cache[key] = photo
    return photo


class Dot(tk.Canvas):
    def __init__(self, parent, d: int = 10, color: str | None = None):
        self._d, self._bg = px(d), bg_of(parent)
        super().__init__(parent, width=self._d, height=self._d, bg=self._bg,
                         highlightthickness=0, bd=0)
        self._color = color or C["gray"]
        self._draw()

    def set(self, color: str | None = None, bg: str | None = None):
        if color:
            self._color = color
        if bg:
            self._bg = bg
            self.configure(bg=bg)
        self._draw()

    def _draw(self):
        self.delete("all")
        rounded_rect(self, 0, 0, self._d, self._d, self._d // 2, self._color, self._bg)


class TabView(tk.Frame):
    """Bottom tab bar (icons + labels) with stacked pages; `.content` is the
    parent for pages, `.select(i)` switches like ttk.Notebook.select."""

    def __init__(self, parent):
        super().__init__(parent, bg=C["bg"])
        self.content = tk.Frame(self, bg=C["bg"])
        self.content.pack(fill="both", expand=True)
        self.status = tk.Label(self, text="", bg=C["bg"], fg=C["secondary"], font=F["footnote"])
        self.status.pack(fill="x", pady=(0, px(4)))
        tk.Frame(self, height=1, bg=C["sep"]).pack(fill="x")
        bar = tk.Frame(self, bg=C["bar"])
        bar.pack(fill="x")
        self._items = tk.Frame(bar, bg=C["bar"])
        self._items.pack(pady=(px(6), px(8)))
        self._pages: list[tk.Frame] = []
        self._tabs: list[tuple[tk.Label, tk.Label]] = []
        self._index: int | None = None

    def add(self, page: tk.Frame, text: str, icon: str, first: bool = False):
        """`first=True` shows the tab at the left end (its index is still its creation order)."""
        i = len(self._pages)
        self._pages.append(page)
        cell = tk.Frame(self._items, bg=C["bar"], width=px(112), height=px(44), cursor="hand2")
        self._cells = getattr(self, "_cells", [])
        self._cells.append((i, cell, first))
        self._regrid()
        cell.pack_propagate(False)
        ic = tk.Label(cell, text=icon_text(icon) or "●", bg=C["bar"], cursor="hand2",
                      font=F["icon_tab"] if ICON_FONT else F["body"])
        ic.pack(pady=(px(2), 0))
        lb = tk.Label(cell, text=text, bg=C["bar"], font=F["caption"], cursor="hand2")
        lb.pack()
        for w in (cell, ic, lb):
            w.bind("<Button-1>", lambda e, i=i: self.select(i))
        self._tabs.append((ic, lb))
        if self._index is None:
            self.select(0)
        else:
            self._paint()

    def _regrid(self):
        order = [c for c in self._cells if c[2]] + [c for c in self._cells if not c[2]]
        for col, (_, cell, _f) in enumerate(order):
            cell.grid(row=0, column=col)

    def select(self, i: int):
        if self._index is not None:
            self._pages[self._index].pack_forget()
        self._index = i
        self._pages[i].pack(in_=self.content, fill="both", expand=True)
        self._paint()

    def index(self) -> int | None:
        return self._index

    def count(self) -> int:
        return len(self._pages)

    def _paint(self):
        for j, (ic, lb) in enumerate(self._tabs):
            c = C["blue"] if j == self._index else C["tab_off"]
            ic.configure(fg=c)
            lb.configure(fg=c)


# ------------------------------------------------------------------ alerts
def _dialog(root: tk.Misc, title: str, message: str, buttons: list[tuple[str, str]],
            initial: str | None = None, default: int = 0, cancel: int | None = None):
    """iOS alert over a dimmed window. buttons: [(label, role)], role is
    default|cancel|destructive. Returns (index or None, entry text or None)."""
    root = root.winfo_toplevel()
    root.update_idletasks()
    result = {"i": cancel, "text": None}
    dim_alpha = 0.5 if DARK_MODE else 0.3
    dim = tk.Toplevel(root)
    dim.overrideredirect(True)
    dim.configure(bg="#000000")
    dim.geometry(f"{root.winfo_width()}x{root.winfo_height()}+{root.winfo_rootx()}+{root.winfo_rooty()}")
    try:
        dim.attributes("-alpha", dim_alpha)
    except tk.TclError:
        pass
    behind = mix(C["bg"], "#000000", dim_alpha)  # what shows around the alert's corners
    top = tk.Toplevel(root)
    top.overrideredirect(True)
    top.configure(bg=behind)
    try:
        top.attributes("-transparentcolor", behind)
    except tk.TclError:
        pass
    color, W = C["alert"], px(290)
    cv = tk.Canvas(top, bg=behind, highlightthickness=0, bd=0, width=W)
    cv.pack()
    body = tk.Frame(cv, bg=color)
    tk.Label(body, text=title, bg=color, fg=C["label"], font=F["body_semi"],
             wraplength=W - px(40), justify="center").pack(padx=px(16), pady=(px(18), px(2)))
    if message:
        tk.Label(body, text=message, bg=color, fg=C["label"], font=F["footnote"],
                 wraplength=W - px(40), justify="center").pack(padx=px(16), pady=(0, px(4)))
    var = tk.StringVar(value=initial or "")
    entry = None
    if initial is not None:
        fld = Field(body, var, width=24, color=C["card"] if DARK_MODE else "#FFFFFF")
        fld.pack(fill="x", padx=px(16), pady=(px(8), px(4)))
        entry = fld.entry
    tk.Frame(body, height=px(12), bg=color).pack()

    def close(i):
        result["i"] = i
        result["text"] = var.get() if entry is not None else None
        top.grab_release()
        top.destroy()

    def make_button(parent, i, label, role):
        fg = C["red"] if role == "destructive" else C["blue"]
        font = F["body_semi"] if role == "default" else F["body"]
        b = tk.Label(parent, text=label, bg=color, fg=fg, font=font, cursor="hand2",
                     height=1, pady=px(10))
        b.bind("<Enter>", lambda e: b.configure(bg=mix(color, C["label"], 0.07)))
        b.bind("<Leave>", lambda e: b.configure(bg=color))
        b.bind("<ButtonRelease-1>", lambda e: close(i))
        return b

    tk.Frame(body, height=1, bg=C["sep"]).pack(fill="x")
    row = tk.Frame(body, bg=color)
    row.pack(fill="x")
    if len(buttons) == 2:
        row.columnconfigure(0, weight=1, uniform="b")
        row.columnconfigure(2, weight=1, uniform="b")
        make_button(row, 0, *buttons[0]).grid(row=0, column=0, sticky="nsew")
        tk.Frame(row, width=1, bg=C["sep"]).grid(row=0, column=1, sticky="ns")
        make_button(row, 1, *buttons[1]).grid(row=0, column=2, sticky="nsew")
    else:
        for i, (label, role) in enumerate(buttons):
            if i:
                tk.Frame(row, height=1, bg=C["sep"]).pack(fill="x")
            make_button(row, i, label, role).pack(fill="x")

    body.update_idletasks()
    r = px(14)
    inset = int(r * 0.3) + 1  # keeps the square body inside the rounded corners
    H = body.winfo_reqheight() + 2 * inset
    cv.configure(height=H)
    rounded_rect(cv, 0, 0, W, H, r, color, behind)
    cv.create_window(inset, inset, window=body, anchor="nw", width=W - 2 * inset,
                     height=H - 2 * inset)
    x = root.winfo_rootx() + (root.winfo_width() - W) // 2
    y = root.winfo_rooty() + (root.winfo_height() - H) // 2
    top.geometry(f"{W}x{H}+{x}+{y}")
    top.lift(dim)
    top.bind("<Return>", lambda e: close(default))
    if cancel is not None:
        top.bind("<Escape>", lambda e: close(cancel))
    try:
        top.grab_set()
    except tk.TclError:
        pass
    top.focus_force()
    if entry is not None:
        entry.focus_set()
        entry.select_range(0, "end")
    root.wait_window(top)
    dim.destroy()
    return result["i"], result["text"]


def alert(root, message: str, title: str = "Rerun") -> None:
    _dialog(root, title, message, [("OK", "default")], cancel=0)


def confirm(root, message: str, title: str = "Rerun", ok: str = "OK", cancel: str = "Cancel",
            destructive: bool = False, default_cancel: bool = False) -> bool:
    """Two-button alert; True when `ok` is chosen. The bold button is the one
    Return picks (Cancel when default_cancel)."""
    cancel_role = "default" if default_cancel else "cancel"
    ok_role = "destructive" if destructive else ("cancel" if default_cancel else "default")
    i, _ = _dialog(root, title, message, [(cancel, cancel_role), (ok, ok_role)],
                   default=0 if default_cancel else 1, cancel=0)
    return i == 1


def ask_string(root, title: str, message: str, initial: str = "") -> str | None:
    i, text = _dialog(root, title, message, [("Cancel", "cancel"), ("OK", "default")],
                      initial=initial, default=1, cancel=0)
    return text if i == 1 else None


# ------------------------------------------------------------------ workspace widgets (Account Manager, Macro Farming)
def rounded_outline(cv: tk.Canvas, x0, y0, x1, y1, r, color: str, width: int = 2):
    cv.create_line(x0 + r, y0, x1 - r, y0, x1, y0 + r, x1, y1 - r, x1 - r, y1, x0 + r, y1, x0, y1 - r, x0, y0 + r,
                   x0 + r, y0, fill=color, width=width, smooth=True)


def animations_enabled() -> bool:
    """False when Windows 'Show animations' is off (reduced motion): widgets then jump instead of easing."""
    try:
        import ctypes
        flag = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)   # SPI_GETCLIENTAREAANIMATION
        return bool(flag.value)
    except (AttributeError, OSError, ImportError):
        return True


class SideNav(tk.Frame):
    """Vertical section list for a workspace. Click, or Up/Down/Home/End when focused.
    `items` is [(key, label)]; `command(key)` runs after a selection."""

    def __init__(self, parent, items: list[tuple[str, str]], command, width: int = 196, title: str = ""):
        self._bg = bg_of(parent)
        super().__init__(parent, bg=self._bg, width=px(width), highlightthickness=0, takefocus=1)
        self.pack_propagate(False)
        self._cmd, self._items, self.current = command, items, None
        if title:
            tk.Label(self, text=title.upper(), bg=self._bg, fg=C["secondary"], font=F["footnote"],
                     anchor="w").pack(fill="x", padx=px(14), pady=(px(6), px(8)))
        self._rows: dict[str, tuple[tk.Frame, tk.Label]] = {}
        for key, label in items:
            row = tk.Frame(self, bg=self._bg, cursor="hand2")
            row.pack(fill="x", padx=px(8), pady=px(1))
            lb = tk.Label(row, text=label, bg=self._bg, fg=C["label"], font=F["body"], anchor="w",
                          cursor="hand2")
            lb.pack(fill="x", padx=px(10), pady=px(7))
            for w in (row, lb):
                w.bind("<Button-1>", lambda e=None, k=key: self.select(k, focus=True))
                w.bind("<Enter>", lambda e=None, k=key: self._paint(hover=k))
                w.bind("<Leave>", lambda e=None: self._paint())
            self._rows[key] = (row, lb)
        self.bind("<Up>", lambda e=None: self._step(-1))
        self.bind("<Down>", lambda e=None: self._step(1))
        self.bind("<Home>", lambda e=None: self.select(self._items[0][0]))
        self.bind("<End>", lambda e=None: self.select(self._items[-1][0]))
        self.bind("<FocusIn>", lambda e=None: self._paint())
        self.bind("<FocusOut>", lambda e=None: self._paint())

    def _step(self, d: int):
        keys = [k for k, _ in self._items]
        i = keys.index(self.current) if self.current in keys else 0
        self.select(keys[max(0, min(len(keys) - 1, i + d))])
        return "break"

    def select(self, key: str, focus: bool = False, notify: bool = True):
        if key not in self._rows:
            return
        self.current = key
        if focus:
            self.focus_set()
        self._paint()
        if notify:
            self._cmd(key)

    def _paint(self, hover: str | None = None):
        focused = self.focus_get() is self
        for key, (row, lb) in self._rows.items():
            if key == self.current:
                bg, fg = mix(self._bg, C["blue"], 0.22 if DARK_MODE else 0.13), C["blue"]
                font = F["body_semi"]
            else:
                bg, fg, font = (C["fill"] if key == hover else self._bg), C["label"], F["body"]
            row.configure(bg=bg, highlightthickness=2 if (focused and key == self.current) else 0,
                          highlightbackground=bg, highlightcolor=C["blue"])
            lb.configure(bg=bg, fg=fg, font=font)


class ProgressBar(tk.Canvas):
    """Thin rounded bar, 0..1. Eases to a new value unless the system asks for reduced motion."""

    def __init__(self, parent, color: str = "blue", height: int = 8, width: int = 160):
        self._bg = bg_of(parent)
        self._h = px(height)
        super().__init__(parent, bg=self._bg, height=self._h, width=px(width), highlightthickness=0, bd=0)
        self._color, self._value, self._shown = C[color], 0.0, 0.0
        self.bind("<Configure>", lambda e=None: self._draw())

    def set(self, value: float, color: str | None = None):
        self._value = max(0.0, min(1.0, value))
        if color:
            self._color = C[color]
        if not animations_enabled() or abs(self._value - self._shown) < 0.01:
            self._shown = self._value
            self._draw()
        else:
            self._ease(6)

    def _ease(self, steps: int):
        if not self.winfo_exists():
            return
        self._shown += (self._value - self._shown) / max(1, steps)
        self._draw()
        if steps > 1:
            self.after(25, lambda: self._ease(steps - 1))

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w = max(self.winfo_width(), 2)
        rounded_rect(self, 0, 0, w, self._h, self._h // 2, C["fill"], self._bg)
        fw = int(w * self._shown)
        if fw >= self._h:
            rounded_rect(self, 0, 0, fw, self._h, self._h // 2, self._color, C["fill"])
        elif fw > 0:
            rounded_rect(self, 0, 0, self._h, self._h, self._h // 2, self._color, C["fill"])


class Pill(tk.Label):
    """Small tinted status label ("Completed", "BETA", ...). Always carries text, never colour alone."""

    def __init__(self, parent, text: str, kind: str = "gray"):
        bg = bg_of(parent)
        c = C.get(kind, C["gray"])
        super().__init__(parent, text=f" {text} ", bg=mix(bg, c, 0.22 if DARK_MODE else 0.14), fg=c,
                         font=F["footnote_semi"], padx=px(4), pady=px(1))


class BarChart(tk.Canvas):
    """Simple bar chart from [(label, value)]. Shows an honest empty state when there is nothing to plot."""

    def __init__(self, parent, title: str, data: list[tuple[str, float]], empty: str = "No data recorded yet",
                 color: str = "blue", height: int = 150, unit: str = ""):
        self._bg = bg_of(parent)
        super().__init__(parent, bg=self._bg, height=px(height), highlightthickness=0, bd=0)
        self.title, self.data, self.empty, self._color, self.unit = title, data, empty, C[color], unit
        self.bind("<Configure>", lambda e=None: self._draw())

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w, h = max(self.winfo_width(), 80), int(float(self["height"]))
        self.create_text(px(2), px(8), text=self.title, anchor="w", fill=C["label"], font=F["footnote_semi"])
        if not self.data or not any(v for _, v in self.data):
            self.create_text(w // 2, h // 2 + px(6), text=self.empty, fill=C["secondary"], font=F["footnote"])
            return
        top, bot = px(28), h - px(20)
        mx = max(v for _, v in self.data) or 1
        n = len(self.data)
        slot = (w - px(8)) / n
        bw = min(px(34), slot * 0.6)
        for i, (lab, v) in enumerate(self.data):
            x = px(4) + slot * i + (slot - bw) / 2
            bh = (bot - top) * (v / mx)
            if v:
                rounded_rect(self, x, bot - bh, x + bw, bot, min(px(5), bw / 2), self._color, self._bg)
            val = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"
            self.create_text(x + bw / 2, bot - bh - px(7), text=val + self.unit, fill=C["secondary"], font=F["caption"])
            self.create_text(x + bw / 2, h - px(8), text=lab, fill=C["secondary"], font=F["caption"])
        self.create_line(px(4), bot, w - px(4), bot, fill=C["sep"])


class Banner(tk.Frame):
    """A prominent notice (e.g. the Terms-of-Service warning). Text wraps with the window."""

    def __init__(self, parent, text: str, kind: str = "orange", title: str = ""):
        bg = bg_of(parent)
        c = C[kind]
        tint = mix(bg, c, 0.2 if DARK_MODE else 0.12)
        super().__init__(parent, bg=tint, highlightthickness=1, highlightbackground=mix(tint, c, 0.5))
        inner = tk.Frame(self, bg=tint)
        inner.pack(fill="x", padx=px(14), pady=px(7))
        if title:
            tk.Label(inner, text=title, bg=tint, fg=c, font=F["body_semi"], anchor="w").pack(fill="x")
        self.label = tk.Label(inner, text=text, bg=tint, fg=C["label"], font=F["footnote"], anchor="w", justify="left")
        self.label.pack(fill="x")
        self.bind("<Configure>", lambda e=None: e is not None and self.label.configure(wraplength=max(200, e.width - px(40))))


def wrapped_label(parent, text: str = "", secondary: bool = True, font: str = "footnote", **kw) -> tk.Label:
    """Label whose wrap width follows its parent, so text never runs off a narrow window."""
    lb = tk.Label(parent, text=text, bg=bg_of(parent), fg=C["secondary"] if secondary else C["label"],
                  font=F[font], anchor="w", justify="left", **kw)
    lb.bind("<Configure>", lambda e=None: e is not None and lb.configure(wraplength=max(120, e.width - 4)))
    return lb


def metric_card(parent, caption: str, value: str = "-", note: str = ""):
    """Card with a small caption, a big number and a grey note. Returns (card, value label, note label)."""
    card = Card(parent, pad=10)
    tk.Label(card.body, text=caption.upper(), bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w").pack(fill="x")
    v = tk.Label(card.body, text=value, bg=C["card"], fg=C["label"], font=F["metric"], anchor="w")
    v.pack(fill="x")
    n = tk.Label(card.body, text=note, bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w", justify="left")
    n.pack(fill="x")
    n.bind("<Configure>", lambda e=None: e is not None and n.configure(wraplength=max(100, e.width - 4)))
    return card, v, n
