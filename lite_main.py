"""ReRun LITE - Auto Crest. Start with:  py lite_main.py

A separate app from ReRun (main.py): its own window, exe name (RerunLite.exe), icon and update channel.
It runs the same Crest and checklist code as ReRun; see rerun_lite/__init__.py.

    RerunLite.exe --restart-test FILE   start a second copy (as a theme change does) that runs --selftest FILE
    RerunLite.exe --selftest FILE   build the window once in a throw-away folder, write "ok" or the error to
                                    FILE and exit. No sign-in, no emulator, nothing can be started: it only
                                    proves that a built exe contains everything the window needs.
"""
import sys
import time
import traceback
from pathlib import Path


def app_root() -> Path:
    # Packaged .exe keeps config/templates next to the executable.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def selftest(out: Path) -> int:
    import shutil
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="rerunlite_selftest_"))
    try:
        from rerun_lite import LITE_SCRIPTS
        from rerun_lite.app import LiteApp
        from rerun_lite.manager import LiteManager
        m = LiteManager(root)
        m.config["setup_seen"] = True
        m.config["live_view_fps"] = 0
        app = LiteApp(m)
        app.withdraw()            # built and laid out, never shown
        errors = []
        app.report_callback_exception = lambda *a: errors.append("".join(traceback.format_exception(*a)))
        for i in range(app.nb.count()):
            app.nb.select(i)
            for _ in range(5):
                app.update()
        tabs = [lb.cget("text") for _, lb in app.nb._tabs]
        assert tuple(m.scripts_available()) == LITE_SCRIPTS, m.scripts_available()
        assert not errors, errors[0]
        app.destroy()
        out.write_text("ok " + " | ".join(tabs), encoding="utf-8")
        return 0
    except Exception:  # noqa: BLE001 - the whole point is to report it
        out.write_text("FAILED\n" + traceback.format_exc(), encoding="utf-8")
        return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    root = app_root()
    sys.path.insert(0, str(root))
    if "--restart-test" in sys.argv:        # start this program again, the way a theme change does, into a self-test
        from rerun_lite import restart
        restart.relaunch(root, ["--selftest", sys.argv[sys.argv.index("--restart-test") + 1]])
        raise SystemExit(0)
    if "--selftest" in sys.argv:
        raise SystemExit(selftest(Path(sys.argv[sys.argv.index("--selftest") + 1])))
    try:
        from rerun_lite import palettes
        from rerun_lite.splash import Splash
        import json
        try:                                                              # the chosen theme's colours, before anything heavy loads
            key = json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8")).get("theme")
        except (OSError, ValueError, AttributeError):
            key = None
        splash = Splash(None, root, "load", "Starting ReRun LITE", theme_key=key if key in palettes.LOOKS else palettes.DEFAULT)

        def load():
            splash.set(12, "Loading the window kit…")
            import PIL.Image  # noqa: F401 - loaded now so the bar is honest about where the time goes
            import tkinter  # noqa: F401
            splash.set(30, "Loading the image tools…")
            import cv2  # noqa: F401
            import numpy  # noqa: F401
            splash.set(62, "Loading ReRun LITE…")
            from rerun_lite.app import run_app
            splash.set(92, "Almost ready…")
            return run_app
        try:
            run_app = splash.run_while(load)
        finally:
            splash.close()
        run_app(root)
    except Exception:  # noqa: BLE001 - the windowed app has no console to show this
        (root / "crash.log").write_text(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}", encoding="utf-8")
        raise
