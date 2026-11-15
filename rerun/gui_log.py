"""Log tab.

Moved verbatim from rerun/gui.py (class App); App inherits LogMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class LogMixin:

    # ================================================================ log
    def _build_log(self):
        _, page, hdr = self._page("Log", "Log", "list")
        ios.Button(hdr, "Save Log…", self._save_log, kind="tinted", icon="save").pack(side="right")
        ios.Button(hdr, "Clear", self._clear_log, kind="tinted", color="red",
                   icon="delete").pack(side="right", padx=(0, px(8)))
        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", padx=px(20), pady=(0, px(10)))
        self.log_level = tk.StringVar(value="All")
        ios.Segmented(bar, list(LOG_LEVELS), self.log_level, command=self._rebuild_log).pack(side="left")
        self.log_inst = ios.Select(bar, values=[ALL_INSTANCES], accent=True, command=self._rebuild_log)
        self.log_inst.set(ALL_INSTANCES)
        self.log_inst.pack(side="left", padx=px(16))
        self.log_search = tk.StringVar()
        fld = ios.Field(bar, self.log_search, width=28)
        fld.pack(side="right")
        self._label(bar, "Search").pack(side="right", padx=(0, px(8)))
        fld.entry.bind("<KeyRelease>", lambda e: self._debounce_log())
        _, self.log_box = ios.text_box(page, mono=True, wrap="none", padx=px(20), pady=(0, px(14)))
        self.log_box.tag_configure("warn", foreground=C["orange"])
        self.log_box.tag_configure("error", foreground=C["red"])
        self.log_box.configure(state="disabled")
        self._log_after = None
        self._log_hidden_before = 0  # entries removed by Clear

    def _backfill_log(self):
        """Show lines logged before the window existed (start-up warnings, config problems...).
        Later lines arrive as events, so only the first `_log_backfill` entries are added here."""
        for e in self.m.log_entries[:getattr(self, "_log_backfill", 0)]:
            self._append_log(e)

    def _log_match(self, e: dict) -> bool:
        levels = LOG_LEVELS.get(self.log_level.get())
        inst = self.log_inst.get()
        q = self.log_search.get().strip().lower()
        return ((levels is None or e["level"] in levels)
                and (inst in ("", ALL_INSTANCES) or e["instance"] == inst)
                and (not q or q in e["line"].lower()))

    def _debounce_log(self):
        if self._log_after:
            self.after_cancel(self._log_after)
        self._log_after = self.after(250, self._rebuild_log)

    def _rebuild_log(self):
        self._log_after = None
        entries = self.m.log_entries[self._log_hidden_before:]
        box = self.log_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        for e in entries:
            if self._log_match(e):
                box.insert("end", e["line"] + "\n", (e["level"],) if e["level"] != "info" else ())
        box.see("end")
        box.configure(state="disabled")

    def _append_log(self, e: dict):
        if not self._log_match(e):
            return
        box = self.log_box
        at_end = box.yview()[1] >= 0.999
        box.configure(state="normal")
        box.insert("end", e["line"] + "\n", (e["level"],) if e["level"] != "info" else ())
        if int(box.index("end-1c").split(".")[0]) > 5000:
            box.delete("1.0", "1000.0")
        if at_end:
            box.see("end")  # don't yank the view while you're reading older lines
        box.configure(state="disabled")

    def _clear_log(self):
        self._log_hidden_before = len(self.m.log_entries)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt")
        if path:
            Path(path).write_text("\n".join(self.m.log_lines), encoding="utf-8")
            self.flash("Log saved", "ok")
