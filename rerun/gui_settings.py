"""Settings tab and the first-run setup check.

Moved verbatim from rerun/gui.py (class App); App inherits SettingsMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class SettingsMixin:

    # ================================================================ settings
    def _build_settings(self):
        """Routine settings (per emulator and script). Built into the Macro Farming workspace."""
        _, page, shdr = self._page("Routine Settings", "Settings", "settings", scroll=True)
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="x", padx=px(20))
        g = ios.Group(wrap)
        g.pack(fill="x")
        self.set_inst = ios.Select(g.row("Instance"), command=self._load_settings_form)
        self.set_inst.pack()
        self.set_script = ios.Select(g.row("Script"),
                                     values=[c.display_name() for c in SCRIPTS.values()],
                                     command=self._load_settings_form)
        self.set_script.pack()
        self.form = tk.Frame(wrap, bg=C["bg"])
        self.form.pack(fill="x", pady=(px(24), 0))
        bar = tk.Frame(wrap, bg=C["bg"])
        bar.pack(fill="x", pady=(px(14), 0))
        ios.Button(bar, "Save Settings", self._save_settings_form, icon="save").pack(side="left")
        self._label(bar, "Changes apply the next time the script starts.").pack(side="left", padx=px(12))
        self.form_vars: dict[str, tk.Variable] = {}
        self.set_script.current(1)

    def _build_app_settings(self):
        """App-wide settings: theme, tray, start options, logging, updates."""
        _, page, shdr = self._page("Settings", "Settings", "settings", scroll=True)
        ios.Button(shdr, "Import from another Rerun…", self.import_old_data, kind="plain",
                   icon="download", small=True).pack(side="right")
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="x", padx=px(20))
        g2 = ios.Group(wrap, header="App", footer="Theme applies the next time Rerun opens.")
        g2.pack(fill="x", pady=(px(30), px(24)))
        self.appearance = ios.Select(g2.row("Theme"), values=list(APPEARANCE.values()),
                                     command=self._save_appearance)
        self.appearance.set(APPEARANCE.get(str(self.m.config.get("appearance", "auto")), "Automatic"))
        self.appearance.pack()
        self.close_to_tray = tk.BooleanVar(value=bool(self.m.config.get("close_to_tray", True)))
        ios.Switch(g2.row("Keep running in the tray", "Closing the window hides Rerun next to "
                          "the clock instead of quitting. Quit from the tray icon's menu."),
                   self.close_to_tray, command=self._save_close_to_tray).pack()
        ui = self.m.config.get("ui") or {}
        self.ui_vars = {
            "start_minimized": tk.BooleanVar(value=bool(ui.get("start_minimized"))),
            "autostart": tk.BooleanVar(value=bool(ui.get("autostart"))),
            "confirm_stop_all": tk.BooleanVar(value=bool(ui.get("confirm_stop_all"))),
        }
        ios.Switch(g2.row("Start minimized to the tray", "Opens hidden next to the clock. Needs the tray "
                          "icon; ignored on a first run."),
                   self.ui_vars["start_minimized"], command=self._save_ui_options).pack()
        ios.Switch(g2.row("Start scripts when Rerun opens", "Starts every instance's script a few seconds "
                          "after Rerun opens - handy after a reboot. Check the settings first."),
                   self.ui_vars["autostart"], command=self._save_ui_options).pack()
        ios.Switch(g2.row("Confirm before Stop All", "Asks when you press the Stop All button. The F12 "
                          "hotkey and the tray menu never ask."),
                   self.ui_vars["confirm_stop_all"], command=self._save_ui_options).pack()
        ios.Button(g2.row("Setup check", "Checks ADB, your instances, screen size, templates "
                          "and the text reader, with a fix for anything missing."),
                   "Run", self.open_setup_check, kind="tinted", small=True).pack()

        lg = self.m.config.get("logging") or {}
        g4 = ios.Group(wrap, header="Logging",
                       footer="rerun.log (next to Rerun) keeps what the Log tab shows, across restarts. "
                              "Applies right away.")
        g4.pack(fill="x", pady=(0, px(24)))
        self.log_file_level = ios.Select(g4.row("Write to rerun.log", "Which lines are saved to the file."),
                                         values=list(LOG_FILE_LEVELS.values()), command=self._save_logging)
        self.log_file_level.set(LOG_FILE_LEVELS.get(str(lg.get("file_level", "all")), "Everything"))
        self.log_file_level.pack()
        self.log_vars = {}
        for key, label, sub, default in (
                ("file_mb", "File size (MB)", "A new file starts when this is reached (0.1 - 100).", 1),
                ("file_count", "Old files kept", "rerun.log.1, .2 ... (1 - 20).", 3),
                ("memory_lines", "Lines in the Log tab", "Older lines drop off (500 - 20000).", 3000)):
            self.log_vars[key] = tk.StringVar(value=str(lg.get(key, default)))
            fld = ios.Field(g4.row(label, sub), self.log_vars[key], width=7, justify="right")
            fld.pack()
            fld.entry.bind("<FocusOut>", lambda e: self._save_logging(), add="+")
            fld.entry.bind("<Return>", lambda e: self._save_logging(), add="+")

        us = updates.settings(self.m.config)
        g3 = ios.Group(wrap, header="Updates",
                       footer="New templates and routines install by themselves (any you captured "
                              "or edited are kept). A new Rerun asks first, then restarts; your "
                              "settings and data stay.")
        g3.pack(fill="x", pady=(0, px(24)))
        self.upd_check = tk.BooleanVar(value=us["check"])
        ios.Switch(g3.row("Check for updates", "When Rerun opens and every few hours."),
                   self.upd_check, command=self._save_update_settings).pack()
        self.upd_channel = ios.Select(g3.row("Channel", "Beta gets fixes first, with less testing."),
                                      values=["Stable", "Beta"], command=self._save_update_settings)
        self.upd_channel.set(us["channel"].title())
        self.upd_channel.pack()
        right = g3.row(f"Rerun {__version__}", " ")
        ios.Button(right, "Check Now", self.check_updates, kind="tinted", small=True).pack()
        # the row's grey subtitle doubles as the update status line
        self.upd_status = right.master.winfo_children()[1].winfo_children()[1]
        self._set_update_status(self._update_idle_text())

    # setup check ------------------------------------------------------------
    def open_setup_check(self):
        """A sheet listing every requirement with a green/red badge and a fix."""
        if getattr(self, "_setup_win", None) is not None and self._setup_win.winfo_exists():
            self._setup_win.lift()
            return
        win = tk.Toplevel(self, bg=C["bg"])
        win.title("Setup Check")
        win.geometry(f"{px(620)}x{px(640)}")
        win.transient(self)
        win.iconphoto(False, self._icon)
        self._setup_win = win
        self.after(10, lambda: ios.style_window(win))
        hdr = ios.page_header(win, "Setup Check")
        ios.Button(hdr, "Check Again", self._run_setup_check, kind="tinted", icon="sync",
                   small=True).pack(side="right")
        self._setup_body = tk.Frame(win, bg=C["bg"])
        self._setup_body.pack(fill="both", expand=True, padx=px(20), pady=(0, px(16)))
        self.m.config["setup_seen"] = True
        self.m.save_config()
        self._run_setup_check()

    def _run_setup_check(self):
        body = self._setup_body
        for w in body.winfo_children():
            w.destroy()
        self._label(body, "Checking ADB, your instances and the text reader…").pack(anchor="w")

        def work():
            from .setup_check import run_checks
            try:
                checks = run_checks(self.m)
            except Exception as e:  # noqa: BLE001
                checks = []
                self.events.put({"type": "_error", "message": f"Setup check failed: {e}"})
            self.events.put({"type": "_setup", "checks": checks})
        threading.Thread(target=work, daemon=True).start()

    def _show_setup_results(self, checks):
        body = getattr(self, "_setup_body", None)
        if body is None or not body.winfo_exists():
            return
        for w in body.winfo_children():
            w.destroy()
        bad = sum(not c.ok for c in checks)
        self._label(body, "Everything Rerun needs is in place." if not bad else
                    f"{bad} thing(s) need attention.", secondary=False, font="body_semi"
                    ).pack(anchor="w", pady=(0, px(10)))
        card = ios.Card(body)
        card.pack(fill="x")
        fixes = {"detect": ("Detect", self.detect_instances),
                 "import": ("Import", self.tpl_import_restart),
                 "adb_help": ("How?", lambda: ios.alert(self, ADB_HELP, "Turn On ADB")),
                 "display_help": ("How?", lambda: ios.alert(self, DISPLAY_HELP, "Screen Size")),
                 "discord_tab": ("Open", lambda: (self.nb.select(self._tab_discord),
                                                  self._setup_win.destroy()))}
        for i, c in enumerate(checks):
            if i:
                tk.Frame(card.body, height=1, bg=C["sep"]).pack(fill="x", padx=(px(40), 0))
            row = tk.Frame(card.body, bg=C["card"])
            row.pack(fill="x")
            tk.Label(row, image=ios.badge("ok" if c.ok else "missing"), bg=C["card"]).pack(
                side="left", padx=(px(12), px(10)), pady=px(10), anchor="n")
            if c.fix and not c.ok and c.fix in fixes:
                label, fn = fixes[c.fix]
                ios.Button(row, label, fn, kind="tinted", small=True).pack(side="right", padx=px(12))
            txt = tk.Frame(row, bg=C["card"])
            txt.pack(side="left", fill="x", expand=True, pady=px(8))
            tk.Label(txt, text=c.title, bg=C["card"], fg=C["label"], font=F["body"],
                     anchor="w").pack(fill="x")
            tk.Label(txt, text=c.detail, bg=C["card"], fg=C["secondary"], font=F["footnote"],
                     anchor="w", justify="left", wraplength=px(430)).pack(fill="x")

    def _save_appearance(self):
        key = next(k for k, v in APPEARANCE.items() if v == self.appearance.get())
        self.m.config["appearance"] = key
        self.m.save_config()
        self.flash(f"Theme set to {APPEARANCE[key]} - restart Rerun to apply", "ok")

    def _save_ui_options(self):
        ui = self.m.config.setdefault("ui", {})
        for key, var in self.ui_vars.items():
            ui[key] = bool(var.get())
        self.m.save_config()

    def _save_logging(self):
        lg = self.m.config.setdefault("logging", {})
        lg["file_level"] = next((k for k, v in LOG_FILE_LEVELS.items() if v == self.log_file_level.get()), "all")
        for key, lo, hi, cast in (("file_mb", 0.1, 100.0, float), ("file_count", 1, 20, int),
                                  ("memory_lines", 500, 20000, int)):
            try:
                value = cast(self.log_vars[key].get().strip().replace(",", "."))
            except ValueError:
                value = (self.m.config["logging"].get(key) or lo)
            value = max(lo, min(value, hi))
            lg[key] = int(value) if cast is int or float(value).is_integer() else value
            self.log_vars[key].set(str(lg[key]))          # show what was actually kept
        self.m.save_config()
        self.m.apply_logging()

    def _save_close_to_tray(self):
        self.m.config["close_to_tray"] = bool(self.close_to_tray.get())
        self.m.save_config()

    def _refresh_instance_lists(self):
        names = list(self.m.instances)
        for box in (self.set_inst, getattr(self, "tpl_inst", None)):
            if box is None:
                continue
            box["values"] = names
            if box.get() not in names and names:
                box.set(names[0])
        for box in (getattr(self, "log_inst", None), getattr(self, "hist_inst", None)):
            if box is not None:
                box["values"] = [ALL_INSTANCES] + names
        if not self.form_vars and names:
            self._load_settings_form()

    def _settings_script_id(self) -> str | None:
        for k, c in SCRIPTS.items():
            if c.display_name() == self.set_script.get():
                return k
        return None

    def _load_settings_form(self):
        for w in self.form.winfo_children():
            w.destroy()
        self.form_vars = {}
        inst, sid = self.set_inst.get(), self._settings_script_id()
        if not inst or not sid:
            return
        values = self.m.script_settings(inst, sid)
        g = ios.Group(self.form, header=f"{SCRIPTS[sid].display_name()} · {inst}")
        g.pack(fill="x")
        for s in SCRIPTS[sid].SETTINGS:
            right = g.row(s.label, s.help or None)
            if s.type == "bool":
                var = tk.BooleanVar(value=bool(values.get(s.key)))
                ios.Switch(right, var).pack()
            elif s.type == "choice":
                var = tk.StringVar(value=str(values.get(s.key)))
                ios.Select(right, values=s.choices, variable=var).pack()
            elif s.type == "int":
                var = tk.StringVar(value=str(values.get(s.key)))
                ios.Stepper(right, var).pack()
            else:
                var = tk.StringVar(value=str(values.get(s.key)))
                ios.Field(right, var, width=26).pack()
            self.form_vars[s.key] = var
        # Per-instance daily schedule (starts whatever script the instance is set to).
        sch = (self.m.config.get("schedules") or {}).get(inst, {})
        gs = ios.Group(self.form, header=f"Schedule · {inst}",
                       footer="Starts this instance's script (the one chosen on the Dashboard) "
                              "every day at that time, using your PC's clock. Use a Chain to "
                              "run several scripts in a row.")
        gs.pack(fill="x", pady=(px(24), 0))
        self.sched_on = tk.BooleanVar(value=bool(sch.get("enabled")))
        ios.Switch(gs.row("Start every day"), self.sched_on).pack()
        self.sched_time = tk.StringVar(value=str(sch.get("time", "06:05")))
        ios.Field(gs.row("At (24-hour HH:MM)"), self.sched_time, width=6, justify="right").pack()

    def _save_settings_form(self):
        inst, sid = self.set_inst.get(), self._settings_script_id()
        if not inst or not sid:
            return
        out = {}
        for s in SCRIPTS[sid].SETTINGS:
            raw = self.form_vars[s.key].get()
            if s.type == "int":
                try:
                    out[s.key] = max(0, int(str(raw).strip() or 0))
                except ValueError:
                    ios.alert(self, f"'{s.label}' must be a whole number.")
                    return
            elif s.type == "bool":
                out[s.key] = bool(raw)
            else:
                out[s.key] = raw
        if sid == "chain":
            from .scripts.chain import parse_steps
            try:
                parse_steps(out.get("steps", ""))
            except ValueError as e:
                ios.alert(self, str(e), "Chain Steps")
                return
        t = self.sched_time.get().strip()
        if self.sched_on.get() and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            ios.alert(self, "Write the schedule time as HH:MM, e.g. 06:05 or 21:30.", "Schedule")
            return
        self.m.config.setdefault("schedules", {})[inst] = {"enabled": bool(self.sched_on.get()),
                                                           "time": t}
        self.m.save_script_settings(inst, sid, out)
        self.flash(f"Saved {SCRIPTS[sid].NAME} settings for {inst} (applies next Start)", "ok")
