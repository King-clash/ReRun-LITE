"""Download pictures for YOUR OWN personal copy of ReRun LITE, into a folder the Artwork page can import.

    py tools/fetch_personal_art.py                      -> ~/ReRun-LITE-art-inbox
    py tools/fetch_personal_art.py --out D:\\anime-art
    py tools/fetch_personal_art.py --only jujutsu-kaisen frieren

Then in ReRun LITE: Settings > Artwork > Import a folder... and choose that folder.

What it downloads: the pictures listed in tools/personal_art_sources.json, which were picked by hand from each anime's Fandom
wiki: a full-body character render (a transparent PNG, about 1000 px tall) for most characters, a clean anime still for a few,
and for the group slots (Akatsuki, Straw Hats, the Forgers...) a group picture or emblem. Each is saved as
`<anime>/<character-id>.<ext>`, the layout the importer reads. Two pictures that show a front and a back view are cropped to
the front figure.

This is for personal use on your own PC. The pictures belong to their owners; they go to a folder outside the repository and
are never committed or bundled. Re-running skips files already downloaded.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "personal_art_sources.json"
UA = "ReRun-LITE-personal-art/2.0 (personal use)"
GAP = 0.4                       # seconds between downloads, to be polite to the wiki's image server


def load_sources(path: Path = SOURCES) -> tuple[dict, set]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["sources"], set(data.get("crop_left") or [])


def extension(url: str) -> str:
    name = url.split("/revision/")[0].rsplit(".", 1)[-1].lower()
    return {"jpeg": "jpg"}.get(name, name if name in ("png", "jpg", "webp", "gif") else "png")


def download(url: str, dest: Path) -> bool:
    try:
        time.sleep(GAP)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
            data = r.read()
        if len(data) < 2000:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except (urllib.error.URLError, OSError):
        return False


def crop_left(path: Path) -> None:
    """A picture that shows a front view and a back view side by side: keep the front (left) figure."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGBA")
        im.crop((0, 0, im.width // 2 + 6, im.height)).save(path)


def run(out: Path, only: list[str] | None = None, get=download, sources: Path = SOURCES, say=print) -> dict:
    """Fill `out` with one folder per anime. Returns {anime id: {"got": [...], "missing": [...]}}."""
    pics, crops = load_sources(sources)
    report: dict = {}
    for anime, slots in pics.items():
        if only and anime not in only:
            continue
        rep = report[anime] = {"got": [], "missing": []}
        for slot, url in slots.items():
            dest = out / anime / f"{slot}.{extension(url)}"
            if dest.exists() or get(url, dest):
                if f"{anime}/{slot}" in crops and not dest.with_suffix(dest.suffix + ".cropped").exists():
                    crop_left(dest)
                    dest.with_suffix(dest.suffix + ".cropped").write_text("", encoding="utf-8")
                rep["got"].append(slot)
            else:
                rep["missing"].append(slot)
        say(f"{anime}: {len(rep['got'])} downloaded" + (f"; failed: {', '.join(rep['missing'])}" if rep["missing"] else ""))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(Path.home() / "ReRun-LITE-art-inbox"))
    ap.add_argument("--only", nargs="*", help="anime ids to fetch (default: all 16)")
    a = ap.parse_args()
    out = Path(a.out)
    rep = run(out, a.only)
    for marker in out.rglob("*.cropped"):                       # bookkeeping files must not reach the importer
        marker.unlink(missing_ok=True)
    bad = sum(len(r["missing"]) for r in rep.values())
    print(f"\nDone{' (' + str(bad) + ' failed; run it again to retry)' if bad else ''}. "
          f"In ReRun LITE: Settings > Artwork > Import a folder... > {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
