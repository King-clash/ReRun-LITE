"""Macro Farming workspace: one place to configure, start, watch and review farming.

It reuses the existing, tested pages instead of copying them: the Dashboard (instances, controls, totals, live view),
the routine settings form and the History log are built into this workspace's stage. What is new here is the
account strip (which account this farming is for, its energy and what its goals suggest), the routine catalogue,
dry run, per-account session history and the always-visible Terms-of-Service warning."""
from __future__ import annotations

from . import safety
from .gui_accounts import STATUS_PILL
from .gui_common import *  # noqa: F401,F403
from .gui_common import __all__ as _common_names  # noqa: F401
from .gui_forms import stamp

FARM_SECTIONS = [("dashboard", "Dashboard"), ("routines", "Routines"), ("settings", "Routine settings"),
                 ("sessions", "Session history"), ("activity", "Activity log"), ("safety", "Safety")]


class FarmingMixin:

    def _build_farming(self):
        page = tk.Frame(self.nb.content, bg=C["bg"])
        self.nb.add(page, "Macro Farming", "play", first=True)
        self._tab_farming = self.nb.count() - 1
        hdr = ios.page_header(page, "Macro Farming")
        ios.Button(hdr, "Emergency Stop", self.stop_all, kind="filled", color="red", icon="stop", small=True).pack(side="right")
        self._farm_state = tk.Label(hdr, text="", bg=C["bg"], fg=C["secondary"], font=F["footnote_semi"])
        self._farm_state.pack(side="right", padx=(0, px(14)))
        self._farm_dot = ios.Dot(hdr, 10)
        self._farm_dot.pack(side="right", padx=(0, px(6)))
        # the warning is part of the workspace, not a page: it is on screen before any automation can be started
        from .safety import TOS_WARNING
        ios.Banner(page, TOS_WARNING, "orange").pack(fill="x", padx=px(20), pady=(0, px(8)))
        strip = ios.Card(page, pad=8)
        strip.pack(fill="x", padx=px(20), pady=(0, px(8)))
        row = tk.Frame(strip.body, bg=C["card"])
        row.pack(fill="x")
        tk.Label(row, text="Farming for", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="left")
        self._farm_picker = ios.Select(row, values=[], accent=True, command=self._farm_pick)
        self._farm_picker.pack(side="left", padx=(px(8), px(18)))
        self._farm_info = tk.Label(row, text="", bg=C["card"], fg=C["label"], font=F["footnote"], anchor="w", justify="left")
        self._farm_info.pack(side="left", fill="x", expand=True)
        self._farm_rec = tk.Label(strip.body, text="", bg=C["card"], fg=C["secondary"], font=F["footnote"], anchor="w", justify="left")
        self._farm_rec.pack(fill="x")
        self._farm_rec.bind("<Configure>", lambda e: self._farm_rec.configure(wraplength=max(200, e.width - 8)))

        body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=px(12), pady=(0, px(10)))
        self._farm_nav = ios.SideNav(body, FARM_SECTIONS, self._farm_show, title="Macro Farming")
        self._farm_nav.pack(side="left", fill="y")
        self._farm_stage = tk.Frame(body, bg=C["bg"])
        self._farm_stage.pack(side="left", fill="both", expand=True, padx=(px(8), 0))
        # existing pages, built once into the stage
        self._farm_pages: dict[str, tk.Misc] = {}
        for key, build in (("dashboard", self._build_dashboard), ("settings", self._build_settings), ("activity", self._build_history)):
            self._host = self._farm_stage
            try:
                build()
            finally:
                self._host = None
            self._farm_pages[key] = self._last_page
        self._farm_scroll = ios.ScrollFrame(self._farm_stage)
        self._farm_inner = self._farm_scroll.inner
        for key in ("routines", "sessions", "safety"):
            self._farm_pages[key] = self._farm_scroll
        self._farm_section = "dashboard"
        self._farm_nav.select("dashboard", notify=False)
        self._farm_show("dashboard")
        self.ops.store.listeners.append(lambda *a: self.after(80, self._refresh_farm_account))
        self._refresh_farm_account()

    # ------------------------------------------------------------------ navigation
    def _farm_show(self, key: str):
        for w in self._farm_stage.winfo_children():
            w.pack_forget()
        self._farm_section = key
        if key in ("routines", "sessions", "safety"):
            self._farm_scroll.pack(fill="both", expand=True)
            self._farm_render()
        else:
            self._farm_pages[key].pack(fill="both", expand=True)
            if key == "activity":
                self.refresh_history()

    def open_farming(self, script: str | None = None):
        """Jump here (e.g. from a goal suggestion); optionally pick the routine for the selected emulator."""
        self.nb.select(self._tab_farming)
        if script:
            name = self.selected() if hasattr(self, "selected") else None
            if name and script in self.m.scripts_available():
                self.m.set_instance_script(name, script)
                self.refresh_instances()
                self._on_select()
        self._farm_nav.select("dashboard")

    def _dashboard_in_view(self) -> bool:
        return self.nb.index() == self._tab_farming and self._farm_section == "dashboard"

    def _farm_pick(self):
        name = self._farm_picker.get()
        a = next((x for x in self.ops.store.all() if x["name"] == name), None)
        if a and a["id"] != self.ops.store.active_id:
            self.ops.use_account(a["id"])
            self._on_account_switched()

    # ------------------------------------------------------------------ account strip + status
    def _refresh_farm_account(self):
        if not hasattr(self, "_farm_picker"):
            return
        st = self.ops.store
        accts = st.all()
        self._farm_picker._values = [a["name"] for a in accts]
        a = st.active()
        if a is None:
            return
        self._farm_picker.set(a["name"])
        e, mx = st.field(a["id"], "energy"), st.field(a["id"], "energy_max")
        energy = (f"Energy {e['value']}/{mx['value']} ({STATUS_PILL[e['status']][0].lower()}, {self._ago(e['t'])})" if e and mx else "Energy not recorded")
        sess = [s for s in st.sessions(a["id"]) if not s.get("dry_run")]
        today = safety.minutes_today(st, a["id"])
        lim = a["safety"]["daily_minutes_limit"]
        bits = [energy, f"{today:.0f} min farmed today" + (f" of {lim}" if lim else ""), f"{len(sess)} session(s) recorded"]
        if a["safety"]["dry_run"]:
            bits.append("DRY-RUN MODE: nothing will be tapped")
        if not a["safety"]["automation_allowed"]:
            bits.append("AUTOMATION OFF for this account")
        self._farm_info.configure(text="   ·   ".join(bits))
        recs = self.ops.goals.recommend(a["id"], self.m.scripts_available())
        self._farm_rec.configure(text=("Suggested: " + recs[0]["action"] + " - " + recs[0]["why"]) if recs else "No goals set for this account (Account Manager > Goals).")

    def _ago(self, t):
        from .gui_forms import ago
        return ago(t)

    def _farm_update_status(self):
        """Idle / running / paused / error summary shown next to Emergency Stop (called every second)."""
        if not hasattr(self, "_farm_state"):
            return
        states = [i.status for i in self.m.instances.values()]
        for st, text, color in (("error", "Error", "red"), ("paused", "Paused", "orange"), ("running", "Automation running", "green"), ("starting", "Starting", "blue")):
            if st in states:
                self._farm_state.configure(text=text)
                self._farm_dot.set(C[color])
                return
        self._farm_state.configure(text="Automation stopped")
        self._farm_dot.set(C["gray"])

    # ------------------------------------------------------------------ start with account checks
    def _start_checked(self, name: str, script: str | None = None, aid: str | None = None,
                       dry_run: bool = False, task: str = "") -> str:
        """Start a script; when several accounts share the emulator, ask which one is really open first."""
        bound = self.ops.store.accounts_for_instance(name)
        confirm = aid if aid and any(b["id"] == aid for b in bound) else None
        if len(bound) > 1 and confirm is None:
            i, _ = ios._dialog(self, "Which account is open?",
                               f"{len(bound)} accounts use {name}. Rerun cannot see which one is logged in, so tell it. "
                               "Starting on the wrong account would farm for that account instead.",
                               [(b["name"], "default") for b in bound] + [("Cancel", "cancel")], cancel=len(bound))
            if i is None or i >= len(bound):
                return "Cancelled"
            confirm = bound[i]["id"]
        return self.m.start(name, script, confirm_account=confirm, dry_run=dry_run, task=task)

    def dry_run_sel(self):
        name = self.selected()
        if not name:
            return
        script = self.m.instances[name].script
        missing = self.m.missing_templates(script)
        if missing:
            ios.alert(self, "Capture these in the Templates tab first:\n\n" + "\n".join(missing[:20]), "Templates Missing")
            return
        self.flash(self._start_checked(name, dry_run=True))

    # ------------------------------------------------------------------ rendered sections
    def _farm_render(self):
        if self._farm_section not in ("routines", "sessions", "safety"):
            return
        for w in self._farm_inner.winfo_children():
            w.destroy()
        wrap = tk.Frame(self._farm_inner, bg=C["bg"])
        wrap.pack(fill="x", padx=px(8), pady=(0, px(16)))
        getattr(self, "_farm_" + self._farm_section)(wrap)

    def _farm_routines(self, p):
        tk.Label(p, text="Routines", bg=C["bg"], fg=C["label"], font=F["title"], anchor="w").pack(fill="x", pady=(px(6), px(2)))
        ios.wrapped_label(p, "Every farming routine Rerun has. Verified means it has been run on a real game; Beta was built from "
                             "ReStart's flow and has not. Start puts the routine on the emulator selected in the Dashboard.").pack(fill="x", pady=(0, px(8)))
        name = self.selected() if hasattr(self, "selected") else None
        tk.Label(p, text=f"Selected emulator: {name or 'none (pick one in the Dashboard)'}", bg=C["bg"], fg=C["secondary"], font=F["footnote"], anchor="w").pack(fill="x")
        for sid, cls in SCRIPTS.items():
            card = ios.Card(p, pad=10)
            card.pack(fill="x", pady=(px(8), 0))
            top = tk.Frame(card.body, bg=C["card"])
            top.pack(fill="x")
            tk.Label(top, text=cls.NAME, bg=C["card"], fg=C["label"], font=F["body_semi"]).pack(side="left")
            ios.Pill(top, "Beta" if cls.BETA else "Verified", "orange" if cls.BETA else "green").pack(side="left", padx=px(8))
            missing = self.m.missing_templates(sid)
            if missing:
                ios.Pill(top, f"{len(missing)} template(s) missing", "red").pack(side="left")
            first = (cls.INSTRUCTIONS or "").strip().split("\n\n")[0].replace("\n", " ")
            ios.wrapped_label(card.body, first[:420], font="footnote").pack(fill="x", pady=(px(4), px(6)))
            bar = tk.Frame(card.body, bg=C["card"])
            bar.pack(fill="x")
            ios.Button(bar, "Start", lambda s=sid: self._routine_start(s), small=True).pack(side="left")
            ios.Button(bar, "Dry Run", lambda s=sid: self._routine_start(s, True), kind="tinted", small=True).pack(side="left", padx=px(8))
            ios.Button(bar, "Settings", lambda s=sid: self._routine_settings(s), kind="plain", small=True).pack(side="left")
        custom = [k for k in self.m.routines]
        if custom:
            ios.section_header(p, "Your own routines", padx=px(4))
            ios.wrapped_label(p, ", ".join(sorted(custom)) + "  (edit in routines/; run them from the Dashboard's script list)").pack(fill="x")

    def _routine_start(self, script: str, dry: bool = False):
        name = self.selected()
        if not name:
            ios.alert(self, "Select an emulator in the Dashboard first.")
            return
        missing = self.m.missing_templates(script)
        if missing:
            ios.alert(self, "Capture these in the Templates tab first:\n\n" + "\n".join(missing[:20]), "Templates Missing")
            return
        cls = SCRIPTS[script]
        if cls.BETA and not dry and not ios.confirm(self, f"{cls.NAME} has not been run on a real game yet. Watch the first runs and stop it "
                                                          "(Emergency Stop or F12) if anything looks wrong.", "Beta Script", ok="Start"):
            return
        self.flash(self._start_checked(name, script, dry_run=dry))
        self._farm_show("dashboard")
        self._farm_nav.select("dashboard", notify=False)

    def _routine_settings(self, script: str):
        self.set_script.set(SCRIPTS[script].display_name())
        self._load_settings_form()
        self._farm_nav.select("settings")

    def _farm_sessions(self, p):
        a = self.ops.store.active()
        tk.Label(p, text=f"Session history - {a['name']}", bg=C["bg"], fg=C["label"], font=F["title"], anchor="w").pack(fill="x", pady=(px(6), px(2)))
        ios.wrapped_label(p, "Every farming session started for this account: routine, emulator, how long, how it ended and what it achieved. "
                             "Dry runs are listed too and marked.").pack(fill="x", pady=(0, px(8)))
        sessions = list(reversed(self.ops.store.sessions(a["id"])))
        card = ios.Card(p, pad=6)
        card.pack(fill="x")
        cols = ("start", "routine", "emulator", "minutes", "status", "results")
        tree = ttk.Treeview(card.body, columns=cols, show="headings", style="IOS.Treeview", selectmode="browse", height=12)
        for c, w, t in (("start", 130, "Started"), ("routine", 110, "Routine"), ("emulator", 110, "Emulator"), ("minutes", 70, "Minutes"), ("status", 120, "Status"), ("results", 220, "Results")):
            tree.heading(c, text=t)
            tree.column(c, width=px(w), stretch=c == "results")
        for s in sessions:
            mins = ((s["end"] or time.time()) - s["start"]) / 60
            res = ", ".join(f"{v} {k}" for k, v in (s.get("results") or {}).items())
            tree.insert("", "end", iid=s["id"], values=(stamp(s["start"]), s["script"], s["instance"], f"{mins:.0f}", s["status"] + (" (dry run)" if s.get("dry_run") else ""), res or "-"))
        tree.pack(fill="x")
        detail = ios.wrapped_label(p, "Select a session to see its details." if sessions else "No sessions recorded for this account yet.", font="footnote")
        detail.pack(fill="x", pady=(px(8), 0))

        def show(_e=None):
            sel = tree.selection()
            s = next((x for x in sessions if sel and x["id"] == sel[0]), None)
            if s:
                detail.configure(text=f"{s['script']} on {s['instance']} · started {stamp(s['start'])} · ended {stamp(s['end'])} · {s['status']}"
                                      + (" · dry run, nothing was tapped" if s.get("dry_run") else "") + (f" · problem: {s['error']}" if s["error"] else "")
                                      + (f" · results: {s['results']}" if s["results"] else " · no results recorded"))
        tree.bind("<<TreeviewSelect>>", show)

    def _farm_safety(self, p):
        a = self.ops.store.active()
        s = a["safety"]
        tk.Label(p, text=f"Safety - {a['name']}", bg=C["bg"], fg=C["label"], font=F["title"], anchor="w").pack(fill="x", pady=(px(6), px(2)))
        ios.wrapped_label(p, safety.SAFETY_NOTE).pack(fill="x", pady=(0, px(8)))
        used = safety.minutes_today(self.ops.store, a["id"])
        card = ios.Card(p, pad=10)
        card.pack(fill="x")
        for text in (f"Automation: {'allowed' if s['automation_allowed'] else 'switched OFF for this account'}",
                     f"Dry-run mode: {'on - nothing is tapped' if s['dry_run'] else 'off'}",
                     f"Daily limit: {s['daily_minutes_limit'] or 'none'} min   ·   used today: {used:.0f} min",
                     f"Session limit: {s['session_minutes_limit'] or 'none'} min",
                     f"Allowed routines: {', '.join(s['allowed_scripts']) or 'all'}"):
            tk.Label(card.body, text=text, bg=C["card"], fg=C["label"], font=F["body"], anchor="w").pack(fill="x", pady=px(2))
        bar = tk.Frame(p, bg=C["bg"])
        bar.pack(fill="x", pady=(px(10), 0))
        ios.Button(bar, "Change Limits", lambda: (self.nb.select(self._tab_accounts), self._am_nav.select("safety")), kind="tinted", small=True).pack(side="left")
        ios.Button(bar, "Emergency Stop", self.stop_all, color="red", icon="stop", small=True).pack(side="left", padx=px(8))
