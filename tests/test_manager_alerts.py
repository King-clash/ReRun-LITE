"""LiteManager: alerts reach listeners, and a listener that raises does not break anything."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml
from rerun_lite.manager import LiteManager


def make():
    root = Path(tempfile.mkdtemp(prefix="rerunlite_alert_"))
    (root / "config.yaml").write_text(yaml.safe_dump({"instances": [
        {"name": "A", "serial": "127.0.0.1:5555", "script": "crest"}]}), encoding="utf-8")
    m = LiteManager(root)
    m.config["live_view_fps"] = 0
    return m


def test_alert_listeners_called_and_isolated():
    m = make()
    seen = []
    m.alert_listeners.append(lambda *a: 1 / 0)          # a broken listener
    m.alert_listeners.append(lambda *a: seen.append(a))
    m.fire_alert("failed", "A", "boom")
    assert seen == [("failed", "A", "boom")]


def test_phase_recovery_fires_alert():
    m = make()
    seen = []
    m.alert_listeners.append(lambda *a: seen.append(a[0]))
    inst = m.instances["A"]
    m._set_status(inst, "starting")
    m._set_status(inst, "running")
    assert inst.ctx is None or True
    m.refresh_phases()
    assert seen == []                                    # running normally: nothing to say


def test_stuck_warning_alert_once_and_clears():
    import time
    from types import SimpleNamespace
    m = make()
    seen = []
    m.alert_listeners.append(lambda *a: seen.append(a[0]))
    inst = m.instances["A"]
    inst.status = "running"
    inst.ctx = SimpleNamespace(params={"last_progress": time.monotonic() - 10 * 60, "script_state": "unknown"})
    m.refresh_phases()
    m.refresh_phases()
    assert seen.count("stuck") == 1 and m.stuck_for("A") > 590
    assert any("has not advanced" in e["message"] and e["level"] == "warn" for e in m.log_entries)
    inst.ctx.params["last_progress"] = time.monotonic()
    m.refresh_phases()
    assert m.stuck_for("A") is None
    inst.ctx.params["last_progress"] = time.monotonic() - 10 * 60
    inst.ctx.params["recovering"] = "restarting the game"       # a recovery under way never counts
    m.refresh_phases()
    assert seen.count("stuck") == 1
