"""Account Manager workspace: shell, account switching, overview dashboard, scanning, information, checklist.
The remaining sections live in gui_accounts2.py (goals, accounts, inventory, events, reports, safety).

Every section is a method `_am_<key>(parent)` that draws the CURRENT account from rerun/accounts.py into
`parent`. Sections are redrawn from the data whenever it changes, so the screen never holds its own copy of an
account's numbers."""
from __future__ import annotations

import threading

from .accounts import FIELDS, SCAN_SUPPORT, AccountError
from .checklist import fmt_until
from .gui_common import *  # noqa: F401,F403
from .gui_common import __all__ as _common_names  # noqa: F401
from .gui_forms import ago, form_dialog, stamp

SECTIONS = [("overview", "Overview"), ("scan", "Scanning"), ("info", "Information"), ("checklist", "Checklist"),
            ("goals", "Goals"), ("units", "Units"), ("accounts", "All accounts"), ("vault", "Crest Vault"),
            ("events", "Events"), ("reports", "Reports & History"), ("safety", "Safety & settings")]

STATE_PILL = {"completed": ("Completed", "green"), "unverified": ("Not yet verified", "orange"),
              "in_progress": ("In progress", "blue"), "failed": ("Failed", "red"),
              "available": ("Available", "gray")}
STATUS_PILL = {"manual": ("Manual", "blue"), "ocr": ("Scanned", "green"), "verified": ("Verified", "green"),
               "unverified": ("Unverified", "orange")}
SUPPORT_PILL = {"supported": ("Supported", "green"), "beta": ("Beta", "orange"),
                "unsupported": ("Not supported yet", "gray")}


class AccountsMixin:

    # ================================================================ shell
    @property
    def ops(self):
        return self.m.ops

    def _build_accounts(self):
        page = tk.Frame(self.nb.content, bg=C["bg"])
        self.nb.add(page, "Accounts", "people", first=True)
        self._tab_accounts = self.nb.count() - 1
        self._am_page = page
        hdr = ios.page_header(page, "Account Manager")
        ios.Button(hdr, "New Account", self.am_new, kind="tinted", icon="add", small=True).pack(side="right")
        self._am_picker = ios.Select(hdr, values=[], accent=True, command=self._am_pick)
        self._am_picker.pack(side="right", padx=(px(12), px(14)))
        self._label(hdr, "Account").pack(side="right", padx=(0, px(8)))
        body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=px(12), pady=(0, px(10)))
        self._am_nav = ios.SideNav(body, SECTIONS, self._am_show, title="Account Manager")
        self._am_nav.pack(side="left", fill="y")
        self._am_stage = tk.Frame(body, bg=C["bg"])
        self._am_stage.pack(side="left", fill="both", expand=True, padx=(px(8), 0))
        self._am_scroll = ios.ScrollFrame(self._am_stage)
        self._am_inner = self._am_scroll.inner
        self._am_units_host = tk.Frame(self._am_stage, bg=C["bg"])
        self._am_section = "overview"
        self._host = self._am_units_host            # the existing Units + Compendium page, built into this workspace
        try:
            self._build_units()
        finally:
            self._host = None
        self._last_page.pack(fill="both", expand=True)
        self._am_units_built = True
        self._am_scan_busy = False
        self.ops.store.listeners.append(self._am_on_change)
        self._am_refresh_picker()
        self._am_nav.select("overview", notify=False)
        self._am_show("overview")

    def _am_on_change(self, kind: str, aid: str, detail: str):
        """Store listener (any thread): redraw on the GUI thread, unless the user is typing in a form field."""
        try:
            self.after(60, self._am_changed)
        except (RuntimeError, tk.TclError):
            pass

    def _am_changed(self):
        self._am_refresh_picker()
        if not self._am_typing():
            self._am_render()

    def _am_typing(self) -> bool:
        w = self.focus_get()
        return isinstance(w, (tk.Entry, tk.Text)) and str(w).startswith(str(self._am_inner))

    def _am_refresh_picker(self):
        accts = self.ops.store.all()
        names = [a["name"] for a in accts]
        self._am_picker._values = names
        act = self.ops.store.active()
        self._am_picker.set(act["name"] if act else "")

    def _am_pick(self):
        name = self._am_picker.get()
        a = next((x for x in self.ops.store.all() if x["name"] == name), None)
        if a and a["id"] != self.ops.store.active_id:
            self.ops.use_account(a["id"])
            self._on_account_switched()

    def _on_account_switched(self):
        self._am_refresh_picker()
        self._am_render()
        for fn in ("refresh_units", "_refresh_farm_account"):
            if hasattr(self, fn):
                try:
                    getattr(self, fn)()
                except Exception as e:  # noqa: BLE001 - a stale widget must not break switching
                    errlog.note("gui.account_switch", e)

    def _am_show(self, key: str):
        self._am_section = key
        if key == "units":
            self._am_scroll.pack_forget()
            self._am_units_host.pack(fill="both", expand=True)
            self.refresh_units()
        else:
            self._am_units_host.pack_forget()
            self._am_scroll.pack(fill="both", expand=True)
            self._am_render()

    def _am_render(self):
        if self._am_section == "units":
            return
        for w in self._am_inner.winfo_children():
            w.destroy()
        a = self.ops.store.active()
        wrap = tk.Frame(self._am_inner, bg=C["bg"])
        wrap.pack(fill="x", padx=px(8), pady=(0, px(16)))
        if a is None:
            ios.wrapped_label(wrap, "No account yet. Press New Account to add one.", font="body").pack(fill="x", pady=px(20))
            return
        getattr(self, "_am_" + self._am_section)(wrap, a)

    # ------------------------------------------------------------------ small building blocks
    def _am_title(self, parent, title: str, sub: str = "") -> tk.Frame:
        row = tk.Frame(parent, bg=C["bg"])
        row.pack(fill="x", pady=(px(6), px(8)))
        right = tk.Frame(row, bg=C["bg"])
        right.pack(side="right")
        tk.Label(row, text=title, bg=C["bg"], fg=C["label"], font=F["title"], anchor="w").pack(side="left")
        if sub:
            ios.wrapped_label(parent, sub).pack(fill="x", pady=(0, px(8)))
        return right

    def _am_card(self, parent, title: str = "", **pack) -> tk.Frame:
        if title:
            ios.section_header(parent, title, padx=px(4), pady=(px(12), px(6)))
        card = ios.Card(parent, pad=10)
        card.pack(fill="x", **pack)
        return card.body

    def _am_empty(self, parent, text: str):
        ios.wrapped_label(parent, text, font="footnote").pack(fill="x", pady=px(6))

    def _am_error(self, e: Exception | str, title: str = "Could not do that"):
        ios.alert(self, str(e), title)

    # ================================================================ account create / edit / remove
    def am_new(self):
        insts = [""] + list(self.m.instances)
        fields = [dict(key="name", label="Name"), dict(key="label", label="Label (optional)", hint="e.g. main, alt, farming"),
                  dict(key="instance", label="Emulator this account plays on", kind="select",
                       value="", options=insts, hint="Blank = not linked. Linking lets Rerun attribute farming to this account."),
                  dict(key="notes", label="Notes", kind="multiline")]

        def save(v):
            try:
                aid = self.ops.store.create(v["name"], v["label"], v["notes"], v["instance"])
            except AccountError as e:
                return str(e)
            self.ops.use_account(aid)
            self._on_account_switched()
            return None
        form_dialog(self, "New Account", fields, save, ok="Create")

    def am_edit(self, a: dict):
        insts = [""] + list(self.m.instances)
        fields = [dict(key="name", label="Name", value=a["name"]), dict(key="label", label="Label", value=a["label"]),
                  dict(key="instance", label="Emulator", kind="select", value=a["instance"], options=insts),
                  dict(key="notes", label="Notes", kind="multiline", value=a["notes"])]

        def save(v):
            try:
                self.ops.store.update(a["id"], name=v["name"], label=v["label"], instance=v["instance"], notes=v["notes"])
            except AccountError as e:
                return str(e)
            return None
        if form_dialog(self, "Edit Account", fields, save):
            self._am_refresh_picker()

    def am_remove(self, a: dict):
        if len(self.ops.store.ids()) <= 1:
            self._am_error("Keep at least one account. Create another before removing this one.")
            return
        if ios.confirm(self, f"Remove '{a['name']}'?\n\nIts files are moved to accounts/_removed/ so they can be "
                             "recovered; nothing is deleted.", "Remove Account", ok="Remove", destructive=True):
            was_active = a["id"] == self.ops.store.active_id
            self.ops.store.remove(a["id"])
            if was_active:
                self.ops.use_account(self.ops.store.active_id)
                self._on_account_switched()

    # ================================================================ overview
    def _am_overview(self, p, a):
        aid, st = a["id"], self.ops.store
        right = self._am_title(p, a["name"])
        ios.Button(right, "Scan Now", lambda: self.am_scan(aid), kind="tinted", icon="sync", small=True).pack(side="right")
        ios.Button(right, "Edit", lambda: self.am_edit(a), kind="plain", icon="edit", small=True).pack(side="right", padx=(0, px(12)))
        meta = tk.Frame(p, bg=C["bg"])
        meta.pack(fill="x", pady=(0, px(6)))
        if a["label"]:
            ios.Pill(meta, a["label"], "blue").pack(side="left", padx=(0, px(6)))
        ios.Pill(meta, "Active account" if aid == st.active_id else "Not active", "green" if aid == st.active_id else "gray").pack(side="left", padx=(0, px(6)))
        ios.Pill(meta, f"Emulator: {a['instance']}" if a["instance"] else "No emulator linked", "gray").pack(side="left", padx=(0, px(6)))
        ok = a["last_scan_ok"]
        stale = self.ops.stale_scan(aid)
        ios.Pill(meta, f"Last successful scan: {ago(ok)}" if ok else "Never scanned", "orange" if stale else "green").pack(side="left")

        grid = tk.Frame(p, bg=C["bg"])
        grid.pack(fill="x", pady=(px(4), 0))
        e, mx = st.field(aid, "energy"), st.field(aid, "energy_max")

        def card(col, caption, key, value=None, note=""):
            f = st.field(aid, key)
            c, v, n = ios.metric_card(grid, caption, value if value is not None else (f"{f['value']:,}" if f else "-"),
                                      note or (STATUS_PILL.get(f["status"], ("", ""))[0] + " · " + ago(f["t"]) if f else "Not recorded"))
            c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else px(8), 0))
            grid.columnconfigure(col, weight=1, uniform="m")
        en_val = f"{e['value']}/{mx['value']}" if e and mx else (str(e["value"]) if e else "-")
        card(0, "Energy", "energy", en_val, (f"{STATUS_PILL[e['status']][0]} · {ago(e['t'])}\nRefill: {self.ops.energy_refill(aid)}" if e else "Not recorded"))
        card(1, "Gems", "gems")
        card(2, "Gold", "gold")
        card(3, "Alch", "tickets")
        if e:
            bar = ios.ProgressBar(p, color="green" if not mx or e["value"] / max(1, mx["value"]) > 0.25 else "orange")
            bar.pack(fill="x", pady=(px(8), 0))
            bar.after(50, lambda: bar.set(e["value"] / mx["value"] if mx else 0))
        others = [(FIELDS[k][0], st.field(aid, k)) for k in ("player_level", "summon_tickets", "raid_tickets") if st.field(aid, k)]
        if others:
            ios.wrapped_label(p, "   ·   ".join(f"{n}: {f['value']:,}" for n, f in others)).pack(fill="x", pady=(px(6), 0))

        cl = self.ops.checklist.summary(aid)
        body = self._am_card(p, "Checklist")
        for per, label in (("daily", "Daily"), ("weekly", "Weekly")):
            r = tk.Frame(body, bg=C["card"])
            r.pack(fill="x", pady=px(3))
            tk.Label(r, text=f"{label}: {cl[per]['done']} of {cl[per]['total']} done", bg=C["card"], fg=C["label"], font=F["body"]).pack(side="left")
            tk.Label(r, text=f"resets in {fmt_until(cl[per]['resets_in'])}", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="right")
            b = ios.ProgressBar(body, color="green")
            b.pack(fill="x")
            tot = max(1, cl[per]["total"])
            b.after(50, lambda b=b, d=cl[per]["done"], t=tot: b.set(d / t))
        if cl["daily"]["remaining"]:
            ios.wrapped_label(body, "Still to do today: " + ", ".join(cl["daily"]["remaining"])).pack(fill="x", pady=(px(6), 0))

        body = self._am_card(p, "Goals")
        prog = [x for x in self.ops.goals.refresh(aid) if x["goal"]["status"] == "active"][:4]
        if not prog:
            self._am_empty(body, "No goals yet. Add one in Goals.")
        for x in prog:
            r = tk.Frame(body, bg=C["card"])
            r.pack(fill="x", pady=px(3))
            tk.Label(r, text=x["goal"]["title"], bg=C["card"], fg=C["label"], font=F["body"]).pack(side="left")
            tk.Label(r, text=f"{x['current'] if x['current'] is not None else '?'} / {x['target']}", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="right")
            b = ios.ProgressBar(body, color="blue")
            b.pack(fill="x")
            b.after(50, lambda b=b, f=x["fraction"]: b.set(f))

        sess = [s for s in reversed(st.sessions(aid))][:4]
        body = self._am_card(p, "Farming activity")
        if not sess:
            self._am_empty(body, "No farming sessions recorded for this account yet.")
        for s in sess:
            dur = ((s["end"] or time.time()) - s["start"]) / 60
            r = tk.Frame(body, bg=C["card"])
            r.pack(fill="x", pady=px(2))
            kind = {"completed": "green", "stopped": "gray", "error": "red", "running": "blue"}.get(s["status"], "gray")
            ios.Pill(r, s["status"].title() + (" (dry run)" if s.get("dry_run") else ""), kind).pack(side="left")
            res = ", ".join(f"{v} {k}" for k, v in (s.get("results") or {}).items())
            tk.Label(r, text=f"  {s['script']} · {stamp(s['start'])} · {dur:.0f} min" + (f" · {res}" if res else ""), bg=C["card"], fg=C["label"], font=F["footnote"]).pack(side="left")

        ios.section_header(p, "History", padx=px(4), pady=(px(14), px(4)))
        charts = tk.Frame(p, bg=C["bg"])
        charts.pack(fill="x")
        specs = [("Crests per game day", "crests_per_day", "orange", ""), ("Farming sessions per game day", "sessions_per_day", "blue", ""),
                 ("Energy used per game day (observed)", "energy_used_per_day", "green", ""), ("Gems by week (last recorded)", "gems_by_week", "blue", "")]
        for i, (title, kind, color, unit) in enumerate(specs):
            card = ios.Card(charts, pad=8)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else px(8), 0), pady=(0, px(8)))
            ch = ios.BarChart(card.body, title, self.ops.series(aid, kind), color=color, unit=unit,
                              empty="Nothing recorded yet")
            ch.pack(fill="x")
            charts.columnconfigure(i % 2, weight=1, uniform="c")
        ios.wrapped_label(p, "Charts use only what Rerun has recorded (scans, farming sessions, the crest log, values you entered). "
                             "Empty means no data yet; nothing is estimated or back-filled.").pack(fill="x")

        recent = [x for x in st.activity(aid, 60) if x["kind"] == "field"][-5:]
        body = self._am_card(p, "Recent resource changes")
        if not recent:
            self._am_empty(body, "No changes recorded yet.")
        for x in reversed(recent):
            tk.Label(body, text=f"{stamp(x['t'])}   {x['detail']}", bg=C["card"], fg=C["label"], font=F["footnote"], anchor="w").pack(fill="x")

    # ================================================================ scanning
    def am_scan(self, aid: str):
        """Scan energy from the linked emulator in a worker thread (never blocks the window)."""
        if self._am_scan_busy:
            return
        self._am_scan_busy = True
        self.flash("Scanning...", "info")

        def work():
            try:
                rep = self.ops.scan_screen(aid)
                msg, kind = (f"Scan: {len(rep['detected'])} value(s) read, {len(rep['uncertain'])} uncertain, "
                             f"{len(rep['missing'])} not found", "ok" if rep["detected"] else "warn")
            except AccountError as e:
                msg, kind = str(e), "error"
            except Exception as e:  # noqa: BLE001
                msg, kind = f"Scan failed: {e}", "error"
            self.events.put({"type": "_scan_done", "message": msg, "kind": kind})      # back to the GUI thread
        threading.Thread(target=work, daemon=True, name="account-scan").start()

    def _am_scan_done(self, msg: str, kind: str):
        self._am_scan_busy = False
        self.flash(msg, kind)
        self._am_render()

    def _am_scan(self, p, a):
        aid = a["id"]
        right = self._am_title(p, "Scanning", "Rerun reads what it has been tested to read, keeps the last reliable value if a "
                                              "reading fails, and never replaces a value with an uncertain one.")
        ios.Button(right, "Scan top bar now", lambda: self.am_scan(aid), icon="sync", small=True).pack(side="right")
        ios.Button(right, "Scan units", lambda: self.am_scan_units(a), kind="tinted", icon="people", small=True).pack(side="right", padx=(0, px(8)))
        body = self._am_card(p, "What can be scanned")
        for key, (level, note) in SCAN_SUPPORT.items():
            r = tk.Frame(body, bg=C["card"])
            r.pack(fill="x", pady=px(3))
            pill = ios.Pill(r, *SUPPORT_PILL[level])
            pill.pack(side="left")
            tk.Label(r, text="  " + (FIELDS[key][0] if key in FIELDS else key.title()), bg=C["card"], fg=C["label"], font=F["body"], width=16, anchor="w").pack(side="left")
            ios.wrapped_label(r, note, font="footnote").pack(side="left", fill="x", expand=True)
        pend = a["pending"]
        body = self._am_card(p, "Readings waiting for you")
        if not pend:
            self._am_empty(body, "None. Uncertain readings are parked here instead of replacing your values.")
        for key, pr in pend.items():
            r = tk.Frame(body, bg=C["card"])
            r.pack(fill="x", pady=px(3))
            tk.Label(r, text=f"{FIELDS[key][0]}: {pr['value']:,}" if isinstance(pr["value"], int) else f"{FIELDS[key][0]}: {pr['value']}", bg=C["card"], fg=C["label"], font=F["body"]).pack(side="left")
            tk.Label(r, text=f"  not applied - {pr['reason']}", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="left")
            ios.Button(r, "Dismiss", lambda k=key: self._am_dismiss(aid, k), kind="plain", color="red", small=True).pack(side="right")
            ios.Button(r, "Use it", lambda k=key: self._am_accept(aid, k), kind="plain", small=True).pack(side="right", padx=(0, px(10)))
        body = self._am_card(p, "Scan history")
        hist = list(reversed(a["scan_history"]))[:10]
        if not hist:
            self._am_empty(body, "No scans yet.")
        for h in hist:
            line = f"{stamp(h['t'])}   {h['source']}: {len(h['detected'])} read, {len(h['uncertain'])} uncertain, {len(h['missing'])} not found"
            tk.Label(body, text=line, bg=C["card"], fg=C["label"], font=F["footnote"], anchor="w").pack(fill="x")
            for d in h["detected"]:
                tk.Label(body, text=f"      read {d['key']} = {d['value']} (confidence {d['confidence']:.0f})", bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w").pack(fill="x")

    def _am_accept(self, aid, key):
        try:
            self.ops.store.accept_pending(aid, key)
        except AccountError as e:
            self._am_error(e)

    def _am_dismiss(self, aid, key):
        a = self.ops.store.get(aid)
        with self.ops.store._lock:
            a["pending"].pop(key, None)
            self.ops.store._save(a)
        self._am_render()

    def am_scan_units(self, a):
        """Run the Compendium Counter (the existing unit scanner) for this account."""
        if not a["instance"] or a["instance"] not in self.m.instances:
            self._am_error("Link this account to an emulator first (Information).")
            return
        if "compendium_counter" not in self.m.scripts_available():
            self._am_error("The unit scanner script is not available.")
            return
        self.flash(self._start_checked(a["instance"], "compendium_counter", a["id"]))

    # ================================================================ information
    def _am_info(self, p, a):
        aid, st = a["id"], self.ops.store
        right = self._am_title(p, "Account information")
        ios.Button(right, "Remove Account", lambda: self.am_remove(a), kind="plain", color="red", small=True).pack(side="right")
        ios.Button(right, "Edit Details", lambda: self.am_edit(a), kind="tinted", icon="edit", small=True).pack(side="right", padx=(0, px(8)))
        g = ios.Group(p)
        g.pack(fill="x")
        for label, val in (("Name", a["name"]), ("Label", a["label"] or "-"), ("Emulator", a["instance"] or "Not linked"),
                           ("Created", stamp(a["created"]))):
            tk.Label(g.row(label), text=val, bg=C["card"], fg=C["secondary"], font=F["body"]).pack()
        if a["notes"]:
            ios.wrapped_label(p, "Notes: " + a["notes"]).pack(fill="x", pady=(px(6), 0))
        ios.section_header(p, "Values", padx=px(4), pady=(px(16), px(6)))
        ios.wrapped_label(p, "Enter anything Rerun cannot scan. A value you enter is yours: switch on 'Maintain by hand' to stop "
                             "scans from even suggesting a different number.").pack(fill="x", pady=(0, px(6)))
        g = ios.Group(p)
        g.pack(fill="x")
        for key, (label, kind, rng, group) in FIELDS.items():
            f = st.field(aid, key)
            sub = (STATUS_PILL[f["status"]][0] + " · " + ago(f["t"])) if f else "Not recorded"
            if key in a["pending"]:
                sub += f"   ·   a scan read {a['pending'][key]['value']} (not applied)"
            r = g.row(label, sub)
            locked = tk.BooleanVar(value=key in a["locked"])
            ios.Button(r, "Edit", lambda k=key: self.am_edit_field(aid, k), kind="tinted", small=True).pack(side="right")
            tk.Label(r, text=(f"{f['value']:,}" if f and isinstance(f["value"], int) else (f["value"] if f else "-")), bg=C["card"], fg=C["label"],
                     font=F["body_semi"]).pack(side="right", padx=(0, px(14)))
            lock = ios.Switch(r, locked, command=lambda k=key, v=locked: st.set_locked(aid, k, v.get()))
            lock.pack(side="right", padx=(0, px(14)))
            tk.Label(r, text="Maintain by hand", bg=C["card"], fg=C["secondary"], font=F["caption"]).pack(side="right")
        self._am_prefs(p, a)

    def am_edit_field(self, aid: str, key: str):
        label, kind, rng, _ = FIELDS[key]
        f = self.ops.store.field(aid, key)

        def save(v):
            try:
                self.ops.store.set_field(aid, key, v["value"], status="manual", source="entered by hand")
            except AccountError as e:
                return str(e)
            return None
        hint = f"Between {rng[0]:,} and {rng[1]:,}." if rng else ""
        form_dialog(self, f"Edit {label}", [dict(key="value", label=label, value="" if not f else f["value"], hint=hint)], save)

    def _am_prefs(self, p, a):
        aid = a["id"]
        g = ios.Group(p, header="Preferences", footer="Used for the energy refill estimate and the weekly reset. "
                                                      "Both stay 'unknown' until you set them - Rerun does not guess the game's numbers.")
        g.pack(fill="x", pady=(px(16), 0))
        regen = tk.StringVar(value=str(a["prefs"]["energy_regen_minutes"]))
        fld = ios.Field(g.row("Minutes per energy point", "0 = unknown"), regen, width=6, justify="right")
        fld.pack()
        wk = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        wsel = ios.Select(g.row("Weekly reset day", "Resets at 6 AM UTC-6 on this day"), values=wk, accent=True,
                          command=lambda: self._am_save_pref(aid, week_reset_weekday=wk.index(wsel.get())))
        wsel.set(wk[a["prefs"]["week_reset_weekday"]])
        wsel.pack()
        for ev in ("<FocusOut>", "<Return>"):
            fld.entry.bind(ev, lambda e: self._am_save_pref(aid, energy_regen_minutes=regen.get()), add="+")

    def _am_save_pref(self, aid, **kw):
        try:
            self.ops.store.update_settings(aid, "prefs", **kw)
        except AccountError as e:
            self._am_error(e)

    # ================================================================ checklist
    def _am_checklist(self, p, a):
        aid = a["id"]
        right = self._am_title(p, "Daily & weekly checklist",
                               "Resets follow the game clock (6 AM UTC-6), not your computer's midnight. A task a script says it "
                               "finished stays 'Not yet verified' until you confirm it. Only tasks with a real, tested script can be started.")
        ios.Button(right, "Add Task", self.am_add_task, kind="tinted", icon="add", small=True).pack(side="right")
        ios.Button(right, "Run Next Due", lambda: self.am_run_next(aid), icon="play", small=True).pack(side="right", padx=(0, px(8)))
        cl = self.ops.checklist
        summ = cl.summary(aid)
        meta = tk.Frame(p, bg=C["bg"])
        meta.pack(fill="x", pady=(0, px(6)))
        for per in ("daily", "weekly"):
            ios.Pill(meta, f"{per.title()}: {summ[per]['done']}/{summ[per]['total']} · resets in {fmt_until(summ[per]['resets_in'])}", "blue").pack(side="left", padx=(0, px(6)))
        avail = self.m.scripts_available()
        for per in ("daily", "weekly"):
            rows = [r for r in cl.rows(aid) if r["period"] == per]
            body = self._am_card(p, per.title() + " tasks")
            for r in rows:
                line = tk.Frame(body, bg=C["card"])
                line.pack(fill="x", pady=px(4))
                txt, kind = STATE_PILL[r["state"]]
                slot = tk.Frame(line, bg=C["card"], width=px(112), height=px(24))     # fixed width: names line up
                slot.pack(side="left")
                slot.pack_propagate(False)
                ios.Pill(slot, txt, kind).pack(anchor="w")
                col = tk.Frame(line, bg=C["card"])
                col.pack(side="left", fill="x", expand=True, padx=px(10))
                tk.Label(col, text=f"{r['name']}   (priority {r['priority']})", bg=C["card"], fg=C["label"], font=F["body"], anchor="w").pack(fill="x")
                auto = r.get("script") and r["script"] in avail
                note = f"Automated by {avail[r['script']]}" if auto else (r.get("note") or "Manual.")
                note += f"  ·  last done {stamp(r['last_done'])}" if r["last_done"] else ""
                tk.Label(col, text=note, bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w").pack(fill="x")
                btns = tk.Frame(line, bg=C["card"])
                btns.pack(side="right")
                tid = r["id"]
                if r["state"] in ("completed", "unverified"):
                    if r["state"] == "unverified":
                        ios.Button(btns, "Confirm", lambda t=tid: self._am_task(aid, "confirm", t), kind="tinted", small=True).pack(side="left", padx=(0, px(6)))
                    ios.Button(btns, "Undo", lambda t=tid: self._am_task(aid, "undo", t), kind="plain", small=True).pack(side="left")
                else:
                    ios.Button(btns, "Mark Done", lambda t=tid: self._am_task(aid, "mark_done", t), kind="tinted", small=True).pack(side="left", padx=(0, px(6)))
                    if auto and r["state"] != "in_progress":
                        ios.Button(btns, "Run", lambda t=tid: self.am_run_task(aid, t), small=True).pack(side="left")
                ios.Button(btns, "", lambda t=tid: self._am_task(aid, "remove_task", t), kind="plain", color="red", icon="delete", small=True).pack(side="left", padx=(px(6), 0))

    def _am_task(self, aid, action, tid):
        try:
            if action == "mark_done":
                self.ops.checklist.mark_done(aid, tid, by="manual")
            elif action == "remove_task":
                if not ios.confirm(self, "Remove this task from the checklist?", "Remove Task", ok="Remove", destructive=True):
                    return
                self.ops.checklist.remove_task(aid, tid)
            else:
                getattr(self.ops.checklist, action)(aid, tid)
        except AccountError as e:
            self._am_error(e)
        self._am_render()

    def am_add_task(self):
        aid = self.ops.store.active_id

        def save(v):
            try:
                self.ops.checklist.add_task(aid, v["name"], v["period"], int(v["priority"] or 5))
            except (AccountError, ValueError) as e:
                return str(e)
            return None
        form_dialog(self, "Add Task", [dict(key="name", label="Task"), dict(key="period", label="Repeats", kind="select", value="daily", options=["daily", "weekly"]),
                                       dict(key="priority", label="Priority (1 = most important)", value="5")], save, ok="Add")

    def am_run_task(self, aid: str, tid: str):
        d = next((x for x in self.ops.checklist.definitions(aid) if x["id"] == tid), None)
        cls = SCRIPTS.get(d["script"]) if d and d.get("script") else None
        if cls is not None and cls.BETA and not ios.confirm(
                self, f"{cls.NAME} has not been run on a real game yet. Watch it and use Emergency Stop (F12) "
                      "if anything looks wrong.", "Beta Script", ok="Start"):
            return
        msg = self.ops.run_task(aid, tid)
        self.flash(msg, "info")
        self._am_render()

    def am_run_next(self, aid: str):
        due = self.ops.checklist.due_automatable(aid, self.m.scripts_available())
        if not due:
            self.flash("Nothing due can be automated - the rest is manual.", "info")
            return
        self.am_run_task(aid, due[0]["id"])
