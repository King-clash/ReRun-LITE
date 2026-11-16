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
SETTINGS_SECTIONS = [(MAIN_SCRIPT, "Auto Crest"), ("palaces", "Palace Selector"),
                     ("discord", "Discord"), ("app", "General"), ("log", "Log")]
SETTINGS_HEADS = {MAIN_SCRIPT: "Automation", "discord": "Alerts", "app": "App"}
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
        for key, build in (("scripts", self._build_settings), ("palaces", self._build_palace_page), ("discord", self._build_discord),
                           ("app", self._build_app_settings), ("log", self._build_log)):
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
        super()._load_settings_form()
        kids = self.form.winfo_children()
        sched = kids[-1] if kids else None          # the "Schedule" group is the last thing in the form
        if isinstance(sched, ios.Group) and sched.footer is not None:
            sched.footer.configure(text=SCHEDULE_NOTE)

    def _dashboard_in_view(self) -> bool:
        return self.nb.index() == self._tab_crest

    def _tab_shown(self, i):
        """A tab came to the front (LiteTabs.on_select)."""
