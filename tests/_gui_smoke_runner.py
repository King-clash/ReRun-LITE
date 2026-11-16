"""Runs the new window pages against stand-in widgets (no real Tk). Catches typos, wrong names and wrong attribute
use in the page-building code. It is NOT a look-and-feel test: nothing is drawn. Run by test_gui_smoke.py in its own
process because it replaces tkinter and rerun.ios for the duration."""
import sys, types, tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tk = MagicMock(name="tkinter")
tk.TclError = type("TclError", (Exception,), {})
tk.StringVar = lambda value="": MagicMock(get=MagicMock(return_value=value))
tk.BooleanVar = lambda value=False: MagicMock(get=MagicMock(return_value=value))
tk.Canvas = lambda *a, **k: MagicMock(winfo_width=lambda: 400, winfo_height=lambda: 150, yview=lambda: (0, 1))
sys.modules["tkinter"] = tk
sys.modules["tkinter.filedialog"] = MagicMock()
ios = types.ModuleType("rerun.ios")
ios.C = {k: "#000" for k in ("bg", "card", "sep", "label", "secondary", "blue", "green", "red", "orange", "gray", "fill")}
ios.F = {k: ("Segoe UI", 10) for k in ("body", "body_semi", "footnote", "footnote_semi", "caption", "large", "button")}
ios.px = lambda v: int(v)
ios.bg_of = lambda w: "#000"
for name in ("Button", "Switch", "Select", "Segmented", "Field", "Group", "confirm", "text_box", "style_window", "ScrollFrame", "page_header"):
    setattr(ios, name, MagicMock(name=name))
ios.text_box = MagicMock(return_value=(MagicMock(), MagicMock()))
sys.modules["rerun.ios"] = ios
import rerun
rerun.ios = ios
common = types.ModuleType("rerun.gui_common")
from rerun import errlog
common.__dict__.update(tk=tk, ios=ios, C=ios.C, F=ios.F, px=ios.px, errlog=errlog, filedialog=MagicMock(), Path=Path,
                       LOG_LEVELS={"All": None}, ALL_INSTANCES="All emulators")
sys.modules["rerun.gui_common"] = common

from rerun_lite.feed_page import FeedMixin
from rerun_lite.sessions_page import SessionsMixin
from rerun_lite.alerts_page import AlertsMixin
from rerun_lite.profiles_page import ProfilesMixin
from rerun_lite.health_page import HealthMixin
from rerun_lite.compact import CompactMixin
from rerun_lite.manager import LiteManager
import yaml


class Base:
    """What the real window offers to these mixins."""
    def __init__(self):
        root = Path(tempfile.mkdtemp(prefix="rerunlite_smoke_"))
        (root / "config.yaml").write_text(yaml.safe_dump({"instances": [{"name": "A", "serial": "x:1", "script": "crest"}]}))
        self.m = LiteManager(root)
        self.m.config["live_view_fps"] = 0
        self._ui = {}
        self.events = MagicMock()
        self.tray, self._tray_on = MagicMock(), True
        self._hotkeys = None
        self._compact = None
        self._pin_var = MagicMock(get=MagicMock(return_value=False))
        self._icon = MagicMock()
        self.close_to_tray = MagicMock(get=MagicMock(return_value=True))
        for n in ("_page", "_label", "flash", "after", "after_cancel", "_load_settings_form", "open_setup_check", "_fix",
                  "withdraw", "deiconify", "lift", "state", "winfo_screenwidth", "winfo_screenheight", "refresh_instances",
                  "_save_ui_state", "stop_all", "quit_app", "clipboard_clear", "clipboard_append", "selected", "status_summary"):
            setattr(self, n, MagicMock(name=n))
        self._page.return_value = (MagicMock(), MagicMock(), MagicMock())
        self.state.return_value = "normal"
        self.winfo_screenwidth.return_value, self.winfo_screenheight.return_value = 1920, 1080
        self.selected.return_value = "A"
        self.status_summary.return_value = "ReRun LITE status"
    def _ui_state(self): return dict(self._ui)
    def _bg_save(self, **kw): self._ui.update(kw)
    def tick_super(self): pass


class Probe(HealthMixin, ProfilesMixin, AlertsMixin, FeedMixin, SessionsMixin, CompactMixin, Base):
    pass


p = Probe()
p._build_log()
p._build_sessions_page()
p._sess_refresh()
p._build_notify_page()
g = MagicMock()
p._global_hotkey_rows(g)
p._hk_vars = {"stop_all": MagicMock(get=lambda: "f12"), "pause_all": MagicMock(get=lambda: "f11"), "compact": MagicMock(get=lambda: "ctrl+alt+m")}
p._hk_status = MagicMock()
p._restart_hotkeys = MagicMock()
p._hotkeys_apply()
assert p.m.config["hotkeys"]["stop_all"] == "f12" and p._ui["hotkey_compact"] == "ctrl+alt+m", (p.m.config["hotkeys"], p._ui)
p._build_profiles_page()
p._prof_inst = MagicMock(get=lambda: "A")
p._prof_pick = MagicMock(get=lambda: "P1")
p._prof_name = MagicMock(get=lambda: "P1")
p._prof_msg = MagicMock()
p._prof_save()
assert "P1" in p._store().profiles, p._prof_msg.configure.call_args
p._prof_name = MagicMock(get=lambda: "P2")
p._prof_rename()
assert "P2" in p._store().profiles
p._build_health_page()
p._health_refresh()
p._sampler = None
import rerun_lite.health_page as hp
p._sampler = __import__("rerun_lite.resources", fromlist=["x"]).Sampler()
p._sampler.sample()
p._health_update_resources()
parts = p._bundle_parts()
assert {"summary.txt", "health.txt", "log.txt", "config.yaml", "ui.json", "sessions.jsonl", "error.log"} <= set(parts)
p._alert_from_thread("failed", "A", "x")
p._throttle = __import__("rerun_lite.notifyprefs", fromlist=["x"]).Throttle()
p._bg_save(notify_desktop={"enabled": True, "only_hidden": False, "failed": True})
p._on_alert("failed", "A", "boom")
assert p.tray.notify.called
p._tray_action = AlertsMixin._tray_action.__get__(p)
# the activity feed and compact window against a manager that has really logged things
p.m.log("A", "Recovery started: restarting the game")
p.m.log("A", "Traceback (most recent call last):\n  File x\nValueError: y", "error")
p._log_backfill = 0
p.log_box.yview = lambda: (0, 1)
p.log_box.index = lambda spec: "3.0"
p._rebuild_log()
p._append_log(p.m.log_entries[-1])
p._copy_log(); p._copy_diagnostics()
assert "Last log lines" in p.clipboard_append.call_args[0][0]
p._build_compact(MagicMock())
p._compact = MagicMock(); p._compact.winfo_exists.return_value = True; p._compact.title.return_value = "x"
p._compact_refresh()
p._compact_stop(); p._compact_pause()
p._compact_start()
assert not p._compact_close.__self__ is None
print("SMOKE OK")
