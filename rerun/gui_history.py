"""History tab.

Moved verbatim from rerun/gui.py (class App); App inherits HistoryMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class HistoryMixin:

    # ================================================================ history
    def _build_history(self):
        _, page, hdr = self._page("History", "History", "history")
        ios.Button(hdr, "Clear", self.clear_history, kind="tinted", color="red",
                   icon="delete").pack(side="right")
        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", padx=px(20), pady=(0, px(10)))
        self.hist_kind = tk.StringVar(value="All")
        ios.Segmented(bar, list(HISTORY_KINDS), self.hist_kind,
                      command=self.refresh_history).pack(side="left")
        self.hist_inst = ios.Select(bar, values=[ALL_INSTANCES], accent=True,
                                    command=self.refresh_history)
        self.hist_inst.set(ALL_INSTANCES)
        self.hist_inst.pack(side="left", padx=px(16))
        self.hist_summary = self._label(bar, "")
        self.hist_summary.pack(side="right")

        body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=px(20), pady=(0, px(14)))
        lc = ios.Card(body, pad=6, stretch=True)
        lc.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lc.body, orient="vertical", style="IOS.Vertical.TScrollbar")
        self.hist_tree = ttk.Treeview(lc.body, columns=("time", "inst", "what"), show="",
                                      style="IOS.Treeview", selectmode="browse",
                                      yscrollcommand=sb.set)
        sb.configure(command=self.hist_tree.yview)
        self.hist_tree.column("time", width=px(130), stretch=False)
        self.hist_tree.column("inst", width=px(110), stretch=False)
        self.hist_tree.column("what", width=px(400), stretch=True)
        for tag, col in (("kept", "green"), ("problem", "red"), ("energy", "orange"),
                         ("quiet", "secondary")):
            self.hist_tree.tag_configure(tag, foreground=C[col])
        sb.pack(side="right", fill="y", pady=px(4))
        self.hist_tree.pack(side="left", fill="both", expand=True)
        self.hist_tree.bind("<<TreeviewSelect>>", lambda e: self._on_hist_select())
        self.hist_empty = tk.Label(lc.body, bg=C["card"], fg=C["secondary"], font=F["footnote"],
                                   justify="center", text="Nothing here yet\nCrests, refills and "
                                   "problems appear here as your scripts run.")

        rc = ios.Card(body, pad=10, stretch=True)
        rc.configure(width=px(380))
        rc.pack(side="left", fill="y", padx=(px(16), 0))
        rc.pack_propagate(False)
        self.hist_pic = tk.Label(rc.body, bg=C["card"])
        self.hist_pic.pack(pady=(px(6), px(10)))
        self.hist_text = tk.Label(rc.body, bg=C["card"], fg=C["label"], font=F["footnote"],
                                  justify="left", anchor="nw", wraplength=px(340),
                                  text="Select an entry to see its picture and details.")
        self.hist_text.pack(fill="x")
        self._hist_rows: dict[str, dict] = {}
        self._hist_photo = None
        self._hist_pending = False
        self.after(80, self.refresh_history)

    def refresh_history(self):
        self._hist_pending = False
        inst = self.hist_inst.get()
        kinds = HISTORY_KINDS.get(self.hist_kind.get())
        entries = [e for e in self.m.history.recent(600, None if inst in ("", ALL_INSTANCES) else inst)
                   if kinds is None or e["kind"] in kinds][:400]
        self.hist_tree.delete(*self.hist_tree.get_children())
        self._hist_rows = {}
        for i, e in enumerate(entries):
            iid = f"h{i}"
            self._hist_rows[iid] = e
            when = datetime.fromtimestamp(e["t"]).strftime("%b %d  %H:%M")
            tag = ("kept",) if e.get("action") == "kept" else \
                ("problem",) if e["kind"] == "failure" or e.get("action") == "stopped" else \
                ("energy",) if e["kind"] == "energy" else \
                ("quiet",) if e.get("action") == "scrapped" else ()
            self.hist_tree.insert("", "end", iid=iid, values=(f"  {when}", e["instance"], e["detail"]),
                                  tags=tag)
        if entries:
            self.hist_empty.place_forget()
        else:
            self.hist_empty.place(relx=0.5, rely=0.45, anchor="center")
        s = self.m.history.crest_summary(None if inst in ("", ALL_INSTANCES) else inst)
        self.hist_summary.configure(
            text=f"Crests kept {s.get('kept', 0)}  ·  scrapped {s.get('scrapped', 0)}"
                 + (f"  ·  unidentified {s['stopped']}" if s.get("stopped") else ""))

    def _on_hist_select(self):
        sel = self.hist_tree.selection()
        e = self._hist_rows.get(sel[0]) if sel else None
        if not e:
            return
        p = self.m.history.thumb_path(e)
        if p:
            img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                self._hist_photo, _ = to_photo(img, px(350), px(420))
                self.hist_pic.configure(image=self._hist_photo)
        else:
            self._hist_photo = None
            self.hist_pic.configure(image="")
        when = datetime.fromtimestamp(e["t"]).strftime("%A %d %B, %H:%M:%S")
        script = SCRIPTS[e["script"]].NAME if e["script"] in SCRIPTS else e["script"]
        extra = "".join(f"\n{k.title()}: {e[k]}" for k in ("rarity", "action") if e.get(k))
        self.hist_text.configure(text=f"{e['detail']}\n\n{when}\n{e['instance']} · {script}{extra}")

    def clear_history(self):
        if ios.confirm(self, "Every history entry and its picture will be deleted. Stats are kept.",
                       "Clear History?", ok="Clear", destructive=True):
            self.m.history.clear()
            self.refresh_history()
