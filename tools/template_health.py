"""Check the template pictures against real screenshots, without touching the game.

It only reads files: the pictures in `templates/` (or --templates) and the screenshots you give it. Nothing is
sent to an emulator, and nothing is written to your data or to `templates/`.

Why: after a Grand Summoners update a button can move or change, and Crest then stops finding it. This shows, for
each screenshot, which pictures are found and how well, so you can see what no longer matches.

Examples:
  py tools/template_health.py                       # every screenshot in tests/fixtures
  py tools/template_health.py shot1.png shot2.png   # your own screenshots (720x1280 portrait)
  py tools/template_health.py shot.png --expect game_start_screen   # fail if that picture is not found
  py tools/template_health.py --quiet               # one line per template, best score over all screenshots

Exit code: 0 normally; 1 when an --expect picture is missing or below its threshold.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rerun.vision import MissingTemplate, TemplateStore, Vision  # noqa: E402

NEAR = 0.05  # within this of the threshold counts as "close to failing"


def load(path: Path) -> np.ndarray | None:
    try:
        return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    except OSError:  # missing or unreadable file
        return None


def live_frame() -> np.ndarray | None:
    """One screenshot of the first connected BlueStacks device. Read-only: it only asks for a screenshot."""
    import shutil
    import subprocess
    exe = shutil.which("adb")
    for cand in (r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe", r"C:\Program Files (x86)\BlueStacks_nxt\HD-Adb.exe"):
        if exe is None and Path(cand).exists():
            exe = cand
    if exe is None:
        print("live: no adb found (BlueStacks' HD-Adb.exe or adb on PATH).")
        return None
    out = subprocess.run([exe, "devices"], capture_output=True, text=True, timeout=30).stdout
    serials = [ln.split()[0] for ln in out.splitlines()[1:] if ln.strip().endswith("device")]
    if not serials:
        print("live: no device connected (is BlueStacks open with ADB on?).")
        return None
    png = subprocess.run([exe, "-s", serials[0], "exec-out", "screencap", "-p"], capture_output=True, timeout=60).stdout
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("live: the screenshot could not be read.")
    return img


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("screenshots", nargs="*", help="screenshot PNGs; default is every PNG in tests/fixtures")
    ap.add_argument("--templates", default=str(ROOT / "templates"), help="template folder")
    ap.add_argument("--expect", action="append", default=[], metavar="NAME",
                    help="a template that must be found in at least one screenshot (repeatable)")
    ap.add_argument("--quiet", action="store_true", help="only the per-template summary")
    ap.add_argument("--palaces", action="store_true",
                    help="also match each palace picture in palaces.yaml against every screenshot "
                         "(use a screenshot of the Crest Palace screen)")
    ap.add_argument("--live", action="store_true",
                    help="also take one screenshot of the BlueStacks screen as it is now (adb screencap; "
                         "nothing is tapped). Open the screen you want checked first.")
    args = ap.parse_args(argv)

    store = TemplateStore(args.templates)  # note: creates the folder if it is missing, never writes files in it
    vision = Vision(store)
    paths = [Path(p) for p in args.screenshots]
    if not paths and not args.live:  # --live on its own checks only the screen as it is now
        paths = sorted((ROOT / "tests" / "fixtures").glob("*.png"))
    frames = []
    for p in paths:
        img = load(p)
        if img is None:
            print(f"skip: cannot read {p}")
            continue
        frames.append((p.name, img))
    if args.live:
        live = live_frame()
        if live is not None:
            frames.append(("live screen", live))
    if not frames:
        print("No screenshots to check.")
        return 1

    names = store.names()
    best: dict[str, tuple[float, str]] = {}
    for fname, img in frames:
        found = []
        for name in names:
            try:
                m = vision.score(img, name)
            except MissingTemplate:
                continue
            if m is None:
                continue
            if name not in best or m.score > best[name][0]:
                best[name] = (m.score, fname)
            thr = store.threshold(name)
            if m.score >= thr:
                found.append((m.score, name, thr))
        if not args.quiet:
            h, w = img.shape[:2]
            print(f"\n{fname}  ({w}x{h})" + ("" if (w, h) == (720, 1280) else "  <- not 720x1280"))
            for score, name, thr in sorted(found, reverse=True):
                flag = "  (close to the limit)" if score - thr < NEAR else ""
                print(f"  found  {name:28s} {score:.2f}  (needs {thr:.2f}){flag}")
            if not found:
                print("  nothing from the template list is on this screen")

    print("\nBest score for each template over all screenshots:")
    never = []
    for name in names:
        score, fname = best.get(name, (0.0, "-"))
        thr = store.threshold(name)
        if score >= thr:
            status = "ok" if score - thr >= NEAR else "close"
        else:
            status = "not seen"
            never.append(name)
        print(f"  {status:9s} {name:28s} best {score:.2f} / needs {thr:.2f}  in {fname}")
    if never:
        print(f"\n{len(never)} of {len(names)} templates were not seen in these screenshots. That is normal when the "
              "screenshots do not show their screens; it only matters for the screens you meant to test.")

    if args.palaces:
        from rerun_lite import palaces
        from rerun_lite.crest import MATCH_MIN, find_tile
        print(f"\nPalace pictures (palaces.yaml) - a palace is opened only at {MATCH_MIN:.2f} or more:")
        plist = palaces.read_list(ROOT)
        if not plist:
            print("  palaces.yaml has no palaces.")
        for p in plist:
            pic = load(palaces.image_path(ROOT, p))
            if pic is None:
                print(f"  missing   {p.name:32s} picture {p.image} cannot be read")
                continue
            top = max(((*find_tile(img, pic), fname) for fname, img in frames), key=lambda r: r[0])
            state = "on screen" if top[0] >= MATCH_MIN else "not seen"
            print(f"  {state:9s} {p.name:32s} best {top[0]:.2f} at {top[3]:.2f}x in {top[4]}")
        from rerun_lite.crest import unknown_banners
        pics = [(p.name, im) for p in plist if (im := load(palaces.image_path(ROOT, p))) is not None]
        extra = [(fname, y) for fname, img in frames for y in unknown_banners(img, pics)]
        for fname, y in extra:
            print(f"  NOT IN THE LIST  a palace banner at height {y} in {fname} matches no picture: "
                  "add it to palaces.yaml with a picture")
        if not extra:
            print("  Every whole banner on these screens matches a picture in the list.")

    bad = 0
    for name in args.expect:
        if not store.has(name):
            print(f"EXPECTED but there is no template named {name!r}")
            bad = 1
            continue
        score, fname = best.get(name, (0.0, "-"))
        thr = store.threshold(name)
        if score < thr:
            print(f"EXPECTED {name}: best {score:.2f} is below {thr:.2f}")
            bad = 1
        else:
            print(f"EXPECTED {name}: found {score:.2f} in {fname}")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
