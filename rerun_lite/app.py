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
from rerun.gui import App
from rerun.ios import px
from rerun.scripts import SCRIPTS

from . import APP_NAME, LITE_SCRIPTS, __version__, channel, theme
from .icon import make_lite_icon
from .manager import LiteManager
from .pages import NOT_LINKED, SCHEDULE_NOTE, PagesMixin  # noqa: F401 - re-exported
from .state import UiStateMixin
from .status import StatusMixin
from .theme import LiteTabs
from .tray import LiteTray

# The original's messages name places in the full app; LITE says where the same thing is here.
LITE_WORDS = (
    ("(Account Manager > Information)", "(choose it next to 'Runs on' at the top of the Dailies tab)"),
    ("pick the account in the Macro Farming tab", "pick the account at the top of the Dailies tab"),
    ("(Account Manager > Safety)", "(that switch is in the full ReRun: Account Manager > Safety)"),
)


class LiteApp(PagesMixin, StatusMixin, UiStateMixin, App):
    WIP_TEXT = (f"{APP_NAME} is a Work In Progress.\n\nIt runs ReRun's Crest and Dailies. Keep an eye on it "
                "while it plays, and report anything odd.")

    def __init__(self, manager: LiteManager, license=None):  # noqa: A002 - same name as the original
        # Mirrors rerun.gui.App.__init__ step for step; only the pages built differ.
        ios.enable_dpi_awareness()
        tk.Tk.__init__(self)
        self.m = manager
        self.license = license
        theme.apply_palette()
        ios.init(self, str(self.m.config.get("appearance", "auto")))
        theme.apply_look()
        self.title(APP_NAME)
        self.geometry(f"{px(1140)}x{px(840)}")
        self._ui_path = channel.data_dir(self.m.root) / "ui.json"     # LITE's own window memory
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

        self.nb = LiteTabs(self, __version__)
        self.nb.pack(fill="both", expand=True)
        self.status = self.nb.status
        self.toast = ios.Toast(self.nb.content)
        self._host = None
        self._build_crest()            # tab 0: Auto Crest
        self._build_dailies()          # tab 1: Dailies
        self._build_history()          # tab 2: the original History page
        self._tab_templates = self.nb.count()
        self._build_templates()        # tab 3: the original Templates page
        self._build_lite_settings()    # tab 4: script settings, Discord, Log, App
        self._lite_script_lists()
        self._build_status()           # chip, badges, shortcuts, Window & files group
        self._apply_pin(bool(self._pin_var.get()))
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

    def _tick(self):
        super()._tick()
        self._refresh_status()
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
