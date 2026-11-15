"""Desktop window in an iOS style: dashboard, script settings, templates,
history, Discord and log, behind a bottom tab bar. Widgets live in ios.py."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - names formerly defined here
from .gui_common import __all__ as _common_names  # noqa: F401
from .gui_updates import UpdatesKeysMixin
from .gui_dashboard import DashboardMixin
from .gui_settings import SettingsMixin
from .gui_templates import TemplatesMixin
from .gui_history import HistoryMixin
from .gui_units import UnitsMixin
from .gui_discord import DiscordMixin
from .gui_log import LogMixin
from .gui_accounts import AccountsMixin
from .gui_accounts2 import AccountsMoreMixin
from .gui_farming import FarmingMixin


class App(AccountsMixin, AccountsMoreMixin, FarmingMixin, UpdatesKeysMixin, DashboardMixin, SettingsMixin, TemplatesMixin,
          HistoryMixin, UnitsMixin, DiscordMixin, LogMixin, tk.Tk):
    def __init__(self, manager: Manager, license=None):
        ios.enable_dpi_awareness()
        super().__init__()
        self.m = manager
        self.license = license   # rerun/license.py License (None: no key check, e.g. tests)
        ios.init(self, str(self.m.config.get("appearance", "auto")))
        self.title("Rerun")
        self.geometry(f"{px(1220)}x{px(900)}")
        saved = qol.clamp_geometry(str((self.m.config.get("ui") or {}).get("geometry") or ""),
                                   self.winfo_screenwidth(), self.winfo_screenheight())
        if saved:                      # where the window was last time (only if still on screen)
            self.geometry(saved)
        self.minsize(px(1060), px(800))
        self._icon = ImageTk.PhotoImage(make_icon(64))
        self.iconphoto(True, self._icon)
        self.events: queue.Queue = queue.Queue()
        self._log_backfill = len(self.m.log_entries)   # lines logged before the window existed
        self.m.listeners.append(self.events.put)
        self.bot = None
        self._hotkeys = None
        self._closing = False
        self._weak_seen: set[str] = set()
        self._upd_busy = False                  # an update check or download is running
        self._upd_declined: set[str] = set()    # app versions you said "Later" to
        self._content_pending = False           # templates staged, waiting for scripts to stop
        self._app_ready: dict | None = None     # downloaded Rerun.exe, swapped in on quit

        self.nb = ios.TabView(self)
        self.nb.pack(fill="both", expand=True)
        self.status = self.nb.status
        self.toast = ios.Toast(self.nb.content)
        self._host = None                       # set while a page is built into a workspace instead of a tab
        self._build_accounts()                  # Account Manager: units live inside it
        self._build_farming()                   # Macro Farming: dashboard, routine settings, history live inside it
        self._build_templates()
        self._tab_discord = self.nb.count()
        self._build_discord()
        self._build_log()
        self._build_app_settings()
        self._backfill_log()
        self._build_companion()
        self.status.configure(text="F12 stops everything  ·  F11 pauses or resumes all")
        if self.license is not None:
            self._show_key_status()
            self.status.configure(cursor="hand2")
            self.status.bind("<Button-1>", lambda e: self.change_key())
            self._schedule_key_check()
            self.after(1000, self._tick_key_timer)
            self.after(600, self._wip_notice)

        self.tray = Tray(lambda action: self.events.put({"type": "_tray", "action": action}))
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

    # small helpers --------------------------------------------------------
    def _page(self, title: str, tab: str, icon: str, scroll: bool = False):
        """Returns (page, content parent, header-right frame)."""
        host = self._host or self.nb.content
        if scroll:
            page = ios.ScrollFrame(host)
            parent = page.inner
        else:
            page = tk.Frame(host, bg=C["bg"])
            parent = page
        if self._host is None:
            self.nb.add(page, tab, icon)
        self._last_page = page                  # a workspace packs this itself
        return page, parent, ios.page_header(parent, title)

    def _label(self, parent, text="", secondary=True, font="footnote", **kw):
        return tk.Label(parent, text=text, bg=ios.bg_of(parent),
                        fg=C["secondary"] if secondary else C["label"], font=F[font], **kw)

    # ================================================================ loop
    def flash(self, text: str, kind: str = "info"):
        if text:
            self.toast.show(text, kind)

    def _poll_events(self):
        history_changed = False
        try:
            for _ in range(500):  # bounded: a burst of log lines can't freeze the window
                ev = self.events.get_nowait()
                t = ev.get("type")
                if t == "log":
                    if self._log_hidden_before > len(self.m.log_entries):
                        self._log_hidden_before = 0  # the log was trimmed since Clear
                    self._append_log(ev)
                    if ev["instance"] == "discord":
                        self._set_d_status(ev["message"])
                    if ev["instance"] in self.m.instances:
                        self.m.instances[ev["instance"]].detail = ev["message"][:120]
                elif t == "status":
                    self.refresh_instances()
                    if ev.get("status") in ("idle", "error") and ev.get("detail") not in ("", None):
                        kind = "error" if ev["status"] == "error" else "info"
                        self.flash(f"{ev['instance']}: {ev['detail']}", kind)
                elif t == "history":
                    history_changed = True
                    if ev.get("entry", {}).get("kind") == "compendium":
                        self.after(50, self.refresh_units)  # a unit scan just finished
                        self.after(90, lambda: self._refresh_compendium_tiles(force=True))
                        self.after(120, self._companion_refresh)
                elif t == "_preview":
                    self._preview_img = ev["img"]
                    self._draw_preview()
                elif t == "_tpl_img":
                    self.set_tpl_image(ev["img"])
                elif t == "_error":
                    ios.alert(self, ev["message"], "Something Went Wrong")
                elif t == "_alert":
                    ios.alert(self, ev["message"], ev.get("title", "Rerun"))
                elif t == "_scan_done":
                    self._am_scan_done(ev["message"], ev["kind"])
                elif t == "_setup":
                    self._show_setup_results(ev["checks"])
                elif t == "_update":
                    self._on_update_result(ev)
                elif t == "_update_progress":
                    self._set_update_status(ev["text"])
                elif t == "_update_app":
                    self._on_app_downloaded(ev)
                elif t == "_hotkey":
                    ev["fn"]()
                elif t == "_tray":
                    self._tray_action(ev["action"])
        except queue.Empty:
            pass
        if history_changed and not self._hist_pending:
            self._hist_pending = True
            self.after(400, self.refresh_history)
        self.after(150, self._poll_events)

    def _tick(self):
        if self._content_pending and not self._busy():
            self._commit_content()
        if self.state() != "withdrawn":
            self.refresh_instances()
            self._auto_preview()
        self._farm_update_status()
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 30 == 0:
            self._check_template_health()
        self.after(1000, self._tick)

    def _check_template_health(self):
        """Warn once per template that starts matching barely above its threshold."""
        for name, h in self.m.vision.health().items():
            if h["weak"] and name not in self._weak_seen:
                self._weak_seen.add(name)
                self.m.log("app", f"Template '{name}' is matching weakly (median {h['median']:.2f}, "
                                  f"needs {h['threshold']:.2f}) - re-capture it in the Templates tab "
                                  "before it stops matching", level="warn")
                self.flash(f"Template '{name}' is fading - see the Templates tab", "warn")

    def _start_hotkeys(self):
        try:
            from pynput import keyboard
        except ImportError:
            return
        hk = self.m.config.get("hotkeys", {})
        mapping = {}
        if hk.get("stop_all"):
            mapping[f"<{hk['stop_all']}>"] = lambda: self.events.put({"type": "_hotkey", "fn": self.stop_all})
        if hk.get("pause_all"):
            mapping[f"<{hk['pause_all']}>"] = lambda: self.events.put(
                {"type": "_hotkey", "fn": self.m.toggle_pause_all})
        try:
            self._hotkeys = keyboard.GlobalHotKeys(mapping)
            self._hotkeys.start()
        except Exception as e:  # noqa: BLE001
            self.flash(f"Global hotkeys unavailable: {e}", "warn")

    # tray / closing ----------------------------------------------------------
    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        self.refresh_instances()

    def _tray_action(self, action: str):
        if action == "show":
            self.show_window()
        elif action == "start_all":
            self.start_all()
        elif action == "stop_all":
            self.stop_all()
        elif action == "pause_all":
            self.m.toggle_pause_all()
        elif action == "quit":
            self.show_window()
            self.quit_app()

    # window memory and start-up options ------------------------------------------
    def _restore_tab(self):
        try:
            tab = int((self.m.config.get("ui") or {}).get("tab") or 0)
            if 0 < tab < self.nb.count():
                self.nb.select(tab)
        except (tk.TclError, TypeError, ValueError) as e:
            errlog.note("gui.restore_tab", e)

    def _save_ui_state(self):
        """Remember the window position/size and the open tab for next time (normal windows only:
        a minimised or hidden window reports a meaningless position)."""
        try:
            ui = self.m.config.setdefault("ui", {})
            if self.state() == "normal":
                ui["geometry"] = self.winfo_geometry()
            ui["tab"] = int(self.nb.index() or 0)
            self.m.save_config()
        except (tk.TclError, OSError) as e:
            errlog.note("gui.save_ui_state", e)

    def _apply_start_options(self):
        """'Start minimized to the tray' and 'Start scripts when Rerun opens' (both off by default).
        Neither runs on a brand-new setup (before the first Setup check)."""
        ui = self.m.config.get("ui") or {}
        done = []
        if not self.m.config.get("setup_seen"):
            return done
        if ui.get("start_minimized") and self._tray_on:
            self.after(60, self.withdraw)
            done.append("minimized")
        if ui.get("autostart"):
            self.after(6000, self._autostart)
            done.append("autostart")
        return done

    def _autostart(self):
        if not (self.m.config.get("ui") or {}).get("autostart"):
            return
        msgs = self.m.start_all()
        self.m.log("app", "Start scripts when Rerun opens: " + (" | ".join(msgs) or "nothing to start"))

    def on_close(self):
        """The window's X: hide to the tray if that's on, otherwise quit."""
        self._save_ui_state()
        if self._tray_on and self.close_to_tray.get():
            self.withdraw()
            if not self._tray_hinted:
                self._tray_hinted = True
                self.tray.notify("Rerun is still running here. Right-click the icon to quit.")
            return
        self.quit_app()

    def quit_app(self):
        running = [n for n, i in self.m.instances.items() if i.status in ("running", "paused", "starting")]
        if running and not ios.confirm(self, "Scripts are still running. Stop them and quit?",
                                       "Quit Rerun?", ok="Stop & Quit", destructive=True):
            return
        self._save_ui_state()
        if self._app_ready:   # a downloaded update: swap it in as Rerun closes
            return self._install_app(restart=False)
        self.m.stop_all()
        self.disconnect_discord()
        self.destroy()

    def destroy(self):
        """Always release the tray icon and hotkey threads (they would otherwise
        keep the process alive after the window is gone)."""
        if not self._closing:
            self._closing = True
            if getattr(self, "_stream", None) is not None:
                self._stream.stop()   # ends the emulator's screenrecord
            self.m.stats.flush()
            tray = getattr(self, "tray", None)
            if tray is not None:
                tray.stop()
            if self._hotkeys:
                self._hotkeys.stop()
        super().destroy()


def run_app(root: str | Path) -> None:
    from .license_gate import _appearance, require_key
    from .migrate import remember
    from .migrate_ui import offer_import
    # A new copy with no data: offer to bring it over from the previous Rerun (before
    # sign-in, so the key comes along too). rerun/migrate.py
    try:
        imported = offer_import(root, _appearance(root))
    except Exception as e:  # noqa: BLE001 - never block start-up on the import offer
        imported = f"Could not look for older Rerun data: {e}"
    lic = require_key(root)   # Rerun opens only with a valid key (rerun/license.py)
    if lic is None:
        return
    remember(root)            # so the next update knows where your data is
    updates.cleanup_after_update(root)
    try:   # templates downloaded last time while scripts ran (rerun/updates.py)
        updated = updates.commit_staged(root)
    except Exception as e:  # noqa: BLE001 - never block start-up on an update
        updated = f"Template update not installed: {e}"
    app = App(Manager(root), license=lic)
    if updated:
        app.after(2500, lambda: app.flash(updated, "ok"))
        app.m.log("app", updated)
    if imported:
        app.after(1500, lambda: app.flash(imported, "ok"))
        app.m.log("app", imported)
    app.mainloop()
