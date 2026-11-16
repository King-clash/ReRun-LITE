"""Keeps the pictures and videos attached to the app.

Every build of ReRun LITE (personal or the public release) carries inside the exe a copy of the files that are not code:
the background video(s) (the `background` folder), the palace pictures (`images/`), the palace list (`palaces.yaml`) and,
in a personal build only, the palace schedule. On start-up the app copies any of them that are missing from its own
folder, so they come back by themselves if the folder is moved, a new build lands in a new folder, or a file is deleted
by accident.

It only ever ADDS files that are missing. A file that exists is never replaced, so anything you changed stays as you
left it. (Whose artwork these are is in CREDITS.md.)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

SEED = "seed"
# (path inside the seed folder, what it is)
PARTS = ("palaces.yaml", "images", "background", "data/lite/palace_schedule.json")
SKIP = {"README.txt"}


def bundle_seed() -> Path | None:
    """The seed folder inside the running exe (None when run from source or when the build carried none)."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    p = Path(base) / SEED
    return p if p.is_dir() else None


def seed_files(seed: Path) -> list[Path]:
    """Every file under `seed`, relative to it."""
    return sorted(p.relative_to(seed) for p in seed.rglob("*") if p.is_file() and p.name not in SKIP)


def restore(root: str | Path, seed: Path | None = None) -> list[str]:
    """Copy into `root` every seeded file that is not there yet. Returns what was copied (relative paths)."""
    root = Path(root)
    seed = seed if seed is not None else bundle_seed()
    if seed is None or not seed.is_dir():
        return []
    copied: list[str] = []
    for rel in seed_files(seed):
        dst = root / rel
        if dst.exists():
            continue                                            # never replace anything that is already there
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(seed / rel, dst)
            copied.append(rel.as_posix())
        except OSError:
            continue
    return copied


def stage(project: str | Path, out: str | Path, schedule: bool = True) -> list[str]:
    """Build time: copy the files that travel with the app (videos, palace pictures, palace list, and - unless
    `schedule` is False - the palace schedule) from the project folder into `out`."""
    project, out = Path(project), Path(out)
    staged: list[str] = []
    for part in PARTS:
        if part.endswith("palace_schedule.json") and not schedule:
            continue                                            # a personal setting: the public release leaves it out
        src = project / part
        if src.is_file():
            files = [src]
        elif src.is_dir():
            files = [p for p in src.rglob("*") if p.is_file() and p.name not in SKIP]
        else:
            continue
        for f in files:
            rel = f.relative_to(project)
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            staged.append(rel.as_posix())
    return staged
