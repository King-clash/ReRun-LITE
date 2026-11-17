"""Settings > Log, as an activity feed: every line has a category (Information, Automation, Warning, Error, Recovery,
System), you can filter by category, emulator, level and words, fold long entries (a traceback) and open them with a
double-click, stop the view following new lines, and copy what you see or a diagnostic summary.

It replaces only how the Log page is built and filled; the lines themselves still come from the Manager's log (and the
same lines still go to rerun.log), so nothing is lost by hiding or folding them here."""
from __future__ import annotations

from rerun.gui_common import *  # noqa: F401,F403 - the names the original log page uses

from .feedcat import CATEGORIES, collapsed

ALL_CATEGORIES = "All categories"
CAT_COLORS = {"Recovery": "blue", "System": "secondary"}       # Warning and Error keep the level colours
MAX_LINES = 5000


class FeedMixin:

    # ================================================================ building the page
    def _build_log(self):
        _, page, hdr = self._page("Log", "Log", "list")
        ios.Button(hdr, "Save Log…", self._save_log, kind="tinted", icon="save").pack(side="right")
        ios.Button(hdr, "Clear", self._clear_log, kind="tinted", color="red",
                   icon="delete").pack(side="right", padx=(0, px(8)))
        ios.Button(hdr, "Copy", self._copy_log, kind="tinted").pack(side="right", padx=(0, px(8)))
        ios.Button(hdr, "Copy diagnostics", self._copy_diagnostics, kind="tinted").pack(side="right", padx=(0, px(8)))

        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", padx=px(20), pady=(0, px(6)))
        self.log_level = tk.StringVar(value="All")
        ios.Segmented(bar, list(LOG_LEVELS), self.log_level, command=self._rebuild_log).pack(side="left")
        self.log_cat = ios.Select(bar, values=[ALL_CATEGORIES, *CATEGORIES], accent=True, command=self._rebuild_log)
        self.log_cat.set(ALL_CATEGORIES)
        self.log_cat.pack(side="left", padx=px(12))
        self.log_inst = ios.Select(bar, values=[ALL_INSTANCES], accent=True, command=self._rebuild_log)
        self.log_inst.set(ALL_INSTANCES)
        self.log_inst.pack(side="left")
        self.log_search = tk.StringVar()
        fld = ios.Field(bar, self.log_search, width=24)
        fld.pack(side="right")
        self._label(bar, "Search").pack(side="right", padx=(0, px(8)))
        fld.entry.bind("<KeyRelease>", lambda e: self._debounce_log())

        bar2 = tk.Frame(page, bg=C["bg"])
        bar2.pack(fill="x", padx=px(20), pady=(0, px(8)))
        self._feed_follow = tk.BooleanVar(value=True)
        ios.Switch(bar2, self._feed_follow, command=self._feed_follow_changed).pack(side="left")
        self._label(bar2, "Follow new lines (turn off to read in peace)").pack(side="left", padx=(px(8), 0))
        self._feed_count = self._label(bar2, "")
        self._feed_count.pack(side="right")

        _, self.log_box = ios.text_box(page, mono=True, wrap="none", padx=px(20), pady=(0, px(14)))
        self.log_box.tag_configure("warn", foreground=C["orange"])
        self.log_box.tag_configure("error", foreground=C["red"])
        for cat, color in CAT_COLORS.items():
            self.log_box.tag_configure(f"cat_{cat}", foreground=C.get(color, C["label"]))
        self.log_box.configure(state="disabled")
        self.log_box.bind("<Double-Button-1>", self._feed_toggle_at)
        self._log_after = None
        self._log_hidden_before = 0       # entries removed by Clear
        self._feed_open: set[int] = set()  # ids of the folded entries the user has opened

    # ================================================================ one entry as text
    def _feed_text(self, e: dict) -> tuple[str, tuple]:
        """(text, tags) for one entry: long ones are folded to their first line until opened."""
        first, more = collapsed(e["line"])
        tags: list[str] = []
        if e["level"] != "info":
            tags.append(e["level"])
        elif e.get("category") in CAT_COLORS:
            tags.append(f"cat_{e['category']}")
        if more:
            tags.append(f"e{id(e)}")
            text = e["line"] if id(e) in self._feed_open else f"{first}    [+{more} lines: double-click to open]"
        else:
            text = e["line"]
        return text, tuple(tags)

    def _feed_toggle_at(self, event):
        box = self.log_box
        try:
            idx = box.index(f"@{event.x},{event.y}")
            for tag in box.tag_names(idx):
                if tag.startswith("e") and tag[1:].isdigit():
                    key = int(tag[1:])
                    self._feed_open ^= {key}
                    self._rebuild_log()
                    return "break"
        except tk.TclError as e:
            errlog.note("lite.feed_toggle", e)
        return None

    # ================================================================ filtering
    def _log_match(self, e: dict) -> bool:
        levels = LOG_LEVELS.get(self.log_level.get())
        inst = self.log_inst.get()
        cat = self.log_cat.get()
        q = self.log_search.get().strip().lower()
        return ((levels is None or e["level"] in levels)
                and (cat in ("", ALL_CATEGORIES) or e.get("category", "Information") == cat)
                and (inst in ("", ALL_INSTANCES) or e["instance"] == inst)
                and (not q or q in e["line"].lower()))

    def _debounce_log(self):
        if self._log_after:
            self.after_cancel(self._log_after)
        self._log_after = self.after(250, self._rebuild_log)

    def _feed_follow_changed(self, *_a):
        if self._feed_follow.get():
            self.log_box.see("end")

    def _update_feed_count(self, shown: int | None = None):
        try:
            total = len(self.m.log_entries) - self._log_hidden_before
            if shown is None:
                shown = int(self.log_box.index("end-1c").split(".")[0]) - 1
            self._feed_count.configure(text=f"{shown} shown of {total}")
        except tk.TclError as e:
            errlog.note("lite.feed_count", e)

    # ================================================================ filling the box
    def _rebuild_log(self, *_a):
        self._log_after = None
        entries = self.m.log_entries[self._log_hidden_before:]
        box = self.log_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        shown = 0
        for e in entries:
            if self._log_match(e):
                text, tags = self._feed_text(e)
                box.insert("end", text + "\n", tags)
                shown += 1
        if self._feed_follow.get():
            box.see("end")
        box.configure(state="disabled")
        self._update_feed_count(shown)

    def _append_log(self, e: dict):
        if not self._log_match(e):
            return
        box = self.log_box
        at_end = box.yview()[1] >= 0.999
        box.configure(state="normal")
        text, tags = self._feed_text(e)
        box.insert("end", text + "\n", tags)
        if int(box.index("end-1c").split(".")[0]) > MAX_LINES:
            box.delete("1.0", "1000.0")
        if at_end and self._feed_follow.get():
            box.see("end")  # don't yank the view while you're reading older lines
        box.configure(state="disabled")
        self._update_feed_count()

    def _clear_log(self):
        self._log_hidden_before = len(self.m.log_entries)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._update_feed_count(0)

    # ================================================================ saving and copying
    def _save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt")
        if path:
            Path(path).write_text("\n".join(self.m.log_lines), encoding="utf-8")
            self.flash("Log saved", "ok")

    def _visible_lines(self) -> list[str]:
        """The lines that match the filters, each in full (folded entries are not cut)."""
        return [e["line"] for e in self.m.log_entries[self._log_hidden_before:] if self._log_match(e)]

    def _copy_log(self):
        lines = self._visible_lines()
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.flash(f"Copied {len(lines)} line(s)", "ok")

    def _copy_diagnostics(self):
        """A status summary plus the last lines of the log: what to paste when asking for help."""
        tail = [e["line"] for e in self.m.log_entries[-60:]]
        text = self.status_summary() + "\n\nLast log lines:\n" + "\n".join(tail)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.flash("Copied a status summary and the last log lines", "ok")
