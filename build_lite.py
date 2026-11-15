"""Build RerunLite.exe - ReRun LITE (Auto Crest and Dailies only).

    py build_lite.py                 dist/RerunLite/RerunLite.exe - your own copy: your config.yaml
                                     is copied next to it
    py build_lite.py --out FOLDER    the same into FOLDER (e.g. while dist/RerunLite's copy runs)
    py build_lite.py --release       release/RerunLite/ + release/RerunLite-<version>.zip - a clean
                                     copy to give to other people

A separate build from build.py (which is not changed and still builds Rerun.exe): another exe name and
icon, started from lite_main.py, with only the template pictures LITE's scripts use and without GS
Companion. It reuses build.py's Tesseract bundling, blank config and leak check as they are.

Every build ends by running the new exe's self-test (RerunLite.exe --selftest), which builds the whole
window once, so a module missing from the exe fails the build here instead of on someone's PC.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import build as full_build  # noqa: E402 - reused: bundle_tesseract, clean_config, check_release

EXE = "RerunLite"
DIST = ROOT / "dist" / EXE
RELEASE = ROOT / "release"
SEP = full_build.SEP
INFO = full_build.INFO      # bundle_tesseract() reports into this; it is also this build's log entry
README = "RERUN_LITE.md"


def write_version_file(path: Path, version: str) -> Path:
    """Windows 'file details' for RerunLite.exe (so it is not an anonymous exe)."""
    nums = [int(x) for x in version.split(".")[:3]] + [0] * (4 - len(version.split(".")[:3]))
    t = tuple(nums[:4])
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Rerun'),
      StringStruct('FileDescription', 'ReRun LITE - Auto Crest and Dailies for Grand Summoners on BlueStacks'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'RerunLite'),
      StringStruct('OriginalFilename', 'RerunLite.exe'),
      StringStruct('ProductName', 'ReRun LITE'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('LegalCopyright', 'github.com/King-clash/ReRun-LITE')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def build_exe(dist: Path) -> bool:
    from rerun import __version__
    from rerun_lite.icon import write_lite_ico
    work = Path(tempfile.mkdtemp(prefix="rlb_"))  # short path for PyInstaller's scratch files
    icon = write_lite_ico(work / "rerunlite.ico")
    vfile = write_version_file(work / "version_info.txt", __version__)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onefile",
        "--name", EXE, "--icon", str(icon), "--version-file", str(vfile), "--noupx",
        "--distpath", str(dist), "--workpath", str(work / "build"),
        "--specpath", str(work),
        # App icon picture, loaded at run time for the window (and tray).
        "--add-data", f"{ROOT / 'rerun' / 'assets'}{SEP}rerun/assets",
        # Back ends these libraries load by name at run time.
        "--hidden-import", "pystray._win32",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--exclude-module", "matplotlib", "--exclude-module", "pytest",
        "--exclude-module", "PIL._avif",
        # Not part of LITE: GS Companion (the full app's own tab) and everything only it needs.
        "--exclude-module", "gsc_app",
        str(ROOT / "lite_main.py"),
    ]
    print(" ".join(cmd))
    code = subprocess.call(cmd, cwd=str(ROOT))
    shutil.rmtree(work, ignore_errors=True)
    if code != 0:
        print("PyInstaller failed")
    return code == 0


def copy_content(dist: Path) -> None:
    """LITE's templates, what this build shipped (so a later LITE update knows which files are untouched
    and may be replaced - rerun_lite/channel.py), and the LITE readme."""
    from rerun.updates import sha256_file
    from rerun_lite import content
    files = content.copy_to(ROOT, dist)
    baseline = {rel: sha256_file(p) for rel, p in files.items()}
    (dist / "lite_content_baseline.json").write_text(json.dumps({"files": baseline}, indent=1), encoding="utf-8")
    if (ROOT / README).exists():
        shutil.copy2(ROOT / README, dist / "README.md")
    INFO["templates"] = len(files)
    INFO["routines"] = 0


def selftest(exe: Path) -> str:
    """Run the exe's own check. Returns '' when it passed, else what went wrong."""
    out = Path(tempfile.mkdtemp(prefix="rlst_")) / "result.txt"
    try:
        r = subprocess.run([str(exe), "--selftest", str(out)], timeout=240)
        text = out.read_text(encoding="utf-8") if out.exists() else ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"the self-test did not finish: {e}"
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)
    if r.returncode != 0 or not text.startswith("ok"):
        return text or f"the self-test exited with code {r.returncode} and wrote nothing"
    INFO["selftest"] = text
    return ""


def built(dist: Path) -> bool:
    if not build_exe(dist):
        return False
    copy_content(dist)
    problem = selftest(dist / f"{EXE}.exe")
    if problem:
        INFO["error"] = "self-test failed"
        print(f"\nThe built {EXE}.exe FAILED its self-test:\n{problem}")
        return False
    print(f"Self-test passed: {INFO['selftest']}")
    return True


def release() -> int:
    """A clean ReRun LITE to give away: the exe, LITE's templates, the readme, a blank config, its own
    Tesseract - and nothing of yours. Checked (build.py's leak check, plus LITE's own folders) before it
    is zipped."""
    from rerun import __version__
    out = RELEASE / EXE
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if not built(out):
        return 1
    (out / "config.yaml").write_text(full_build.clean_config(), encoding="utf-8")
    ocr = full_build.bundle_tesseract(out)
    problems = full_build.check_release(out)
    problems += [f"{name}/ holds personal data" for name in ("accounts", "data") if (out / name).exists()]
    INFO["leak_check"] = "passed" if not problems else f"FAILED ({len(problems)})"
    if problems:
        INFO["error"] = "not safe to share: " + "; ".join(problems[:3])
        print(f"\nNOT SAFE TO SHARE - release/{EXE} has personal data:\n  " + "\n  ".join(problems))
        return 1
    zpath = RELEASE / f"{EXE}-{__version__}.zip"
    zpath.unlink(missing_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p, Path(EXE) / p.relative_to(out))
    size = zpath.stat().st_size / 1e6
    INFO["zip_mb"] = round(size, 1)
    print(f"\nRelease ready: {zpath} ({size:.0f} MB)\n  OCR: {ocr}\n  Checked: no token, no stats/History/"
          "units/crest log/key/accounts, blank config.")
    return 0


def main() -> int:
    from rerun import __version__
    INFO["version"] = __version__
    if "--release" in sys.argv:
        return release()
    dist = DIST
    if "--out" in sys.argv:
        dist = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    if not built(dist):
        return 1
    if (ROOT / "config.yaml").exists():
        shutil.copy2(ROOT / "config.yaml", dist / "config.yaml")
    print(f"\nBuilt {dist / (EXE + '.exe')}")
    return 0


if __name__ == "__main__":
    from tools.buildlog import logged
    if "--release" in sys.argv:
        _kind, _out = "release", RELEASE / EXE
    elif "--out" in sys.argv:
        _kind, _out = "build --out", Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    else:
        _kind, _out = "build", DIST
    raise SystemExit(logged("ReRun LITE", _out / f"{EXE}.exe", main, kind=_kind, info=INFO))
