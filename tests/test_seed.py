"""The pictures and videos stay attached to the app: every build carries them, gives back any that are missing,
never replaces what is there, and only the public release leaves out your personal palace schedule.   Run:  py tests/test_seed.py"""
from __future__ import annotations

import inspect
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun_lite import seed  # noqa: E402


def make_project(base: Path) -> Path:
    p = base / "project"
    (p / "images").mkdir(parents=True)
    (p / "background").mkdir()
    (p / "data" / "lite").mkdir(parents=True)
    (p / "palaces.yaml").write_text("Ember Palace: images/ember_palace.png\n", encoding="utf-8")
    (p / "images" / "ember_palace.png").write_bytes(b"png-bytes")
    (p / "background" / "mine.gif").write_bytes(b"gif-bytes")
    (p / "background" / "README.txt").write_text("a note", encoding="utf-8")
    (p / "data" / "lite" / "palace_schedule.json").write_text('{"mode": "weekday"}', encoding="utf-8")
    for name in ("config.yaml", "license.json", "stats.json", "crash.log"):                 # NOT yours to bundle
        (p / name).write_text("private", encoding="utf-8")
    (p / "data" / "lite" / "ui.json").write_text("{}", encoding="utf-8")
    (p / "data" / "lite" / "cache").mkdir()
    (p / "data" / "lite" / "cache" / "big.mp4").write_bytes(b"cache")
    return p


def test_a_personal_build_bundles_only_your_pictures_videos_list_and_schedule():
    base = Path(tempfile.mkdtemp(prefix="rl_seed_"))
    try:
        project = make_project(base)
        out = base / "seed"
        staged = seed.stage(project, out)
        assert sorted(staged) == ["background/mine.gif", "data/lite/palace_schedule.json", "images/ember_palace.png", "palaces.yaml"]
        public = seed.stage(project, base / "seed_public", schedule=False)                   # the public release leaves the schedule out
        assert sorted(public) == ["background/mine.gif", "images/ember_palace.png", "palaces.yaml"]
        assert not (base / "seed_public" / "data").exists()
        assert not (out / "config.yaml").exists() and not (out / "license.json").exists() and not (out / "stats.json").exists()
        assert not (out / "background" / "README.txt").exists()                              # the program's own note is not yours
        assert not (out / "data" / "lite" / "ui.json").exists() and not (out / "data" / "lite" / "cache").exists()
        assert seed.stage(base / "nothing here", base / "seed2") == []                       # no files of yours: nothing bundled
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_missing_files_come_back_and_existing_ones_are_never_replaced():
    base = Path(tempfile.mkdtemp(prefix="rl_seed_"))
    try:
        project = make_project(base)
        bundled = base / "seed"
        seed.stage(project, bundled)
        root = base / "new folder"                                                           # a brand new app folder
        root.mkdir()
        assert sorted(seed.restore(root, bundled)) == ["background/mine.gif", "data/lite/palace_schedule.json", "images/ember_palace.png", "palaces.yaml"]
        assert (root / "images" / "ember_palace.png").read_bytes() == b"png-bytes"
        assert seed.restore(root, bundled) == []                                             # a second start copies nothing
        (root / "palaces.yaml").write_text("Ember Palace: images/my_own.png\n", encoding="utf-8")      # you changed it
        (root / "images" / "ember_palace.png").unlink()                                      # ... and lost a picture
        assert seed.restore(root, bundled) == ["images/ember_palace.png"]                    # only the missing one returns
        assert (root / "palaces.yaml").read_text(encoding="utf-8") == "Ember Palace: images/my_own.png\n"   # your edit stays
        assert seed.restore(root, base / "no such seed") == [] and seed.restore(root) == []   # from source there is no bundle
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_restored_files_are_what_the_app_looks_for():
    from rerun_lite import background, palaces
    base = Path(tempfile.mkdtemp(prefix="rl_seed_"))
    try:
        project = make_project(base)
        (project / "images" / "ember_palace.png").write_bytes(b"x")
        seed.stage(project, base / "seed")
        root = base / "app"
        root.mkdir()
        seed.restore(root, base / "seed")
        assert background.find_video(root).name == "mine.gif"                                # your video is the one that plays
        assert [(p.name, p.image) for p in palaces.read_list(root)] == [("Ember Palace", "images/ember_palace.png")]
        assert palaces.load_schedule(root).mode == "weekday"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_every_build_carries_the_pictures_and_only_the_public_one_leaves_out_your_schedule():
    import build_lite
    assert build_lite.INCLUDE_SCHEDULE is True                                               # a personal build carries the schedule too
    src = inspect.getsource(build_lite.release)
    assert "INCLUDE_SCHEDULE = False" in src                                                 # ... the release leaves it out
    assert src.index("INCLUDE_SCHEDULE = False") < src.index("built(out)")                   # before anything is built
    assert "seed.stage(ROOT, work / \"seed\"" in inspect.getsource(build_lite.build_exe)     # the exe always carries the seed
    assert "seed.stage(ROOT, dist" in inspect.getsource(build_lite.copy_content)            # ... and so does the folder beside it


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
