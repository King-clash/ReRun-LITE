"""ReRun LITE's window: Auto Crest and what it needs.

`LiteApp` is the original window class (rerun.gui.App) with a different __init__: it builds four tabs
(Auto Crest, History, Templates, Settings) and every page on them is drawn by the ORIGINAL page builder
(see pages.py). What this file adds: the tab layout, LITE's name where the original says "Rerun", "no-op"
stand-ins for the pages LITE does not have, the Discord bot without the unit commands, LITE's own update channel
and start-up. The look is theme.py and background.py; everyday conveniences are status.py.
"""
from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path

from PIL import ImageTk

from rerun import ios, qol, updates
from rerun.gui import App
from rerun.ios import px
from rerun.scripts import SCRIPTS

from . import APP_NAME, LITE_SCRIPTS, __version__, appearance, channel, seed, theme
from .icon import make_lite_icon
from .manager import LiteManager
from .appearance_page import AppearancePageMixin
from .background import BackgroundMixin
from .quality import QualityMixin
from .shortcuts_page import ShortcutsPageMixin
from .extras import ExtrasMixin
from .pages import SCHEDULE_NOTE, PagesMixin  # noqa: F401 - re-exported
from .palace_page import PalacePageMixin
from .splash import Splash
from .state import UiStateMixin
from .status import StatusMixin
from .theme import LiteTabs
from .tray import LiteTray

# The original's messages name places in the full app; LITE says where the same thing is here.
LITE_WORDS = (
    ("(Account Manager > Safety)", "(that switch is in the full ReRun: Account Manager > Safety)"),
)


class LiteApp(PagesMixin, PalacePageMixin, AppearancePageMixin, ShortcutsPageMixin, QualityMixin, StatusMixin, ExtrasMixin,
              BackgroundMixin, UiStateMixin, App):
    WIP_TEXT = (f"{APP_NAME} is a Work In Progress.\n\nIt runs Auto Crest. Keep an eye on it "
                "while it plays, and report anything odd.")

    def __init__(self, manager: LiteManager, license=None, splash: bool = False):  # noqa: A002 - same name as the original
        # Mirrors rerun.gui.App.__init__ step for step; only the pages built differ.
        ios.enable_dpi_awareness()
        tk.Tk.__init__(self)
        self.m = manager
        self.license = license
        self._splash = None
        self._ui_path = channel.data_dir(self.m.root) / "ui.json"     # LITE's own window memory (and its appearance)
        self._look = theme.saved_appearance(self.m.root)
        if splash:                                                  # sign-in is done: show how far the window has got
            self.withdraw()
            self._splash = Splash(self, manager.root, "open", "Opening ReRun LITE", "Starting…",
                                  colors=appearance.splash_colors(self._look))
        self._init_look()                                          # palette, fonts, density: from the saved appearance
        self.title(APP_NAME)
        self.geometry(f"{px(1140)}x{px(840)}")
        self._pin_var = tk.BooleanVar(value=bool(self._ui_state().get("pinned")))
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

        self._build_ui()
        if self.license is not None:
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
        self._restore_emulator()
        self._progress(100, "Ready")
        if self._splash is not None:
            self._splash.close()
            self._splash = None
            self.deiconify()
        self._apply_start_options()
        self.after(4000, self._schedule_update_check)

    # ================================================================ the look, and building the window from it
    def _init_look(self) -> None:
        """Resolve the saved appearance into colours, fonts, sizes and the density, and give them to the widget kit."""
        res = theme.apply(self._look)
        ios.init(self, res.ios_mode)
        theme.apply_look()
        theme.apply_density()
        self.configure(bg=ios.C["bg"])

    def _build_ui(self) -> None:
        """Everything inside the window: the tab bar and every page. Called once at start-up, and again by
        apply_appearance() so a change of look shows at once, without a restart."""
        self.nb = LiteTabs(self, __version__)
        self.nb.pack(fill="both", expand=True)
        self.status = self.nb.status
        self.toast = ios.Toast(self.nb.content)
        self._host = None
        self._progress(30, "Building Auto Crest…")
        self._build_crest()            # tab 0: Auto Crest
        self._progress(48, "Building History…")
        self._build_history()          # tab 1: the original History page
        self._progress(60, "Building Templates…")
        self._tab_templates = self.nb.count()
        self._build_templates()        # tab 2: the original Templates page
        self._progress(74, "Building Settings…")
        self._build_lite_settings()    # tab 3: Crest and palace settings, Discord, Appearance, General, Log
        self._lite_script_lists()
        self._progress(88, "Starting the background…")
        self._build_backdrop()         # the video behind the window (background.py)
        self._build_extras()           # Start/Stop button, sound, remembered emulator (extras.py)
        self._build_status()           # chip, badges, Window & files group
        self._build_quality()          # shortcuts, command palette, right-click menus, template filter (quality.py)
        self._apply_pin(bool(self._pin_var.get()))
        self._backfill_log()
        self.nb.on_select = self._tab_shown
        self.status.configure(text="F12 stops everything  ·  F11 pauses or resumes all")
        if self.license is not None:
            self._show_key_status()
            self.status.configure(cursor="hand2")
            self.status.bind("<Button-1>", lambda e: self.change_key())

    def apply_appearance(self, new: appearance.Appearance) -> None:
        """Use `new` right now: save it, rebuild the window in the new colours and sizes, and put the user back where
        they were (same tab, same Settings entry, same emulator). Nothing that is running is touched."""
        new = new.clean()
        if new == self._look:
            return
        tab, section = self.nb.index(), self._set_nav.current
        emulator = self.selected()
        self._look = new
        self._bg_save(appearance=new.to_dict())
        veil = tk.Frame(self, bg=ios.C["bg"])                       # covers the window while it is rebuilt (about 2 s)
        tk.Label(veil, text="Applying…", bg=ios.C["bg"], fg=ios.C["secondary"], font=ios.F["body"]).place(relx=0.5, rely=0.5, anchor="center")
        veil.place(x=0, y=0, relwidth=1, relheight=1)
        veil.lift()
        self.update_idletasks()
        self.backdrop.stop()
        self.nb.destroy()
        self._init_look()
        self.minsize(px(1060), px(800))
        self._build_ui()
        self._status_sig = None
        self._set_nav.select(section)
        self.nb.select(tab)
        if emulator in self.m.instances:
            self.inst_list.sel = emulator
        self.refresh_instances()
        self._refresh_status()
        veil.destroy()
        self.after(60, ios.style_window, self)                     # the title bar follows light / dark too

    def _tick(self):
        super()._tick()
        self._refresh_status()

    def _progress(self, pct: float, text: str) -> None:
        if self._splash is not None:
            self._splash.step(pct, text)

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


# ==================================================================== start-up
def run_app(root: str | Path) -> None:
    """rerun.gui.run_app for LITE: the same sign-in, import offer and update clean-up, then LiteApp."""
    from rerun import license_gate
    from rerun.license_gate import require_key
    from rerun.migrate import remember

    from .import_offer import offer_import
    root = Path(root)
    channel.apply(root)       # before anything looks for updates: LITE's own channel and files
    seed.restore(root)        # a personal build gives back its own videos / palace pictures when they are missing
    look = theme.apply_palette(theme.saved_theme(root))             # the chosen theme, for the windows before the app too
    license_gate._appearance = lambda _root: look                   # the sign-in window uses it as well
    try:
        imported = offer_import(root, look)
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
    app = LiteApp(LiteManager(root), license=lic, splash=True)
    if updated:
        app.after(2500, lambda: app.flash(updated, "ok"))
        app.m.log("app", updated)
    if imported:
        app.after(1500, lambda: app.flash(imported, "ok"))
        app.m.log("app", imported)
    app.mainloop()


__all__ = ["LiteApp", "LiteTabs", "run_app"]
