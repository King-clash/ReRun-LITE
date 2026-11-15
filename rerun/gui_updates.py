"""Updates, key and licence handling.

Moved verbatim from rerun/gui.py (class App); App inherits UpdatesKeysMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class UpdatesKeysMixin:

    # data from an older Rerun (rerun/migrate.py) ---------------------------------
    def import_old_data(self):
        """Settings › Import from another Rerun…: copy its data in, then restart Rerun."""
        from .migrate import describe, has_user_data, import_data, summary
        d = filedialog.askdirectory(parent=self, title="Folder of your other Rerun")
        if not d:
            return
        if not has_user_data(d):
            return ios.alert(self, "That folder has no Rerun data (no stats, History, units or key).",
                             "Import")
        if any(i.status in ("running", "paused", "starting") for i in self.m.instances.values()):
            return ios.alert(self, "Stop your scripts first, then import.", "Import")
        if not ios.confirm(self, f"Copy the data from\n{d}\n{describe(d)}\n\nIt replaces this Rerun's "
                                 "settings, stats, crest log, History, units and key. This Rerun's "
                                 "current data is moved to backups/before_import_… first, and the "
                                 "other folder is not changed. Rerun closes afterwards; start it "
                                 "again to load the data.", "Import Data?", ok="Import"):
            return
        self.m.stats.flush()
        try:
            done = import_data(d, self.m.root, replace=True)
        except (OSError, ValueError) as e:
            return ios.alert(self, f"Could not import: {e}", "Import")
        # closing must not write this session's stats over the imported ones
        self.m.stats.flush = lambda *a, **k: None
        ios.alert(self, f"Copied: {summary(done)}.\n\nRerun closes now - start it again.", "Import")
        self.m.stop_all()
        self.disconnect_discord()
        self.destroy()

    # updates (rerun/updates.py) ---------------------------------------------------
    UPDATE_EVERY_MS = 6 * 3600 * 1000

    def _busy(self) -> bool:
        return any(i.status in ("running", "paused", "starting") for i in self.m.instances.values())

    def _update_idle_text(self) -> str:
        if not updates.settings(self.m.config)["url"]:
            return "Updates are not set up in this build."
        ver = updates.load_state(self.m.root).get("content_version")
        return f"Templates: {ver}" if ver else "Not checked yet."

    def _set_update_status(self, text: str):
        lbl = getattr(self, "upd_status", None)
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text=text)

    def _save_update_settings(self, *_):
        u = self.m.config.setdefault("updates", {})
        u["check"] = bool(self.upd_check.get())
        u["channel"] = self.upd_channel.get().lower()
        self.m.save_config()
        self._set_update_status(self._update_idle_text())

    def _schedule_update_check(self):
        s = updates.settings(self.m.config)
        if s["url"] and s["check"]:
            self.check_updates(quiet=True)
        self.after(self.UPDATE_EVERY_MS, self._schedule_update_check)

    def check_updates(self, quiet: bool = False):
        """Fetch the signed manifest; download new templates (applied once no script runs)
        and offer a newer Rerun.exe. quiet = the automatic check (no 'up to date' message)."""
        if self._upd_busy:
            return None if quiet else self.flash("Already checking for updates…")
        if not updates.settings(self.m.config)["url"]:
            self._set_update_status(self._update_idle_text())
            return None if quiet else ios.alert(
                self, "This Rerun has no update address yet, so it cannot look for updates.",
                "Updates")
        self._upd_busy = True
        self._set_update_status("Checking for updates…")
        cfg, root = dict(self.m.config), self.m.root

        def work():
            res, staged = updates.check(root, cfg), ""
            if not res.error and res.plan is not None and not res.plan.empty:
                try:
                    updates.stage_content(root, cfg, res.plan)
                    staged = res.plan.describe()
                except Exception as e:  # noqa: BLE001 - reported, never raised
                    res.error = f"Template update failed: {e}"
            self.events.put({"type": "_update", "result": res, "staged": staged, "quiet": quiet})
        threading.Thread(target=work, daemon=True).start()
        return None

    def _on_update_result(self, ev: dict):
        self._upd_busy = False
        res, quiet = ev["result"], ev["quiet"]
        if res.error:
            self._set_update_status(res.error)
            self.m.log("app", f"Update check: {res.error}", level="warn")
            if not quiet:
                ios.alert(self, res.error, "Updates")
            return
        self._set_update_status(f"{res.summary()}  ·  checked {datetime.now():%H:%M}")
        if ev["staged"]:
            self.m.log("app", f"Template update downloaded: {ev['staged']}")
            self._content_pending = True
            self._commit_content()
        if res.app:
            self._offer_app_update(res.app, quiet)
        elif not quiet and not ev["staged"]:
            self.flash(f"Rerun {__version__} is up to date", "ok")

    def _commit_content(self):
        """Move downloaded templates/routines into place - now, unless a script runs."""
        if not self._content_pending:
            return
        if self._busy():
            self._set_update_status("New templates downloaded - they install when your scripts stop.")
            return
        self._content_pending = False
        try:
            msg = updates.commit_staged(self.m.root)
        except (UpdateError, OSError) as e:
            self.m.log("app", f"Template update not installed: {e}", level="error")
            self._set_update_status(f"Template update not installed: {e}")
            return
        if not msg:
            return
        self.m.store.reload()
        try:
            from .engine import load_routines
            self.m.routines = load_routines(self.m.root / "routines")
        except Exception as e:  # noqa: BLE001 - a bad routine must not undo the template update
            self.m.log("app", f"Custom routines: {e}", level="error")
        if hasattr(self, "refresh_checklist"):
            self.refresh_checklist()
        self.m.log("app", msg)
        self.flash(msg, "ok")
        self._set_update_status(msg)

    def _offer_app_update(self, app: dict, quiet: bool):
        v = str(app["version"])
        if not updates.frozen():
            self._set_update_status(f"Rerun {v} is available (this copy runs from source).")
            self.m.log("app", f"Rerun {v} is available; this copy runs from source, so it is not "
                              "installed")
            return
        if self._app_ready and self._app_ready.get("version") == v:
            return self._ask_restart()
        if quiet and v in self._upd_declined:
            return
        notes = str(app.get("notes") or "").strip()
        mb = int(app.get("size") or 0) / 1e6
        if not ios.confirm(self, f"Rerun {v} is available (you have {__version__})."
                                 + (f"\n\n{notes}" if notes else "")
                                 + f"\n\nDownload it now ({mb:.0f} MB)? Rerun restarts to finish; "
                                   "your settings and data stay.",
                           "Update Available", ok="Download", cancel="Later"):
            self._upd_declined.add(v)
            self._set_update_status(f"Rerun {v} is available - Check Now to download it.")
            return
        self._upd_busy = True
        cfg, root = dict(self.m.config), self.m.root
        last = [-1]

        def progress(got, total):
            pct = int(got * 100 / total) if total else 0
            if pct != last[0]:
                last[0] = pct
                self.events.put({"type": "_update_progress", "text": f"Downloading Rerun {v}… {pct}%"})

        def work():
            try:
                updates.download_app(root, cfg, app, progress)
                self.events.put({"type": "_update_app", "app": app})
            except Exception as e:  # noqa: BLE001 - reported, never raised
                self.events.put({"type": "_update_app", "app": app, "error": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def _on_app_downloaded(self, ev: dict):
        self._upd_busy = False
        if ev.get("error"):
            self._set_update_status(ev["error"])
            return ios.alert(self, ev["error"], "Update")
        self._app_ready = ev["app"]
        self.m.log("app", f"Rerun {ev['app']['version']} downloaded")
        self._ask_restart()

    def _ask_restart(self):
        v = self._app_ready["version"]
        warn = "\n\nYour scripts are running: restarting stops them." if self._busy() else ""
        if not ios.confirm(self, f"Rerun {v} is ready.{warn}\n\nRestart now to finish? "
                                 "(Later: it installs when you quit Rerun.)",
                           "Restart Rerun?", ok="Restart Now", cancel="Later"):
            self._set_update_status(f"Rerun {v} installs when you quit Rerun.")
            return
        self._install_app(restart=True)

    def _install_app(self, restart: bool):
        try:
            updates.launch_swap(self.m.root, restart=restart)
        except (UpdateError, OSError) as e:
            self._app_ready = None
            return ios.alert(self, f"Could not install the update: {e}", "Update")
        self._app_ready = None
        self.m.stop_all()
        self.disconnect_discord()
        self.destroy()

    # key (rerun/license.py) ---------------------------------------------------
    def _show_key_status(self):
        lic = self.license
        text = "F12 stops everything  ·  F11 pauses or resumes all  ·  " + lic.describe() + \
            "  (click to change key)"
        if self.status.cget("text") != text:
            self.status.configure(text=text)
        self.title("Rerun" if lic.lifetime else f"Rerun  ·  key: {lic.describe()}")

    WIP_TEXT = ("Rerun is a Work In Progress.\n\nSome features are still in Beta and may not "
                "behave as expected. Keep an eye on it while it plays, and report anything odd.")

    def _wip_notice(self):
        """Shown every time you sign in (app start and after entering a new key)."""
        if not self._closing:
            ios.alert(self, self.WIP_TEXT, "Work In Progress")

    @staticmethod
    def key_timer_text(lic, now: float | None = None) -> tuple[str, str]:
        """('Key: 29d 23:59:12 left', colour key) for the Dashboard countdown."""
        if lic.lifetime:
            return "Key: Lifetime", "green"
        left = max(0, int(lic.remaining(now)))
        d, rest = divmod(left, 86400)
        h, rest = divmod(rest, 3600)
        m, s = divmod(rest, 60)
        clock = f"{h:02d}:{m:02d}:{s:02d}"
        text = f"Key: {d}d {clock} left" if d else f"Key: {clock} left"
        return text, ("red" if left < 3600 else "orange" if left < 86400 else "secondary")

    def _tick_key_timer(self):
        """Dashboard countdown of the key's time left, every second."""
        if self._closing or self.license is None:
            return
        text, color = self.key_timer_text(self.license)
        if self.key_timer.cget("text") != text:
            self.key_timer.configure(text=text, fg=C[color])
        if not self.license.lifetime and self.license.remaining() <= 0 and not self.m.locked:
            self._schedule_key_check(10)   # ended: stop at once rather than within the minute
        self.after(1000, self._tick_key_timer)

    def _schedule_key_check(self, ms: int = 60_000):
        """One pending key check at a time."""
        pending = getattr(self, "_key_check_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except tk.TclError:
                pass
        self._key_check_id = self.after(ms, self._check_key)

    def _check_key(self):
        self._key_check_id = None
        """Every minute: remember the time (clock check) and stop when the key runs out."""
        from .license import KeyError_, KeyStore, fmt_left
        if self._closing or self.license is None:
            return
        store = KeyStore(self.m.root)
        try:
            self.license = store.current()
            store.touch()
        except KeyError_ as e:
            return self._key_expired(str(e))
        left = self.license.remaining()
        if left < 3 * 86400 and not getattr(self, "_key_warned", False):
            self._key_warned = True
            self.flash(f"Your Rerun key runs out in {fmt_left(left)}", "info")
        self._show_key_status()
        self._schedule_key_check()

    def _key_expired(self, reason: str):
        """Key no longer valid: stop every script, block remote starts, ask for a new key."""
        from .license import KeyStore
        from .license_gate import ask_key
        self.m.locked = True
        self.m.stop_all()
        self.m.log("app", f"Key: {reason} - scripts stopped until a valid key is entered")
        if self.state() == "withdrawn":
            self.deiconify()
        lic = ask_key(self, KeyStore(self.m.root), reason)
        if lic is None:
            self.m.stop_all()
            self.disconnect_discord()
            return self.destroy()
        self.license, self.m.locked = lic, False
        self._key_warned = False
        self.flash("Signed in: " + lic.describe(), "ok")
        self._show_key_status()
        self.after(300, self._wip_notice)
        self._schedule_key_check()

    def change_key(self):
        """Click on the status line: enter another key (Cancel keeps the current one)."""
        from .license import KeyStore
        from .license_gate import ask_key
        store = KeyStore(self.m.root)
        old = store.saved_key()
        lic = ask_key(self, store, "", quit_text="Cancel")
        if lic is None:
            if old:
                store.save(old)
            return
        self.license = lic
        self._key_warned = False
        self.flash("Key changed: " + lic.describe(), "ok")
        self._show_key_status()
        self.after(300, self._wip_notice)
