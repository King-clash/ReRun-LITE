import io, sys, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rerun_lite import diagnostics as d, health as h

TOKEN = "MTAwMDAwMDAwMDAwMDAwMDAw.GabcDE.abcdefghijklmnopqrstuvwxyz012345"


def test_redact_config_by_key_and_by_look():
    cfg = {"discord": {"enabled": True, "token": TOKEN, "channel_id": 123, "webhook": "https://discord.com/api/webhooks/1/abc",
                       "note": f"see {TOKEN}"}, "hotkeys": {"stop_all": "f12"}, "adb_path": r"C:\Users\Dan\adb.exe",
           "license_key": "ABCD-1234"}
    r = d.redact(cfg)
    s = str(r)
    assert TOKEN not in s and "api/webhooks" not in s and "ABCD-1234" not in s and "Dan" not in s
    assert r["discord"]["enabled"] is True and r["hotkeys"]["stop_all"] == "f12" and r["discord"]["channel_id"] == 123


def test_bundle_is_flat_redacted_zip():
    z = zipfile.ZipFile(io.BytesIO(d.build_bundle({"../evil/log.txt": f"x {TOKEN} y", "a.txt": r"C:\Users\Bob\x"})))
    assert sorted(z.namelist()) == ["a.txt", "log.txt"]
    assert TOKEN not in z.read("log.txt").decode() and "Bob" not in z.read("a.txt").decode()


def test_clean_session_drops_account():
    assert "account" not in d.clean_session({"account": "me", "runs": 3}) and d.clean_session({"runs": 3})["runs"] == 3


class Runs:
    def sessions(self, limit=5): return [{"ended": "failed", "runs": 0}] * 3 + [{"ended": "completed"}]


class M:
    root = Path("/tmp")
    instances = {"A": object()}
    log_entries = [{"level": "error", "message": "boom"}, {"level": "info", "message": "config.yaml: unknown setting 'x'"}]
    runs = Runs()
    def stuck_for(self, n): return None
    def script_settings(self, n, s): return {"mode_247": True, "max_restarts_per_day": 0}
    def missing_templates(self, s): return []
    def template_checklist(self, s): return []
    config = {}


def test_health_items(monkeypatch):
    from rerun_lite import readiness
    monkeypatch.setattr(readiness, "crest_problems", lambda m, i: [])
    items = h.run_local(M())
    titles = {i.title: i for i in items}
    assert titles["A: no limit on game restarts"].fix == "set_cap:A"
    assert titles["Recent errors"].state == "warn" and titles["config.yaml"].state == "warn"
    assert titles["Recent sessions"].state == "warn"
    assert h.worst(items) == "warn" and "WARN" in h.as_text(items)


def test_a_log_line_about_a_saved_screen_loses_the_user_name_and_pictures_cannot_enter_a_bundle():
    line = r"Crest: today is X. A picture of the screen was saved to C:\Users\Dandre\Documents\ReRun-LITE\debug\20261119_palace_not_found.png."
    cleaned = d.redact_text(line)
    assert "Dandre" not in cleaned and "<user>" in cleaned
    z = zipfile.ZipFile(io.BytesIO(d.build_bundle({"log.txt": cleaned})))
    assert z.namelist() == ["log.txt"]                                   # the bundle is built from text only
    try:
        d.build_bundle({"debug/shot.png": b"\x89PNG not text"})
        raise AssertionError("a picture must not be accepted as a bundle part")
    except (TypeError, AttributeError, ValueError):
        pass
