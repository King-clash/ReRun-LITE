"""Settings > Health: is everything in order, what the app is using, the stuck watch, and the diagnostic bundle.

The checks are local and quick (health.py); the slow one - ADB, the emulator connection, the game, the screen size - is
the existing Setup Check, one button away. Nothing here changes a setting unless you press a Fix button and confirm."""
from __future__ import annotations

import json
import platform
import sys

import yaml

from rerun.gui_common import *  # noqa: F401,F403 - tk, ios, C, F, px, errlog, filedialog, Path

from . import APP_NAME, __version__, diagnostics, health, resources, stuck
from .charts import LineChart

DOT = {"ok": "green", "warn": "orange", "bad": "red", "info": "gray"}
SAMPLE_EVERY = 5          # seconds between resource readings


class HealthMixin:

    # ================================================================ background sampling (cheap: a few system calls)
    def _tick(self):
        super()._tick()
        n = getattr(self, "_health_n", 0)
        self._health_n = n + 1
        try:
            if not getattr(self, "_stuck_applied", False):
                self._stuck_applied = True
                self.m.stuck.set_minutes(self._ui_state().get("stuck_minutes", stuck.DEFAULT_MINUTES))
            if n % SAMPLE_EVERY == 0:
                if getattr(self, "_sampler", None) is None:
                    self._sampler = resources.Sampler()
                self._sampler.sample()
                if self._health_visible():
                    self._health_update_resources()
        except Exception as e:  # noqa: BLE001 - monitoring must never break the window
            errlog.note("lite.health_tick", e)

    def _health_visible(self) -> bool:
        page = getattr(self, "_health_root", None)
        try:
            return page is not None and page.winfo_ismapped()
        except tk.TclError:
            return False

    # ================================================================ the page
    def _build_health_page(self):
        page_w, page, hdr = self._page("Health", "Health", "settings", scroll=True)
        self._health_root = page_w
        ios.Button(hdr, "Create diagnostic bundle…", self._health_bundle, kind="tinted").pack(side="right")
        ios.Button(hdr, "Full setup check", self.open_setup_check, kind="tinted").pack(side="right", padx=(0, px(8)))
        ios.Button(hdr, "Refresh", self._health_refresh, kind="tinted").pack(side="right", padx=(0, px(8)))
        self._health_summary = self._label(page, "", secondary=False, font="body_semi", anchor="w")
        self._health_summary.pack(fill="x", padx=px(20), pady=(0, px(6)))
        self._health_list = tk.Frame(page, bg=C["bg"])
        self._health_list.pack(fill="x", padx=px(20))

        g = ios.Group(page, header="Stuck watch",
                      footer="Warns once in the Log (and as a notification, if you turned those on) when Crest has not "
                             "advanced for this long. It never taps or restarts anything: the engine's own limits do that.")
        g.pack(fill="x", padx=px(20), pady=(px(12), 0))
        self._stuck_pick = ios.Select(g.row("Warn after"), values=self._stuck_labels(), accent=True,
                                      command=lambda *_: self._stuck_changed())
        self._stuck_pick.set(self._stuck_label(self.m.stuck.minutes))
        self._stuck_pick.pack()

        g2 = ios.Group(page, header="This app and the PC")
        g2.pack(fill="x", padx=px(20), pady=(px(12), px(24)))
        self._res_text = self._label(g2.row("Now"), "No reading yet", secondary=False)
        self._res_text.pack()
        r = g2.row("App memory (MB), last 10 minutes")
        self._res_chart = LineChart(r, px(110), "Collecting readings…")
        self._res_chart.pack(fill="x", expand=True)
        self._health_refresh()

    @staticmethod
    def _stuck_label(m: int) -> str:
        return "Off" if not m else f"{m} minutes"

    def _stuck_labels(self) -> list[str]:
        return [self._stuck_label(m) for m in stuck.CHOICES]

    def _stuck_changed(self):
        label = self._stuck_pick.get()
        minutes = next((m for m in stuck.CHOICES if self._stuck_label(m) == label), stuck.DEFAULT_MINUTES)
        self.m.stuck.set_minutes(minutes)
        self._bg_save(stuck_minutes=minutes)
        self._health_refresh()

    # ---------------------------------------------------------------- items
    def _health_items(self):
        return health.run_local(self.m, getattr(self, "_sampler", None), self.m.stuck)

    def _health_refresh(self, *_a):
        try:
            items = self._health_items()
            for w in self._health_list.winfo_children():
                w.destroy()
            worst = health.worst(items)
            self._health_summary.configure(text={"ok": "Everything looks fine.", "warn": "A few things need a look.",
                                                 "bad": "Something needs fixing."}[worst])
            g = ios.Group(self._health_list)
            g.pack(fill="x")
            for it in items:
                right = g.row(it.title, it.detail, wrap=520)
                if it.fix:
                    ios.Button(right, self._fix_label(it.fix), lambda f=it.fix: self._health_fix(f),
                               kind="tinted", small=True).pack(side="left", padx=(0, px(8)))
                tk.Label(right, text="●", bg=C["card"], fg=C.get(DOT.get(it.state, "gray"), C["gray"]),
                         font=F["body_semi"]).pack(side="left")
            self._health_update_resources()
        except Exception as e:  # noqa: BLE001
            errlog.note("lite.health_refresh", e)

    @staticmethod
    def _fix_label(fix: str) -> str:
        return "Set a limit" if fix.startswith("set_cap:") else {"templates": "Open Templates", "settings": "Open settings",
                                                                   "palaces": "Open Palace Selector", "emulator": "Open Auto Crest",
                                                                   "setup_check": "Run setup check"}.get(fix, "Fix")

    def _health_fix(self, fix: str):
        if fix.startswith("set_cap:"):
            name = fix.split(":", 1)[1]
            if name not in self.m.instances:
                return
            if ios.confirm(self, f"Set 'Max game restarts per day' for {name} to {health.CAP_SUGGESTION}? "
                                 "After that many restarts in a game day, Crest stops and tells you instead of restarting "
                                 "again. You can change it any time in Settings > Auto Crest.", "Set a limit?", ok="Set"):
                vals = dict(self.m.script_settings(name, "crest"))
                vals["max_restarts_per_day"] = health.CAP_SUGGESTION
                self.m.save_script_settings(name, "crest", vals)
                try:
                    self._load_settings_form()
                except Exception as e:  # noqa: BLE001
                    errlog.note("lite.health_form", e)
                self._health_refresh()
        elif fix == "setup_check":
            self.open_setup_check()
        else:
            self._fix(fix)

    def _health_update_resources(self):
        s = getattr(self, "_sampler", None)
        if s is None or not hasattr(self, "_res_text"):
            return
        self._res_text.configure(text=s.text())
        hist = [h["app_mb"] for h in list(s.history)[-120:] if h.get("app_mb") is not None]
        self._res_chart.set(hist)

    # ================================================================ diagnostic bundle
    def _health_bundle(self):
        path = filedialog.asksaveasfilename(defaultextension=".zip", initialfile=diagnostics.default_name())
        if not path:
            return
        try:
            data = diagnostics.build_bundle(self._bundle_parts())
            Path(path).write_bytes(data)
        except Exception as e:  # noqa: BLE001
            errlog.note("lite.bundle", e)
            self.flash(f"Could not create the bundle: {e}", "err")
            return
        self.flash("Diagnostic bundle saved (secrets removed, nothing uploaded)", "ok")

    def _bundle_parts(self) -> dict[str, str]:
        m = self.m
        sampler = getattr(self, "_sampler", None)
        info = [f"{APP_NAME} {__version__}", f"Python {sys.version.split()[0]} on {platform.platform()}",
                f"Instances: {len(m.instances)}", "", self.status_summary(), "",
                "Resources: " + (sampler.text() if sampler else "no reading")]
        parts = {
            "summary.txt": "\n".join(info),
            "health.txt": health.as_text(self._health_items()),
            "log.txt": "\n".join(m.log_lines[-1000:]),
            "config.yaml": yaml.safe_dump(diagnostics.redact(m.config), sort_keys=False, allow_unicode=True),
            "ui.json": json.dumps(diagnostics.redact(self._ui_state()), indent=1),
            "sessions.jsonl": "".join(json.dumps(diagnostics.clean_session(s)) + "\n" for s in m.runs.sessions(limit=30)),
            "error.log": diagnostics.tail(Path(m.root) / "error.log"),
        }
        return parts
