"""Finding older copies of ReRun LITE and moving them to the Recycle Bin (only on request, never the running copy).
Run:  py tests/test_old_versions.py"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ios  # noqa: E402
from rerun_lite import old_versions as ov  # noqa: E402
from tests.test_lite import close, open_lite, texts, wait_until  # noqa: E402


def make_install(folder: Path, data: bool = False, size: int = 2000):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "RerunLite.exe").write_bytes(b"x" * size)
    if data:
        (folder / "stats.json").write_text("{}", encoding="utf-8")


def tree() -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="ov_")).resolve()
    make_install(tmp / "RerunLite-1.1.2" / "RerunLite")                      # the running copy
    make_install(tmp / "RerunLite-1.1.0" / "RerunLite")                      # older, wrapped in a version folder
    make_install(tmp / "RerunLite-1.1.1" / "RerunLite", data=True)           # older, holds data
    (tmp / "RerunLite-1.0.0.zip").write_bytes(b"z" * 500)                    # an older download
    (tmp / "RerunLite-1.1.2.zip").write_bytes(b"z" * 500)                    # this version's own download
    (tmp / "RerunLite-9.0.0.zip").write_bytes(b"z" * 500)                    # a newer one
    make_install(tmp / "RerunLite-1.3.0" / "RerunLite")                      # a newer folder
    (tmp / "RerunLite-0.9").mkdir()                                          # named alike, no exe: not an install
    (tmp / "src" / ".git").mkdir(parents=True)
    make_install(tmp / "src" / "dist" / "RerunLite-1.0.0")                   # build output of a source checkout
    make_install(tmp / "Elsewhere" / "Old" / "RerunLite-1.0.5")              # deeper, no wrapper
    return tmp, tmp / "RerunLite-1.1.2" / "RerunLite"


def test_older_copies_are_found_and_everything_else_is_left_alone():
    tmp, cur = tree()
    try:
        found = ov.find_old(cur, "1.1.2", roots=[tmp])
        names = {o.target.name for o in found}
        assert names == {"RerunLite-1.1.1", "RerunLite-1.1.0", "RerunLite-1.0.0.zip", "RerunLite-1.0.5"}, names
        by = {o.target.name: o for o in found}
        assert by["RerunLite-1.1.1"].has_data and not by["RerunLite-1.1.0"].has_data
        assert by["RerunLite-1.0.0.zip"].kind == "zip" and all(o.size > 0 for o in found)
        assert [ov.version_text(o.version) for o in found][:2] == ["1.1.1", "1.1.0"]        # newest version first
        assert by["RerunLite-1.1.0"].target == tmp / "RerunLite-1.1.0"                      # the wrapper folder goes with it
        for o in found:
            assert ov.safe_to_remove(o, cur) == ""
        # the running copy, its wrapper and its parent are never removable, however they got into a list
        for t in (cur, cur.parent, tmp):
            assert ov.safe_to_remove(ov.Old(t, "folder", (1, 0, 0)), cur), t
        assert ov.safe_to_remove(ov.Old(tmp / "RerunLite-0.9", "folder", (0, 9)), cur)    # no exe inside
        assert ov.safe_to_remove(ov.Old(tmp / "src" / "dist" / "RerunLite-1.0.0", "folder", (1, 0, 0)), cur)   # a source checkout
        assert ov.safe_to_remove(ov.Old(Path(tmp.anchor), "folder", (1, 0, 0)), cur)
        assert ov.safe_to_remove(ov.Old(tmp / "gone", "folder", (1, 0, 0)), cur) == "already gone"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_versions_are_read_and_sizes_are_shown():
    assert ov.parse_version("RerunLite-1.1.1") == (1, 1, 1) and ov.parse_version("Rerun LITE v2.0") == (2, 0)
    assert ov.parse_version("RerunLite-1.1.1.zip") == (1, 1, 1) and ov.parse_version("Rerun-1.2.1") is None
    assert ov.parse_version("downloads") is None and (1, 1, 1) < (1, 1, 2) < (1, 2) and not (1, 1, 2) < (1, 1, 2)
    assert [ov.human_size(n) for n in (0, 900, 2048, 5 * 1024 ** 2, 126 * 1024 ** 2, 3 * 1024 ** 3)] == ["0 B", "900 B", "2 KB", "5 MB", "126 MB", "3 GB"]


def test_removal_goes_to_the_recycle_bin_one_by_one_and_reports_failures():
    tmp, cur = tree()
    try:
        found = ov.find_old(cur, "1.1.2", roots=[tmp])
        calls = []

        def fake(paths):
            calls.append(paths[0].name)
            return "in use" if paths[0].name == "RerunLite-1.1.0" else ""
        done, failed = ov.remove(found, cur, remover=fake)
        assert len(done) == 3 and [(o.label, why) for o, why in failed] == [("RerunLite-1.1.0", "in use")]
        assert (tmp / "RerunLite-1.1.0").exists() and "RerunLite-1.1.2" not in calls        # the fake removed nothing; the running copy was never offered
        calls.clear()                                                                        # a refused one never reaches the remover
        done, failed = ov.remove([ov.Old(cur, "folder", (1, 0))], cur, remover=fake)
        assert not done and failed and not calls
        victim = Path(tempfile.mkdtemp(prefix="ov_trash_")).resolve()                        # the real Recycle Bin, on a tiny folder made here
        (victim / "a.txt").write_text("x", encoding="utf-8")
        assert ov.recycle([victim]) == "" and not victim.exists()
        assert ov.recycle([]) == ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_window_lists_ticks_what_is_safe_and_removes_only_after_confirmation():
    tmp, cur = tree()
    root, m, inst, app = open_lite()
    real_recycle, real_safe, real_dialog, real_confirm = ov.recycle, ov.safe_to_remove, ov.OldVersionsDialog, ios.confirm
    try:
        found = ov.find_old(cur, "1.1.2", roots=[tmp])
        removed = []
        ov.recycle = lambda paths: (removed.extend(p.name for p in paths), "")[1]
        ov.safe_to_remove = lambda o, current: ""                     # the tree here is not the running app's
        app._ov_scan = lambda done: done(found)
        app.show_old_versions()
        app.update()
        dlg = next(w for w in app.winfo_children() if isinstance(w, ov.OldVersionsDialog))
        said = " ".join(texts(dlg))
        buttons = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ios.Button):
                    buttons.append(c._text)
                walk(c)
        walk(dlg)
        for needle in ("Older versions found", "RerunLite-1.1.1", "RerunLite-1.1.0", "RerunLite-1.0.0.zip", "Holds your own data"):
            assert needle in said, needle
        assert "Not now" in buttons and "Don't ask again" in buttons and any(b.startswith("Move 3") for b in buttons), buttons
        picked = {o.label for o in dlg.chosen()}
        assert picked == {"RerunLite-1.1.0", "RerunLite-1.0.0.zip", "RerunLite-1.0.5"}, picked     # the one with data is not ticked
        asked = []
        ios.confirm = lambda *a, **k: (asked.append(a[1]), False)[1]
        dlg.remove_selected()
        assert asked and not removed and dlg.winfo_exists()                                      # declined: nothing happens
        ios.confirm = lambda *a, **k: (asked.append(a[1]), True)[1]
        dlg.remove_selected()
        assert sorted(removed) == ["RerunLite-1.0.0.zip", "RerunLite-1.0.5", "RerunLite-1.1.0"] and not dlg.winfo_exists()
        app.show_old_versions()                                                                  # "do not ask again" is remembered
        app.update()
        dlg = next(w for w in app.winfo_children() if isinstance(w, ov.OldVersionsDialog))
        dlg.never()
        assert app._ov_dismissed() == {str(o.target) for o in found}
        shown = []
        ov.OldVersionsDialog = lambda *a, **k: shown.append(1)
        app._ov_auto()                                                                           # the start-up check stays quiet for exactly those
        assert wait_until(app, lambda: True) and not shown
        assert not app.errors, app.errors
    finally:
        ov.recycle, ov.safe_to_remove, ov.OldVersionsDialog, ios.confirm = real_recycle, real_safe, real_dialog, real_confirm
        close(app, root)
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_settings_page_and_the_palette_offer_it():
    root, m, inst, app = open_lite()
    try:
        app.nb.select(app._tab_settings)
        app._set_nav.select("app")
        app.update()
        assert "Older versions" in " ".join(texts(app._set_pages["app"]))
        assert any(c.title == "Find older versions of ReRun LITE" for c in app.commands())
    finally:
        close(app, root)


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t0 = time.time()
            t()
            print(f"PASS {t.__name__} ({time.time() - t0:.0f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, repr(e), flush=True)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
