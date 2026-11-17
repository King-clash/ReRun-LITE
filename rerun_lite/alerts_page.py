"""Desktop notifications, the system-wide hotkeys and the live tray status.

* Settings > Notifications: which events may show a Windows notification (off until you switch it on).
* Settings > Keyboard shortcuts > System-wide: edit the global hotkeys (Stop, Pause/Resume, Compact window).
* The tray icon's hover text and its first menu line show what Crest is doing.

The worker threads only queue a request; everything that touches Tk happens in the window's own loop."""
from __future__ import annotations

import time

from rerun.gui_common import *  # noqa: F401,F403 - tk, ios, C, F, px, errlog

from . import hotkeys, notifyprefs, phases
from .compact_logic import PAUSABLE  # noqa: F401


class AlertsMixin:

    # ================================================================ hooks into the window's start-up and loop
    def _start_hotkeys(self):
        """Replaces the original: same F11/F12 by default, but any combination, plus the compact-window hotkey."""
        if not getattr(self, "_alerts_hooked", False):
            self._alerts_hooked = True
            self._throttle = notifyprefs.Throttle()
            self.m.alert_listeners.append(self._alert_from_thread)
        self._hk_msg = ""
        try:
            from pynput import keyboard  # noqa: PLC0415
        except ImportError:
            self._hk_msg = "System-wide hotkeys need the 'pynput' package, which is not installed."
            return
        values = self._hotkey_values()
        err = hotkeys.clashes(values)
        if err:
            self._hk_msg = err
            return
        run = lambda fn: (lambda: self.events.put({"type": "_hotkey", "fn": fn}))  # noqa: E731
        maps = hotkeys.mapping(values, {"stop_all": run(self.stop_all), "pause_all": run(self.m.toggle_pause_all),
                                        "compact": run(self.toggle_compact)})
        if not maps:
            return
        try:
            self._hotkeys = keyboard.GlobalHotKeys(maps)
            self._hotkeys.start()
        except Exception as e:  # noqa: BLE001
            self._hotkeys = None
            self._hk_msg = f"System-wide hotkeys are unavailable: {e}"
            self.flash(self._hk_msg, "warn")

    def _restart_hotkeys(self):
        try:
            if self._hotkeys:
                self._hotkeys.stop()
        except Exception as e:  # noqa: BLE001
            errlog.note("lite.hotkeys_stop", e)
        self._hotkeys = None
        self._start_hotkeys()

    def _hotkey_values(self) -> dict[str, str]:
        cfg = self.m.config.get("hotkeys") or {}
        return {"stop_all": str(cfg.get("stop_all") or ""), "pause_all": str(cfg.get("pause_all") or ""),
                "compact": str(self._ui_state().get("hotkey_compact") or "")}

    def _tray_action(self, action: str):
        if action == "toggle_notify":
            prefs = self._notify_prefs()
            prefs["enabled"] = not prefs["enabled"]
            self._bg_save(notify_desktop=prefs)
            self._notify_sync_vars()
            self.flash("Desktop notifications " + ("on" if prefs["enabled"] else "off"), "ok")
        else:
            super()._tray_action(action)

    def _tick(self):
        super()._tick()
        try:
            self._tray_status()
        except Exception as e:  # noqa: BLE001
            errlog.note("lite.tray_status", e)

    # ================================================================ tray status
    def _tray_status_text(self) -> str:
        run = [n for n, i in self.m.instances.items() if i.status in ("running", "starting", "paused")]
        if not run:
            return "Idle"
        n = run[0]
        ph, detail = self.m.phase(n)
        live = self.m.runs.live(n) or {}
        text = phases.LABEL.get(ph, ph)
        if live:
            text += f" - {live.get('runs', 0)} runs"
        return (f"{n}: {text}" if len(run) == 1 else f"{len(run)} emulators: {text}")[:100]

    def _tray_status(self):
        if not getattr(self, "_tray_on", False):
            return
        text = self._tray_status_text()
        if text != getattr(self, "_tray_last", None):
            self._tray_last = text
            self.tray.set_status(text)

    # ================================================================ desktop notifications
    def _notify_prefs(self) -> dict:
        return notifyprefs.load(self._ui_state().get("notify_desktop"))

    def _alert_from_thread(self, kind: str, instance: str, detail: str):
        self.events.put({"type": "_hotkey", "fn": lambda: self._on_alert(kind, instance, detail)})

    def _window_visible(self) -> bool:
        if self._compact_alive() and self._compact.state() == "normal":
            return True
        return self.state() == "normal"

    def _on_alert(self, kind: str, instance: str, detail: str):
        prefs = self._notify_prefs()
        if not notifyprefs.decide(prefs, kind, self._window_visible()):
            return
        if not self._throttle.allow(kind, instance, time.monotonic()):
            return
        title, text = notifyprefs.message(kind, instance, detail)
        if getattr(self, "_tray_on", False):
            self.tray.notify(text, title)
        else:
            self.flash(f"{title}: {text}", "warn")

    def _build_notify_page(self):
        _, page, hdr = self._page("Notifications", "Notifications", "list", scroll=True)
        g = ios.Group(page, header="Desktop notifications",
                      footer="A Windows notification near the clock. Off until you turn it on. The same event is never "
                             "shown more than once a minute for one emulator. Discord alerts are separate (Discord page).")
        g.pack(fill="x", padx=px(20), pady=(px(6), px(12)))
        self._nt_vars: dict[str, tk.BooleanVar] = {}
        prefs = self._notify_prefs()

        def switch(key, title, sub=None):
            var = tk.BooleanVar(value=prefs[key])
            self._nt_vars[key] = var
            ios.Switch(g.row(title, sub), var, command=self._notify_save).pack()

        switch("enabled", "Show desktop notifications")
        switch("only_hidden", "Only when the window is hidden or minimized",
               "Skip the pop-up while you are looking at ReRun LITE (the compact window counts as looking).")
        g2 = ios.Group(page, header="Tell me when")
        g2.pack(fill="x", padx=px(20), pady=(0, px(12)))
        for key, title in notifyprefs.KINDS:
            var = tk.BooleanVar(value=prefs[key])
            self._nt_vars[key] = var
            ios.Switch(g2.row(title), var, command=self._notify_save).pack()
        g3 = ios.Group(page, header="Try it")
        g3.pack(fill="x", padx=px(20), pady=(0, px(24)))
        ios.Button(g3.row("Send a test notification", "Uses the tray icon, so it needs the tray to be running."),
                   "Send test", self._notify_test, kind="tinted").pack()

    def _notify_sync_vars(self):
        prefs = self._notify_prefs()
        for k, v in getattr(self, "_nt_vars", {}).items():
            v.set(prefs[k])

    def _notify_save(self):
        self._bg_save(notify_desktop={k: bool(v.get()) for k, v in self._nt_vars.items()})

    def _notify_test(self):
        if getattr(self, "_tray_on", False):
            self.tray.notify("This is a test notification from ReRun LITE.", "Test")
            self.flash("Test sent - look near the clock", "ok")
        else:
            self.flash("The tray icon is not running, so there is nothing to show a notification with.", "warn")

    # ================================================================ system-wide hotkeys: the rows on the shortcuts page
    def _global_hotkey_rows(self, group):
        values = self._hotkey_values()
        self._hk_vars: dict[str, tk.StringVar] = {}
        for slot, title, default in hotkeys.SLOTS:
            var = tk.StringVar(value=values.get(slot, default))
            self._hk_vars[slot] = var
            right = group.row(title, "Leave empty for none." if slot == "compact" else None)
            ios.Field(right, var, width=16).pack(side="left")
        r = group.row("Apply", "Examples: f12, ctrl+alt+s. A plain letter is not allowed (it would stop working everywhere).")
        ios.Button(r, "Apply hotkeys", self._hotkeys_apply, kind="tinted", small=True).pack(side="left")
        self._hk_status = self._label(group, getattr(self, "_hk_msg", ""), font="footnote")
        self._hk_status.pack(fill="x", padx=px(14), pady=(px(2), px(8)))

    def _hotkeys_apply(self):
        typed = {slot: v.get() for slot, v in self._hk_vars.items()}
        canon = {}
        for slot, text in typed.items():
            try:
                canon[slot] = hotkeys.parse(text)[0]
            except ValueError as e:
                self._hk_status.configure(text=f"{dict((s, t) for s, t, _ in hotkeys.SLOTS)[slot]}: {e}", fg=C["red"])
                return
        err = hotkeys.clashes(canon)
        if err:
            self._hk_status.configure(text=err, fg=C["red"])
            return
        cfg = self.m.config.setdefault("hotkeys", {})
        cfg["stop_all"], cfg["pause_all"] = canon["stop_all"], canon["pause_all"]
        self.m.save_config()
        self._bg_save(hotkey_compact=canon["compact"])
        for slot, v in self._hk_vars.items():
            v.set(canon[slot])
        self._restart_hotkeys()
        self._hk_status.configure(text=getattr(self, "_hk_msg", "") or "Saved. The new hotkeys work now.",
                                  fg=C["red"] if getattr(self, "_hk_msg", "") else C["green"])
