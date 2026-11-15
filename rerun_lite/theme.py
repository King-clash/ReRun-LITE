"""ReRun LITE's look: a calmer, higher-contrast palette, outlined cards, a brand top bar and a grouped side list.

Everything here changes the ios widget kit only inside the LITE process (at run time); rerun/ios.py on disk
stays as it was copied from ReRun, so a fix brought over from ReRun still applies cleanly.
"""
from __future__ import annotations

import tkinter as tk

from rerun import ios
from rerun.ios import C, F, px

GOLD = "#E3B15C"          # the "LITE" mark
GOLD_TEXT = "#1B1405"

# Deep blue-black surfaces, one indigo accent, soft semantic colours. Same keys as ios.LIGHT / ios.DARK.
DARK = {
    "bg": "#0B0E14", "card": "#131824", "sep": "#232B3C", "label": "#F2F4F8",
    "secondary": "#8E97AA", "tertiary": "#4A5267", "blue": "#7381FF", "green": "#34D399",
    "red": "#F87171", "orange": "#FBBF24", "gray": "#8E97AA", "fill": "#1F2638",
    "field": "#1A2030", "bar": "#0E121B", "tab_off": "#7A8499", "viewer": "#070A0F",
    "alert": "#1A2030", "menu": "#1A2030",
}
LIGHT = {
    "bg": "#F4F5F9", "card": "#FFFFFF", "sep": "#E3E6EE", "label": "#12151C",
    "secondary": "#6B7385", "tertiary": "#B4BACA", "blue": "#4A5BE0", "green": "#16A34A",
    "red": "#DC2626", "orange": "#D97706", "gray": "#8A93A6", "fill": "#E8EAF1",
    "field": "#EEF0F6", "bar": "#FFFFFF", "tab_off": "#7A8499", "viewer": "#E4E7EF",
    "alert": "#FFFFFF", "menu": "#FFFFFF",
}

_applied = False


def apply_palette() -> None:
    """Before ios.init: the kit builds its colours from these two tables."""
    ios.DARK.update(DARK)
    ios.LIGHT.update(LIGHT)


def apply_look() -> None:
    """After ios.init: outlined cards. Safe to call twice."""
    global _applied
    F["page"] = (F["large"][0], 18, "bold")      # ios.init rebuilds F for every window, so set it every time
    if _applied:
        return
    _applied = True

    def layout(self, e):
        self._cv.delete("all")
        border = C["sep"]
        ios.rounded_rect(self._cv, 0, 0, e.width, e.height, self._r, border, self._bg)
        ios.rounded_rect(self._cv, 1, 1, e.width - 1, e.height - 1, max(self._r - 1, 2), self.color, border)

    ios.Card._layout = layout

    # The tab bar already names the page, so the page title is smaller and leaves the room to the content.
    def page_header(parent, title: str) -> tk.Frame:
        bg = ios.bg_of(parent)
        f = tk.Frame(parent, bg=bg)
        f.pack(fill="x", padx=px(20), pady=(px(12), px(8)))
        tk.Label(f, text=title, bg=bg, fg=C["label"], font=F["page"]).pack(side="left")
        right = tk.Frame(f, bg=bg)
        right.pack(side="right")
        return right

    ios.page_header = page_header


# ==================================================================== widgets
class LiteTabs(ios.TabView):
    """Brand bar across the top (name, LITE mark, version, the five tabs), the page below, a thin status line at
    the bottom. Same interface as the original tab bar: .content, .status, .add, .select, .index, .count.
    `alias` lets a page the original reaches as a tab (Discord) open the right Settings section; `on_select`
    tells the window which tab came to the front."""

    def __init__(self, parent, version: str = ""):
        tk.Frame.__init__(self, parent, bg=C["bg"])
        self.alias: dict = {}
        self.on_select = None
        bar = C["bar"]
        top = tk.Frame(self, bg=bar)
        top.pack(fill="x")
        row = tk.Frame(top, bg=bar)
        row.pack(fill="x", padx=px(20))
        mark = tk.Frame(row, bg=bar)
        mark.pack(side="left", pady=px(8))
        tk.Label(mark, text="ReRun", bg=bar, fg=C["label"], font=F["title"]).pack(side="left")
        tk.Label(mark, text="LITE", bg=GOLD, fg=GOLD_TEXT, font=F["caption"][:2] + ("bold",),
                 padx=px(6), pady=px(1)).pack(side="left", padx=(px(8), 0))
        if version:
            tk.Label(mark, text=version, bg=bar, fg=C["secondary"], font=F["footnote"]).pack(side="left", padx=(px(8), 0))
        self._items = tk.Frame(row, bg=bar)
        self._items.pack(side="left", padx=(px(34), 0))
        right = tk.Frame(row, bg=bar)
        right.pack(side="right")
        self.pin = tk.Label(right, text="", bg=bar, fg=C["tab_off"], font=F["footnote_semi"], cursor="hand2",
                            padx=px(8), pady=px(3))
        self.pin.pack(side="right", padx=(px(8), 0))
        self.chip = tk.Label(right, text="", bg=bar, fg=C["secondary"], font=F["footnote_semi"], cursor="hand2",
                             padx=px(10), pady=px(3))
        self.chip.pack(side="right")
        self._badges: list[tk.Label] = []
        tk.Frame(self, height=1, bg=C["sep"]).pack(fill="x")
        foot = tk.Frame(self, bg=bar)
        foot.pack(side="bottom", fill="x")
        tk.Frame(self, height=1, bg=C["sep"]).pack(side="bottom", fill="x")
        self.status = tk.Label(foot, text="", bg=bar, fg=C["secondary"], font=F["footnote"])
        self.status.pack(pady=px(4))
        self.content = tk.Frame(self, bg=C["bg"])
        self.content.pack(fill="both", expand=True)
        self._pages: list[tk.Frame] = []
        self._tabs: list[tuple[tk.Label, tk.Label]] = []
        self._lines: list[tk.Frame] = []
        self._index: int | None = None
        self._hover: int | None = None

    def add(self, page: tk.Frame, text: str, icon: str, first: bool = False):
        i = len(self._pages)
        self._pages.append(page)
        bar = C["bar"]
        cell = tk.Frame(self._items, bg=bar, cursor="hand2")
        cell.pack(side="left", padx=px(2))
        line = tk.Frame(cell, height=px(2), bg=bar)
        line.pack(side="bottom", fill="x")
        inner = tk.Frame(cell, bg=bar, cursor="hand2")
        inner.pack(padx=px(13), pady=(px(12), px(10)))
        ic = tk.Label(inner, text=ios.icon_text(icon) or "●", bg=bar, cursor="hand2",
                      font=F["icon"] if ios.ICON_FONT else F["body"])
        ic.pack(side="left", padx=(0, px(7)))
        lb = tk.Label(inner, text=text, bg=bar, cursor="hand2", font=F["body_semi"])
        lb.pack(side="left")
        badge = tk.Label(inner, text="", bg=bar, fg=C["bar"], font=F["caption"][:2] + ("bold",), padx=px(5))
        self._badges.append(badge)               # shown (packed) only while it has something to say
        for w in (cell, inner, ic, lb, badge):
            w.bind("<Button-1>", lambda e, i=i: self.select(i))
            w.bind("<Enter>", lambda e, i=i: self._set_hover(i))
            w.bind("<Leave>", lambda e: self._set_hover(None))
        self._tabs.append((ic, lb))
        self._lines.append(line)
        if self._index is None:
            self.select(0)
        else:
            self._paint()

    def set_badge(self, i: int, text: str | None, kind: str = "blue") -> None:
        """A small pill after a tab's name (a count, a tick, a dot). `text=None` hides it."""
        b = self._badges[i]
        if not text:
            b.pack_forget()
            return
        b.configure(text=text, bg=C[kind], fg=GOLD_TEXT if kind in ("orange", "green") else "#FFFFFF")
        if not b.winfo_manager():
            b.pack(side="left", padx=(px(7), 0))

    def set_chip(self, text: str, kind: str = "gray", dot: bool = True) -> None:
        """The live status at the right of the top bar: a coloured dot and a short sentence."""
        c = C[kind]
        self.chip.configure(text=("●  " if dot else "") + text, fg=c, bg=ios.mix(C["bar"], c, 0.16))

    def set_pin(self, on: bool) -> None:
        self.pin.configure(text=("Pinned" if on else "Pin"), fg=C["blue"] if on else C["tab_off"],
                           bg=ios.mix(C["bar"], C["blue"], 0.16) if on else C["bar"])

    def _set_hover(self, i):
        self._hover = i
        self._paint()

    def select(self, i):
        if i in self.alias:
            tab, show = self.alias[i]
            super().select(tab)
            show()
            i = tab
        else:
            super().select(i)
        if self.on_select is not None:
            self.on_select(i)

    def _paint(self):
        for j, ((ic, lb), line) in enumerate(zip(self._tabs, self._lines)):
            on = j == self._index
            fg = C["label"] if on else (C["label"] if j == self._hover else C["tab_off"])
            ic.configure(fg=C["blue"] if on else fg)
            lb.configure(fg=fg)
            line.configure(bg=C["blue"] if on else C["bar"])


class GroupedNav(ios.SideNav):
    """The original side list with small captions above groups of entries. `groups` is {key: caption}: the
    caption is drawn above that entry."""

    def __init__(self, parent, items, command, groups: dict, **kw):
        super().__init__(parent, items, command, **kw)
        for key, caption in groups.items():
            tk.Label(self, text=caption.upper(), bg=self._bg, fg=C["secondary"], font=F["caption"],
                     anchor="w").pack(fill="x", padx=px(18), pady=(px(12), px(2)), before=self._rows[key][0])


class Tip:
    """A small hover label (e.g. "Dailies  Ctrl+2"). Appears after half a second, goes away on leave or click."""

    def __init__(self, widget: tk.Widget, text):
        self.w, self.text, self.tw, self._job = widget, text, None, None
        widget.bind("<Enter>", self._arm, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _arm(self, e=None):
        self._hide()
        self._job = self.w.after(500, self._show)

    def _show(self):
        text = self.text() if callable(self.text) else self.text
        if not text or not self.w.winfo_exists():
            return
        self.tw = tw = tk.Toplevel(self.w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{self.w.winfo_rootx() + px(4)}+{self.w.winfo_rooty() + self.w.winfo_height() + px(6)}")
        tk.Label(tw, text=text, bg=C["menu"], fg=C["label"], font=F["footnote"], padx=px(8), pady=px(4),
                 justify="left", highlightthickness=1, highlightbackground=C["sep"]).pack()

    def _hide(self, e=None):
        if self._job:
            self.w.after_cancel(self._job)
            self._job = None
        if self.tw is not None:
            self.tw.destroy()
            self.tw = None


class Notice(tk.Frame):
    """A tinted one-line notice with a button on the right (the Auto Crest "needs setup" strip). Text wraps."""

    def __init__(self, parent, kind: str = "orange"):
        bg = ios.bg_of(parent)
        c = C[kind]
        tint = ios.mix(bg, c, 0.2 if ios.DARK_MODE else 0.12)
        super().__init__(parent, bg=tint, highlightthickness=1, highlightbackground=ios.mix(tint, c, 0.5))
        inner = tk.Frame(self, bg=tint)
        inner.pack(fill="x", padx=px(14), pady=px(7))
        self.button_host = tk.Frame(inner, bg=tint)
        self.button_host.pack(side="right", padx=(px(10), 0))
        self.label = tk.Label(inner, text="", bg=tint, fg=C["label"], font=F["footnote"], anchor="w", justify="left")
        self.label.pack(side="left", fill="x", expand=True)
        self.bind("<Configure>", lambda e: self.label.configure(wraplength=max(200, e.width - px(190))))
        self._btn = None

    def show(self, text: str, button: str, command) -> None:
        self.label.configure(text=text)
        if self._btn is not None:
            self._btn.destroy()
        self._btn = ios.Button(self.button_host, button, command, kind="tinted", small=True)
        self._btn.pack()
