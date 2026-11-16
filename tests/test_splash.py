"""The start-up progress window: the bar follows real steps, the time left comes from the last start, a failure inside
the loading work is not swallowed, and the main window opens through it.   Run:  py tests/test_splash.py"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun_lite import splash as sp  # noqa: E402


def test_time_left_is_read_from_the_previous_start():
    last = {"total": 6.0, "marks": {"12": 0.5, "30": 2.0, "62": 4.0, "92": 5.5}}
    assert sp.remaining(last, 12) == 5.5 and sp.remaining(last, 30) == 4.0 and sp.remaining(last, 92) == 0.5
    assert sp.remaining(last, 45) == 4.0                                  # between two steps: the last one passed
    assert sp.remaining(last, 5) == 6.0                                   # before the first mark: the whole time
    assert sp.remaining({}, 30) is None and sp.remaining({"total": 5}, 30) is None      # a first start: unknown
    assert sp.left_text(None) == "" and sp.left_text(0.4) == "Almost ready" and sp.left_text(4.2) == "About 4 s left"


def test_marks_are_saved_and_read_back():
    root = Path(tempfile.mkdtemp(prefix="rl_sp_"))
    try:
        m = sp.Marks(root)
        assert m.last("load") == {}
        m.save("load", 4.236, {12: 0.4, 40: 1.93})
        again = sp.Marks(root)
        assert again.last("load") == {"total": 4.24, "marks": {"12": 0.4, "40": 1.93}}
        (root / "data" / "lite" / "startup.json").write_text("not json", encoding="utf-8")
        assert sp.Marks(root).last("load") == {}                          # a broken file is not an error
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_bar_follows_the_work_and_reaches_the_end():
    root = Path(tempfile.mkdtemp(prefix="rl_sp_"))
    try:
        (root / "data" / "lite").mkdir(parents=True)
        (root / "data" / "lite" / "startup.json").write_text(
            json.dumps({"load": {"total": 3.0, "marks": {"12": 0.3, "50": 1.5}}}), encoding="utf-8")
        s = sp.Splash(None, root, "load", "Starting ReRun LITE")
        seen = []

        def work():
            s.set(12, "one")
            time.sleep(0.25)
            seen.append(("one", s.shown))
            s.set(50, "two")
            time.sleep(0.4)
            seen.append(("two", s.shown))
            return "result"
        assert s.run_while(work) == "result"
        assert seen[0][1] < 50 <= seen[1][1] + 1                          # it moved while the work was still running
        assert s.shown >= 99.9 and s.text == "two"
        assert sp.left_text(sp.remaining(s.last, 12)) == "About 3 s left"   # from the file written before
        s.close()
        saved = json.loads((root / "data" / "lite" / "startup.json").read_text(encoding="utf-8"))["load"]
        assert saved["total"] > 0.6 and {"12", "50", "100"} <= set(saved["marks"])     # this start is remembered for the next
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_error_in_the_loading_work_comes_out_and_the_window_can_still_close():
    s = sp.Splash(None, None, "load")
    try:
        def boom():
            s.set(30, "loading")
            raise RuntimeError("cv2 is missing")
        try:
            s.run_while(boom)
            raise AssertionError("the error was swallowed")
        except RuntimeError as e:
            assert "cv2 is missing" in str(e)
    finally:
        s.close()
        s.close()                                                         # closing twice is harmless


def test_the_main_window_opens_through_the_progress_bar():
    import tempfile as tf

    import yaml

    from rerun_lite import content
    from rerun_lite.app import LiteApp
    from rerun_lite.manager import LiteManager
    root = Path(tf.mkdtemp(prefix="rl_sp_"))
    try:
        content.copy_to(ROOT, root)
        (root / "config.yaml").write_text(yaml.safe_dump({"instances": [{"name": "A", "serial": "127.0.0.1:5555", "script": "crest"}]}), encoding="utf-8")
        (root / "data" / "lite").mkdir(parents=True, exist_ok=True)
        (root / "data" / "lite" / "ui.json").write_text(json.dumps({"bg_on": False}), encoding="utf-8")
        m = LiteManager(root)
        m.config["setup_seen"] = True
        m.config["live_view_fps"] = 0
        steps = []
        real = sp.Splash.step
        sp.Splash.step = lambda self, pct, text=None: (steps.append((pct, text)), real(self, pct, text))[1]
        try:
            app = LiteApp(m, splash=True)
        finally:
            sp.Splash.step = real
        try:
            app.update()
            assert [p for p, _ in steps] == sorted(p for p, _ in steps) and steps[-1] == (100, "Ready")
            assert {"Building Auto Crest…", "Building Settings…"} <= {t for _, t in steps}
            assert app._splash is None and app.state() == "normal"        # the bar is gone and the window is up
            saved = json.loads((root / "data" / "lite" / "startup.json").read_text(encoding="utf-8"))
            assert "open" in saved and saved["open"]["total"] > 0
        finally:
            app.destroy()
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, repr(e))
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
