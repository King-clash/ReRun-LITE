"""First-run setup check: everything Rerun needs, each with a fix.

Runs off the UI thread (ADB calls can take seconds). Each Check says what is
wrong in plain words and which fix button applies."""
from __future__ import annotations

from dataclasses import dataclass

from .adb import AdbError, discover_bluestacks_instances


@dataclass
class Check:
    title: str
    ok: bool
    detail: str
    fix: str | None = None  # detect | import | adb_help | display_help | discord_tab | None


def run_checks(m) -> list[Check]:
    out: list[Check] = []
    # 1. adb
    try:
        path = m.adb_path()
        out.append(Check("ADB found", True, path))
        adb_ok = True
    except AdbError as e:
        out.append(Check("ADB found", False, str(e), "adb_help"))
        adb_ok = False
    # 2. instances
    if not m.instances:
        found = discover_bluestacks_instances()
        out.append(Check("Instances", False,
                         f"No instances listed yet. BlueStacks has {len(found)}." if found
                         else "No instances listed and no BlueStacks instances found.",
                         "detect"))
    for name, inst in m.instances.items():
        if not adb_ok:
            break
        try:
            dev = m.device(name)
            dev.connect()
            out.append(Check(f"{name}: connected", True, inst.serial))
        except AdbError as e:
            out.append(Check(f"{name}: connected", False,
                             f"{inst.serial}: {str(e).splitlines()[0]}", "adb_help"))
            continue
        try:
            pkg = dev.resolve_package(m.config.get("game_package"))
            out.append(Check(f"{name}: Grand Summoners installed", True, pkg))
        except AdbError as e:
            out.append(Check(f"{name}: Grand Summoners installed", False, str(e)))
        try:
            img = dev.screencap()
            h, w = img.shape[:2]
            good = (w, h) == (720, 1280)
            out.append(Check(f"{name}: screen size", good,
                             f"{w}x{h}" + ("" if good else " - set BlueStacks Display to 1280x720 "
                                                           "(the game then runs at 720x1280)"),
                             None if good else "display_help"))
        except AdbError as e:
            out.append(Check(f"{name}: screen size", False, str(e)))
    # 3. templates for the tested scripts
    from .scripts import SCRIPTS
    missing = sorted({n for sid, c in SCRIPTS.items() if not c.BETA
                      for n in m.missing_templates(sid)})
    out.append(Check("Templates", not missing,
                     "All templates for Any Quest, Crest and Login & Mail are captured." if not missing
                     else f"{len(missing)} missing: {', '.join(missing[:6])}"
                          + ("..." if len(missing) > 6 else ""),
                     None if not missing else "import"))
    # 4. text reader
    from .ocr import OcrUnavailable, find_tesseract
    try:
        exe, _ = find_tesseract(m.config.get("tesseract_path"))
        out.append(Check("Text reader (OCR)", True, str(exe)))
        ocr_ok = True
    except OcrUnavailable as e:
        out.append(Check("Text reader (OCR)", False, str(e)))
        ocr_ok = False
    # 4b. Crest: can it start from the Home screen?
    from .scripts.crest import CrestScript
    for name, inst in m.instances.items():
        if inst.script != "crest":
            continue
        cfg = m.script_settings(name, "crest")
        if not cfg.get("start_home", True):
            out.append(Check(f"{name}: Crest starts from wherever the game is", True,
                             "'Always start from the Home screen' is off."))
            continue
        prefs = ";".join(str(cfg.get(k) or "") for k in ("palace_name", "palace_by_day")).strip(";")
        need = CrestScript.nav_missing(m.store.has, prefs, ocr_ok)
        out.append(Check(f"{name}: Crest can start from the Home screen", not need,
                         "Ready: it walks Home > Exploring > Crest Palace > palace > quest." if not need
                         else "Missing: " + ", ".join(need) + ". Capture it in the Templates tab, set "
                              "'Palace to farm' in the Crest settings, or turn the setting off."))
    # 5. discord (only if turned on)
    d = m.config.get("discord", {})
    if d.get("enabled"):
        ok = bool(d.get("token")) and bool(d.get("channel_id"))
        out.append(Check("Discord bot", ok, "Token and channel set." if ok
                         else "Turned on, but the token or channel ID is missing.",
                         None if ok else "discord_tab"))
    return out
