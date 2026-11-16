"""Settings > Keyboard shortcuts: every action with its key; click a key to change it."""
from __future__ import annotations

import tkinter as tk

from rerun import ios
from rerun.ios import C, F, px

from . import shortcuts as sc


class ShortcutsPageMixin:
    def _build_shortcuts_page(self):
        _, page, hdr = self._page("Keyboard shortcuts", "Settings", "settings", scroll=True)
        ios.Button(hdr, "Reset all", self._sc_reset_all, kind="tinted", small=True).pack(side="right")
        self._sc_wrap = tk.Frame(page, bg=C["bg"])
        self._sc_wrap.pack(fill="x", padx=px(20))
        self._sc_capturing = None
        self._sc_msg = None
        if getattr(self, "_shortcuts", None) is None:
            self._shortcuts = sc.Shortcuts(self._ui_state().get("shortcuts"))
        self._sc_build()

    def _sc_build(self):
        for w in self._sc_wrap.winfo_children():
            w.destroy()
        self._sc_msg = tk.Label(self._sc_wrap, text="Click a key, then press the new combination. Esc cancels, Backspace removes it.",
                                bg=C["bg"], fg=C["secondary"], font=F["footnote"], anchor="w")
        self._sc_msg.pack(fill="x", pady=(px(6), px(4)), padx=px(4))
        for group in ("Go", "Run", "Window"):
            g = ios.Group(self._sc_wrap, header=group)
            g.pack(fill="x", pady=(px(12), 0))
            for a in (x for x in sc.ACTIONS if x.group == group):
                spec = self._shortcuts.get(a.id)
                changed = spec != sc.normalize(a.default)
                right = g.row(a.label, ("Changed from " + sc.describe(a.default)) if changed else None)
                if changed:
                    ios.Button(right, "Reset", lambda i=a.id: self._sc_reset(i), kind="plain", small=True).pack(side="left", padx=(0, px(8)))
                btn = ios.Button(right, sc.describe(spec), lambda i=a.id: self._sc_capture(i), kind="gray", small=True)
                btn.pack(side="left")
                btn.action_id = a.id
        g = ios.Group(self._sc_wrap, header="System-wide",
                      footer="These work even when the game has focus. They are set in config.yaml (hotkeys:).")
        g.pack(fill="x", pady=(px(12), px(24)))
        for line in sc.GLOBAL_HOTKEYS:
            key, text = line.split(" ", 1)
            tk.Label(g.row(text), text=key, bg=C["card"], fg=C["secondary"], font=F["body"]).pack()

    # ------------------------------------------------------------ capturing a key
    def _sc_capture(self, action: str):
        if self._sc_capturing:
            return
        self._sc_capturing = action
        self._sc_say(f"Press the new keys for '{sc.BY_ID[action].label}'…  (Esc cancels, Backspace removes)", C["blue"])
        for seq in getattr(self, "_bound_keys", ()):            # while capturing, the current shortcuts must not fire
            self.unbind_all(seq)
        self.bind("<KeyPress>", self._sc_key, add="+")
        self.focus_force()

    def _sc_key(self, e):
        action = self._sc_capturing
        if not action:
            return
        sym = str(e.keysym)
        if sym in sc.MODIFIER_KEYS:
            return "break"
        self._sc_end()
        if sym == "Escape":
            self._sc_say("Cancelled.", C["secondary"])
            return "break"
        spec = "" if sym in ("BackSpace", "Delete") else sc.from_event(e)
        problem = self._shortcuts.set(action, spec)
        if problem:
            self._sc_say(problem, C["red"])
        else:
            self.save_shortcuts()
            self._sc_build()
            self._sc_say(f"{sc.BY_ID[action].label}: {sc.describe(spec)}", C["green"])
        return "break"

    def _sc_end(self):
        self._sc_capturing = None
        try:
            self.unbind("<KeyPress>")
        except tk.TclError:
            pass
        self._bind_shortcuts()

    def _sc_say(self, text: str, color: str):
        if self._sc_msg is not None and self._sc_msg.winfo_exists():
            self._sc_msg.configure(text=text, fg=color)

    def _sc_reset(self, action: str):
        self._shortcuts.reset(action)
        self.save_shortcuts()
        self._sc_build()

    def _sc_reset_all(self):
        self._shortcuts.reset()
        self.save_shortcuts()
        self._sc_build()
        self._sc_say("All shortcuts are back to their defaults.", C["green"])
