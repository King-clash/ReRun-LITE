"""Keep your data when Rerun is updated.

Rerun keeps its data next to Rerun.exe. Replacing Rerun.exe in the same folder keeps
everything already (and new settings are merged into your config, never reset). A new
copy started from another folder used to start empty; now:

  * every start records its folder in %LOCALAPPDATA%\\Rerun\\installs.json;
  * a copy that starts with none of your data finds the previous Rerun (that list, plus
    the usual places: Downloads, Desktop, Documents) and offers to bring its data over;
  * Settings › "Import from another Rerun…" does the same from a folder you pick.

Importing COPIES (the old folder is never changed):
  config.yaml (replaces the new copy's; the new one is kept as config.before_import.yaml),
  stats, crest log + screenshots, History, Units (roster, scans, names, targets), the key
  (license.json), the daily-summary state, GS Companion data and its settings, templates
  you captured or tuned, and your own routines. Files the new copy already has are kept,
  except config.yaml. A note of what was copied goes to migrated_from.json.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

# files / folders that are yours (never part of a download)
USER_FILES = ["stats.json", "crest_log.jsonl", "license.json", "summary_state.json",
              "compendium_report.csv", "discord_board.json"]
USER_DIRS = ["history", "units", "crest_shots", "data"]
# any of these means "this folder already has your data"
MARKERS = ["stats.json", "crest_log.jsonl", "license.json", "history/history.jsonl",
           "units/roster.json"]
REGISTRY = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Rerun" / "installs.json"
SEARCH_DIRS = ("Downloads", "Desktop", "Documents")
SEARCH_DEPTH = 3


def has_user_data(folder: str | Path) -> bool:
    f = Path(folder)
    return any((f / m).exists() for m in MARKERS)


def data_time(folder: str | Path) -> float:
    """When the folder's data last changed (newest marker)."""
    f = Path(folder)
    times = []
    for m in MARKERS:
        try:
            times.append((f / m).stat().st_mtime)
        except OSError:
            pass
    return max(times, default=0.0)


def facts(folder: str | Path) -> dict:
    """How much data a folder holds: units, History entries, crests logged, key."""
    f = Path(folder)

    def lines(p: Path) -> int:
        try:
            with p.open("rb") as fh:
                return sum(1 for _ in fh)
        except OSError:
            return 0
    try:
        units = len(json.loads((f / "units" / "roster.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        units = 0
    return {"units": units, "history": lines(f / "history" / "history.jsonl"),
            "crest_log": lines(f / "crest_log.jsonl"), "key": (f / "license.json").exists(),
            "last_used": data_time(f)}


def describe(folder: str | Path) -> str:
    x = facts(folder)
    bits = [f"{x['units']} units" if x["units"] else "", f"{x['history']:,} History entries"
            if x["history"] else "", f"{x['crest_log']:,} crest records" if x["crest_log"] else "",
            "key" if x["key"] else ""]
    when = time.strftime("%d %b %Y %H:%M", time.localtime(x["last_used"])) if x["last_used"] else "?"
    return " · ".join(b for b in bits if b) + f"  (last used {when})"


def richness(folder: str | Path) -> int:
    x = facts(folder)
    return x["units"] * 10 + x["history"] + x["crest_log"]


# ---------------------------------------------------------------- where Rerun ran
def _load_registry(path: Path = REGISTRY) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(folder: str | Path, path: Path = REGISTRY) -> None:
    """Record that Rerun ran from this folder (best effort)."""
    try:
        d = _load_registry(path)
        d.setdefault("folders", {})[str(Path(folder).resolve())] = time.time()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def mark_declined(folder: str | Path, path: Path = REGISTRY) -> None:
    """'Start fresh' was chosen for this folder: don't ask again."""
    try:
        d = _load_registry(path)
        d.setdefault("declined", []).append(str(Path(folder).resolve()))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass


def was_declined(folder: str | Path, path: Path = REGISTRY) -> bool:
    return str(Path(folder).resolve()) in _load_registry(path).get("declined", [])


def _scan(home: Path) -> list[Path]:
    """Folders with Rerun.exe or main.py next to Rerun data, a few levels below the usual
    places (cheap: stops at SEARCH_DEPTH, skips hidden and big system folders)."""
    out = []
    for base in SEARCH_DIRS:
        root = home / base
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                if ((d / "Rerun.exe").exists() or (d / "main.py").exists()) and has_user_data(d):
                    out.append(d)
                if depth >= SEARCH_DEPTH:
                    continue
                for c in d.iterdir():
                    if c.is_dir() and not c.name.startswith((".", "$")) and \
                            c.name not in ("node_modules", "__pycache__", "backups", "history",
                                           "units", "templates", "debug", "data"):
                        stack.append((c, depth + 1))
            except OSError:
                continue
    return out


def find_previous(current: str | Path, path: Path = REGISTRY,
                  home: Path | None = None) -> list[Path]:
    """Other Rerun folders with your data, newest data first."""
    cur = Path(current).resolve()
    seen, found = set(), []
    for f in list(_load_registry(path).get("folders", {})) + [str(p) for p in _scan(home or Path.home())]:
        p = Path(f).resolve()
        if p == cur or p in seen or not p.is_dir() or not has_user_data(p) or (p / ".git").exists():
            continue  # (.git: Rerun's source folder, not an install)
        seen.add(p)
        found.append(p)
    return sorted(found, key=data_time, reverse=True)


# ---------------------------------------------------------------- copying
def _copy_tree_missing(src: Path, dst: Path, skip: tuple[str, ...] = ()) -> int:
    """Copy files from src that dst doesn't have yet. Returns how many."""
    n = 0
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in skip for part in rel.parts) or not p.is_file():
            continue
        t = dst / rel
        if t.exists():
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, t)
        n += 1
    return n


def _templates(src: Path, dst: Path) -> int:
    """Templates you captured or tuned: any template whose image or settings differ from
    the new copy's (or that it lacks). The new copy's stock templates stay otherwise."""
    s, d = src / "templates", dst / "templates"
    if not s.is_dir():
        return 0
    try:
        sm = json.loads((s / "_meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sm = {}
    try:
        dm = json.loads((d / "_meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dm = {}
    n = 0
    d.mkdir(parents=True, exist_ok=True)
    for img in s.glob("*.png"):
        name, t = img.stem, d / img.name
        differs = not t.exists() or sm.get(name) != dm.get(name) or \
            img.stat().st_size != t.stat().st_size
        if differs:
            shutil.copy2(img, t)
            if name in sm:
                dm[name] = sm[name]
            n += 1
    if n:
        (d / "_meta.json").write_text(json.dumps(dm, indent=2), encoding="utf-8")
    return n


def import_data(src: str | Path, dst: str | Path, replace: bool = False) -> dict:
    """Copy your data from an older Rerun folder into this one (src is never changed).
    replace=True (Settings › Import): this folder's own data is first moved to
    backups/before_import_<time>/ so the other folder's data replaces it whole."""
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst:
        raise ValueError("That is this Rerun's own folder")
    if not has_user_data(src):
        raise ValueError(f"No Rerun data found in {src}")
    done: dict[str, int] = {}
    if replace:
        keep = dst / "backups" / time.strftime("before_import_%Y%m%d_%H%M%S")
        for name in USER_FILES + [d for d in USER_DIRS if d != "data"]:
            if (dst / name).exists() and (src / name).exists():
                keep.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst / name), str(keep / name))
        if keep.exists():
            done["backup"] = 1
    cfg = src / "config.yaml"
    if cfg.exists():
        if (dst / "config.yaml").exists():
            shutil.copy2(dst / "config.yaml", dst / "config.before_import.yaml")
        shutil.copy2(cfg, dst / "config.yaml")
        done["config.yaml"] = 1
    for f in USER_FILES:
        if (src / f).exists() and not (dst / f).exists():
            shutil.copy2(src / f, dst / f)
            done[f] = 1
    for folder in USER_DIRS:
        if (src / folder).is_dir():
            n = _copy_tree_missing(src / folder, dst / folder, skip=("raw",))
            if n:
                done[folder + "/"] = n
    n = _templates(src, dst)
    if n:
        done["templates/"] = n
    if (src / "routines").is_dir():
        n = _copy_tree_missing(src / "routines", dst / "routines")
        if n:
            done["routines/"] = n
    note = {"from": str(src), "t": time.time(), "copied": done}
    (dst / "migrated_from.json").write_text(json.dumps(note, indent=1), encoding="utf-8")
    return done


def summary(done: dict) -> str:
    names = {"config.yaml": "settings", "stats.json": "stats", "crest_log.jsonl": "crest log",
             "license.json": "key", "history/": "History", "units/": "Units",
             "crest_shots/": "crest screenshots", "data/": "GS Companion data",
             "templates/": "templates", "routines/": "routines"}
    parts = [names.get(k, k) for k in done if k in names]
    return ", ".join(parts) if parts else "nothing new"


__all__ = ["has_user_data", "remember", "find_previous", "import_data", "summary", "describe",
           "richness", "facts", "mark_declined", "was_declined", "REGISTRY"]
