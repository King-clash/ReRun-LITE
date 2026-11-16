"""More everyday conveniences: a one-click Start / Stop in the top bar, today's palace on Auto Crest, a sound for
alerts, the emulator you picked remembered, and shortcuts for starting and stopping."""
from __future__ import annotations

import os
import sys
import tkinter as tk

from rerun import errlog, ios
from rerun.ios import C, F, px

from . import palaces, restart, theme
from .theme import Tip


class ExtrasMixin:
    # ================================================================ set-up
    def _build_extras(self):
        nb = self.nb
        nb.action.bind("<Button-1>", lambda e: self._toggle_run())
        Tip(nb.action, lambda: "Stop everything   Ctrl+." if self._busy_any()
            else "Start Crest on the selected emulator   Ctrl+Enter")
        self.bind_all("<Control-Return>", lambda e: self._toggle_run())
        self.bind_all("<Control-period>", lambda e: self._stop_run())
        self._sound = bool(self._ui_state().get("sound_alerts", False))
        self._sound_var = tk.BooleanVar(value=self._sound)
        self.m.listeners.append(self._maybe_sound)
        self._saved_emulator = None
        self._last_today = None
        self._refresh_action()
        self._build_theme_select()

    # ================================================================ theme (Settings > General > Theme)
    def _build_theme_select(self):
        """The original Theme row lists Automatic / Light / Dark and saves to config.yaml. LITE lists Ahri, Dark, Light and
        Automatic and keeps its choice in its own file (data/lite/ui.json), so a full ReRun sharing the folder is unaffected."""
        self.appearance["values"] = list(theme.THEMES.values())
        self.appearance.set(theme.THEMES.get(self._theme, theme.THEMES[theme.DEFAULT_THEME]))
        self.appearance._cmd = self._set_theme

    def _set_theme(self):
        key = next((k for k, v in theme.THEMES.items() if v == self.appearance.get()), theme.DEFAULT_THEME)
        if key == self._theme:
            return
        self._bg_save(theme=key)
        self._theme = key
        if ios.confirm(self, f"ReRun LITE restarts to change the theme to {theme.THEMES[key]}. Restart now?", "Theme",
                       ok="Restart"):
            self._restart()
        else:
            self.flash("Theme saved. It applies the next time ReRun LITE opens.", "ok")

    def _restart(self):
        try:
            restart.relaunch(self.m.root)
        except OSError as e:
            self.flash(f"Could not restart: {e}", "warn")
            return
        self.quit_app()

    def _make_today_line(self, page, after):
        """One quiet line under the warning: which palace the selector picked for today."""
        self._today_line = tk.Label(page, text="", bg=C["bg"], fg=C["secondary"], font=F["footnote"], anchor="w")
        self._today_after = after

    # ================================================================ start / stop
    def _busy_any(self) -> bool:
        return any(i.status in ("running", "paused", "starting") for i in self.m.instances.values())

    def _toggle_run(self):
        if self._busy_any():
            self._stop_run()
        else:
            if not self.selected() and self.m.instances:
                self.inst_list.sel = next(iter(self.m.instances))
                self.refresh_instances()
            self.nb.select(self._tab_crest)
            self.start_sel()
        return "break"

    def _stop_run(self):
        if self._busy_any():
            self.stop_all_clicked()
        return "break"

    def _refresh_action(self):
        busy = self._busy_any()
        self.nb.set_action("Stop" if busy else "Start", "red" if busy else "blue")

    # ================================================================ sound
    def _maybe_sound(self, ev: dict):
        if ev.get("type") == "notify" and self._sound and sys.platform == "win32":
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception as e:  # noqa: BLE001 - a missing sound must never break an alert
                errlog.note("lite.sound", e)

    def _set_sound(self):
        self._sound = bool(self._sound_var.get())
        self._bg_save(sound_alerts=self._sound)
        if self._sound:
            self._maybe_sound({"type": "notify"})

    # ================================================================ called every second from _refresh_status
    def _refresh_extras(self):
        self._refresh_action()
        name = self.selected()
        if name and name != self._saved_emulator:                 # remember the emulator you picked
            self._saved_emulator = name
            self._bg_save(emulator=name)
        c = palaces.choose(self.m.root)
        sig = (c.mode, c.day, c.palace.name if c.palace else "", c.ok)
        if sig != self._last_today:
            self._last_today = sig
            if c.mode != "off" and c.palace is not None:
                self._today_line.configure(text=f"Today ({c.day}):  {c.palace.name}" + ("" if c.ok else "   -   picture missing"),
                                           fg=C["secondary"] if c.ok else C["orange"])
                if not self._today_line.winfo_manager():
                    self._today_line.pack(fill="x", padx=px(22), pady=(0, px(6)), after=self._today_after)
            elif self._today_line.winfo_manager():
                self._today_line.pack_forget()

    def _restore_emulator(self):
        name = self._ui_state().get("emulator")
        if name in self.m.instances:
            self.inst_list.sel = name
            self.refresh_instances()
            self._saved_emulator = name

    # ================================================================ files
    def _open_path(self, path):
        try:
            os.startfile(str(path))                                  # noqa: S606 - the user's own folder / file
        except OSError as e:
            self.flash(f"Could not open it: {e}", "warn")
