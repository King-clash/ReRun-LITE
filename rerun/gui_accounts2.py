"""Account Manager sections, part 2: goals, all accounts, crest vault, events, reports and history, safety."""
from __future__ import annotations

import time

from . import safety
from .accounts import FIELDS, AccountError
from .crest_stats import RARITIES
from .gui_common import *  # noqa: F401,F403
from .gui_common import __all__ as _common_names  # noqa: F401
from .gui_forms import ago, form_dialog, parse_datetime, stamp
from .checklist import fmt_until
from .vault import VERDICTS

VERDICT_PILL = {"keep": "green", "review": "orange", "possible duplicate": "blue", "consider discarding": "red"}
GOAL_TYPE_LABELS = {"resource": "Reach an amount (gems, gold...)", "unit_level": "Get a unit to a level",
                    "crest": "Collect crests", "custom": "Something else (tracked by hand)"}
ACTIVITY_FILTERS = {"All": None, "Values": {"field"}, "Scans": {"scan"}, "Tasks": {"task"},
                    "Farming": {"session"}, "Goals": {"goal"}, "Alerts": {"alert"}}


class AccountsMoreMixin:

    # ================================================================ goals
    def _am_goals(self, p, a):
        aid = a["id"]
        right = self._am_title(p, "Goals & what to farm next",
                               "Goals read real numbers: your recorded values, your unit roster and the crest log. "
                               "Suggestions say why, and Rerun never spends gems, summons or anything else on its own.")
        ios.Button(right, "Add Goal", self.am_add_goal, icon="add", small=True).pack(side="right")
        recs = self.ops.goals.recommend(aid, self.m.scripts_available())
        body = self._am_card(p, "Suggested next")
        if not recs:
            self._am_empty(body, "Add a goal and Rerun will suggest which routine supports it.")
        for r in recs:
            line = tk.Frame(body, bg=C["card"])
            line.pack(fill="x", pady=px(4))
            col = tk.Frame(line, bg=C["card"])
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=f"{r['goal']}  →  {r['action']}", bg=C["card"], fg=C["label"], font=F["body_semi"], anchor="w").pack(fill="x")
            ios.wrapped_label(col, r["why"], font="footnote").pack(fill="x")
            if r["script"]:
                ios.Button(line, "Open in Macro Farming", lambda s=r["script"]: self.open_farming(s), kind="tinted", small=True).pack(side="right")
        prog = self.ops.goals.refresh(aid)
        for status, title in (("active", "Active goals"), ("done", "Reached")):
            items = [x for x in prog if x["goal"]["status"] == status]
            if not items and status == "done":
                continue
            body = self._am_card(p, title)
            if not items:
                self._am_empty(body, "None yet.")
            for x in items:
                g = x["goal"]
                line = tk.Frame(body, bg=C["card"])
                line.pack(fill="x", pady=px(5))
                top = tk.Frame(line, bg=C["card"])
                top.pack(fill="x")
                tk.Label(top, text=g["title"], bg=C["card"], fg=C["label"], font=F["body_semi"]).pack(side="left")
                ios.Pill(top, f"priority {g['priority']}", "gray").pack(side="left", padx=px(8))
                tk.Label(top, text=f"{x['current']:,} / {x['target']:,}" if x["current"] is not None else f"? / {x['target']:,}", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="right")
                b = ios.ProgressBar(line, color="green" if x["done"] else "blue")
                b.pack(fill="x", pady=(px(3), px(2)))
                b.after(50, lambda b=b, f=x["fraction"]: b.set(f))
                sub = tk.Frame(line, bg=C["card"])
                sub.pack(fill="x")
                note = f"Source: {x['source']}" + (f" · {x['remaining']:,} to go" if x["remaining"] else "") + \
                    (f" · reached {stamp(g['done_at'])}" if g["done_at"] else "")
                tk.Label(sub, text=note, bg=C["card"], fg=C["secondary"], font=F["caption"]).pack(side="left")
                ios.Button(sub, "Remove", lambda i=g["id"]: self._am_goal_remove(aid, i), kind="plain", color="red", small=True).pack(side="right")
                if status == "active":
                    ios.Button(sub, "Edit", lambda i=g["id"]: self.am_edit_goal(aid, i), kind="plain", small=True).pack(side="right", padx=(0, px(10)))
                    if g["type"] == "custom":
                        ios.Button(sub, "+1", lambda i=g["id"], m=g["manual"]: self._am_goal_edit(aid, i, manual=m + 1), kind="plain", small=True).pack(side="right", padx=(0, px(10)))
        hist = [(g, h) for g in a["goals"] for h in g["history"]]
        hist.sort(key=lambda gh: gh[1]["t"], reverse=True)
        body = self._am_card(p, "Goal history")
        if not hist:
            self._am_empty(body, "Nothing yet.")
        for g, h in hist[:8]:
            tk.Label(body, text=f"{stamp(h['t'])}   {g['title']}: {h['event']}", bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w").pack(fill="x")

    def _am_goal_edit(self, aid, gid, **kw):
        try:
            self.ops.goals.edit(aid, gid, **kw)
        except AccountError as e:
            self._am_error(e)

    def _am_goal_remove(self, aid, gid):
        if ios.confirm(self, "Remove this goal? It stays in the goal history.", "Remove Goal", ok="Remove", destructive=True):
            self.ops.goals.remove(aid, gid)

    def am_add_goal(self):
        aid = self.ops.store.active_id
        numeric = {FIELDS[k][0]: k for k in FIELDS if FIELDS[k][1] == "int"}
        fields = [dict(key="type", label="Goal type", kind="select", value=GOAL_TYPE_LABELS["crest"], options=list(GOAL_TYPE_LABELS.values())),
                  dict(key="title", label="Title", hint="e.g. Farm 3 Heavenly Light crests"),
                  dict(key="target", label="Target number", value="1", hint="Crests to collect, level to reach, amount to save, or steps"),
                  dict(key="rarity", label="Crest rarity (crest goals)", kind="select", value="", options=[""] + list(RARITIES)),
                  dict(key="palace", label="Palace name contains (crest goals, optional)"),
                  dict(key="unit", label="Unit name (unit goals)"),
                  dict(key="field", label="Value (amount goals)", kind="select", value="Gems", options=list(numeric)),
                  dict(key="priority", label="Priority (1 = most important)", value="5")]

        def save(v):
            gtype = next(k for k, lab in GOAL_TYPE_LABELS.items() if lab == v["type"])
            try:
                spec = {"resource": {"key": numeric[v["field"]]}, "unit_level": {"unit": v["unit"]},
                        "crest": {"rarity": v["rarity"], "palace": v["palace"]}, "custom": {}}[gtype]
                self.ops.goals.add(aid, gtype, v["title"], v["target"], int(v["priority"] or 5), **spec)
            except (AccountError, ValueError) as e:
                return str(e)
            return None
        form_dialog(self, "Add Goal", fields, save, ok="Add",
                    intro="Fill in the fields that match the goal type; the others are ignored.")

    def am_edit_goal(self, aid, gid):
        g = next(x for x in self.ops.store.get(aid)["goals"] if x["id"] == gid)

        def save(v):
            try:
                self.ops.goals.edit(aid, gid, title=v["title"], target=v["target"], priority=int(v["priority"] or 5))
            except (AccountError, ValueError) as e:
                return str(e)
            return None
        form_dialog(self, "Edit Goal", [dict(key="title", label="Title", value=g["title"]), dict(key="target", label="Target", value=g["target"]),
                                        dict(key="priority", label="Priority", value=g["priority"])], save)

    # ================================================================ all accounts / multi-account
    def _am_accounts(self, p, a):
        st = self.ops.store
        right = self._am_title(p, "All accounts",
                               "Every account keeps its own values, tasks, goals, crests, units and history. Nothing is shared between them.")
        ios.Button(right, "New Account", self.am_new, icon="add", small=True).pack(side="right")
        body = self._am_card(p, "Accounts")
        for acct in st.all():
            cl = self.ops.checklist.summary(acct["id"])
            line = tk.Frame(body, bg=C["card"])
            line.pack(fill="x", pady=px(5))
            col = tk.Frame(line, bg=C["card"])
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=acct["name"] + (f"  ·  {acct['label']}" if acct["label"] else ""), bg=C["card"], fg=C["label"], font=F["body_semi"], anchor="w").pack(fill="x")
            tk.Label(col, text=f"Emulator: {acct['instance'] or 'not linked'}   ·   daily {cl['daily']['done']}/{cl['daily']['total']}   ·   "
                               f"last scan {ago(acct['last_scan_ok'])}", bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w").pack(fill="x")
            if acct["id"] == st.active_id:
                ios.Pill(line, "Active", "green").pack(side="right")
            else:
                ios.Button(line, "Switch To", lambda i=acct["id"]: self._am_switch(i), kind="tinted", small=True).pack(side="right")
        body = self._am_card(p, "Emulator sharing and account switching")
        shared = {}
        for acct in st.all():
            if acct["instance"]:
                shared.setdefault(acct["instance"], []).append(acct["name"])
        lines = [f"{inst}: {', '.join(names)}" + ("   ← shared, you confirm which account is open before every start" if len(names) > 1 else "")
                 for inst, names in shared.items()] or ["No account is linked to an emulator yet."]
        for ln in lines:
            tk.Label(body, text=ln, bg=C["card"], fg=C["label"], font=F["footnote"], anchor="w").pack(fill="x")
        ios.wrapped_label(body, "\nWhat exists: each account is linked to an emulator; farming is attributed to the linked account; when several "
                                "accounts share an emulator Rerun refuses to start until you confirm which one is open (it cannot see which "
                                "account is logged in); limits and notifications are per account.\n"
                                "NOT automated: logging out and in to switch accounts. Rerun has no reader for the profile or login screens, so it "
                                "could not verify that the right account is open afterwards - and a wrong guess would farm on the wrong account. "
                                "That needs screenshots of those screens first.", font="footnote").pack(fill="x")
        body = self._am_card(p, "Run plan (what a future scheduler would run; nothing runs automatically)")
        avail = self.m.scripts_available()
        any_due = False
        for acct in st.all():
            due = self.ops.checklist.due_automatable(acct["id"], avail)
            if due:
                any_due = True
                tk.Label(body, text=f"{acct['name']}: " + " → ".join(f"{d['name']} ({avail[d['script']]})" for d in due), bg=C["card"], fg=C["label"], font=F["footnote"], anchor="w", justify="left").pack(fill="x")
        if not any_due:
            self._am_empty(body, "No automatable task is due on any account.")

    def _am_switch(self, aid):
        self.ops.use_account(aid)
        self._on_account_switched()

    # ================================================================ crest vault
    def _am_vault(self, p, a):
        aid = a["id"]
        right = self._am_title(p, "Inventory & Crest Vault",
                               "Crests come from the crest log (what Rerun saw while farming). Substats are not readable from the screen yet, so you "
                               "enter them. The vault only RECOMMENDS keep / review / duplicate / discard - Rerun never scraps, sells or discards anything.")
        ios.Button(right, "Add Crest", self.am_add_crest, icon="add", small=True).pack(side="right")
        ios.Button(right, "Rules", self.am_vault_rules, kind="tinted", icon="settings", small=True).pack(side="right", padx=(0, px(8)))
        items = self.ops.vault.items(aid)
        if not hasattr(self, "_vault_filter"):
            self._vault_filter = {"text": tk.StringVar(), "rarity": "", "verdict": "", "sort": "newest"}
        flt = self._vault_filter
        bar = tk.Frame(p, bg=C["bg"])
        bar.pack(fill="x", pady=(0, px(6)))
        ios.Field(bar, flt["text"], width=18).pack(side="left")
        flt["text"].trace_add("write", lambda *x: self._am_vault_fill())
        for key, label, vals in (("rarity", "Rarity", ["All"] + list(RARITIES)), ("verdict", "Advice", ["All"] + list(VERDICTS)),
                                 ("sort", "Sort", ["newest", "oldest", "rarity"])):
            tk.Label(bar, text=label, bg=C["bg"], fg=C["secondary"], font=F["footnote"]).pack(side="left", padx=(px(14), px(4)))
            sel = ios.Select(bar, values=vals, accent=True, command=lambda k=key: self._am_vault_set(k))
            sel.set(flt[key] or "All" if key != "sort" else flt[key])
            sel.pack(side="left")
            flt[key + "_sel"] = sel
        self._vault_summary = ios.wrapped_label(p, "")
        self._vault_summary.pack(fill="x")
        card = ios.Card(p, pad=6)
        card.pack(fill="x")
        cols = ("when", "rarity", "name", "palace", "substats", "advice")
        self.vault_tree = ttk.Treeview(card.body, columns=cols, show="headings", style="IOS.Treeview", selectmode="extended", height=12)
        for c, w, t in (("when", 130, "Found"), ("rarity", 60, "Rarity"), ("name", 160, "Crest"), ("palace", 130, "Palace"), ("substats", 220, "Substats"), ("advice", 150, "Advice")):
            self.vault_tree.heading(c, text=t)
            self.vault_tree.column(c, width=px(w), stretch=c in ("substats", "name"))
        self.vault_tree.pack(fill="x")
        self.vault_tree.bind("<<TreeviewSelect>>", lambda e: self._am_vault_detail())
        self._vault_items = items
        self._vault_detail_lbl = ios.wrapped_label(p, "Select a crest to see why it got its advice. Select two to compare them.", font="footnote")
        self._vault_detail_lbl.pack(fill="x", pady=(px(8), 0))
        btns = tk.Frame(p, bg=C["bg"])
        btns.pack(fill="x", pady=(px(8), 0))
        ios.Button(btns, "Edit Substats / Note", self.am_edit_crest, kind="tinted", small=True).pack(side="left")
        ios.Button(btns, "Compare Selected", self.am_compare_crests, kind="plain", small=True).pack(side="left", padx=px(10))
        ios.Button(btns, "Remove Hand-Added", self.am_remove_crest, kind="plain", color="red", small=True).pack(side="right")
        self._am_vault_fill()

    def _am_vault_set(self, key):
        v = self._vault_filter[key + "_sel"].get()
        self._vault_filter[key] = "" if v == "All" else v
        self._am_vault_fill()

    def _am_vault_fill(self):
        if not hasattr(self, "vault_tree") or not self.vault_tree.winfo_exists():
            return
        f = self._vault_filter
        shown = self.ops.vault.search(self._vault_items, f["text"].get(), f["rarity"], f["verdict"], f["sort"])
        self.vault_tree.delete(*self.vault_tree.get_children())
        for i in shown:
            self.vault_tree.insert("", "end", iid=i["key"], values=(stamp(i["t"]), i["rarity"], i["name"] or "(unnamed)", i["palace"], ", ".join(i["substats"]) or "-", i["verdict"]))
        dups = self.ops.vault.duplicates(self.ops.store.active_id)
        self._vault_summary.configure(text=f"{len(shown)} of {len(self._vault_items)} crest(s) shown · {len(dups)} group(s) of possible duplicates"
                                           + ("" if self._vault_items else " · No crests recorded for this account yet (farm with the Crest script, or add one by hand)."))

    def _selected_crests(self):
        keys = self.vault_tree.selection()
        return [i for i in self._vault_items if i["key"] in keys]

    def _am_vault_detail(self):
        sel = self._selected_crests()
        if len(sel) == 1:
            i = sel[0]
            self._vault_detail_lbl.configure(text=f"{i['name'] or 'Unnamed crest'} ({i['rarity']}): {i['verdict']} - {i['why']}. "
                                                  f"Source: {'crest log' if i['source'] == 'ledger' else 'added by hand'}; action taken when found: {i['action'] or '-'}."
                                                  + (f" Note: {i['note']}" if i["note"] else ""))

    def am_add_crest(self):
        aid = self.ops.store.active_id

        def save(v):
            try:
                self.ops.vault.add_manual(aid, v["rarity"], v["name"], [s for s in v["substats"].split(",")], v["palace"], v["note"])
            except AccountError as e:
                return str(e)
            return None
        form_dialog(self, "Add Crest By Hand", [dict(key="rarity", label="Rarity", kind="select", value="4+", options=list(RARITIES)), dict(key="name", label="Crest name"),
                                                dict(key="substats", label="Substats (comma separated)", hint="e.g. ATK +12%, Crit +5%"), dict(key="palace", label="Palace (optional)"),
                                                dict(key="note", label="Note")], save, ok="Add")

    def am_edit_crest(self):
        sel = self._selected_crests()
        if len(sel) != 1:
            ios.alert(self, "Select one crest first.")
            return
        i, aid = sel[0], self.ops.store.active_id

        def save(v):
            try:
                self.ops.vault.annotate(aid, i["key"], substats=v["substats"].split(","), note=v["note"], name=v["name"] or None)
            except AccountError as e:
                return str(e)
            return None
        form_dialog(self, "Crest Details", [dict(key="name", label="Name", value=i["name"]), dict(key="substats", label="Substats (comma separated)", value=", ".join(i["substats"])),
                                            dict(key="note", label="Note", value=i["note"])], save)

    def am_compare_crests(self):
        sel = self._selected_crests()
        if len(sel) != 2:
            ios.alert(self, "Select exactly two crests to compare.")
            return
        a, b = sel
        rows = [("Name", a["name"] or "-", b["name"] or "-"), ("Rarity", a["rarity"], b["rarity"]), ("Palace", a["palace"] or "-", b["palace"] or "-"),
                ("Substats", ", ".join(a["substats"]) or "-", ", ".join(b["substats"]) or "-"), ("Advice", a["verdict"], b["verdict"]), ("Found", stamp(a["t"]), stamp(b["t"]))]
        ios.alert(self, "\n".join(f"{k}:  {x}   |   {y}" for k, x, y in rows), "Compare Crests")

    def am_remove_crest(self):
        sel = [i for i in self._selected_crests() if i["source"] == "manual"]
        if not sel:
            ios.alert(self, "Only crests you added by hand can be removed. Crests from the crest log are a record of what happened.")
            return
        for i in sel:
            self.ops.vault.remove_manual(self.ops.store.active_id, i["key"])
        self._am_render()

    def am_vault_rules(self):
        aid = self.ops.store.active_id
        r = self.ops.vault.rules(aid)

        def save(v):
            try:
                self.ops.vault.set_rules(aid, keep_rarities=[x.strip() for x in v["keep"].split(",") if x.strip()],
                                         discard_rarities=[x.strip() for x in v["discard"].split(",") if x.strip()],
                                         wanted_substats=[x.strip() for x in v["wanted"].split(",") if x.strip()], duplicate_limit=v["dup"])
            except (AccountError, ValueError) as e:
                return str(e)
            return None
        if form_dialog(self, "Crest Rules", [dict(key="keep", label="Always keep these rarities", value=", ".join(r["keep_rarities"]), hint=f"Choose from: {', '.join(RARITIES)}"),
                                             dict(key="discard", label="Suggest discarding these rarities (when no wanted substat)", value=", ".join(r["discard_rarities"])),
                                             dict(key="wanted", label="Wanted substats (words to match)", value=", ".join(r["wanted_substats"]), hint="e.g. atk, crit"),
                                             dict(key="dup", label="Same crest more than this many times = possible duplicate", value=r["duplicate_limit"])], save,
                       intro="These rules only change the advice shown. Rerun never acts on it."):
            self._am_render()

    # ================================================================ events
    def _am_events(self, p, a):
        aid = a["id"]
        right = self._am_title(p, "Events",
                               "Add limited-time events by hand. There is no verified shared event list, so none is imported; "
                               "Rerun will not trust an unofficial source for dates. Reminders go to Discord (set per account in Safety & settings).")
        ios.Button(right, "Add Event", lambda: self.am_event_form(), icon="add", small=True).pack(side="right")
        now = time.time()
        evs = sorted(self.ops.store.events(), key=lambda e: e["end"])
        body = self._am_card(p, "Upcoming and active")
        shown = [e for e in evs if e["end"] >= now]
        if not shown:
            self._am_empty(body, "No upcoming events. Add one with its start and end dates.")
        for e in shown:
            done = e["id"] in a["event_done"]
            active = e["start"] <= now
            line = tk.Frame(body, bg=C["card"])
            line.pack(fill="x", pady=px(5))
            col = tk.Frame(line, bg=C["card"])
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=e["title"], bg=C["card"], fg=C["label"], font=F["body_semi"], anchor="w").pack(fill="x")
            when = f"ends in {fmt_until(e['end'] - now)}" if active else f"starts {stamp(e['start'])}"
            tk.Label(col, text=f"{when} · ends {stamp(e['end'])}" + (f" · goal: {e['goal']}" if e["goal"] else ""), bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w").pack(fill="x")
            if e["description"]:
                ios.wrapped_label(col, e["description"], font="caption").pack(fill="x")
            ios.Pill(line, "Done" if done else ("Active" if active else "Upcoming"), "green" if done else ("blue" if active else "gray")).pack(side="right", padx=(px(8), 0))
            ios.Button(line, "Delete", lambda i=e["id"]: self._am_event_delete(i), kind="plain", color="red", small=True).pack(side="right", padx=(px(8), 0))
            ios.Button(line, "Edit", lambda ev=e: self.am_event_form(ev), kind="plain", small=True).pack(side="right", padx=(px(8), 0))
            ios.Button(line, "Not done" if done else "Mark done", lambda i=e["id"], d=done: self.ops.store.set_event_done(aid, i, not d), kind="tinted", small=True).pack(side="right")
        past = [e for e in evs if e["end"] < now]
        if past:
            body = self._am_card(p, "Ended")
            for e in past[-6:]:
                tk.Label(body, text=f"{e['title']} · ended {stamp(e['end'])} · " + ("completed" if e["id"] in a["event_done"] else "not marked done"), bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w").pack(fill="x")

    def am_event_form(self, ev: dict | None = None):
        def save(v):
            try:
                self.ops.store.save_event(v["title"], parse_datetime(v["start"]), parse_datetime(v["end"]), v["description"], v["goal"], ev["id"] if ev else "")
            except (AccountError, ValueError) as e:
                return str(e)
            return None
        today = time.strftime("%Y-%m-%d")
        form_dialog(self, "Edit Event" if ev else "Add Event",
                    [dict(key="title", label="Title", value=ev["title"] if ev else ""), dict(key="start", label="Starts", value=stamp(ev["start"]) if ev else today, hint="YYYY-MM-DD or YYYY-MM-DD HH:MM, your local time"),
                     dict(key="end", label="Ends", value=stamp(ev["end"]) if ev else ""), dict(key="goal", label="Event goal (optional)", value=ev["goal"] if ev else ""),
                     dict(key="description", label="Description", kind="multiline", value=ev["description"] if ev else "")], save)

    def _am_event_delete(self, eid):
        if ios.confirm(self, "Delete this event for all accounts?", "Delete Event", ok="Delete", destructive=True):
            self.ops.store.delete_event(eid)

    # ================================================================ reports + history
    def _am_reports(self, p, a):
        aid = a["id"]
        right = self._am_title(p, "Reports & activity history")
        discord_up = bool(self.m.discord)
        b = ios.Button(right, "Send To Discord", lambda: self._am_send_report(aid), kind="tinted", icon="send", small=True)
        b.pack(side="right")
        b.set_enabled(discord_up)
        card, t = ios.text_box(p, mono=True)
        t.configure(height=11)
        t.insert("1.0", self.ops.daily_report(aid).replace("**", ""))
        t.configure(state="disabled")
        if not discord_up:
            ios.wrapped_label(p, "Discord is not connected, so the report can't be sent. It is generated from this account's data only.").pack(fill="x", pady=(px(4), 0))
        if not hasattr(self, "_act_filter"):
            self._act_filter = tk.StringVar(value="All")
        ios.section_header(p, "Activity", padx=px(4), pady=(px(14), px(6)))
        ios.Segmented(p, list(ACTIVITY_FILTERS), self._act_filter, command=self._am_render).pack(anchor="w", pady=(0, px(6)))
        kinds = ACTIVITY_FILTERS[self._act_filter.get()]
        rows = [x for x in reversed(self.ops.store.activity(aid, 400)) if kinds is None or x["kind"] in kinds][:60]
        body = self._am_card(p)
        if not rows:
            self._am_empty(body, "Nothing recorded yet.")
        for x in rows:
            tk.Label(body, text=f"{stamp(x['t'])}   {x['kind']:<8} {x['detail']}", bg=C["card"], fg=C["label"], font=F["mono"], anchor="w", justify="left").pack(fill="x")

    def _am_send_report(self, aid):
        if not self.m.discord:
            self._am_error("Discord is not connected.")
            return
        self.m.discord.send(self.ops.daily_report(aid), None, False)
        self.flash("Report sent to Discord", "ok")

    # ================================================================ safety + settings
    def _am_safety(self, p, a):
        aid = a["id"]
        self._am_title(p, "Safety & settings")
        ios.Banner(p, safety.TOS_WARNING, "orange", "Terms of Service").pack(fill="x", pady=(0, px(6)))
        ios.wrapped_label(p, safety.SAFETY_NOTE).pack(fill="x", pady=(0, px(8)))
        s, n = a["safety"], a["notify"]
        g = ios.Group(p, header="Automation for this account")
        g.pack(fill="x")
        v1, v2 = tk.BooleanVar(value=s["automation_allowed"]), tk.BooleanVar(value=s["dry_run"])
        ios.Switch(g.row("Allow automation", "Off = Rerun refuses to start any script for this account."), v1,
                   command=lambda: self._am_set(aid, "safety", automation_allowed=v1.get())).pack()
        ios.Switch(g.row("Dry-run mode", "Scripts run but nothing is tapped: Rerun lists what it WOULD do, then stops."), v2,
                   command=lambda: self._am_set(aid, "safety", dry_run=v2.get())).pack()
        for key, label, sub in (("daily_minutes_limit", "Daily limit (minutes)", "Farming minutes per game day (6 AM UTC-6). 0 = no limit."),
                                ("session_minutes_limit", "Session limit (minutes)", "A single run is stopped after this long. 0 = no limit.")):
            var = tk.StringVar(value=str(s[key]))
            f = ios.Field(g.row(label, sub), var, width=6, justify="right")
            f.pack()
            for ev in ("<FocusOut>", "<Return>"):
                f.entry.bind(ev, lambda e, k=key, v=var: self._am_set(aid, "safety", **{k: v.get()}), add="+")
        scripts = tk.StringVar(value=", ".join(s["allowed_scripts"]))
        f = ios.Field(g.row("Only allow these scripts", "Script ids separated by commas, e.g. crest, login_mail. Blank = all."), scripts, width=24)
        f.pack()
        for ev in ("<FocusOut>", "<Return>"):
            f.entry.bind(ev, lambda e: self._am_set(aid, "safety", allowed_scripts=[x.strip() for x in scripts.get().split(",") if x.strip()]), add="+")
        ios.Button(g.row("Emergency stop", "Stops every running script on every emulator at once (also F12)."), "Stop Everything", self.stop_all, kind="filled", color="red", small=True).pack()
        g = ios.Group(p, header="Discord alerts for this account", footer="Alerts are sent once per game day and respect your quiet hours and ping settings.")
        g.pack(fill="x", pady=(px(16), 0))
        for key, label, sub in (("enabled", "Send Discord messages", "Off = nothing for this account reaches Discord."), ("daily_report", "Daily report", "At the daily summary time."),
                                ("failures", "Failed or interrupted routines", ""), ("low_energy", "Low energy", "Uses the alert level below."),
                                ("event_warnings", "Event expiry warnings", ""), ("ping", "@mention me", "Off = this account's alerts never ping you.")):
            v = tk.BooleanVar(value=n[key])
            ios.Switch(g.row(label, sub or None), v, command=lambda k=key, vv=v: self._am_set(aid, "notify", **{k: vv.get()})).pack()
        for key, label, sub in (("low_energy_below", "Low-energy level", "Alert when energy is below this. 0 = off."), ("event_warn_hours", "Event warning (hours before end)", "")):
            var = tk.StringVar(value=str(n[key]))
            f = ios.Field(g.row(label, sub or None), var, width=6, justify="right")
            f.pack()
            for ev in ("<FocusOut>", "<Return>"):
                f.entry.bind(ev, lambda e, k=key, vv=var: self._am_set(aid, "notify", **{k: vv.get()}), add="+")

    def _am_set(self, aid, section, **kw):
        try:
            self.ops.store.update_settings(aid, section, **kw)
        except AccountError as e:
            self._am_error(e)
