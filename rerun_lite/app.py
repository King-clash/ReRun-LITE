"""ReRun LITE's window: Auto Crest and Dailies, and only what those two need.

`LiteApp` is the original window class (rerun.gui.App) with a different __init__: it builds five tabs instead
of the full app's workspaces, and every page on them is drawn by the ORIGINAL page builder -

  Auto Crest   rerun/gui_dashboard.py  _build_dashboard   (emulators, Start / Dry Run / Pause / Stop,
                                                          totals, crest counts, instructions, Live View)
  Dailies      rerun/gui_accounts.py   _am_checklist      (the daily & weekly checklist and its Run buttons)
  History      rerun/gui_history.py    _build_history
  Templates    rerun/gui_templates.py  _build_templates
  Settings     rerun/gui_settings.py   _build_settings + _build_app_settings,
               rerun/gui_discord.py    _build_discord,  rerun/gui_log.py  _build_log

so a button here does exactly what the same button does in the full app. What this file adds is small: the
tab layout, the two selectors Dailies needs from Account Manager > Information (which emulator the account
plays on, the weekly reset day), LITE's name where the original says "Rerun", and "no-op" stand-ins for the
pages LITE does not have (Units, GS Companion, Account Manager, Macro Farming).

Not in LITE: every other script, custom routines, Account Manager (overview, scanning, information, goals,
all accounts, Crest Vault, events, reports, safety), Units and the Compendium, GS Companion.
"""
from __future__ import annotations

import json
import queue
import shutil
import tkinter as tk
from pathlib import Path

from PIL import ImageTk

from rerun import errlog, ios, qol, updates
from rerun.accounts import AccountError
from rerun.gui import App
from rerun.ios import C, F, px
from rerun.safety import TOS_WARNING
from rerun.scripts import SCRIPTS

from . import APP_NAME, DAILIES_SCRIPTS, LITE_SCRIPTS, MAIN_SCRIPT, __version__, channel
from .icon import make_lite_icon
from .manager import LiteManager
from .tray import LiteTray

# The original page builders name their page; LITE shows the Dashboard under the feature's own name.
PAGE_NAMES = {"Dashboard": ("Auto Crest", "Auto Crest", "home")}
SETTINGS_SECTIONS = [("scripts", "Crest & Dailies"), ("discord", "Discord"), ("log", "Log"), ("app", "App")]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
NOT_LINKED = "Not linked"
# The original's messages name places in the full app; LITE says where the same thing is here.
LITE_WORDS = (
    ("(Account Manager > Information)", "(choose it next to 'Runs on' at the top of the Dailies tab)"),
    ("pick the account in the Macro Farming tab", "pick the account at the top of the Dailies tab"),
    ("(Account Manager > Safety)", "(that switch is in the full ReRun: Account Manager > Safety)"),
)
SCHEDULE_NOTE = ("Starts Crest on this emulator every day at that time, using your PC's clock. "
                 "Dailies tasks are started from the Dailies tab.")


def _labels(root: tk.Misc):
    """Every Label under `root`."""
    for w in root.winfo_children():
        if isinstance(w, tk.Label):
            yield w
        yield from _labels(w)


class LiteTabs(ios.TabView):
    """The original tab bar. `alias` lets a page the original reaches as a tab (Discord) open the right
    section of LITE's Settings tab; `on_select` tells the window which tab came to the front."""

    def __init__(self, parent):
        super().__init__(parent)
        self.alias: dict = {}
        self.on_select = None

    def select(self, i):
        if i in self.alias:
            tab, show = self.alias[i]
            super().select(tab)
            show()
            i = tab
        else:
            super().select(i)
        if self.on_select is not None:
            self.on_select(i)


class LiteApp(App):
    WIP_TEXT = (f"{APP_NAME} is a Work In Progress.\n\nIt runs ReRun's Crest and Dailies. Keep an eye on it "
                "while it plays, and report anything odd.")

    def __init__(self, manager: LiteManager, license=None):  # noqa: A002 - same name as the original
        # Mirrors rerun.gui.App.__init__ step for step; only the pages built differ.
        ios.enable_dpi_awareness()
        tk.Tk.__init__(self)
        self.m = manager
        self.license = license
        ios.init(self, str(self.m.config.get("appearance", "auto")))
        self.title(APP_NAME)
        self.geometry(f"{px(1140)}x{px(840)}")
        self._ui_path = channel.data_dir(self.m.root) / "ui.json"     # LITE's own window memory
        saved = qol.clamp_geometry(str(self._ui_state().get("geometry") or ""),
                                   self.winfo_screenwidth(), self.winfo_screenheight())
        if saved:
            self.geometry(saved)
        self.minsize(px(1060), px(800))    # the Dashboard and Templates pages need this much, as in ReRun
        self._icon = ImageTk.PhotoImage(make_lite_icon(64))
        self.iconphoto(True, self._icon)
        self.events: queue.Queue = queue.Queue()
        self._log_backfill = len(self.m.log_entries)
        self.m.listeners.append(self.events.put)
        self.bot = None
        self._hotkeys = None
        self._closing = False
        self._weak_seen: set[str] = set()
        self._upd_busy = False
        self._upd_declined: set[str] = set()
        self._content_pending = False
        self._app_ready: dict | None = None

        self.nb = LiteTabs(self)
        self.nb.pack(fill="both", expand=True)
        self.status = self.nb.status
        self.toast = ios.Toast(self.nb.content)
        self._host = None
        self._build_crest()            # tab 0: Auto Crest
        self._build_dailies()          # tab 1: Dailies
        self._build_history()          # tab 2: the original History page
        self._build_templates()        # tab 3: the original Templates page
        self._build_lite_settings()    # tab 4: script settings, Discord, Log, App
        self._lite_script_lists()
        self._backfill_log()
        self.nb.on_select = self._tab_shown
        self.status.configure(text="F12 stops everything  ·  F11 pauses or resumes all")
        if self.license is not None:
            self._show_key_status()
            self.status.configure(cursor="hand2")
            self.status.bind("<Button-1>", lambda e: self.change_key())
            self._schedule_key_check()
            self.after(1000, self._tick_key_timer)
            self.after(600, self._wip_notice)

        self.tray = LiteTray(lambda action: self.events.put({"type": "_tray", "action": action}))
        self._tray_on = self.tray.start()
        self._tray_hinted = False

        self.refresh_instances()
        self.m.start_scheduler()
        if not self.m.config.get("setup_seen"):
            self.after(1200, self.open_setup_check)
        self.after(10, lambda: ios.style_window(self))
        self.after(150, self._poll_events)
        self.after(1000, self._tick)
        self._start_hotkeys()
        if self.m.config["discord"].get("enabled"):
            self.after(500, self.connect_discord)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._restore_tab()
        self._apply_start_options()
        self.after(4000, self._schedule_update_check)

    # ================================================================ pages
    def _page(self, title: str, tab: str, icon: str, scroll: bool = False):
        title, tab, icon = PAGE_NAMES.get(title, (title, tab, icon))
        return super()._page(title, tab, icon, scroll)

    def _build_crest(self):
        """Auto Crest: the original Dashboard page as it is, without the script chooser (an emulator in LITE
        always runs Crest) and without the unit Compendium line (Units are not part of LITE)."""
        self._tab_crest = self.nb.count()
        self._build_dashboard()
        page, hdr = self._last_page, self.key_timer.master
        ios.Banner(page, TOS_WARNING, "orange").pack(fill="x", padx=px(20), pady=(0, px(8)), after=hdr.master)
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

    def _build_dailies(self):
        """Dailies: the original daily & weekly checklist (AccountsMixin._am_checklist draws it). The strip above
        it holds the two things the checklist needs that live in Account Manager > Information in the full app."""
        page = tk.Frame(self.nb.content, bg=C["bg"])
        self.nb.add(page, "Dailies", "check")
        self._tab_dailies = self.nb.count() - 1
        hdr = ios.page_header(page, "Dailies")
        ios.Button(hdr, "Script Settings", lambda: self.open_script_settings(DAILIES_SCRIPTS[0]), kind="plain",
                   icon="settings", small=True).pack(side="right")
        self._dl_account = tk.Frame(hdr, bg=C["bg"])      # the account picker: shown only with 2+ accounts
        self._am_picker = ios.Select(self._dl_account, values=[], accent=True, command=self._am_pick)
        self._am_picker.pack(side="right", padx=(px(8), px(18)))
        self._label(self._dl_account, "Account").pack(side="right")
        ios.Banner(page, TOS_WARNING, "orange").pack(fill="x", padx=px(20), pady=(0, px(8)))
        strip = ios.Card(page, pad=8)
        strip.pack(fill="x", padx=px(20))
        row = tk.Frame(strip.body, bg=C["card"])
        row.pack(fill="x")
        tk.Label(row, text="Runs on", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="left")
        self._dl_inst = ios.Select(row, values=[NOT_LINKED], accent=True, command=self._dl_link)
        self._dl_inst.pack(side="left", padx=(px(8), px(26)))
        tk.Label(row, text="Weekly reset day", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="left")
        self._dl_week = ios.Select(row, values=WEEKDAYS, accent=True, command=self._dl_set_week)
        self._dl_week.pack(side="left", padx=(px(8), 0))
        ios.wrapped_label(strip.body, "Run starts the task's script on that emulator. Weekly tasks reset at 6 AM UTC-6 on "
                                      "that day - Monday is a guess until you set the game's real day.").pack(fill="x")
        self._am_scroll = ios.ScrollFrame(page)
        self._am_scroll.pack(fill="both", expand=True, padx=px(12), pady=(px(4), px(10)))
        self._am_inner = self._am_scroll.inner
        self._am_section = "checklist"
        self._am_scan_busy = False
        self._dl_sig = None
        self.ops.store.listeners.append(self._am_on_change)
        self._am_refresh_picker()
        self._am_render()

    def _build_lite_settings(self):
        """Settings: the original script-settings, Discord, Log and App pages, behind one side list."""
        page = tk.Frame(self.nb.content, bg=C["bg"])
        self.nb.add(page, "Settings", "settings")
        self._tab_settings = self.nb.count() - 1
        body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=px(12), pady=(px(10), px(10)))
        self._set_nav = ios.SideNav(body, SETTINGS_SECTIONS, self._set_show, title="Settings")
        self._set_nav.pack(side="left", fill="y")
        self._set_stage = tk.Frame(body, bg=C["bg"])
        self._set_stage.pack(side="left", fill="both", expand=True, padx=(px(8), 0))
        self._set_pages: dict[str, tk.Misc] = {}
        for key, build in (("scripts", self._build_settings), ("discord", self._build_discord),
                           ("log", self._build_log), ("app", self._build_app_settings)):
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
        self._set_nav.select("scripts", notify=False)
        self._set_show("scripts")

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

    def _set_show(self, key: str):
        for w in self._set_stage.winfo_children():
            w.pack_forget()
        self._set_pages[key].pack(fill="both", expand=True)

    def open_script_settings(self, script: str):
        """Settings > Crest & Dailies, showing `script` for the emulator in use."""
        if script == MAIN_SCRIPT:
            inst = self.selected()
        else:
            a = self.ops.store.active()
            inst = a["instance"] if a else ""
        if inst in self.m.instances:
            self.set_inst.set(inst)
        self.set_script.set(SCRIPTS[script].display_name())
        self._load_settings_form()
        self.nb.select(self._tab_settings)
        self._set_nav.select("scripts")

    def _load_settings_form(self):
        super()._load_settings_form()
        kids = self.form.winfo_children()
        sched = kids[-1] if kids else None          # the "Schedule" group is the last thing in the form
        if isinstance(sched, ios.Group) and sched.footer is not None:
            sched.footer.configure(text=SCHEDULE_NOTE)

    def _dashboard_in_view(self) -> bool:
        return self.nb.index() == self._tab_crest

    def _tab_shown(self, i):
        if i == getattr(self, "_tab_dailies", None):
            self._am_render()                       # fresh "resets in ..." countdowns

    # ================================================================ dailies strip
    def _am_refresh_picker(self):
        super()._am_refresh_picker()
        many = len(self.ops.store.ids()) > 1
        if many and not self._dl_account.winfo_manager():
            self._dl_account.pack(side="right")
        elif not many and self._dl_account.winfo_manager():
            self._dl_account.pack_forget()
        self._dl_sync()

    def _dl_sync(self):
        """Show the active account's emulator and weekly reset day."""
        names = list(self.m.instances)
        self._dl_inst["values"] = [NOT_LINKED] + names
        a = self.ops.store.active()
        if a is None:
            return
        linked = a["instance"]
        self._dl_inst.set(linked if linked in names else (f"{linked} (removed)" if linked else NOT_LINKED))
        self._dl_week.set(WEEKDAYS[int(a["prefs"].get("week_reset_weekday", 0)) % 7])

    def _dl_link(self):
        a = self.ops.store.active()
        if a is None:
            return
        pick = self._dl_inst.get()
        try:
            self.ops.store.update(a["id"], instance="" if pick == NOT_LINKED else pick)
        except AccountError as e:
            self._am_error(e)
        self._dl_sync()

    def _dl_set_week(self):
        a = self.ops.store.active()
        if a is not None:
            self._am_save_pref(a["id"], week_reset_weekday=WEEKDAYS.index(self._dl_week.get()))

    def _refresh_instance_lists(self):
        super()._refresh_instance_lists()
        if hasattr(self, "_dl_inst") and self._dl_inst["values"][1:] != list(self.m.instances):
            self._dl_sync()                         # an emulator was added, renamed or removed

    def _dl_signature(self):
        a = self.ops.store.active()
        if a is None:
            return None
        return a["id"], tuple((r["id"], r["state"]) for r in self.ops.checklist.rows(a["id"]))

    def _am_render(self):
        super()._am_render()
        self._dl_sig = self._dl_signature()

    def _tick(self):
        super()._tick()
        # the checklist redraws when a task's state changes by the clock (the 6 AM reset), not only on a click
        if self._ticks % 20:
            return
        try:
            if not self._am_typing() and self._dl_signature() != self._dl_sig:
                self._am_render()
        except (KeyError, tk.TclError) as e:      # focus is in a widget Tk cannot name: try again next time
            errlog.note("lite.dailies_redraw", e)

    # ================================================================ LITE's name and places
    def flash(self, text: str, kind: str = "info"):
        for old, new in LITE_WORDS:
            text = (text or "").replace(old, new)
        super().flash(text, kind)

    def _show_key_status(self):
        super()._show_key_status()
        self.title(self.title().replace("Rerun", APP_NAME, 1))

    def _show_setup_results(self, checks):
        for c in checks:
            if c.title == "Templates":          # the original counts Any Quest too; LITE has Crest + Login & Mail
                missing = sorted({n for sid in LITE_SCRIPTS if not SCRIPTS[sid].BETA
                                  for n in self.m.missing_templates(sid)})
                c.ok, c.fix = not missing, (None if not missing else "import")
                c.detail = ("All templates for Crest and Login & Mail are captured." if not missing else
                            f"{len(missing)} missing: {', '.join(missing[:6])}" + ("..." if len(missing) > 6 else ""))
        super()._show_setup_results(checks)

    # pages LITE does not have: the original code may still ask them to redraw
    def refresh_units(self, *a, **k):
        return None

    def _companion_refresh(self, *a, **k):
        return None

    # ================================================================ discord
    def connect_discord(self):
        """The original connect, with LITE's bot (no /units and /compendium: LITE has no unit roster)."""
        from .bot import LiteBot
        self.disconnect_discord()
        try:
            self.bot = LiteBot(self.m)
        except RuntimeError as e:
            self._set_d_status(f"Not connected: {e}")
            return
        if not self.m.config["discord"].get("channel_id"):
            self._set_d_status("Set the alert channel ID first.")
            return
        self.bot.start()
        self._set_d_status("Connecting...")

    # ================================================================ updates
    def _set_update_status(self, text: str):
        super()._set_update_status(text.replace("Rerun", APP_NAME))

    def _on_update_result(self, ev: dict):
        res = ev["result"]
        if channel.not_published(res.error):     # nothing published for LITE yet: a fact, not a failure
            self._upd_busy = False
            self._set_update_status(channel.NOT_PUBLISHED)
            if not ev["quiet"]:
                self.flash(channel.NOT_PUBLISHED, "info")
            return
        super()._on_update_result(ev)

    # ================================================================ window memory (LITE's own file)
    def _ui_state(self) -> dict:
        try:
            d = json.loads(self._ui_path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _restore_tab(self):
        try:
            tab = int(self._ui_state().get("tab") or 0)
            if 0 < tab < self.nb.count():
                self.nb.select(tab)
        except (tk.TclError, TypeError, ValueError) as e:
            errlog.note("lite.restore_tab", e)

    def _save_ui_state(self):
        """Window position/size and open tab, in data/lite/ui.json - not in config.yaml, so a full ReRun
        sharing the folder keeps its own."""
        try:
            ui = self._ui_state()
            if self.state() == "normal":
                ui["geometry"] = self.winfo_geometry()
            ui["tab"] = int(self.nb.index() or 0)
            self._ui_path.write_text(json.dumps(ui, indent=1), encoding="utf-8")
        except (tk.TclError, OSError) as e:
            errlog.note("lite.save_ui_state", e)


# ==================================================================== start-up
def bring_accounts(root: str | Path) -> int:
    """After a first-run import: also copy the other ReRun's accounts/ folder (the checklist's history and
    your own tasks live there) when this copy has none. rerun/migrate.py does not copy it. Returns files copied."""
    root = Path(root)
    try:
        src = Path(json.loads((root / "migrated_from.json").read_text(encoding="utf-8"))["from"]) / "accounts"
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    dst = root / "accounts"
    if not src.is_dir() or dst.exists():
        return 0
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("_removed", "*.tmp"))
    return sum(1 for p in dst.rglob("*") if p.is_file())


def run_app(root: str | Path) -> None:
    """rerun.gui.run_app for LITE: the same sign-in, import offer and update clean-up, then LiteApp."""
    from rerun.license_gate import _appearance, require_key
    from rerun.migrate import remember
    from rerun.migrate_ui import offer_import
    root = Path(root)
    channel.apply(root)       # before anything looks for updates: LITE's own channel and files
    try:
        imported = offer_import(root, _appearance(root))
        if imported and bring_accounts(root):
            imported = imported.rstrip(".") + ", checklist."
    except Exception as e:  # noqa: BLE001 - never block start-up on the import offer
        imported = f"Could not look for older Rerun data: {e}"
    lic = require_key(root)   # the same key as ReRun (rerun/license.py)
    if lic is None:
        return
    remember(root)
    updates.cleanup_after_update(root)
    try:
        updated = updates.commit_staged(root)
    except Exception as e:  # noqa: BLE001 - never block start-up on an update
        updated = f"Template update not installed: {e}"
    app = LiteApp(LiteManager(root), license=lic)
    if updated:
        app.after(2500, lambda: app.flash(updated, "ok"))
        app.m.log("app", updated)
    if imported:
        app.after(1500, lambda: app.flash(imported, "ok"))
        app.m.log("app", imported)
    app.mainloop()


__all__ = ["LiteApp", "LiteTabs", "run_app", "bring_accounts"]
