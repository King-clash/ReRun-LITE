"""Build Rerun.exe.

    python build.py                 dist/Rerun/Rerun.exe - your own copy: your config.yaml and
                                    GS Companion data are copied next to it
    python build.py --out FOLDER    the same into FOLDER (e.g. while dist/Rerun's copy runs)
    python build.py --release       release/Rerun/ + release/Rerun-<version>.zip - a clean copy
                                    to give to other people (see release() below)

Rerun.exe is one self-contained file (a one-file build has no deep internal folders, so it
also builds inside long paths that Windows' 260-character limit would otherwise break).
Templates, routines and README are copied next to it, so the .exe works exactly like
`python main.py`."""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist" / "Rerun"
RELEASE = ROOT / "release"
SEP = ";" if sys.platform == "win32" else ":"
INFO: dict = {}   # facts about this build for the build log (tools/buildlog.py, BUILDS.md)


def write_version_file(path: Path, version: str) -> Path:
    """Windows 'file details' (Properties > Details) for Rerun.exe. An exe with no company, product
    or description looks anonymous to Defender and SmartScreen; this labels it honestly."""
    nums = [int(x) for x in version.split(".")[:3]] + [0] * (4 - len(version.split(".")[:3]))
    t = tuple(nums[:4])
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Rerun'),
      StringStruct('FileDescription', 'Rerun - Grand Summoners automation helper for BlueStacks'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'Rerun'),
      StringStruct('OriginalFilename', 'Rerun.exe'),
      StringStruct('ProductName', 'Rerun'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('LegalCopyright', 'github.com/King-clash/ReRun-LITE')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def build_exe(dist: Path) -> bool:
    sys.path.insert(0, str(ROOT))
    from rerun.appicon import write_ico
    work = Path(tempfile.mkdtemp(prefix="rrb_"))  # short path for PyInstaller's scratch files
    icon = write_ico(work / "rerun.ico")
    from rerun import __version__
    vfile = write_version_file(work / "version_info.txt", __version__)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onefile",
        "--name", "Rerun", "--icon", str(icon), "--version-file", str(vfile), "--noupx",
        "--distpath", str(dist), "--workpath", str(work / "build"),
        "--specpath", str(work),
        # App icon picture, loaded at run time for the window (and tray).
        "--add-data", f"{ROOT / 'rerun' / 'assets'}{SEP}rerun/assets",
        # Back ends these libraries load by name at run time.
        "--hidden-import", "pystray._win32",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        # GS Companion tab (imported inside a try block in rerun/gui.py), and the Giant Boss /
        # Story / Event stage list it reads next to gsc_app/page.py
        "--add-data", f"{ROOT / 'gsc_app' / 'stage_catalog.json'}{SEP}gsc_app",
        "--hidden-import", "gsc_app.page", "--hidden-import", "gsc_app.update_data",
        "--hidden-import", "gsc_app.scrape",
        "--exclude-module", "matplotlib", "--exclude-module", "pytest",
        # Pillow's AVIF plugin (4 MB) - Rerun only reads and writes PNG/JPEG; Pillow skips it when absent.
        "--exclude-module", "PIL._avif",
        str(ROOT / "main.py"),
    ]
    print(" ".join(cmd))
    code = subprocess.call(cmd)
    shutil.rmtree(work, ignore_errors=True)
    if code != 0:
        print("PyInstaller failed")
    return code == 0


def copy_content(dist: Path) -> None:
    """Templates and routines, plus what this build shipped, so a later template update
    (rerun/updates.py) knows which files are untouched and may be replaced."""
    for folder in ("templates", "routines"):
        src = ROOT / folder
        if src.is_dir():
            shutil.copytree(src, dist / folder, dirs_exist_ok=True)
    from tools.publish_update import content_files
    from rerun.updates import BASELINE_FILE, sha256_file
    baseline = {rel: sha256_file(p) for rel, p in content_files(ROOT).items()}
    (dist / BASELINE_FILE).write_text(json.dumps({"files": baseline}, indent=1), encoding="utf-8")
    shutil.copy2(ROOT / "README.md", dist / "README.md")
    INFO["templates"] = sum(r.startswith("templates/") for r in baseline)
    INFO["routines"] = sum(r.startswith("routines/") and not r.endswith(".md") for r in baseline)


# ------------------------------------------------------------------ Tesseract bundle
def pe_imports(path: Path) -> list[str]:
    """DLL names a Windows .exe/.dll imports (normal and delay-load), read from its PE header."""
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return []
    n_sections, opt_size = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    dirs = opt + (112 if struct.unpack_from("<H", data, opt)[0] == 0x20B else 96)
    sections = [struct.unpack_from("<IIII", data, pe + 24 + opt_size + i * 40 + 8)
                for i in range(n_sections)]   # virtual size, address, raw size, raw pointer

    def off(rva: int) -> int | None:
        for vsize, vaddr, rsize, rptr in sections:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return rva - vaddr + rptr
        return None

    def cstr(rva: int) -> str:
        o = off(rva)
        return data[o:data.index(b"\0", o)].decode("ascii", "replace") if o is not None else ""

    names = []
    for index, size, name_at in ((1, 20, 12), (13, 32, 4)):   # imports, delay imports
        rva = struct.unpack_from("<I", data, dirs + index * 8)[0]
        o = off(rva) if rva else None
        while o is not None and data[o:o + size] != b"\0" * size:
            name_rva = struct.unpack_from("<I", data, o + name_at)[0]
            if name_rva:
                names.append(cstr(name_rva))
            o += size
    return names


def tesseract_files(exe: Path) -> list[Path]:
    """tesseract.exe plus every DLL it needs from its own folder (Windows' own are left out)."""
    folder, todo, found = exe.parent, [exe], {}
    while todo:
        f = todo.pop()
        for dll in pe_imports(f):
            local = folder / dll
            if dll.lower() not in found and local.is_file():
                found[dll.lower()] = local
                todo.append(local)
    return [exe, *sorted(found.values())]


NOTICE = """Text reading (OCR) in Rerun uses Tesseract {version}
  Tesseract OCR - Apache License 2.0 - https://github.com/tesseract-ocr/tesseract
  Windows build: UB Mannheim - https://github.com/UB-Mannheim/tesseract/wiki
  eng.traineddata - Apache License 2.0 - https://github.com/tesseract-ocr/tessdata

The DLLs in this folder are unmodified open-source libraries from that build (MSYS2/MinGW
packages: Leptonica, libpng, libjpeg-turbo, libtiff, libwebp, OpenJPEG, giflib, zlib, zstd,
xz, lz4, bzip2, brotli, libdeflate, Lerc, libarchive, curl, libssh2, OpenSSL, libpsl,
libidn2, libunistring, libiconv, gettext, expat, libb2, jbigkit, GCC runtime, winpthreads).
Each is under its own licence (BSD/MIT/zlib-style, Apache 2.0, LGPL, or the GCC Runtime
Library Exception); sources: https://packages.msys2.org. They are separate files you can
replace with your own builds.

Files: {files}
"""


def bundle_tesseract(out: Path) -> str:
    from rerun.ocr import OcrUnavailable, find_tesseract
    try:
        exe, data = find_tesseract(os.environ.get("RERUN_TESSERACT"))
    except OcrUnavailable:
        INFO["ocr"] = "not bundled"
        return "no Tesseract on this PC to bundle (text reading will need its own install)"
    if exe.parent.resolve() == (out / "tesseract").resolve():
        raise SystemExit("Refusing to bundle Tesseract from the release folder itself")
    dest = out / "tesseract"
    (dest / "tessdata").mkdir(parents=True, exist_ok=True)
    files = tesseract_files(exe)
    for f in files:
        shutil.copy2(f, dest / f.name)
    shutil.copy2(data / "eng.traineddata", dest / "tessdata" / "eng.traineddata")
    ver = subprocess.run([str(dest / "tesseract.exe"), "--version"], capture_output=True,
                         text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    first = (ver.stdout or ver.stderr).splitlines()[0] if (ver.stdout or ver.stderr) else "?"
    if ver.returncode != 0:
        raise SystemExit(f"The bundled Tesseract does not start: {first}")
    (dest / "THIRD_PARTY_NOTICES.txt").write_text(
        NOTICE.format(version=first.replace("tesseract ", ""),
                      files=", ".join(f.name for f in files) + ", tessdata/eng.traineddata"),
        encoding="utf-8")
    m = re.search(r"(\d+\.\d+\.\d+)", first)
    INFO["ocr"] = f"Tesseract {m.group(1)}" if m else "bundled"
    return f"{first} from {exe.parent} ({len(files)} files)"


# ------------------------------------------------------------------ release
# Never in a release: your settings, data and key (rerun/migrate.py lists what is yours).
FORBIDDEN_DIRS = {"history", "units", "crest_shots", "data", "debug", "debug_crest", "backups",
                  "screenshots"}
FORBIDDEN_FILES = {"stats.json", "crest_log.jsonl", "license.json", "summary_state.json",
                   "compendium_report.csv", "discord_board.json", "installs.json",
                   "content_state.json", "migrated_from.json", "crash.log", "issued_keys.csv"}


def clean_config() -> str:
    """config.example.yaml with every personal field blanked, whatever it holds."""
    import yaml
    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8")) or {}
    d = cfg.setdefault("discord", {})
    d.update({"enabled": False, "token": "", "channel_id": 0, "ping_user_id": 0,
              "allowed_user_ids": []})
    cfg["schedules"] = {}
    cfg.pop("setup_seen", None)
    return yaml.safe_dump(cfg, sort_keys=False)


def _secrets() -> list[str]:
    """Discord tokens in your own configs, to be sure none ends up in the release."""
    import yaml
    found = set()
    for p in [ROOT / "config.yaml", *ROOT.glob("dist/*/config.yaml*"), *ROOT.glob("config.yaml*")]:
        try:
            tok = ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("discord") or {}).get("token")
        except Exception:  # noqa: BLE001 - a broken backup file is not a reason to stop
            continue
        if tok and len(str(tok)) > 20:
            found.add(str(tok))
    return sorted(found)


def check_release(out: Path) -> list[str]:
    """Problems that would leak your data; empty = safe to share."""
    problems, secrets = [], [s.encode() for s in _secrets()]
    for p in out.rglob("*"):
        rel = p.relative_to(out).as_posix()
        if p.is_dir():
            if p.name in FORBIDDEN_DIRS and p.parent == out:
                problems.append(f"{rel}/ holds personal data")
            continue
        if p.name in FORBIDDEN_FILES or p.suffix.lower() in (".bak", ".log") \
                or "signing_key" in p.name:
            problems.append(f"{rel} is personal")
        if p.suffix.lower() in (".yaml", ".yml", ".json", ".txt", ".md", ".csv", ".jsonl"):
            blob = p.read_bytes()
            if any(s in blob for s in secrets):
                problems.append(f"{rel} contains your Discord token")
    import yaml
    d = (yaml.safe_load((out / "config.yaml").read_text(encoding="utf-8")) or {}).get("discord", {})
    if d.get("token") or d.get("channel_id") or d.get("ping_user_id") or d.get("allowed_user_ids"):
        problems.append("config.yaml has Discord details filled in")
    return problems


def release() -> int:
    """A clean Rerun to give away: the exe, templates, routines, README, a blank config, its
    own Tesseract - and nothing of yours (no Discord token, stats, History, units, crest
    log, key or GS Companion data). Checked before it is zipped."""
    from rerun import __version__
    out = RELEASE / "Rerun"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if not build_exe(out):
        return 1
    copy_content(out)
    (out / "config.yaml").write_text(clean_config(), encoding="utf-8")
    ocr = bundle_tesseract(out)
    problems = check_release(out)
    INFO["leak_check"] = "passed" if not problems else f"FAILED ({len(problems)})"
    if problems:
        INFO["error"] = "not safe to share: " + "; ".join(problems[:3])
        print("\nNOT SAFE TO SHARE - release/Rerun has personal data:\n  " + "\n  ".join(problems))
        return 1
    zpath = RELEASE / f"Rerun-{__version__}.zip"
    zpath.unlink(missing_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p, Path("Rerun") / p.relative_to(out))
    size = zpath.stat().st_size / 1e6
    INFO["zip_mb"] = round(size, 1)
    print(f"\nRelease ready: {zpath} ({size:.0f} MB)\n  OCR: {ocr}\n  Checked: no token, "
          "no stats/History/units/crest log/key, blank config. GS Companion data left out.")
    return 0


def main() -> int:
    if "--release" in sys.argv:
        return release()
    dist = DIST
    if "--out" in sys.argv:
        dist = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    if not build_exe(dist):
        return 1
    copy_content(dist)
    # GS Companion's data is local only (git-ignored, never inside the exe): when you have
    # it, it is copied next to the exe for the Companion tab and unit names.
    gsc = ROOT / "data" / "gscompanion"
    INFO["gsc_data"] = (gsc / "units.json").exists()
    if (gsc / "units.json").exists():
        shutil.copytree(gsc, dist / "data" / "gscompanion", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("raw", "companion_settings.json"))
    if (ROOT / "config.yaml").exists():
        shutil.copy2(ROOT / "config.yaml", dist / "config.yaml")
    print(f"\nBuilt {dist / 'Rerun.exe'}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from tools.buildlog import logged
    if "--release" in sys.argv:
        _kind, _out = "release", RELEASE / "Rerun"
    elif "--out" in sys.argv:
        _kind, _out = "build --out", Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    else:
        _kind, _out = "build", DIST
    raise SystemExit(logged("Rerun", _out / "Rerun.exe", main, kind=_kind, info=INFO))
