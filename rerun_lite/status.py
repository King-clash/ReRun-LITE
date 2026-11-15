"""Everyday conveniences around the pages: the live status chip, tab badges, the Auto Crest "needs setup" notice,
keyboard shortcuts, pin-on-top, and a small "Window & files" group on Settings > General."""
from __future__ import annotations

import os
import tkinter as tk

from rerun import errlog, ios
from rerun.ios import px

from . import MAIN_SCRIPT, readiness
from .theme import Notice, Tip

SHORTCUTS = (
    ("Ctrl+1 ... Ctrl+5", "Auto Crest, Dailies, History, Templates, Settings"),
    ("Ctrl+Tab / Ctrl+Shift+Tab", "Next / previous tab"),
    ("Ctrl+,", "Settings"),
    ("Ctrl+T", "Keep the window on top (Pin)"),
    ("F1", "This list"),
    ("F11", "Pause or resume everything (works in the game too)"),
    ("F12", "Stop everything (works in the game too)"),
)
TAB_NAMES = ("Auto Crest", "Dailies", "History", "Templates", "Settings")
FIX_BUTTON = {"emulator": "Show", "templates": "Open Templates", "settings": "Crest Settings"}


class StatusMixin:
    # ================================================================ set-up
    def _build_status(self):
        """After the pages exist: tooltips, shortcuts, the chip, the notice, the extra Settings group."""
        nb = self.nb
        for i, name in enumerate(TAB_NAMES[: nb.count()]):
            for w in nb._tabs[i] + (nb._badges[i],):
                Tip(w, f"{name}   Ctrl+{i + 1}")
        nb.chip.bind("<Button-1>", lambda e: self._chip_clicked())
        Tip(nb.chip, lambda: self._chip_tip)
        nb.pin.bind("<Button-1>", lambda e: self._toggle_pin())
        Tip(nb.pin, "Keep this window above other windows   Ctrl+T")
        self._chip_tip = "Click to open Auto Crest"
        for n in range(1, 6):
            self.bind_all(f"<Control-Key-{n}>", lambda e, n=n: self._go_tab(n - 1))
        self.bind_all("<Control-comma>", lambda e: self._go_tab(self._tab_settings))
        self.bind_all("<Control-Tab>", lambda e: self._cycle_tab(1))
        self.bind_all("<Control-Shift-Tab>", lambda e: self._cycle_tab(-1))
        self.bind_all("<Control-ISO_Left_Tab>", lambda e: self._cycle_tab(-1))
        self.bind_all("<Control-t>", lambda e: self._toggle_pin())
        self.bind_all("<F1>", lambda e: self.show_shortcuts())
        self._extend_general()
        self._problems: list[readiness.Problem] = []
        self._status_sig = None
        self._title_suffix = ""

    def _go_tab(self, i: int):
        if 0 <= i < self.nb.count():
            self.nb.select(i)
        return "break"

    def _cycle_tab(self, d: int):
        self.nb.select((self.nb.index() + d) % self.nb.count())
        return "break"

    def show_shortcuts(self):
        width = max(len(k) for k, _ in SHORTCUTS)
        ios.alert(self, "\n".join(f"{k.ljust(width)}   {v}" for k, v in SHORTCUTS), "Keyboard shortcuts")

    # ================================================================ pin on top
    def _toggle_pin(self):
        self._apply_pin(not bool(self._pin_var.get()))
        return "break"

    def _apply_pin(self, on: bool):
        self._pin_var.set(on)
        try:
            self.attributes("-topmost", bool(on))
        except tk.TclError as e:
            errlog.note("lite.pin", e)
        self.nb.set_pin(bool(on))

    # ================================================================ Settings > General: Window & files
    def _extend_general(self):
        w = self.appearance
        while w is not None and not isinstance(w, ios.Group):
            w = w.master
        if w is None:
            return
        g = ios.Group(w.master, header="Window & files",
                      footer="Pin keeps the window above the game while you watch Crest. It is remembered.")
        g.pack(fill="x", pady=(0, px(24)), after=w)
        ios.Switch(g.row("Keep this window on top", "Same as the Pin button at the top right (Ctrl+T)."),
                   self._pin_var, command=lambda: self._apply_pin(bool(self._pin_var.get()))).pack()
        ios.Button(g.row("Open the data folder", "Where settings, history and crest pictures are kept."),
                   "Open", self._open_data_folder, kind="tinted", small=True).pack()
        ios.Button(g.row("Keyboard shortcuts", "Switch tabs, pin the window and more."),
                   "Show", self.show_shortcuts, kind="tinted", small=True).pack()

    def _open_data_folder(self):
        try:
            os.startfile(str(self.m.root))          # noqa: S606 - the user's own folder
        except OSError as e:
            self.flash(f"Could not open the folder: {e}", "warn")

    # ================================================================ live status
    def _chip_clicked(self):
        if self._problems and not readiness.running(self.m)[0]:
            self._fix(self._problems[0].fix)
        else:
            self.nb.select(self._tab_crest)

    def _fix(self, where: str):
        if where == "templates":
            self.nb.select(self._tab_templates)
        elif where == "settings":
            self.open_script_settings(MAIN_SCRIPT)
        else:
            self.nb.select(self._tab_crest)

    def _refresh_status(self):
        """The chip, badges, notice and window title. Cheap enough to run every second; the file checks inside it
        (templates, settings) only every fifth time."""
        n = getattr(self, "_status_n", 0)
        self._status_n = n + 1
        if n % 5 == 0 or self._status_sig is None:
            try:
                self._problems = readiness.crest_problems(self.m, self.selected())
                self._left = readiness.dailies_left(self.ops)
            except Exception as e:  # noqa: BLE001 - a status line must never break the window
                errlog.note("lite.readiness", e)
                self._problems, self._left = [], None
        run, paused = readiness.running(self.m)
        errored = [k for k, i in self.m.instances.items() if i.status == "error"]
        if run:
            who = run[0] if len(run) == 1 else f"{len(run)} emulators"
            chip = (f"Crest running on {who}" if len(run) == 1 else f"Running on {who}", "green")
        elif paused:
            chip = ("Paused", "orange")
        elif errored:
            chip = (f"Error on {errored[0]}", "red")
        elif self._problems:
            chip = ("Needs setup", "orange")
        else:
            chip = ("Ready", "gray")
        left = self._left
        sig = (chip, bool(run), bool(paused), tuple(self._problems), left)
        if sig == self._status_sig:
            return
        self._status_sig = sig
        self.nb.set_chip(*chip)
        self._chip_tip = ("Click to fix: " + self._problems[0].text) if self._problems and not run \
            else "Click to open Auto Crest"
        fixes = {p.fix for p in self._problems}
        self.nb.set_badge(self._tab_crest, "●" if run else ("II" if paused else ("!" if self._problems else None)),
                          "green" if run else "orange")
        self.nb.set_badge(self._tab_dailies, None if left is None else (str(left) if left else "✓"),
                          "blue" if left else "green")
        self.nb.set_badge(self._tab_templates, "!" if "templates" in fixes else None, "orange")
        self.nb.set_badge(self._tab_settings, "!" if "settings" in fixes else None, "orange")
        if self._problems:
            p = self._problems[0]
            self._ready_notice.show(p.text, FIX_BUTTON[p.fix], lambda: self._fix(p.fix))
            if not self._ready_notice.winfo_manager():
                self._ready_notice.pack(fill="x", padx=px(20), pady=(0, px(8)), after=self._tos_banner)
        elif self._ready_notice.winfo_manager():
            self._ready_notice.pack_forget()
        cur = self.title()
        if self._title_suffix and cur.endswith(self._title_suffix):
            cur = cur[: -len(self._title_suffix)]
        self._title_suffix = f"  ·  {chip[0]}" if (run or paused or errored) else ""
        self.title(cur + self._title_suffix)

    def _make_ready_notice(self, page, after):
        """The Auto Crest "needs setup" strip, created hidden (packed by _refresh_status when there is something to fix)."""
        self._tos_banner = after
        self._ready_notice = Notice(page, "orange")


__all__ = ["StatusMixin"]
