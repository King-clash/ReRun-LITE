"""LiteApp's window memory: data/lite/ui.json (not config.yaml, so a full ReRun sharing the folder keeps its own)."""
from __future__ import annotations

import json
import tkinter as tk

from rerun import errlog


class UiStateMixin:
    def _ui_state(self) -> dict:
        try:
            d = json.loads(self._ui_path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _restore_tab(self):
        try:
            tab = int(self._ui_state().get("tab") or 0)
            if 0 < tab < self.nb.count():
                self.nb.select(tab)
            section = self._ui_state().get("section")            # the Settings entry that was open
            if section in dict(self._set_nav._items):
                self._set_nav.select(section)
        except (tk.TclError, TypeError, ValueError) as e:
            errlog.note("lite.restore_tab", e)

    def _save_ui_state(self):
        """Window position/size and open tab, in data/lite/ui.json - not in config.yaml, so a full ReRun
        sharing the folder keeps its own."""
        try:
            ui = self._ui_state()
            if self.state() == "normal":
                ui["geometry"] = self.winfo_geometry()
            ui["tab"] = int(self.nb.index() or 0)
            ui["section"] = self._set_nav.current
            ui["pinned"] = bool(self._pin_var.get())
            self._ui_path.write_text(json.dumps(ui, indent=1), encoding="utf-8")
        except (tk.TclError, OSError) as e:
            errlog.note("lite.save_ui_state", e)


