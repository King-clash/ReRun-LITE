"""Build log: every build of Rerun, GS Companion and the Keygen, listed in one place.

Each run of build.py, gsc_app/build_exe.py or tools/build_keygen.py - finished or failed - adds
a line to builds.jsonl and rewrites BUILDS.md, a table of all of them (newest first):
when, what, which version and git commit (and whether there were uncommitted changes), how long
it took, the exe's size and fingerprint, and for Rerun the templates, routines, OCR bundle,
zip size and the release leak check.

    py tools/buildlog.py              rewrite BUILDS.md and print the latest builds
    py tools/buildlog.py --backfill   also add exes already in dist/ and release/ that were
                                      built before this log existed (facts read from the files)
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "builds.jsonl"
TABLE = ROOT / "BUILDS.md"
OWN_FILES = {"builds.jsonl", "BUILDS.md"}


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def git_facts() -> dict:
    changed = [ln[3:] for ln in _git("status", "--porcelain").splitlines()
               if ln[3:].strip('"') not in OWN_FILES]
    return {"commit": _git("rev-parse", "--short", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "uncommitted": len(changed)}


def _version() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from rerun import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return ""


def _pyinstaller() -> str:
    try:
        import PyInstaller
        return PyInstaller.__version__
    except Exception:  # noqa: BLE001
        return ""


def sha12(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def exe_facts(exe: Path, since: float = 0.0) -> dict:
    """Size and fingerprint of the exe - only if it was written by this build."""
    exe = Path(exe)
    if not exe.is_file() or exe.stat().st_mtime < since:
        return {}
    return {"exe_mb": round(exe.stat().st_size / 1e6, 1), "exe_sha": sha12(exe)}


def record(entry: dict) -> dict:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    render()
    return entry


def logged(app: str, exe: Path, build: Callable[[], int], kind: str = "build",
           info: dict | None = None) -> int:
    """Run a build function and log it, whatever happens. `info` is filled in by the build
    with extra facts (templates, zip size, leak check...)."""
    info = info if info is not None else {}
    start, code, error = time.time(), 1, ""
    try:
        code = int(build() or 0)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        error = "" if code == 0 else str(e.code if not isinstance(e.code, int) else "")
    except BaseException as e:  # noqa: BLE001 - log it, then let it through
        error = f"{type(e).__name__}: {e}"
        _write(app, exe, kind, start, 1, error, info)
        traceback.print_exc()
        raise
    _write(app, exe, kind, start, code, error or info.pop("error", ""), info)
    return code


def _write(app, exe, kind, start, code, error, info) -> None:
    try:
        e = {"time": datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M:%S"), "app": app,
             "kind": kind, "version": _version() if app == "Rerun" else "",
             **git_facts(), "ok": code == 0, "seconds": round(time.time() - start, 1),
             "output": _rel(Path(exe).parent), **(exe_facts(exe, start) if code == 0 else {}),
             "python": platform.python_version(), "pyinstaller": _pyinstaller()}
        if error:
            e["error"] = str(error)[:300]
        e.update({k: v for k, v in info.items() if v not in (None, "")})
        record(e)
        print(f"Logged in BUILDS.md ({'ok' if e['ok'] else 'FAILED'}, {e['seconds']} s)")
    except Exception as ex:  # noqa: BLE001 - the log must never break a build
        print(f"(build log not written: {ex})")


# ------------------------------------------------------------------ the table
def load() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def _cell(v) -> str:
    return "-" if v in (None, "", [], {}) else str(v).replace("|", "/")


def render() -> str:
    rows = sorted(load(), key=lambda e: e.get("time", ""), reverse=True)
    lines = ["# Builds", "",
             "Every build of Rerun, GS Companion and the Keygen, newest first. Written by "
             "`tools/buildlog.py` each time a build script runs (from `builds.jsonl`); do not "
             "edit by hand.", ""]
    latest = {}
    for e in rows:
        if e.get("ok"):
            latest.setdefault((e["app"], e.get("kind")), e)
    if rows:
        fails = sum(not e.get("ok") for e in rows)
        lines += [f"**{len(rows)} builds** ({len(rows) - fails} ok, {fails} failed). Latest good build "
                  "of each:", "",
                  "| App | Kind | When | Version | Commit | Exe | Output |",
                  "|---|---|---|---|---|---|---|"]
        for (app, kind), e in sorted(latest.items()):
            lines.append(f"| {app} | {kind} | {e['time']} | {_cell(e.get('version'))} | "
                         f"{_commit(e)} | {_cell(e.get('exe_mb'))} MB | `{e.get('output')}` |")
        lines += ["", "## All builds", "",
                  "| When | App | Kind | Version | Commit | Result | Took | Exe MB | Exe SHA-256 | "
                  "Zip MB | Templates | Routines | OCR | Leak check | Output |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for e in rows:
            result = "ok" if e.get("ok") else f"**failed**{': ' + _cell(e['error']) if e.get('error') else ''}"
            took = f"{e['seconds']:.0f} s" if isinstance(e.get("seconds"), (int, float)) else "-"
            lines.append(" | ".join([
                f"| {e.get('time', '-')}", e.get("app", "-"), _cell(e.get("kind")),
                _cell(e.get("version")), _commit(e), result, took, _cell(e.get("exe_mb")),
                f"`{e['exe_sha']}`" if e.get("exe_sha") else "-", _cell(e.get("zip_mb")),
                _cell(e.get("templates")), _cell(e.get("routines")), _cell(e.get("ocr")),
                _cell(e.get("leak_check")), f"`{_cell(e.get('output'))}` |"]))
        lines += ["", "*Commit*: `+N` = N files had uncommitted changes when it was built; "
                      "`~` = guessed from the file date (built before this log existed)."]
    else:
        lines.append("No builds yet.")
    text = "\n".join(lines) + "\n"
    TABLE.write_text(text, encoding="utf-8")
    return text


def _commit(e: dict) -> str:
    c = e.get("commit") or "-"
    if e.get("guessed"):
        c = "~" + c
    if e.get("uncommitted"):
        c += f" +{e['uncommitted']}"
    return f"`{c}`"


# ------------------------------------------------------------------ backfill
KNOWN = [("Rerun", "dist/Rerun/Rerun.exe", "build"),
         ("Rerun", "dist/Rerun (key system)/Rerun.exe", "build"),
         ("Rerun", "release/Rerun/Rerun.exe", "release"),
         ("GS Companion", "dist/GS Companion/GS Companion.exe", "build"),
         ("Rerun Keygen", "dist/Rerun Keygen/Rerun Keygen.exe", "build")]


def backfill() -> int:
    """Log exes built before this log existed, from what the files still tell."""
    have = {e.get("exe_sha") for e in load()}
    added = 0
    for app, rel, kind in KNOWN:
        exe = ROOT / rel
        if not exe.is_file():
            continue
        sha = sha12(exe)
        if sha in have:
            continue
        built = exe.stat().st_mtime
        stamp = datetime.fromtimestamp(built)
        commit = _git("log", "-1", "--format=%h", f"--before={stamp.isoformat()}")
        e = {"time": stamp.strftime("%Y-%m-%d %H:%M:%S"), "app": app, "kind": kind,
             "commit": commit, "guessed": True, "ok": True, "output": _rel(exe.parent),
             "exe_mb": round(exe.stat().st_size / 1e6, 1), "exe_sha": sha, "backfilled": True}
        if app == "Rerun":
            e["templates"] = len(list((exe.parent / "templates").glob("*.png"))) or None
            z = sorted((ROOT / "release").glob("Rerun-*.zip")) if kind == "release" else []
            if z:
                e["zip_mb"] = round(z[-1].stat().st_size / 1e6, 1)
            if (exe.parent / "tesseract" / "tesseract.exe").is_file():
                e["ocr"] = "bundled"
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        added += 1
    render()
    return added


def main(argv: list[str]) -> int:
    if "--backfill" in argv:
        print(f"Added {backfill()} earlier build(s)")
    text = render()
    print("\n".join(text.splitlines()[:16]))
    print(f"\nFull list: {TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
