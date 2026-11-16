"""Download pictures for YOUR OWN personal copy of ReRun LITE, into a folder the Artwork page can import.

    py tools/fetch_personal_art.py                      -> ~/ReRun-LITE-art-inbox
    py tools/fetch_personal_art.py --out D:\\anime-art
    py tools/fetch_personal_art.py --check              -> only show which MyAnimeList entry each anime resolves to
    py tools/fetch_personal_art.py --only jujutsu-kaisen frieren

Then in ReRun LITE: Settings > Artwork > Import a folder... and choose that folder.

What it does: for each of the 16 anime it asks the public Jikan API (api.jikan.moe, an unofficial MyAnimeList reader) for the
anime's pictures and its characters, matches the characters that Settings > Artwork lists by name, and saves their pictures
(and a few of the anime's own pictures as background and banner) as `<anime>/<character-id>.jpg`, `background*.jpg` and
`banner.jpg`. Slots that are not a single character (a crew, a group, a car) get one of the anime's pictures instead.

This is for personal use on your own PC. The pictures belong to their owners; they go to a folder outside the repository,
are never committed or bundled, and the download is rate-limited to be polite to the free API. The pictures are what
MyAnimeList hosts: character pictures are small (about 225 x 350), so they look soft when stretched. Use your own larger
pictures with `Import a folder...` where you have them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.artwork_tool import CATALOG  # noqa: E402

API = "https://api.jikan.moe/v4"
UA = "ReRun-LITE-personal-art/1.0 (personal use)"
GAP = 0.8                       # seconds between requests; Jikan allows about 3 a second and 60 a minute

# anime id -> (MyAnimeList id or None, search text used when the id is None or wrong)
SOURCES = {
    "jujutsu-kaisen": (40748, "Jujutsu Kaisen"), "solo-leveling": (52299, "Ore dake Level Up na Ken"),
    "naruto": (1735, "Naruto: Shippuuden"), "bleach": (41467, "Bleach: Sennen Kessen-hen"),
    "evangelion": (30, "Neon Genesis Evangelion"), "demon-slayer": (38000, "Kimetsu no Yaiba"),
    "one-piece": (21, "One Piece"), "attack-on-titan": (16498, "Shingeki no Kyojin"),
    "chainsaw-man": (44511, "Chainsaw Man"), "frieren": (52991, "Sousou no Frieren"),
    "cowboy-bebop": (1, "Cowboy Bebop"), "tokyo-ghoul": (22319, "Tokyo Ghoul"),
    "hunter-x-hunter": (11061, "Hunter x Hunter (2011)"), "initial-d": (None, "Initial D First Stage"),
    "dragon-ball": (813, "Dragon Ball Z"), "spy-x-family": (50265, "Spy x Family"),
}


def tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def pick_character(wanted: str, chars: list[dict]) -> dict | None:
    """The Jikan character entry for the name Settings > Artwork lists. Jikan writes "Gojo, Satoru"; the list says
    "Gojo Satoru", so compare words. First every wanted word must be in the entry; failing that the wanted name's longest
    word must be. The best-liked entry wins a tie. None when nothing fits (a group, say)."""
    want = tokens(wanted)
    if not want:
        return None
    hits = [c for c in chars if want <= tokens(c["character"]["name"])]
    if not hits:
        key = max(want, key=len)
        hits = [c for c in chars if key in tokens(c["character"]["name"])] if len(key) >= 4 else []
    return max(hits, key=lambda c: c.get("favorites") or 0) if hits else None


def character_picture(entry: dict) -> str:
    j = (entry.get("character") or {}).get("images", {}).get("jpg", {})
    url = j.get("image_url") or ""
    return "" if "questionmark" in url else url


def anime_pictures(data: list[dict]) -> list[str]:
    """Large picture addresses from /pictures, best first (they are already ordered by the site)."""
    out = []
    for d in data:
        j = d.get("jpg") or {}
        u = j.get("large_image_url") or j.get("image_url")
        if u:
            out.append(u)
    return out


def fetch_json(url: str, tries: int = 4) -> dict:
    for n in range(tries):
        time.sleep(GAP)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and n < tries - 1:
                time.sleep(2 + 3 * n)
                continue
            raise
    return {}


def download(url: str, dest: Path) -> bool:
    try:
        time.sleep(GAP / 2)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=45) as r:
            data = r.read()
        if len(data) < 500:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except (urllib.error.URLError, OSError):
        return False


def resolve(cid: str, fetch=fetch_json) -> tuple[int | None, str]:
    """(MyAnimeList id, its title) for an anime, checking the known id and falling back to a search."""
    mal, query = SOURCES[cid]
    if mal:
        try:
            d = fetch(f"{API}/anime/{mal}").get("data") or {}
            if d.get("mal_id") == mal:
                return mal, str(d.get("title") or "")
        except (urllib.error.URLError, OSError, ValueError):
            pass
    d = (fetch(f"{API}/anime?q={urllib.parse.quote(query)}&limit=1&sfw=true").get("data") or [{}])[0]
    return d.get("mal_id"), str(d.get("title") or "")


def run(out: Path, only: list[str] | None = None, check: bool = False, fetch=fetch_json, get=download, say=print) -> dict:
    """Fill `out` with one folder per anime. Returns {anime id: {"got": [...], "missing": [...]}}."""
    report: dict = {}
    for cid, name, _accent, chars in CATALOG:
        if only and cid not in only:
            continue
        mal, title = resolve(cid, fetch)
        say(f"{name}: {('MyAnimeList ' + str(mal) + ' = ' + title) if mal else 'NOT FOUND'}")
        rep = report[cid] = {"got": [], "missing": [], "mal": mal, "title": title}
        if not mal or check:
            continue
        pics = anime_pictures(fetch(f"{API}/anime/{mal}/pictures").get("data") or [])
        roster = fetch(f"{API}/anime/{mal}/characters").get("data") or []
        folder = out / cid
        spare = list(pics)                                      # pictures not yet used, for slots that are not a character
        for cn, (char_id, char_name) in enumerate(chars):
            entry = pick_character(char_name, roster)
            url = character_picture(entry) if entry else ""
            if not url and spare:
                url = spare.pop(0 if cn == 0 else -1)           # a crew, a group, a car: use one of the anime's own pictures
            if url and get(url, folder / f"{char_id}.jpg"):
                rep["got"].append(char_id)
            else:
                rep["missing"].append(char_id)
        for i, url in enumerate(pics[:3], 1):
            if get(url, folder / f"background-{i}.jpg"):
                rep["got"].append(f"background-{i}")
        if pics and get(pics[0], folder / "banner.jpg"):
            rep["got"].append("banner")
        say(f"    saved {len(rep['got'])}; no picture for: {', '.join(rep['missing']) or 'none'}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(Path.home() / "ReRun-LITE-art-inbox"))
    ap.add_argument("--only", nargs="*", help="anime ids to fetch (default: all 16)")
    ap.add_argument("--check", action="store_true", help="only show which MyAnimeList entry each anime resolves to")
    a = ap.parse_args()
    out = Path(a.out)
    try:
        run(out, a.only, a.check)
    except (urllib.error.URLError, OSError) as e:
        print(f"Could not reach the Jikan API: {e}")
        return 1
    if not a.check:
        print(f"\nDone. In ReRun LITE: Settings > Artwork > Import a folder... > {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
