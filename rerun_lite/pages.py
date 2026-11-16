"""The pages LITE builds, each drawn by the ORIGINAL page builder:

  Auto Crest   _build_dashboard (emulators, Start / Dry Run / Pause / Stop, totals, crest counts, instructions,
               Live View), minus the script chooser and the unit Compendium line
  Settings     _build_settings (the Crest entry, the palace selector), _build_discord, _build_app_settings, _build_log,
               behind one grouped side list

History and Templates are the original pages as they are (built by LiteApp.__init__).
"""
from __future__ import annotations

import tkinter as tk

from rerun import ios
from rerun.ios import C, px
from rerun.safety import TOS_WARNING
from rerun.scripts import SCRIPTS

from . import APP_NAME, LITE_SCRIPTS, MAIN_SCRIPT, __version__
from .theme import GroupedNav

# The original page builders name their page; LITE shows the Dashboard under the feature's own name.
PAGE_NAMES = {"Dashboard": ("Auto Crest", "Auto Crest", "home"), "Settings": ("General", "Settings", "settings")}
# Settings side list: one entry per script (the original page has a Script chooser; here the list is the chooser),
# then Discord, then the app's own pages. A caption is drawn above the entries named in SETTINGS_HEADS.
SETTINGS_SECTIONS = [(MAIN_SCRIPT, "Auto Crest"), ("palaces", "Palace Selector"), ("profiles", "Profiles"),
                     ("discord", "Discord"), ("notifications", "Notifications"), ("appearance", "Appearance"), ("shortcuts", "Keyboard shortcuts"), ("app", "General"),
                     ("sessions", "Sessions"), ("health", "Health"), ("log", "Log")]
SETTINGS_HEADS = {MAIN_SCRIPT: "Automation", "discord": "Alerts", "appearance": "App", "sessions": "Activity"}
SCHEDULE_NOTE = ("Starts Crest on this emulator every day at that time, using your PC's clock. "
                 "Crest is the only script ReRun LITE runs.")


def _labels(root: tk.Misc):
    """Every Label under `root`."""
    for w in root.winfo_children():
        if isinstance(w, tk.Label):
            yield w
        yield from _labels(w)


class PagesMixin:
    def _page(self, title: str, tab: str, icon: str, scroll: bool = False):
        shown, tab, icon = PAGE_NAMES.get(title, (title, tab, icon))
        res = super()._page(shown, tab, icon, scroll)
        if title == "Routine Settings":                      # its title follows the script picked in the side list
            self._rs_title = res[2].master.winfo_children()[0]
        return res

    def _build_crest(self):
        """Auto Crest: the original Dashboard page as it is, without the script chooser (an emulator in LITE
        always runs Crest) and without the unit Compendium line (Units are not part of LITE)."""
        self._tab_crest = self.nb.count()
        self._build_dashboard()
        page, hdr = self._last_page, self.key_timer.master
        banner = ios.Banner(page, TOS_WARNING, "orange")
        banner.pack(fill="x", padx=px(20), pady=(0, px(8)), after=hdr.master)
        self._make_ready_notice(page, banner)           # "needs setup" strip, shown only when something is missing
        ios.Button(hdr, "Crest Settings", lambda: self.open_script_settings(MAIN_SCRIPT), kind="plain",
                   icon="settings", small=True).pack(side="right", padx=(0, px(18)))
        group = self.script_box.master
        while group is not None and not isinstance(group, ios.Group):
            group = group.master
        if group is not None:
            group.pack_forget()
        self.comp_line.pack_forget()
        note = self.crest_note                    # wraps instead of running off a narrow window
        note.bind("<Configure>", lambda e: note.configure(wraplength=max(px(200), e.width - 4)), add="+")

    def _build_lite_settings(self):
        """Settings: the original script-settings, Discord, App and Log pages, behind one grouped side list."""
        page = tk.Frame(self.nb.content, bg=C["bg"])
        self.nb.add(page, "Settings", "settings")
        self._tab_settings = self.nb.count() - 1
        body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=px(12), pady=(px(10), px(10)))
        self._set_nav = GroupedNav(body, SETTINGS_SECTIONS, self._set_show, SETTINGS_HEADS)
        self._set_nav.pack(side="left", fill="y")
        self._set_stage = tk.Frame(body, bg=C["bg"])
        self._set_stage.pack(side="left", fill="both", expand=True, padx=(px(8), 0))
        self._set_pages: dict[str, tk.Misc] = {}
        for key, build in (("scripts", self._build_settings), ("palaces", self._build_palace_page), ("profiles", self._build_profiles_page), ("discord", self._build_discord), ("notifications", self._build_notify_page), ("appearance", self._build_appearance_page),
                           ("shortcuts", self._build_shortcuts_page),
                           ("app", self._build_app_settings), ("sessions", self._build_sessions_page), ("health", self._build_health_page), ("log", self._build_log)):
            self._host = self._set_stage
            try:
                build()
            finally:
                self._host = None
            self._set_pages[key] = self._last_page
        # the original opens the Discord page with nb.select(self._tab_discord): here it is a section
        self._tab_discord = "discord"
        self.nb.alias["discord"] = (self._tab_settings, lambda: self._set_nav.select("discord"))
        for key in ("discord", "app"):                           # these two pages talk about the app by name
            for lb in _labels(self._set_pages[key]):
                text = str(lb.cget("text"))
                if "Rerun" in text:
                    lb.configure(text=text.replace("Rerun", APP_NAME))
        title = self.upd_status.master.winfo_children()[0]       # the "Rerun x.y.z" row of the Updates group
        title.configure(text=f"{APP_NAME} {__version__}")
        row = self.set_script.master.master                      # the original's "Script" row: the side list replaces it
        kids = row.master.winfo_children()
        for w in (kids[kids.index(row) - 1], row):               # the row and the divider above it
            w.pack_forget()
        self._set_nav.select(MAIN_SCRIPT, notify=False)
        self._set_show(MAIN_SCRIPT, load=False)

    def _lite_script_lists(self):
        """The two script pickers (settings, template checklist) list LITE's scripts, Crest first. The Templates
        page's hint is given a wrap width that follows the window (LITE's window may be narrower than its text)."""
        names = list(self.m.scripts_available().values())
        for box in (self.set_script, self.tpl_script):
            box["values"] = names
            box.set(names[0])
        for w in self.tpl_inst.master.master.winfo_children():
            if isinstance(w, tk.Label):
                w.bind("<Configure>", lambda e, w=w: w.configure(wraplength=max(px(200), e.width - 4)), add="+")

    def _set_show(self, key: str, load: bool = True):
        for w in self._set_stage.winfo_children():
            w.pack_forget()
        if key == "palaces":
            self._pal_build()                         # fresh list, today and picture checks
        elif key == "sessions":
            self._sess_refresh()
        elif key == "profiles":
            self._prof_refresh()
        elif key == "health":
            self._health_refresh()
        script = key in LITE_SCRIPTS                  # the three script entries share the original settings page
        self._set_pages["scripts" if script else key].pack(fill="both", expand=True)
        if script:
            name = SCRIPTS[key].display_name()
            self.set_script.set(name)
            self._rs_title.configure(text=f"{name} Settings")
            if load:
                self._load_settings_form()

    def open_script_settings(self, script: str):
        """Settings > the entry for `script`, showing it for the emulator in use."""
        inst = self.selected()
        if inst in self.m.instances:
            self.set_inst.set(inst)
        self.nb.select(self._tab_settings)
        self._set_nav.select(script)

    def _load_settings_form(self):
        if self._settings_script_id() == MAIN_SCRIPT and self.set_inst.get():
            self._crest_form()
        else:
            super()._load_settings_form()
        kids = self.form.winfo_children()
        sched = kids[-1] if kids else None          # the "Schedule" group is the last thing in the form
        if isinstance(sched, ios.Group) and sched.footer is not None:
            sched.footer.configure(text=SCHEDULE_NOTE)

    def _crest_form(self):
        """Crest's 22 settings as five short groups instead of one long list. Same settings, same variables, same Save."""
        for w in self.form.winfo_children():
            w.destroy()
        self.form_vars = {}
        inst = self.set_inst.get()
        values = self.m.script_settings(inst, MAIN_SCRIPT)
        by_key = {st.key: st for st in SCRIPTS[MAIN_SCRIPT].SETTINGS}
        groups = [(f"Crest · {inst}", "Run", ("runs", "past_party", "max_minutes", "stop_at", "mode_247", "max_restarts_per_day"), None),
                  (None, "Energy and potions", ("potion", "potion_limit", "crystal_refresh", "crystal_limit", "game_refill", "energy_floor"), None),
                  (None, "What to keep", ("keep", "stop_on_unknown", "verify_text"), None),
                  (None, "Getting to the palace", ("start_home", "home_fail", "allow_back", "palace_name", "palace_by_day", "quest_name"), None),
                  (None, "Troubleshooting", ("save_debug",), None)]
        used = {k for _, _, keys, _ in groups for k in keys}
        extra = tuple(k for k in by_key if k not in used)
        if extra:
            groups.append((None, "More", extra, None))
        first = True
        for _, title, keys, _ in groups:
            keys = [k for k in keys if k in by_key]
            if not keys:
                continue
            g = ios.Group(self.form, header=title if not first else f"{title}  ·  {inst}")
            g.pack(fill="x", pady=(0 if first else px(20), 0))
            first = False
            for key in keys:
                st = by_key[key]
                right = g.row(st.label, st.help or None)
                if st.type == "bool":
                    var = tk.BooleanVar(value=bool(values.get(key)))
                    ios.Switch(right, var).pack()
                elif st.type == "choice":
                    var = tk.StringVar(value=str(values.get(key)))
                    ios.Select(right, values=st.choices, variable=var).pack()
                elif st.type == "int":
                    var = tk.StringVar(value=str(values.get(key)))
                    ios.Stepper(right, var).pack()
                else:
                    var = tk.StringVar(value=str(values.get(key)))
                    ios.Field(right, var, width=26).pack()
                self.form_vars[key] = var
        sch = (self.m.config.get("schedules") or {}).get(inst, {})
        gs = ios.Group(self.form, header=f"Schedule · {inst}", footer=SCHEDULE_NOTE)
        gs.pack(fill="x", pady=(px(20), 0))
        self.sched_on = tk.BooleanVar(value=bool(sch.get("enabled")))
        ios.Switch(gs.row("Start every day"), self.sched_on).pack()
        self.sched_time = tk.StringVar(value=str(sch.get("time", "06:05")))
        ios.Field(gs.row("At (24-hour HH:MM)"), self.sched_time, width=6, justify="right").pack()

    def _dashboard_in_view(self) -> bool:
        return self.nb.index() == self._tab_crest

    def _tab_shown(self, i):
        """A tab came to the front (LiteTabs.on_select)."""
