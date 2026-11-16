"""Manage the bundled anime artwork: the folder tree, each anime's config, and the manifest that records where every
picture came from.   Run:  py tools/artwork_tool.py init | check | add ...

  init    Create assets/anime/<anime>/{backgrounds,characters,banners,previews} and each anime's collection.json for the
          16 anime, and an empty manifest.json. It only creates what is missing; it never overwrites a file.
  check   Read the manifest and every picture and report anything that would stop a picture being shown: a file with no
          entry, an entry with no source address / licence / permitted use, a missing file, wrong size. Exit code 1 on
          a problem, so it can run before a release.
  add     Record one picture you have the right to bundle:
            py tools/artwork_tool.py add jujutsu-kaisen/characters/gojo.webp --character gojo \
               --source-url https://... --licence "..." --permitted "..." --attribution "..."
          It reads the picture's size, writes the entry and marks it approved. Do not use it for a picture whose licence
          does not allow redistribution; users can add such pictures themselves in Settings > Artwork.

No picture is ever downloaded by this tool, and none is bundled until an entry like the one above exists.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun_lite import artwork  # noqa: E402

ANIME_DIR = ROOT / "assets" / "anime"

# id, name, accent colour (a hint for borders and captions only), characters (id, name)
CATALOG = [
    ("jujutsu-kaisen", "Jujutsu Kaisen", "#5B6CFF",
     [("gojo", "Gojo Satoru"), ("sukuna", "Ryomen Sukuna"), ("yuji", "Yuji Itadori"), ("megumi", "Megumi Fushiguro")]),
    ("solo-leveling", "Solo Leveling", "#7B4DFF",
     [("jinwoo", "Sung Jinwoo"), ("shadows", "Shadow Army"), ("hunters", "Hunters")]),
    ("naruto", "Naruto Akatsuki", "#D6322E",
     [("itachi", "Itachi Uchiha"), ("pain", "Pain"), ("obito", "Obito Uchiha"), ("akatsuki", "Akatsuki")]),
    ("bleach", "Bleach: Thousand-Year Blood War", "#E8E8F0",
     [("ichigo", "Ichigo Kurosaki"), ("aizen", "Sosuke Aizen"), ("rukia", "Rukia Kuchiki")]),
    ("evangelion", "Neon Genesis Evangelion", "#8E44D6",
     [("unit-01", "Evangelion Unit-01"), ("rei", "Rei Ayanami"), ("asuka", "Asuka Langley Soryu"), ("nerv", "NERV")]),
    ("demon-slayer", "Demon Slayer", "#1FA37A",
     [("tanjiro", "Tanjiro Kamado"), ("nezuko", "Nezuko Kamado"), ("rengoku", "Kyojuro Rengoku")]),
    ("one-piece", "One Piece", "#E5B422",
     [("luffy", "Monkey D. Luffy"), ("zoro", "Roronoa Zoro"), ("sanji", "Sanji"), ("straw-hats", "Straw Hat Pirates")]),
    ("attack-on-titan", "Attack on Titan", "#8A7A52",
     [("eren", "Eren Yeager"), ("levi", "Levi Ackerman"), ("mikasa", "Mikasa Ackerman"), ("survey-corps", "Survey Corps")]),
    ("chainsaw-man", "Chainsaw Man", "#E8553A",
     [("denji", "Denji"), ("power", "Power"), ("makima", "Makima")]),
    ("frieren", "Frieren: Beyond Journey's End", "#7FB8D6",
     [("frieren", "Frieren"), ("fern", "Fern"), ("stark", "Stark")]),
    ("cowboy-bebop", "Cowboy Bebop", "#D9A441",
     [("spike", "Spike Spiegel"), ("faye", "Faye Valentine"), ("jet", "Jet Black")]),
    ("tokyo-ghoul", "Tokyo Ghoul", "#C2263B",
     [("kaneki", "Ken Kaneki"), ("touka", "Touka Kirishima")]),
    ("hunter-x-hunter", "Hunter x Hunter", "#3FAE5A",
     [("gon", "Gon Freecss"), ("killua", "Killua Zoldyck"), ("kurapika", "Kurapika"), ("hisoka", "Hisoka Morow")]),
    ("initial-d", "Initial D", "#E04A3C",
     [("takumi", "Takumi Fujiwara"), ("ae86", "Toyota AE86")]),
    ("dragon-ball", "Dragon Ball", "#F28C1E",
     [("goku", "Son Goku"), ("vegeta", "Vegeta"), ("gohan", "Son Gohan")]),
    ("spy-x-family", "Spy x Family", "#E8678F",
     [("loid", "Loid Forger"), ("yor", "Yor Forger"), ("anya", "Anya Forger"), ("forgers", "The Forger family")]),
]


def collection_config(order: int, cid: str, name: str, accent: str, chars) -> dict:
    """The same structure for every anime. Picture fields stay "" until a picture with a recorded right to be shown is
    added (paths are relative to the anime's own folder)."""
    return {
        "id": cid, "name": name, "order": order, "accent": accent,
        "artwork": {"defaultBackground": "", "header": "", "preview": "",
                    "characters": [{"id": c, "name": n, "image": ""} for c, n in chars]},
        "appearance": dict(artwork.DEFAULT_APPEARANCE),
    }


def init() -> int:
    made = 0
    ANIME_DIR.mkdir(parents=True, exist_ok=True)
    manifest = ANIME_DIR / "manifest.json"
    if not manifest.exists():
        manifest.write_text(json.dumps({
            "schema": artwork.SCHEMA,
            "note": "A picture in this folder is shown only when it is listed here with a source_url, a licence, "
                    "permitted_use and \"approved\": true. Use tools/artwork_tool.py add. Fields: file (relative to "
                    "assets/anime), collection, kind, character, label, width, height, source_url, licence, "
                    "permitted_use, attribution, approved.",
            "assets": []}, indent=1), encoding="utf-8")
        made += 1
    for order, (cid, name, accent, chars) in enumerate(CATALOG, 1):
        for kind in artwork.KINDS:
            keep = ANIME_DIR / cid / kind / ".gitkeep"
            if not keep.exists():
                keep.parent.mkdir(parents=True, exist_ok=True)
                keep.write_text("", encoding="utf-8")
                made += 1
        cfg = ANIME_DIR / cid / "collection.json"
        if not cfg.exists():
            cfg.write_text(json.dumps(collection_config(order, cid, name, accent, chars), indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            made += 1
    print(f"{made} file(s) created under {ANIME_DIR.relative_to(ROOT)}")
    return 0


def check() -> int:
    problems: list[str] = []
    data = json.loads((ANIME_DIR / "manifest.json").read_text(encoding="utf-8")) if (ANIME_DIR / "manifest.json").exists() else {}
    entries = {e.get("file"): e for e in data.get("assets") or [] if isinstance(e, dict)}
    cols = artwork.load_collections(ROOT)
    for cid, *_ in CATALOG:
        if cid not in cols:
            problems.append(f"{cid}: collection.json is missing or unreadable")
    for rel, e in entries.items():
        for why in artwork.manifest_problems(e):
            problems.append(f"{rel}: {why}")
        path = ANIME_DIR / str(rel)
        if not path.is_file():
            problems.append(f"{rel}: listed in the manifest but the file is missing")
            continue
        try:
            from PIL import Image
            with Image.open(path) as im:
                if (im.width, im.height) != (e.get("width"), e.get("height")):
                    problems.append(f"{rel}: size is {im.width}x{im.height}, the manifest says {e.get('width')}x{e.get('height')}")
        except Exception as ex:  # noqa: BLE001
            problems.append(f"{rel}: cannot be opened ({ex})")
    for cid in cols:
        for kind in artwork.KINDS:
            for p in (ANIME_DIR / cid / kind).glob("*"):
                if p.suffix.lower() in artwork.IMAGE_TYPES and f"{cid}/{kind}/{p.name}" not in entries:
                    problems.append(f"{cid}/{kind}/{p.name}: no manifest entry, so it will not be shown (or bundled)")
    for col in cols.values():
        for rel in (col.background, col.header, col.preview, *[c.image for c in col.characters]):
            if rel and f"{col.id}/{rel}" not in entries:
                problems.append(f"{col.id}: collection.json names {rel}, which has no manifest entry")
    print("\n".join(problems) if problems else f"OK: {len(cols)} collections, {len(entries)} listed picture(s)")
    return 1 if problems else 0


def add(args) -> int:
    path = ANIME_DIR / args.file
    if not path.is_file():
        print(f"No such file: {path}")
        return 1
    rel = Path(args.file).as_posix()
    parts = rel.split("/")
    if len(parts) != 3 or parts[1] not in artwork.KINDS:
        print("The path must look like <anime>/<backgrounds|characters|banners|previews>/<file>.webp")
        return 1
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
    entry = {"file": rel, "collection": parts[0], "kind": parts[1], "character": args.character or "", "label": args.label or "",
             "width": w, "height": h, "source_url": args.source_url, "licence": args.licence, "permitted_use": args.permitted,
             "attribution": args.attribution or "", "approved": True}
    bad = artwork.manifest_problems(entry)
    if bad:
        print("Not added: " + ", ".join(bad))
        return 1
    mf = ANIME_DIR / "manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    data["assets"] = [e for e in data.get("assets", []) if e.get("file") != rel] + [entry]
    mf.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Recorded {rel} ({w}x{h}). Remember to add it to CREDITS.md.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("check")
    a = sub.add_parser("add")
    a.add_argument("file", help="path under assets/anime, e.g. jujutsu-kaisen/characters/gojo.webp")
    a.add_argument("--character", default="")
    a.add_argument("--label", default="")
    a.add_argument("--source-url", required=True)
    a.add_argument("--licence", required=True)
    a.add_argument("--permitted", required=True, help="what the licence lets this app do with the picture")
    a.add_argument("--attribution", default="")
    args = ap.parse_args()
    return {"init": lambda: init(), "check": lambda: check(), "add": lambda: add(args)}[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
