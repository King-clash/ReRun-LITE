"""The "Bring your data over?" window (most recent data first, older data in a drop-down) and starting the program
again (the theme-change crash).   Run:  py tests/test_import_offer.py"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ios  # noqa: E402
from rerun_lite import import_offer, restart, theme  # noqa: E402


def make_old(base: Path, name: str, days_ago: float, crests: int = 3) -> Path:
    """An older ReRun folder with a little data, last changed `days_ago` days ago."""
    f = base / name
    f.mkdir()
    (f / "crest_log.jsonl").write_text("\n".join(json.dumps({"n": i}) for i in range(crests)) + "\n", encoding="utf-8")
    (f / "stats.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - days_ago * 86400
    for p in f.iterdir():
        os.utime(p, (stamp, stamp))
    return f


def window():
    win = tk.Tk()
    ios.init(win, theme.apply_palette("ahri"))
    win.withdraw()
    return win


def texts(w) -> list[str]:
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Label):
            out.append(str(c.cget("text")).strip())
        out += texts(c)
    return out


def test_only_the_most_recent_data_shows_and_the_rest_waits_in_a_drop_down():
    base = Path(tempfile.mkdtemp(prefix="rl_imp_"))
    win = window()
    try:
        old_a, new, old_b = make_old(base, "ReRun old", 40), make_old(base, "ReRun newest", 1, crests=9), make_old(base, "ReRun older", 200)
        mine = base / "ReRun LITE"
        mine.mkdir()
        got = []
        page = import_offer.ImportPage(win, mine, [old_a, new, old_b], got.append)       # given in no particular order
        page.pack()
        win.update()
        assert page.newest == new and page.older == [old_a, old_b]                       # newest first, then by age
        assert page.choice.get() == str(new)                                             # already chosen: just press Import
        shown = texts(page)
        assert "ReRun newest" in shown and any("last used yesterday" in t for t in shown)
        assert "ReRun old" not in shown or not page.older_host.winfo_manager()          # the older ones are not on show
        assert not page.older_host.winfo_manager() and "Older data (2)" in " ".join(shown).replace("▸  ", "")
        assert page.toggle.cget("text").startswith("▸")
        page.toggle_older()                                                              # open the drop-down
        win.update()
        assert page.older_host.winfo_manager() == "pack" and page.toggle.cget("text").startswith("▾")
        assert {"ReRun old", "ReRun older"} <= set(texts(page.older_host))
        page.toggle_older()                                                              # and close it again
        win.update()
        assert not page.older_host.winfo_manager()
        # importing without touching anything takes the most recent data
        page.do_import()
        assert got and got[0].startswith("Copied from") and str(new) in got[0]
        assert (mine / "crest_log.jsonl").read_text(encoding="utf-8").count("\n") == 9   # newest's 9 records, not another's
        assert (new / "crest_log.jsonl").exists()                                        # the source is not changed
    finally:
        win.destroy()
        shutil.rmtree(base, ignore_errors=True)


def test_an_older_folder_can_be_picked_and_a_chosen_folder_joins_the_drop_down():
    base = Path(tempfile.mkdtemp(prefix="rl_imp_"))
    win = window()
    try:
        new, old = make_old(base, "ReRun newest", 2), make_old(base, "ReRun old", 90, crests=5)
        mine = base / "ReRun LITE"
        mine.mkdir()
        got = []
        page = import_offer.ImportPage(win, mine, [new, old], got.append)
        page.pack()
        win.update()
        page.choice.set(str(old))                                                        # the user picks the older one
        page.do_import()
        assert (mine / "crest_log.jsonl").read_text(encoding="utf-8").count("\n") == 5
        # Choose folder...: a folder of the user's own goes into the drop-down, selected, and opens it
        mine2 = base / "second"
        mine2.mkdir()
        extra = make_old(base, "somewhere else", 10, crests=2)
        page2 = import_offer.ImportPage(win, mine2, [new], got.append)
        page2.pack()
        win.update()
        assert not page2.toggle.winfo_manager()                                          # nothing older: no drop-down at all
        import_offer.filedialog.askdirectory = lambda **k: str(extra)
        page2.choose()
        win.update()
        assert page2.choice.get() == str(extra) and page2.older_host.winfo_manager() == "pack" and "Older data (1)" in page2.toggle.cget("text")
        import_offer.filedialog.askdirectory = lambda **k: str(base / "no data here")
        (base / "no data here").mkdir()
        page2.choose()
        assert "no ReRun data" in page2.msg.cget("text") and page2.choice.get() == str(extra)     # a folder without data is refused
    finally:
        win.destroy()
        shutil.rmtree(base, ignore_errors=True)


def test_ago_reads_naturally():
    now = 1_000_000_000.0
    assert [import_offer.ago(now - d * 86400, now) for d in (0, 1, 5, 20, 100, 800)] == \
        ["today", "yesterday", "5 days ago", "2 weeks ago", "3 months ago", "over a year ago"]
    assert import_offer.ago(0) == "unknown"


def test_the_saved_appearance_is_read_before_the_app_exists():
    root = Path(tempfile.mkdtemp(prefix="rl_th_"))
    try:
        assert theme.saved_appearance(root).look == "plain"                                  # nothing saved: the default look
        (root / "data" / "lite").mkdir(parents=True)
        ui = root / "data" / "lite" / "ui.json"
        ui.write_text(json.dumps({"appearance": {"look": "midnight", "accent": "#7C5CFC", "density": "compact"}}), encoding="utf-8")
        a = theme.saved_appearance(root)
        assert (a.look, a.accent, a.density) == ("midnight", "#7C5CFC", "compact")
        ui.write_text(json.dumps({"theme": "light"}), encoding="utf-8")                      # a 1.0.x file: carried over
        a = theme.saved_appearance(root)
        assert (a.look, a.mode) == ("classic", "light")
        ui.write_text(json.dumps({"theme": "ahri", "bg_on": False}), encoding="utf-8")
        assert theme.saved_appearance(root).look == "ahri" and theme.saved_appearance(root).background == "off"
        ui.write_text(json.dumps({"appearance": {"look": "nonsense", "accent": "red"}}), encoding="utf-8")
        a = theme.saved_appearance(root)
        assert a.look == "plain" and a.accent == ""                                           # unknown values fall back
        ui.write_text("not json", encoding="utf-8")
        assert theme.saved_appearance(root).look == "plain"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_restart_gives_the_new_process_its_own_unpacked_copy():
    """The crash: after a theme change the exe started itself again, the new process was pointed at the old one's
    temporary folder, that folder vanished when the old process quit, and 'No module named cv2...' followed."""
    seen = {}

    class Fake:
        def __init__(self, cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
    real = restart.subprocess.Popen
    restart.subprocess.Popen = Fake
    old_env = dict(os.environ)
    os.environ["_MEIPASS2"] = r"C:\Temp\_MEI12345"                                       # what a one-file exe's child inherits
    try:
        restart.relaunch(ROOT, ["--selftest", "x.txt"])
    finally:
        restart.subprocess.Popen = real
        os.environ.clear()
        os.environ.update(old_env)
    env = seen["kw"]["env"]
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and "_MEIPASS2" not in env
    assert seen["cmd"][-2:] == ["--selftest", "x.txt"] and seen["kw"]["cwd"] == str(ROOT)
    assert seen["kw"]["close_fds"] is True
    # a frozen exe starts itself directly; from source it starts the same script again
    assert restart.command(["a"])[-1] == "a"
    sys.frozen = True
    try:
        assert restart.command(["a"]) == [sys.executable, "a"]
    finally:
        del sys.frozen


def test_a_real_restart_from_source_runs_a_second_copy():
    """Start the program again for real (from source) into its self-test, and wait for the second copy's answer."""
    out = Path(tempfile.mkdtemp(prefix="rl_rs_")) / "answer.txt"
    try:
        sys.argv = [str(ROOT / "lite_main.py")]
        restart.relaunch(ROOT, ["--selftest", str(out)])
        t0 = time.time()
        while not out.exists() and time.time() - t0 < 90:
            time.sleep(0.5)
        assert out.exists() and out.read_text(encoding="utf-8").startswith("ok "), out.read_text(encoding="utf-8") if out.exists() else "no answer"
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


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
