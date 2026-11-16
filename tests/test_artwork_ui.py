"""The anime artwork in the real window: the five places it appears, the Artwork page, that a change never rebuilds the
window or touches Crest, and that missing pictures are harmless.   Run:  py tests/test_artwork_ui.py  (needs a display)"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ios  # noqa: E402
from rerun_lite import artwork as art  # noqa: E402
from rerun_lite import background, theme  # noqa: E402
from tests.test_artwork import picture  # noqa: E402
from tests.test_lite import close, open_lite, pump, texts, wait_until  # noqa: E402

TWO_INSTANCES = [{"name": "Instance 1", "serial": "127.0.0.1:5555"}, {"name": "Instance 2", "serial": "127.0.0.1:5565"}]


def add(app, cid, kind, name, size=(1600, 900), colour=(60, 90, 200), character="", alpha=False):
    src = picture(app.m.root / "src" / name, size, colour, alpha)
    return app._art_state().lib.add_user_image(cid, kind, src, character, Path(name).stem)


def buttons(w) -> list[str]:
    """The text of every ios.Button under `w` (they are canvases, so texts() does not see them)."""
    out = [str(w._text)] if isinstance(w, ios.Button) else []
    for c in w.winfo_children():
        out += buttons(c)
    return out


def strips(app):
    return getattr(app, "_art_header", None), getattr(app, "_art_panel", None)


def test_with_no_artwork_the_window_is_unchanged():
    root, m, inst, app = open_lite(TWO_INSTANCES)
    try:
        pump(app, 10)
        assert app.errors == []
        head, panel = strips(app)
        assert head is not None and panel is not None
        assert not head._on_screen and not panel._on_screen                       # nothing to show: no space taken
        assert app._art_background_spec() is None and app.backdrop.art is None
        assert all(r.get("art") is None for r in app.inst_list._rows.values())
        assert "Artwork" in dict(app._set_nav._items).values()
    finally:
        close(app, root)


def test_every_place_shows_the_artwork_and_a_change_never_rebuilds_or_touches_crest():
    root, m, inst, app = open_lite(TWO_INSTANCES)
    try:
        nb_before, backdrop_before = app.nb, app.backdrop
        cid = "jujutsu-kaisen"
        bg = add(app, cid, "backgrounds", "night.png")
        char = add(app, cid, "characters", "gojo.png", (800, 1200), (230, 230, 240), "gojo", alpha=True)
        c = app._art_state()
        c.prefs.collection = cid
        c.prefs.set(cid, showInstanceArtwork=True, character="gojo", variant=char.key, background=bg.key)
        sig_before = (tuple(i.status for i in m.instances.values()), id(m.instances))
        app._art_changed()
        head, panel = strips(app)
        assert wait_until(app, lambda: head._photo is not None and panel._photo is not None, 10), "strips were not drawn"
        assert head._on_screen and head.winfo_height() >= 60 and panel._on_screen                       # B and D
        assert wait_until(app, lambda: all(r.get("art") is not None for r in app.inst_list._rows.values()), 10)   # C
        for r in app.inst_list._rows.values():
            assert r["art"] in r["paint"] and r["art"].image.width() == r["art"].image.height()
        spec = app._art_background_spec()                                                               # A
        assert spec is not None and spec.path == bg.path and spec.opacity == 0.18
        assert app.backdrop.art is not None and app.backdrop.path == bg.path
        # a change is applied in place: same window, same backdrop object, nothing about the emulators moved
        assert app.nb is nb_before and app.backdrop is backdrop_before and app.errors == []
        assert sig_before == (tuple(i.status for i in m.instances.values()), id(m.instances))
        app._art_set("opacity", 0.35)
        assert wait_until(app, lambda: app.backdrop.player is not None and abs(app.backdrop.player.dim - 0.35) < 1e-6, 5)
        app._art_set("blur", 6.0)
        app._art_set("position", "top")
        assert app.backdrop.player.blur == 6.0 and app.backdrop.player.anchor == (0.5, 0.0)
        assert app.backdrop.player.path == bg.path
        # D: the strip sits beside the numbers, not on top of them
        tiles = app.tiles["runs"].master
        assert panel.master is tiles.master and panel.winfo_y() >= tiles.winfo_y() + tiles.winfo_height() - 2
        # switching things off hides them, and takes their space back
        app._art_set("showHeaderArtwork", False)
        app._art_set("showPanelArtwork", False)
        app._art_set("showInstanceArtwork", False)
        app._art_set("showBackground", False)
        pump(app, 4)
        assert not head._on_screen and not panel._on_screen
        assert all(r.get("art") is None for r in app.inst_list._rows.values())
        assert app._art_background_spec() is None
        app._art_set_enabled(False)
        app._art_set("showHeaderArtwork", True)
        pump(app, 4)
        assert not head._on_screen                                                                      # the master switch wins
        assert app.errors == []
    finally:
        close(app, root)


def test_the_choice_is_saved_and_comes_back_and_works_on_any_look():
    root, m, inst, app = open_lite(TWO_INSTANCES)
    try:
        cid = "naruto"
        pic = add(app, cid, "characters", "itachi.png", (800, 1000), (160, 20, 20), "itachi")
        c = app._art_state()
        c.prefs.collection = cid
        c.prefs.set(cid, character="itachi", variant=pic.key, opacity=0.3)
        app._art_changed()
        saved = json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))
        assert saved["artwork"]["collection"] == cid and saved["artwork"]["per"][cid]["opacity"] == 0.3
        assert saved["appearance"]["look"] == "plain"                                                   # the look is separate
        look_before = theme.CURRENT.appearance
        for look in ("midnight", "classic", "sakura"):                                                  # any look takes any anime
            app.apply_appearance(look=look) if False else app.apply_appearance(app._look.__class__(look, "dark"))
            pump(app, 6)
            head, _ = strips(app)
            assert wait_until(app, lambda: head._on_screen and head._photo is not None, 10), look
            assert app._art_settings().character_id == "itachi" and app.errors == [], look
        assert look_before != theme.CURRENT.appearance
        again = art.prefs_from_ui(app._ui_state())
        assert again.collection == cid and again.per[cid]["character"] == "itachi"
    finally:
        close(app, root)


def test_the_artwork_page_gallery_search_favourites_and_reset():
    root, m, inst, app = open_lite(TWO_INSTANCES)
    try:
        app.nb.select(app._tab_settings)
        app._set_nav.select("artwork")
        pump(app, 8)
        page = app._set_pages["artwork"]
        grid = app._art_grid
        assert len(grid.winfo_children()) == 16                                                         # E: 16 gallery cards
        words = " ".join(texts(grid))
        assert "Jujutsu Kaisen" in words and "Spy x Family" in words and "No artwork installed" in words
        assert wait_until(app, lambda: all(t._photo is not None for t in grid.winfo_children()), 15), "cards not drawn"
        # search
        app._art_q.set("gojo")
        assert wait_until(app, lambda: len(grid.winfo_children()) == 1, 3)
        assert "Matches: Gojo Satoru" in " ".join(texts(grid))
        app._art_q.set("nothing like this")
        assert wait_until(app, lambda: "Nothing matches." in texts(grid), 3)
        app._art_q.set("")
        assert wait_until(app, lambda: len(grid.winfo_children()) == 16, 3)
        # choosing an anime fills the detail, applies at once and survives a favourite and a reset
        app._art_choose_collection("one-piece")
        pump(app, 4)
        detail = " ".join(texts(app._art_detail_host))
        assert "Monkey D. Luffy" in detail and "Roronoa Zoro" in detail and "Add picture…" in buttons(app._art_detail_host)
        assert "Image position" in detail and "Header banner height" in detail
        app._art_pick_character("zoro")
        assert app._art_settings().character_id == "zoro"
        app._art_toggle_fav(art.fav_key("one-piece", "characters", "zoro"))
        app._art_fav_var.set("Favourites")
        app._art_filter_changed()
        assert wait_until(app, lambda: len(grid.winfo_children()) == 1, 3)
        app._art_fav_var.set("All")
        app._art_filter_changed()
        app._art_set("opacity", 0.4)
        app._art_reset("one-piece")
        s = app._art_settings()
        assert s.opacity == 0.18 and s.character_id == "luffy" and app._art_state().prefs.favourites      # favourites kept
        app._art_on.set(False)
        app._art_set_enabled(False)
        assert "Off" == app._art_status.cget("text")
        assert app.errors == []
        assert page.winfo_exists()
    finally:
        close(app, root)


def test_adding_and_removing_a_picture_from_the_page_and_a_bad_one_is_refused():
    root, m, inst, app = open_lite(TWO_INSTANCES)
    try:
        app.nb.select(app._tab_settings)
        app._set_nav.select("artwork")
        app._art_choose_collection("frieren")
        pump(app, 4)
        from rerun_lite import artwork_ui
        src = picture(root / "fern.png", (700, 900), (120, 80, 200))
        artwork_ui.filedialog.askopenfilename = lambda **k: str(src)
        artwork_ui.ios.confirm = lambda *a, **k: True
        app._art_add("frieren", "characters", "fern")
        assert wait_until(app, lambda: app._art_settings().variant.startswith("user:characters/fern--"), 8)
        assert app._art_settings().character_id == "fern" and any("Added" in t for t in app.shown)
        assert "1 picture." in " ".join(texts(app._art_detail_host)) and "Remove" in buttons(app._art_detail_host)
        bad = root / "not_a_picture.png"
        bad.write_text("nope", encoding="utf-8")
        artwork_ui.filedialog.askopenfilename = lambda **k: str(bad)
        app.shown.clear()
        app._art_add("frieren", "backgrounds")
        assert wait_until(app, lambda: any("not a picture" in t for t in app.shown), 8)
        assert app._art_settings().background == "default"                                            # nothing changed
        mine = app._art_state().lib.images("frieren", "characters", "fern")[0]
        app._art_remove(mine)
        pump(app, 4)
        assert app._art_state().lib.images("frieren", "characters", "fern") == [] and app._art_settings().variant == ""
        assert app.errors == []
    finally:
        close(app, root)


def test_a_missing_or_damaged_picture_never_crashes_the_window():
    root, m, inst, app = open_lite(TWO_INSTANCES)
    try:
        cid = "bleach"
        bg = add(app, cid, "backgrounds", "sky.png")
        ch = add(app, cid, "characters", "ichigo.png", (600, 800), (200, 120, 30), "ichigo")
        c = app._art_state()
        c.prefs.collection = cid
        c.prefs.set(cid, showInstanceArtwork=True)
        app._art_changed()
        head, panel = strips(app)
        assert wait_until(app, lambda: head._photo is not None, 10)
        bg.path.write_bytes(b"damaged")                                                               # damaged on disk
        ch.path.unlink()                                                                              # and gone
        app._art_changed()
        app.apply_appearance(app._look.__class__("sakura", "light"))
        pump(app, 10)
        assert app._art_background_spec() is not None                                                 # a file is there, the player copes
        t0 = time.time()
        while app.backdrop.player is not None and app.backdrop.player.is_alive() and time.time() - t0 < 3:
            app.update()
            time.sleep(0.05)
        assert app.errors == []
        app._set_nav.select("artwork")
        pump(app, 6)
        assert len(app._art_grid.winfo_children()) == 16 and app.errors == []
    finally:
        close(app, root)


def test_a_still_picture_background_is_toned_blurred_and_positioned():
    import numpy as np
    root = Path(__import__("tempfile").mkdtemp(prefix="rerunlite_still_"))
    try:
        im = np.zeros((200, 400, 3), np.uint8)
        im[:, :200] = (255, 0, 0)
        im[:, 200:] = (0, 0, 255)
        left = background.cover(im, 100, 100, (0.0, 0.5))
        right = background.cover(im, 100, 100, (1.0, 0.5))
        assert left[50, 10].tolist() == [255, 0, 0] and right[50, 90].tolist() == [0, 0, 255]
        picture(root / "wide.png", (400, 200), (250, 250, 250))
        p = background.Player(root / "wide.png", (320, 180), 0.2, 8, veil="#000000", scrim=0.0, blur=4.0, anchor=(0.5, 0.5))
        p.start()
        t0 = time.time()
        while p.frame is None and time.time() - t0 < 5:
            time.sleep(0.02)
        assert p.frame is not None and p.frame.shape == (180, 320, 3), p.error
        centre = int(p.frame[90, 160].mean())
        assert 30 < centre < 60, centre                                                              # 20% of 250, a little less at the edge
        stamp = p.stamp
        time.sleep(0.4)
        assert p.stamp == stamp                                                                       # a still is not redrawn every frame
        p.dim = 0.5
        time.sleep(0.4)
        assert p.stamp > stamp and int(p.frame[90, 160].mean()) > centre
        p.stop()
        bad = background.Player(root / "nothing.png", (100, 100), 0.2, 8)
        bad.start()
        bad.join(3)
        assert bad.error and bad.frame is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t0 = time.time()
            t()
            print(f"PASS {t.__name__} ({time.time() - t0:.0f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, repr(e), flush=True)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
