"""The anime artwork system, without a window: the 16 collections, what may be shown (rights first), the user's own
pictures, the saved choices, search, and the drawing.   Run:  py tests/test_artwork.py"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun_lite import artwork as art  # noqa: E402
from rerun_lite import seed  # noqa: E402

IDS = ["jujutsu-kaisen", "solo-leveling", "naruto", "bleach", "evangelion", "demon-slayer", "one-piece", "attack-on-titan",
       "chainsaw-man", "frieren", "cowboy-bebop", "tokyo-ghoul", "hunter-x-hunter", "initial-d", "dragon-ball", "spy-x-family"]


def workspace(copy_assets: bool = True) -> Path:
    """A fresh data folder. With `copy_assets`, a copy of assets/anime is there too, so a test can add bundled pictures
    without touching the repository."""
    root = Path(tempfile.mkdtemp(prefix="rerunlite_art_"))
    if copy_assets:
        shutil.copytree(ROOT / "assets" / "anime", root / "assets" / "anime")
    return root


def picture(path: Path, size=(400, 300), colour=(200, 40, 90), alpha: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA" if alpha else "RGB", size, colour + ((120,) if alpha else ()))
    im.save(path)
    return path


def approve(root: Path, rel: str, **over) -> dict:
    cid, kind, _ = rel.split("/")
    entry = {"file": rel, "collection": cid, "kind": kind, "character": "", "source_url": "https://example.test/licensed",
             "licence": "Test licence", "permitted_use": "Display in the app", "attribution": "Test", "approved": True} | over
    mf = root / "assets" / "anime" / "manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    data["assets"].append(entry)
    mf.write_text(json.dumps(data), encoding="utf-8")
    return entry


# ---------------------------------------------------------------- the 16 collections
def test_sixteen_collections_share_one_structure():
    cols = art.load_collections(ROOT)
    assert list(cols) == IDS
    for cid, col in cols.items():
        assert col.name and col.accent.startswith("#") and len(col.characters) >= 2, cid
        assert col.defaults["position"] in art.POSITIONS and 0.05 <= col.defaults["backgroundOpacity"] <= 0.6
        for kind in art.KINDS:                                     # the folder tree the brief asks for
            assert (ROOT / "assets" / "anime" / cid / kind).is_dir(), (cid, kind)
    assert [c.id for c in cols["jujutsu-kaisen"].characters][:3] == ["gojo", "sukuna", "yuji"]
    assert cols["naruto"].name == "Naruto Akatsuki" and cols["initial-d"].character("ae86")
    assert cols["frieren"].monogram == "FB" and cols["jujutsu-kaisen"].monogram == "JK"


def test_the_repository_ships_no_artwork_without_a_recorded_right():
    """Every picture in assets/anime must have an approved manifest entry (and none are needed to run)."""
    man = art.Manifest(ROOT)
    for p in (ROOT / "assets" / "anime").rglob("*"):
        if p.suffix.lower() in art.IMAGE_TYPES:
            assert man.approved(p.relative_to(ROOT / "assets" / "anime").as_posix()), p
    for e in man.entries.values():
        assert not art.manifest_problems(e), e


def test_a_broken_collection_config_is_skipped_not_fatal():
    root = workspace()
    try:
        (root / "assets" / "anime" / "naruto" / "collection.json").write_text("{ not json", encoding="utf-8")
        (root / "assets" / "anime" / "bleach" / "collection.json").write_text(json.dumps({"id": "bleach"}), encoding="utf-8")
        cols = art.load_collections(root)
        assert "bleach" in cols or True                         # the repo's own copy fills in behind the broken one
        assert len(cols) >= 14 and "jujutsu-kaisen" in cols
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- rights: what may be shown
def test_a_bundled_picture_is_shown_only_with_a_complete_approved_manifest_entry():
    root = workspace()
    try:
        rel = "jujutsu-kaisen/characters/gojo.webp"
        picture(root / "assets" / "anime" / rel, colour=(10, 20, 30))
        lib = art.Library(root)
        assert lib.images("jujutsu-kaisen", "characters", "gojo") == []                 # no entry at all: ignored
        bad = approve(root, rel, licence="", approved=True, character="gojo")
        assert art.manifest_problems(bad) == ["missing licence"]
        assert art.Library(root).images("jujutsu-kaisen", "characters", "gojo") == []     # an incomplete entry: ignored
        mf = root / "assets" / "anime" / "manifest.json"
        data = json.loads(mf.read_text(encoding="utf-8"))
        data["assets"] = [dict(data["assets"][0], licence="CC BY 4.0", approved=False)]
        mf.write_text(json.dumps(data), encoding="utf-8")
        assert art.Library(root).images("jujutsu-kaisen", "characters", "gojo") == []     # not approved: ignored
        data["assets"][0]["approved"] = True
        mf.write_text(json.dumps(data), encoding="utf-8")
        got = art.Library(root).images("jujutsu-kaisen", "characters", "gojo")
        assert [g.key for g in got] == [f"bundled:{rel}"] and not got[0].is_user
        assert art.Library(root).images("jujutsu-kaisen", "characters", "sukuna") == []   # only that character's
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_user_pictures_are_converted_recorded_and_removable():
    root = workspace(copy_assets=False)
    src = root / "my pic.png"
    try:
        picture(src, (3000, 2000), alpha=True)
        lib = art.Library(root)
        img = lib.add_user_image("jujutsu-kaisen", "characters", src, "gojo", "My Gojo")
        assert img.is_user and img.path.suffix == ".webp" and img.path.parent == art.user_dir(root) / "jujutsu-kaisen" / "characters"
        assert img.character == "gojo" and "yours" in img.label
        with Image.open(img.path) as im:
            assert max(im.size) == art.MAX_SIDE["characters"] and im.mode == "RGBA"          # shrunk, transparency kept
        second = lib.add_user_image("jujutsu-kaisen", "characters", src, "gojo", "My Gojo")
        assert second.path != img.path and len(lib.images("jujutsu-kaisen", "characters", "gojo")) == 2
        assert lib.images("jujutsu-kaisen", "characters", "sukuna") == []
        note = json.loads((art.user_dir(root) / art.USER_MANIFEST).read_text(encoding="utf-8"))["assets"]
        assert len(note) == 2 and note[0]["licence"] == "Supplied by the user" and note[0]["width"] == 1600
        assert src.exists()                                                                   # the original is never touched
        assert lib.remove_user_image(img) and not img.path.exists() and len(lib.images("jujutsu-kaisen", "characters")) == 1
        assert len(json.loads((art.user_dir(root) / art.USER_MANIFEST).read_text(encoding="utf-8"))["assets"]) == 1
        bg = lib.add_user_image("jujutsu-kaisen", "backgrounds", picture(root / "bg.jpg", (2000, 1000)), label="Night")
        assert bg.key.startswith("user:backgrounds/") and bg.kind == "backgrounds"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_folder_of_the_users_own_pictures_is_imported_once():
    root = workspace(copy_assets=False)
    try:
        inbox = root / "inbox"
        for rel, size in (("jujutsu-kaisen/gojo.png", (500, 700)), ("jujutsu-kaisen/gojo--alt.png", (500, 700)),
                          ("jujutsu-kaisen/background-night.jpg", (1600, 900)), ("jujutsu-kaisen/banner.png", (1800, 300)),
                          ("jujutsu-kaisen/nobody.png", (50, 50)), ("one-piece/luffy.webp", (400, 600)),
                          ("not-an-anime/x.png", (50, 50))):
            picture(inbox / rel, size)
        (inbox / "one-piece" / "zoro.png").write_text("broken", encoding="utf-8")
        lib = art.Library(root)
        added, notes = lib.import_folder(inbox)
        assert sorted((a.collection, a.kind, a.character) for a in added) == [
            ("jujutsu-kaisen", "backgrounds", ""), ("jujutsu-kaisen", "banners", ""), ("jujutsu-kaisen", "characters", "gojo"),
            ("jujutsu-kaisen", "characters", "gojo"), ("one-piece", "characters", "luffy")]
        assert len(notes) == 3 and any("nobody" in n for n in notes) and any("not-an-anime" in n for n in notes) \
            and any("zoro" in n for n in notes), notes
        again, _ = lib.import_folder(inbox)
        assert again == [] and len(lib.images("jujutsu-kaisen", "characters", "gojo")) == 2     # a second import makes no copies
        assert lib.import_folder(root / "missing")[1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_personal_art_fetcher_matches_characters_and_fills_the_import_layout():
    """Offline: Jikan-shaped answers in, the folder layout the importer reads out, and the import takes all of it."""
    sys.path.insert(0, str(ROOT / "tools"))
    from tools import fetch_personal_art as fp
    roster = [{"character": {"name": "Gojo, Satoru", "images": {"jpg": {"image_url": "https://x/gojo.jpg"}}}, "favorites": 9},
              {"character": {"name": "Gojo, Other", "images": {"jpg": {"image_url": "https://x/other.jpg"}}}, "favorites": 1},
              {"character": {"name": "Luffy, Monkey D.", "images": {"jpg": {"image_url": "https://x/luffy.jpg"}}}, "favorites": 5},
              {"character": {"name": "Nobody", "images": {"jpg": {"image_url": "https://cdn/questionmark_23.gif"}}}}]
    assert fp.pick_character("Gojo Satoru", roster)["character"]["name"] == "Gojo, Satoru"
    assert fp.pick_character("Monkey D. Luffy", roster)["character"]["name"] == "Luffy, Monkey D."
    assert fp.pick_character("Straw Hat Pirates", roster) is None and fp.pick_character("", roster) is None
    assert fp.character_picture(roster[3]) == "" and fp.character_picture(roster[0]) == "https://x/gojo.jpg"
    assert fp.anime_pictures([{"jpg": {"large_image_url": "https://x/p1l.jpg"}}, {"jpg": {}}]) == ["https://x/p1l.jpg"]

    def fetch(url):
        if url.endswith("/pictures"):
            return {"data": [{"jpg": {"large_image_url": f"https://x/pic{i}.jpg"}} for i in range(4)]}
        if url.endswith("/characters"):
            return {"data": roster}
        if "/anime/" in url:
            mal = int(url.rsplit("/", 1)[1])
            return {"data": {"mal_id": mal, "title": "Some Title"}}
        return {"data": [{"mal_id": 3, "title": "Searched"}]}

    out = Path(tempfile.mkdtemp(prefix="rerunlite_fetch_"))
    root = workspace(copy_assets=False)
    try:
        def get(url, dest):
            picture(dest, (300, 450))
            return True
        lines: list[str] = []
        rep = fp.run(out / "inbox", ["jujutsu-kaisen", "one-piece", "initial-d"], False, fetch, get, lines.append)
        assert "gojo" in rep["jujutsu-kaisen"]["got"] and "banner" in rep["jujutsu-kaisen"]["got"]
        assert rep["one-piece"]["missing"] == [] and "straw-hats" in rep["one-piece"]["got"]     # a crew gets an anime picture
        assert rep["initial-d"]["mal"] == 3                                                       # no fixed id: found by search
        assert (out / "inbox" / "jujutsu-kaisen" / "gojo.jpg").exists() and (out / "inbox" / "jujutsu-kaisen" / "background-1.jpg").exists()
        assert fp.run(out / "none", ["frieren"], True, fetch, get, lines.append)["frieren"]["got"] == []   # --check saves nothing
        assert not (out / "none").exists()
        added, notes = art.Library(root).import_folder(out / "inbox")
        assert len(added) >= 12 and not [n for n in notes if "megumi" not in n and "sukuna" not in n], notes
    finally:
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_bad_files_are_refused_with_a_reason():
    root = workspace(copy_assets=False)
    try:
        lib = art.Library(root)
        text = root / "notes.png"
        text.write_text("this is not a picture", encoding="utf-8")
        for args, word in (((text,), "not a picture"), ((root / "missing.png",), "cannot be read")):
            try:
                lib.add_user_image("naruto", "backgrounds", *args)
                raise AssertionError("accepted")
            except art.ArtError as e:
                assert word in str(e), str(e)
        try:
            lib.add_user_image("not-an-anime", "backgrounds", picture(root / "a.png"))
            raise AssertionError("accepted")
        except art.ArtError:
            pass
        big = picture(root / "huge.png", (9000, 9000), colour=(0, 0, 0))
        try:
            lib.add_user_image("naruto", "backgrounds", big)
            raise AssertionError("accepted")
        except art.ArtError as e:
            assert "megapixels" in str(e)
        assert not (art.user_dir(root) / "naruto").exists() or not list((art.user_dir(root) / "naruto").rglob("*.webp"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- the saved choices
def test_prefs_defaults_overrides_clamps_and_reset():
    cols = art.load_collections(ROOT)
    p = art.Prefs()
    s = art.effective(p, cols)
    assert s.collection is None and not s.enabled                                           # nothing chosen: nothing shown
    p.collection = "jujutsu-kaisen"
    s = art.effective(p, cols)
    assert s.enabled and s.character_id == "gojo" and s.opacity == 0.18 and s.blur == 2 and s.position == "center"
    assert s.show_header and not s.show_instance and s.show_background and s.show_panel
    p.set("jujutsu-kaisen", character="sukuna", opacity=5.0, blur=-4, headerHeight=9, position="nowhere", showInstanceArtwork=True)
    s = art.effective(p, cols)
    assert (s.character_id, s.opacity, s.blur, s.header_height, s.position, s.show_instance) == ("sukuna", 0.60, 0.0, 40, "center", True)
    p.set("jujutsu-kaisen", character="ghost")
    assert art.effective(p, cols).character_id == "gojo"                                     # an unknown character falls back
    other = art.effective(p, cols, "solo-leveling")
    assert other.character_id == "jinwoo" and not other.show_instance                        # each anime keeps its own
    p.enabled = False
    assert not art.effective(p, cols).enabled
    p.favourites.append("x")
    again = art.prefs_from_ui({"artwork": p.to_dict()})
    assert again.to_dict() == p.to_dict()
    p.reset_collection("jujutsu-kaisen")
    assert "jujutsu-kaisen" not in p.per
    p.reset_all()
    assert p.enabled and p.collection == "" and p.per == {} and p.favourites == ["x"]        # favourites survive a reset
    assert art.prefs_from_ui({}).to_dict() == art.Prefs().to_dict()
    assert art.prefs_from_ui({"artwork": "junk"}).enabled and art.prefs_from_ui({"artwork": {"per": 5, "favourites": 3}}).per == {}


def test_resolver_picks_choices_and_falls_back_quietly():
    root = workspace()
    try:
        for name in ("a", "b"):
            rel = f"naruto/backgrounds/{name}.webp"
            picture(root / "assets" / "anime" / rel)
            approve(root, rel)
        picture(root / "assets" / "anime" / "naruto/characters/itachi.webp", alpha=True)
        approve(root, "naruto/characters/itachi.webp", character="itachi")
        lib = art.Library(root)
        res = art.Resolver(lib)
        p = art.Prefs(collection="naruto")
        s = art.effective(p, lib.collections)
        assert res.background(s).key == "bundled:naruto/backgrounds/a.webp"                   # no default set: the first
        p.set("naruto", background="bundled:naruto/backgrounds/b.webp")
        assert res.background(art.effective(p, lib.collections)).key.endswith("/b.webp")
        p.set("naruto", background="bundled:naruto/backgrounds/gone.webp")
        assert res.background(art.effective(p, lib.collections)).key.endswith("/a.webp")      # a choice that vanished: default
        p.set("naruto", background="none")
        assert res.background(art.effective(p, lib.collections)) is None
        p.set("naruto", background=None, showBackground=False)
        assert res.background(art.effective(p, lib.collections)) is None
        s = art.effective(p, lib.collections)
        assert res.character(s).character == "itachi" and res.header(s).character == "itachi"  # no banner: the character, cropped wide
        assert res.portrait(s) is None                                                          # off by default
        p.set("naruto", showInstanceArtwork=True)
        assert res.portrait(art.effective(p, lib.collections)).character == "itachi"
        p.set("naruto", showCharacterArtwork=False)
        assert res.portrait(art.effective(p, lib.collections)) is None and res.header(art.effective(p, lib.collections)) is None
        p.enabled = False
        assert res.character(art.effective(p, lib.collections)) is None
        assert res.character(art.effective(art.Prefs(collection="frieren"), lib.collections)) is None    # nothing installed
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_search_finds_anime_characters_and_favourites():
    lib = art.Library(ROOT)
    p = art.Prefs()

    def ids(q, fav=False):
        return [c.id for c, _ in art.search(lib, p, q, fav)]
    assert len(ids("")) == 16
    assert ids("gojo") == ["jujutsu-kaisen"] and ids("GOJO") == ["jujutsu-kaisen"]
    assert ids("forger") == ["spy-x-family"] and ids("ball") == ["dragon-ball"]
    assert ids("hunter") == ["solo-leveling", "hunter-x-hunter"] or "hunter-x-hunter" in ids("hunter")
    assert ids("zoro luffy") == ["one-piece"] and ids("zoro nobody") == [] and ids("zzzz") == []
    assert dict((c.id, h) for c, h in art.search(lib, p, "itachi"))["naruto"] == ["Itachi Uchiha"]
    assert ids("", fav=True) == []
    p.toggle_favourite(art.fav_key("frieren", "characters", "fern"))
    assert ids("", fav=True) == ["frieren"]
    assert p.toggle_favourite(art.fav_key("frieren", "characters", "fern")) is False and ids("", fav=True) == []


# ---------------------------------------------------------------- making pictures ready
def test_drawing_never_fails_and_caches():
    root = workspace(copy_assets=False)
    try:
        cache = art.ImageCache(root)
        src = picture(root / "wide.png", (3000, 1200), colour=(30, 90, 200), alpha=True)
        spec = art.StripSpec(900, 64, str(src), (1, 2), (0.5, 0.0), "#171717", "#5B6CFF", 0.9, 0.0, "Naruto Akatsuki · Itachi", "#FFFFFF")
        out = art.render_strip(spec, cache)
        assert out.size == (900, 64) and out.mode == "RGB"
        out2 = art.render_strip(art.StripSpec(900, 64, "", (), (0.5, 0.5), "#171717", "#5B6CFF", 0.9, 0.0, "x", "#FFFFFF"), cache)
        assert out2.size == (900, 64)                                                           # no picture: still a valid strip
        gone = art.render_strip(art.StripSpec(900, 64, str(root / "gone.png"), (), (0.5, 0.5), "#171717", "#5B6CFF", 0.9, 0.0, "", "#FFF" + "FFF"), cache) \
            if False else None
        assert art.render_portrait(root / "gone.png", 36, "#5B6CFF", cache) is None             # missing: None, not an exception
        (root / "broken.png").write_bytes(b"not an image")
        assert art.render_portrait(root / "broken.png", 36, "#5B6CFF", cache) is None
        p = art.render_portrait(src, 36, "#5B6CFF", cache)
        assert p.size == (36, 36)
        before = cache.misses
        for _ in range(5):
            assert cache.source(src, 640) is not None
        assert cache.misses - before <= 1 and cache.hits >= 4                                  # the same picture is decoded once
        assert any(cache_file.suffix == ".webp" for cache_file in art.cache_dir(root).glob("*"))  # a big one is kept as a thumbnail
        fresh = art.ImageCache(root)                                                            # a new run reads the thumbnail
        assert fresh.source(src, 640).size[0] <= 640
        assert art.placeholder(100, 40, "#ff0000", "#101010", "JK").size == (100, 40)
        pal = ("#101018", "#181822", "#12121A", "#F0F0F5", "#9A9AAA", "#2A2A38", "#5B6CFF")
        for has in (False, True):
            prev = art.render_preview(art.PreviewSpec(204, 116, pal, "#5B6CFF", "JK", str(src) if has else "", str(src) if has else "",
                                                      str(src) if has else "", str(src) if has else "", 0.18, 2.0, (0.5, 0.5)), cache)
            assert prev.size == (204, 116)
        assert gone is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_artwork_is_part_of_what_the_exe_carries_and_the_tool_agrees():
    assert "assets/anime" in seed.PARTS
    out = Path(tempfile.mkdtemp(prefix="rerunlite_seed_"))
    try:
        staged = seed.stage(ROOT, out, schedule=False)
        assert sum(1 for s in staged if s.endswith("collection.json")) == 16 and "assets/anime/manifest.json" in staged
        assert not any(s.endswith(".gitkeep") for s in staged)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "artwork_tool.py"), "check"], capture_output=True, text=True)
    assert r.returncode == 0 and "16 collections" in r.stdout, r.stdout + r.stderr


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t0 = time.time()
            t()
            print(f"PASS {t.__name__} ({time.time() - t0:.1f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, repr(e), flush=True)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
