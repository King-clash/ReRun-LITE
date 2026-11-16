"""More everyday conveniences: a one-click Start / Stop in the top bar, today's palace on Auto Crest, a sound for
alerts, the emulator you picked remembered, and shortcuts for starting and stopping."""
from __future__ import annotations

import os
import sys
import tkinter as tk

from rerun import errlog, ios
from rerun.ios import C, F, px

from . import palaces
from .theme import Tip


class ExtrasMixin:
    # ================================================================ set-up
    def _build_extras(self):
        nb = self.nb
        nb.action.bind("<Button-1>", lambda e: self._toggle_run())
        Tip(nb.action, lambda: f"Stop everything   {self._key_hint('stop')}" if self._busy_any()
            else f"Start Crest on the selected emulator   {self._key_hint('start')}")
        self._sound = bool(self._ui_state().get("sound_alerts", False))
        self._sound_var = tk.BooleanVar(value=self._sound)
        if self._maybe_sound not in self.m.listeners:          # the window can be built again (a new look): listen once
            self.m.listeners.append(self._maybe_sound)
        self._saved_emulator = None
        self._last_today = None
        self._refresh_action()
        self._tidy_general()

    # ================================================================ Settings > General
    def _tidy_general(self):
        """The original General page opens with a Theme row (Automatic / Light / Dark, saved in config.yaml). LITE has a
        whole Appearance page, so that row is hidden and the explanation under it says where to go."""
        row = self.appearance.master.master
        body = row.master
        kids = body.winfo_children()
        i = kids.index(row)
        row.pack_forget()
        if i + 1 < len(kids):                       # the divider under it
            kids[i + 1].pack_forget()
        group = body.master
        while group is not None and not isinstance(group, ios.Group):
            group = group.master
        if group is not None and group.footer is not None:
            group.footer.configure(text="Colours, accent, density and the background are in Settings > Appearance.")

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
