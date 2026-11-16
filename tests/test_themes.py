"""The themes and their backgrounds: every theme's palette and video, the toning (dim / scrim) of the video, the one-time
enlarging of a small video, and the window staying right when it is maximised.   Run:  py tests/test_themes.py"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ios  # noqa: E402
from rerun_lite import background, palettes, theme, upscale  # noqa: E402
from rerun_lite.colors import contrast  # noqa: E402
from tests.test_lite import close, lite_root, manager  # noqa: E402

KEYS = ["bg", "card", "sep", "label", "secondary", "tertiary", "blue", "green", "red", "orange", "gray", "fill", "field",
        "bar", "tab_off", "viewer", "alert", "menu"]


def luminance(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_every_theme_is_complete_readable_and_has_its_video():
    assert list(palettes.LOOKS) == ["ahri", "midnight", "sakura", "ember", "aurora", "neon"]
    assert list(theme.THEMES)[-3:] == ["dark", "light", "auto"]                          # ReRun's own themes come last
    for key, look in palettes.LOOKS.items():
        assert set(KEYS) <= set(look.palette), key
        p = look.palette
        # text must stand out from the page and from the cards, whichever way round the theme is
        assert abs(luminance(p["label"]) - luminance(p["bg"])) > 0.6, key
        assert abs(luminance(p["label"]) - luminance(p["card"])) > 0.55, key
        assert luminance(p["bg"]) < 0.2 if look.dark else luminance(p["bg"]) > 0.8, key
        assert abs(luminance(p["secondary"]) - luminance(p["bg"])) > 0.3, key              # grey text still reads
        assert (ROOT / "assets" / look.video).is_file(), f"{key}: assets/{look.video} is missing (py tools/make_background.py)"
        cap = cv2.VideoCapture(str(ROOT / "assets" / look.video))
        assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) >= 200 and int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) >= upscale.ENOUGH_WIDTH
        cap.release()
        assert background.asset_video(ROOT, look.video).name == look.video
        colors = palettes.splash_colors(key)                                                # the start-up window has colours too
        assert colors["bg"] == p["bg"] and colors["fill"] == p["blue"]


def test_each_theme_loads_into_the_widget_kit_and_classic_stays_the_original():
    original_dark, original_light = dict(theme.CLASSIC_DARK), dict(theme.CLASSIC_LIGHT)
    for key, look in palettes.LOOKS.items():
        assert theme.apply_palette(key) == ("dark" if look.dark else "light")
        table = ios.DARK if look.dark else ios.LIGHT
        assert table["bg"] == look.palette["bg"] and theme.current() is look
        assert contrast(table["blue"], table["card"]) >= 3.0, key                            # the accent reads on the panel
        assert theme.is_custom() and theme.mark_colors() == look.mark
    assert theme.apply_palette("dark") == "dark" and all(ios.DARK[k] == v for k, v in original_dark.items())
    assert not theme.is_custom() and theme.current() is None
    assert theme.apply_palette("light") == "light" and all(ios.LIGHT[k] == v for k, v in original_light.items())
    assert theme.apply_palette("midnight") and theme.apply_palette("auto") == "auto"
    theme.apply_palette("ahri")


def make_clip(path: Path, w: int, h: int, frames: int = 8) -> Path:
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for i in range(frames):
        img = np.full((h, w, 3), (40 + i * 10, 90, 160), np.uint8)
        cv2.circle(img, (w // 2 + i * 3, h // 2), h // 4, (240, 240, 240), -1)
        vw.write(img)
    vw.release()
    return path


def test_the_video_is_toned_toward_the_theme_colour_and_softened_behind_controls():
    tmp = Path(tempfile.mkdtemp(prefix="rl_th_"))
    try:
        clip = make_clip(tmp / "c.mp4", 320, 180)
        results = {}
        for label, veil, scrim in (("dark", "#101020", 0.0), ("dark+scrim", "#101020", 0.8), ("light", "#FBF3F6", 0.0)):
            pl = background.Player(clip, (320, 180), 0.5, 30, veil=veil, scrim=scrim)
            pl.rects = ((40, 60, 120, 100),) if scrim else ()
            pl.start()
            t0 = time.time()
            while pl.frame is None and time.time() - t0 < 5:
                time.sleep(0.02)
            pl.stop()
            assert pl.frame is not None and pl.frame.shape == (180, 320, 3), label
            results[label] = pl.frame.astype(np.float32)
        plain, scrimmed, light = results["dark"], results["dark+scrim"], results["light"]
        assert plain[90, 160].mean() < 150                                                  # a dark theme darkens the video
        inside, outside = (slice(70, 90), slice(60, 100)), (slice(140, 170), slice(220, 300))
        assert scrimmed[inside].mean() < plain[inside].mean() - 8                          # darker behind the control ...
        assert abs(scrimmed[outside].mean() - plain[outside].mean()) < 2                   # ... and untouched away from it
        assert light.mean() > plain.mean() + 60                                            # a light theme lightens it instead
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_small_video_is_enlarged_once_in_the_background_and_then_used():
    tmp = Path(tempfile.mkdtemp(prefix="rl_up_"))
    try:
        small = make_clip(tmp / "small.gif.mp4", 160, 90, frames=6)
        assert upscale.needs_upscale(160) and not upscale.needs_upscale(1280) and not upscale.needs_upscale(1920)
        cache = tmp / "cache"
        assert upscale.ready(small, cache) is None
        seen = []
        assert upscale.build(small, upscale.cache_path(small, cache), progress=seen.append)
        got = upscale.ready(small, cache)
        w, h, _fps, frames = upscale.source_size(got)
        assert got and (w, h, frames) == (1920, 1080, 6) and seen[-1] == 100 and seen == sorted(seen)
        assert not list(cache.glob("*.part.mp4"))                                           # only a finished file is kept
        # a cancelled build leaves nothing behind
        stop = upscale.threading.Event()
        stop.set()
        other = make_clip(tmp / "other.mp4", 160, 90, frames=6)
        assert upscale.build(other, upscale.cache_path(other, cache), cancel=stop) is False
        assert upscale.ready(other, cache) is None
        # a copy changes when the source changes (so an edited video is not stale)
        before = upscale.cache_path(small, cache)
        make_clip(small, 160, 90, frames=7)
        assert upscale.cache_path(small, cache) != before
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def open_app(theme_key: str, extra: dict | None = None, background_dir: Path | None = None):
    from rerun_lite.app import LiteApp
    root = lite_root(real_templates=True)
    (root / "data" / "lite").mkdir(parents=True, exist_ok=True)
    (root / "data" / "lite" / "ui.json").write_text(json.dumps({"theme": theme_key, **(extra or {})}), encoding="utf-8")
    if background_dir is not None:
        shutil.copytree(background_dir, root / "background")
    m, _inst = manager(root)
    app = LiteApp(m)
    app.errors = []
    app.report_callback_exception = lambda *a: app.errors.append(a)
    app.geometry("1140x840+30+30")
    return root, app


def wait(app, cond, seconds=8.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < seconds:
        app.update()
        time.sleep(0.02)
    return cond()


def test_every_lite_theme_opens_with_its_colours_and_its_own_background():
    from tests.test_lite import texts
    for key, look in palettes.LOOKS.items():
        root, app = open_app(key)
        try:
            assert app._look.look == key and ios.C["bg"] == look.palette["bg"], key
            assert contrast(ios.C["blue"], ios.C["card"]) >= 3.0, key
            assert wait(app, lambda: app.backdrop.active), key
            assert app.backdrop.path.name == look.video                                      # its own animation
            assert str(app.attributes("-transparentcolor")).lower() == look.palette["bg"].lower()
            assert "Behind buttons and text" in " ".join(texts(app._set_pages["appearance"]))
            assert wait(app, lambda: app.backdrop.player is not None and app.backdrop.player.frame is not None), key
            assert not app.errors, (key, app.errors)
        finally:
            app.backdrop.stop()
            close(app, root)
            theme.apply_palette("ahri")


def test_the_dropped_gif_is_for_ahri_only_and_is_enlarged_then_swapped_in():
    tmp = Path(tempfile.mkdtemp(prefix="rl_bg_"))
    (tmp / "b").mkdir()
    make_clip(tmp / "b" / "mine.mp4", 160, 90, frames=6)                                    # a small video dropped in background/
    try:
        root, app = open_app("ahri", background_dir=tmp / "b")
        try:
            assert wait(app, lambda: app.backdrop.active)
            bd = app.backdrop
            assert bd.path.name == "mine.mp4"                                                # the user's file, named as such
            assert wait(app, lambda: bd.playing is not None and bd.playing != bd.path, 40)   # ... enlarged copy swapped in
            assert upscale.source_size(bd.playing)[:2] == (1920, 1080) and bd.playing.parent.name == "cache"
            assert bd.player.path == bd.playing
            assert wait(app, lambda: bd.player.frame is not None)
            assert not app.errors, app.errors
        finally:
            app.backdrop.stop()
            close(app, root)
        root, app = open_app("midnight", background_dir=tmp / "b")                          # another theme ignores that folder
        try:
            assert wait(app, lambda: app.backdrop.active)
            assert app.backdrop.path.name == "midnight.mp4" and app.backdrop.playing == app.backdrop.path
        finally:
            app.backdrop.stop()
            close(app, root)
            theme.apply_palette("ahri")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_maximising_the_window_keeps_the_video_behind_it_at_the_right_size():
    root, app = open_app("ahri")
    try:
        assert wait(app, lambda: app.backdrop.active)
        bd = app.backdrop
        app.state("zoomed")                                                                  # maximise
        for _ in range(40):
            app.update()
            time.sleep(0.02)
        assert app.state() == "zoomed" and app.winfo_width() > 1200
        assert (bd.win.winfo_width(), bd.win.winfo_height()) == (app.winfo_width(), app.winfo_height())
        assert (bd.win.winfo_rootx(), bd.win.winfo_rooty()) == (app.winfo_rootx(), app.winfo_rooty())
        assert bd.player.size == (app.winfo_width(), app.winfo_height())
        assert wait(app, lambda: bd.player.frame is not None and bd.player.frame.shape[1] == app.winfo_width())
        assert bd.player.frame.shape[0] == app.winfo_height()                                # a frame of the full-screen size
        app.state("normal")                                                                  # and back
        for _ in range(40):
            app.update()
            time.sleep(0.02)
        assert bd.player.size == (app.winfo_width(), app.winfo_height()) and app.winfo_width() < 1300
        assert not app.errors, app.errors
    finally:
        app.backdrop.stop()
        close(app, root)


def test_the_scrim_finds_the_labels_and_buttons_that_sit_on_the_background():
    root, app = open_app("ahri")
    try:
        assert wait(app, lambda: app.backdrop.active)
        app.nb.select(0)
        for _ in range(10):
            app.update()
        rects = app.backdrop._collect_rects()
        assert 10 < len(rects) <= background.MAX_RECTS
        ox, oy = app.winfo_rootx(), app.winfo_rooty()

        def covered(widget) -> bool:
            x0, y0 = widget.winfo_rootx() - ox, widget.winfo_rooty() - oy
            cx, cy = x0 + widget.winfo_width() // 2, y0 + widget.winfo_height() // 2
            return any(a <= cx <= c and b <= cy <= d for a, b, c, d in rects)
        stop_all = next(w for w in _walk(app) if isinstance(w, ios.Button) and getattr(w, "_text", "") == "Start All")
        assert covered(stop_all)                                                             # a button on the page background
        assert all(a < c and b < d for a, b, c, d in rects)
    finally:
        app.backdrop.stop()
        close(app, root)


def _walk(w):
    for c in w.winfo_children():
        yield c
        yield from _walk(c)


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
