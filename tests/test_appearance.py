"""The appearance system and the workflow features around it: colour maths, generated palettes, the saved choices, applying
a look at once, the shortcuts you can change, the command palette, right-click menus, the template filter, undo and copy.
Run:  py tests/test_appearance.py"""
from __future__ import annotations

import json
import sys
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ios  # noqa: E402
from rerun_lite import appearance as ap  # noqa: E402
from rerun_lite import colors, palettes, quality, shortcuts, theme  # noqa: E402
from tests.test_lite import close, open_lite, texts, wait_until  # noqa: E402

KEYS = ["bg", "card", "sep", "label", "secondary", "tertiary", "blue", "green", "red", "orange", "gray", "fill", "field",
        "bar", "tab_off", "viewer", "alert", "menu", "hover", "select", "ring", "on_accent", "accent_hover"]


# ------------------------------------------------------------------------------------------------ colours
def test_colour_maths_is_right():
    assert colors.contrast("#000000", "#FFFFFF") > 20.9 and colors.contrast("#777777", "#777777") == 1.0
    for h in ("#3E7BFA", "#E2447F", "#14A89B", "#808080", "#FFFFFF", "#000000", "#E59A10"):
        L, C, hue = colors.to_oklch(h)
        back = colors.from_oklch(L, C, hue)
        assert all(abs(int(back[i:i + 2], 16) - int(h[i:i + 2], 16)) <= 1 for i in (1, 3, 5)), (h, back)
    assert colors.to_oklch("#808080")[1] < 0.01                                           # grey has no chroma
    assert colors.valid_hex("#abc") and colors.valid_hex("A1B2C3") and not colors.valid_hex("red") and not colors.valid_hex("#12345")
    for accent in ("#FFFF00", "#101010", "#3E7BFA"):                                       # a pale or a dark accent can be fitted
        fitted = colors.fit_lightness(accent, "#15171C", 3.2, 0.5, 0.9)
        assert colors.contrast(fitted, "#15171C") >= 3.2, accent
    assert colors.readable_on("#3E7BFA") == "#FFFFFF" and colors.readable_on("#FFE066") != "#FFFFFF"


# ------------------------------------------------------------------------------------------------ palettes
def test_every_accent_gives_a_readable_palette_in_both_modes_and_contrast_levels():
    custom = ["#FF0000", "#00FF00", "#FFFF00", "#0000FF", "#FFFFFF", "#000000", "#7C5CFC"]   # a user can pick anything
    for dark in (True, False):
        for high in (False, True):
            for accent in [*ap.ACCENTS.values(), *custom]:
                res = ap.resolve(ap.Appearance("plain", "dark" if dark else "light", accent, "high" if high else "standard"))
                p = res.palette
                assert set(KEYS) <= set(p), set(KEYS) - set(p)
                tag = (dark, high, accent)
                assert colors.contrast(p["label"], p["bg"]) >= 12, tag                       # body text
                assert colors.contrast(p["label"], p["card"]) >= 12, tag
                assert colors.contrast(p["secondary"], p["bg"]) >= 4.5, tag                  # grey text still passes AA
                assert colors.contrast(p["secondary"], p["card"]) >= 4.5, tag
                assert colors.contrast(p["blue"], p["card"]) >= 3.0, tag                     # the accent is visible on a panel
                assert colors.contrast(p["on_accent"], p["blue"]) >= 3.0, tag                # text on a filled button reads
                assert colors.contrast(p["sep"], p["bg"]) >= 1.1 and p["sep"] != p["bg"], tag   # a hairline can be seen
                assert p["bg"] != p["card"] and p["card"] != p["fill"], tag                  # three surfaces, three steps
                for k in ("green", "red", "orange"):
                    assert colors.contrast(p[k], p["card"]) >= 2.6, (tag, k)                 # status colours show up
    standard = ap.resolve(ap.Appearance("plain", "dark")).palette
    high = ap.resolve(ap.Appearance("plain", "dark", contrast="high")).palette
    assert colors.contrast(high["secondary"], high["bg"]) > colors.contrast(standard["secondary"], standard["bg"])
    assert colors.contrast(high["sep"], high["bg"]) > colors.contrast(standard["sep"], standard["bg"])
    light = ap.resolve(ap.Appearance("plain", "light")).palette
    assert colors.luminance(light["bg"]) > 0.85 > 0.2 > colors.luminance(standard["bg"])


def test_the_choices_resolve_and_save_sensibly():
    a = ap.Appearance()
    assert (a.look, a.mode, a.accent, a.density, a.background) == ("plain", "system", "", "comfortable", "auto")
    assert ap.Appearance("nonsense", "x", "red", "y", "z", "").clean() == a                  # anything unknown -> the default
    assert ap.resolve(ap.Appearance("plain", "system"), system_dark=True).dark and not ap.resolve(ap.Appearance("plain", "system"), False).dark
    assert not ap.resolve(ap.Appearance("plain", "light"), system_dark=True).dark            # an explicit mode wins over Windows
    ahri = ap.resolve(ap.Appearance("ahri", "light"))                                         # a themed look has its own mode
    assert ahri.dark and ahri.palette["bg"] == palettes.LOOKS["ahri"].palette["bg"] and ahri.video == "spirit_blossom.mp4"
    assert not ap.resolve(ap.Appearance("sakura", "dark")).dark
    recoloured = ap.resolve(ap.Appearance("ahri", accent="#14A89B")).palette                 # an accent can be put on any look
    assert recoloured["blue"] == "#14A89B" and recoloured["bg"] == palettes.LOOKS["ahri"].palette["bg"]
    assert ap.resolve(ap.Appearance("plain")).video == "" and ap.resolve(ap.Appearance("plain", background="neon")).video == "neon.mp4"
    assert ap.resolve(ap.Appearance("ahri", background="off")).video == "" and ap.resolve(ap.Appearance("midnight", background="custom")).video == ""
    assert ap.resolve(ap.Appearance("classic", "dark")).tokens.outline is False and ap.resolve(ap.Appearance("plain")).tokens.radius == 6
    # saved choices: new format, the 1.0.x format, and junk
    d = ap.Appearance("midnight", "dark", "#7C5CFC", "high", "compact", "off", "x.mp4")
    assert ap.from_ui({"appearance": d.to_dict()}) == d
    assert ap.from_ui({"theme": "neon"}).look == "neon" and ap.from_ui({"theme": "dark"}) == ap.Appearance("classic", "dark")
    assert ap.from_ui({"theme": "ahri", "bg_path": "C:/v.gif"}).background == "custom" and ap.from_ui({}) == ap.Appearance()
    assert ap.from_ui({"appearance": "junk"}) == ap.Appearance()
    assert ap.splash_colors(ap.Appearance("ahri"))["bg"] == palettes.LOOKS["ahri"].palette["bg"]


# ------------------------------------------------------------------------------------------------ applying a look at once
def widget_colours(w) -> set[str]:
    out = set()
    for c in [w, *iter_children(w)]:
        for opt in ("bg", "background", "fg", "foreground", "highlightbackground", "activebackground"):
            try:
                v = str(c.cget(opt))
            except tk.TclError:
                continue
            if v.startswith("#"):
                out.add(v.upper())
    return out


def iter_children(w):
    for c in w.winfo_children():
        yield c
        yield from iter_children(c)


def test_a_look_is_applied_at_once_everywhere_and_the_user_stays_where_they_were():
    root, m, inst, app = open_lite()
    try:
        app.nb.select(app._tab_settings)
        app._set_nav.select("appearance")
        app.update()
        before = widget_colours(app.nb)
        ahri = ap.resolve(ap.Appearance("ahri")).palette
        app.apply_appearance(ap.Appearance("ahri"))
        app.update()
        assert app._look.look == "ahri" and ios.C["bg"] == ahri["bg"] and app.nb.index() == app._tab_settings
        assert app._set_nav.current == "appearance" and not app.errors, app.errors            # same place, no error
        after = widget_colours(app.nb)
        plain = ap.resolve(ap.Appearance("plain", "dark")).palette
        assert ahri["bg"].upper() in after and plain["bg"].upper() not in after - {ahri["bg"].upper()}
        # nothing of the old look is left on any widget (every colour in the tree belongs to the new palette or is white/black)
        new_colours = {v.upper() for v in ios.C.values() if str(v).startswith("#")}
        old_only = {c for c in before - new_colours if c in {v.upper() for v in plain.values() if str(v).startswith("#")}}
        assert not (old_only & after), old_only & after
        # a custom accent reaches buttons, the Start button in the bar, tabs and the selected row
        app.apply_appearance(replace(app._look, look="plain", mode="dark", accent="#E2447F"))
        app.update()
        accent = ios.C["blue"]
        assert abs(colors.to_oklch(accent)[2] - colors.to_oklch("#E2447F")[2]) < 8 and app.nb.action.cget("bg").upper() == accent.upper()
        assert any(str(l.cget("bg")).upper() == accent.upper() for l in app.nb._lines)       # the open tab's underline
        buttons = [w for w in iter_children(app.nb) if isinstance(w, ios.Button) and w._kind == "filled"]
        assert buttons and all(b._color.upper() == accent.upper() for b in buttons)
        assert json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))["appearance"]["accent"] == "#E2447F"
        # the same choices again do nothing; density changes the sizes, not the text
        calls = []
        real = app._build_ui
        app._build_ui = lambda: (calls.append(1), real())[1]
        app.apply_appearance(app._look)
        assert not calls
        app._build_ui = real
        comfortable = ios.px(100)
        app.apply_appearance(replace(app._look, density="compact"))
        assert ios.px(100) < comfortable and ios.px(100) == round(comfortable * 0.88)
        app.apply_appearance(replace(app._look, density="comfortable"))
        assert ios.px(100) == comfortable and not app.errors, app.errors
    finally:
        theme.apply(ap.Appearance("ahri"))
        close(app, root)


def test_the_appearance_page_controls_work_and_are_not_decoration():
    root, m, inst, app = open_lite()
    try:
        app.nb.select(app._tab_settings)
        app._set_nav.select("appearance")
        app.update()
        page = app._set_pages["appearance"]
        said = " ".join(texts(page)).lower()
        for needle in ("Look", "Mode", "Accent colour", "Readability", "Background", "Contrast", "Density", "Dimming", "Plain", "Classic", "Neon"):
            assert needle.lower() in said, needle
        swatches = next(w for w in iter_children(page) if isinstance(w, type(app).__mro__[0]) is False and w.__class__.__name__ == "Swatches")
        r = ios.px(11)
        swatches.event_generate("<Button-1>", x=2 * (2 * r + ios.px(10)) + r + ios.px(4), y=r + ios.px(4))     # the third colour: Rose
        assert wait_until(app, lambda: app._look.accent == ap.ACCENTS["Rose"])
        app._ap_mode.set("Light")
        app._ap_mode_changed()
        assert wait_until(app, lambda: app._look.mode == "light" and not ios.DARK_MODE)
        app._ap_density.set("Compact")
        app._ap_density_changed()
        assert wait_until(app, lambda: app._look.density == "compact")
        app._ap_background_changed("Neon")
        assert wait_until(app, lambda: app._look.background == "neon")
        app._ap_set(look="sakura")                                                           # a themed look
        assert wait_until(app, lambda: app._look.look == "sakura" and ios.C["bg"] == palettes.LOOKS["sakura"].palette["bg"])
        assert app._look.accent == ap.ACCENTS["Rose"] and not app.errors, app.errors          # the chosen accent follows the look
    finally:
        theme.apply(ap.Appearance("ahri"))
        close(app, root)


# ------------------------------------------------------------------------------------------------ shortcuts
def test_shortcut_keys_are_spelled_bound_and_checked_for_clashes():
    assert [shortcuts.normalize(x) for x in ("ctrl + k", "CTRL+SHIFT+c", "alt+x", "F1", "ctrl+,")] == ["Ctrl+K", "Ctrl+Shift+C", "Alt+X", "F1", "Ctrl+,"]
    assert shortcuts.to_tk("Ctrl+Enter") == "<Control-Return>" and shortcuts.to_tk("Ctrl+,") == "<Control-comma>"
    assert shortcuts.to_tk("Ctrl+1") == "<Control-Key-1>" and shortcuts.to_tk("Ctrl+Shift+C") == "<Control-Shift-Key-C>" and shortcuts.to_tk("F1") == "<F1>"
    assert shortcuts.to_tk("") == "" and shortcuts.to_tk("Ctrl+Shift+Tab") == "<Control-ISO_Left_Tab>"
    ev = lambda sym, state: SimpleNamespace(keysym=sym, state=state)                         # noqa: E731
    assert shortcuts.from_event(ev("k", shortcuts.CONTROL)) == "Ctrl+K" and shortcuts.from_event(ev("Return", shortcuts.CONTROL)) == "Ctrl+Enter"
    assert shortcuts.from_event(ev("Control_L", shortcuts.CONTROL)) == "" and shortcuts.from_event(ev("c", shortcuts.CONTROL | shortcuts.SHIFT)) == "Ctrl+Shift+C"
    s = shortcuts.Shortcuts({"start": "ctrl+l", "bogus": "x"})
    assert s.get("start") == "Ctrl+L" and s.get("palette") == "Ctrl+K" and "bogus" not in s.keys
    assert "already used" in s.set("stop", "Ctrl+K") and "Use Ctrl" in s.set("stop", "K") and s.get("stop") == "Ctrl+."
    assert s.set("stop", "Ctrl+J") == "" and s.changed() == {"start": "Ctrl+L", "stop": "Ctrl+J"}
    assert s.set("stop", "") == "" and s.get("stop") == "" and s.owner("") == ""             # a key can be removed
    s.reset("stop")
    assert s.get("stop") == "Ctrl+." and s.changed() == {"start": "Ctrl+L"}
    assert len({a.id for a in shortcuts.ACTIONS}) == len(shortcuts.ACTIONS) and len({a.default for a in shortcuts.ACTIONS}) == len(shortcuts.ACTIONS)


def test_changing_a_shortcut_in_the_app_rebinds_it_saves_it_and_is_listed():
    root, m, inst, app = open_lite()
    try:
        assert app.bind_all(shortcuts.to_tk("Ctrl+K")) and app.bind_all(shortcuts.to_tk("Ctrl+1")) and app.bind_all("<F1>")
        app.nb.select(app._tab_settings)
        app._set_nav.select("shortcuts")
        app.update()
        said = " ".join(texts(app._set_pages["shortcuts"]))
        for a in shortcuts.ACTIONS:
            assert a.label in said, a.label
        app._sc_capture("stop")                                                              # click the key, press a new one
        assert app._sc_capturing == "stop"
        assert app._sc_key(SimpleNamespace(keysym="j", state=shortcuts.CONTROL)) == "break"
        assert app._shortcuts.get("stop") == "Ctrl+J" and app._sc_capturing is None
        assert app.bind_all(shortcuts.to_tk("Ctrl+J")) and not app.bind_all(shortcuts.to_tk("Ctrl+."))   # rebound, old key freed
        assert json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))["shortcuts"] == {"stop": "Ctrl+J"}
        app._sc_capture("start")                                                             # a key that is taken is refused
        app._sc_key(SimpleNamespace(keysym="k", state=shortcuts.CONTROL))
        assert app._shortcuts.get("start") == "Ctrl+Enter" and "already used" in app._sc_msg.cget("text")
        app._sc_capture("dry_run")
        app._sc_key(SimpleNamespace(keysym="Escape", state=0))                              # Esc cancels
        assert app._shortcuts.get("dry_run") == "Ctrl+D" and app._sc_capturing is None
        app._sc_reset_all()
        assert app._shortcuts.changed() == {} and json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))["shortcuts"] == {}
        started = []
        app.open_palette = lambda: started.append("palette") or "break"
        app._bind_shortcuts()
        app.event_generate("<Control-Key-k>")
        app.update()
        assert started == ["palette"]                                                        # the key really runs the action
        assert not app.errors, app.errors
    finally:
        close(app, root)


# ------------------------------------------------------------------------------------------------ command palette
def test_the_command_palette_finds_and_runs_things():
    C_ = quality.Command
    cmds = [C_("Go to Templates", "Go", lambda: None), C_("Open Templates settings", "Settings", lambda: None, keywords="pictures"),
            C_("Start Crest", "Run", lambda: None), C_("Look: Neon", "Appearance", lambda: None, keywords="theme")]
    assert [c.title for c in quality.search(cmds, "")] == [c.title for c in cmds]
    assert {c.title for c in quality.search(cmds, "templ")[:2]} == {"Go to Templates", "Open Templates settings"}
    assert [c.title for c in quality.search(cmds, "neon")] == ["Look: Neon"] and [c.title for c in quality.search(cmds, "theme")] == ["Look: Neon"]
    assert [c.title for c in quality.search(cmds, "settings pictures")] == ["Open Templates settings"] and quality.search(cmds, "zzz") == []
    assert len(quality.search(cmds * 5, "", limit=9)) == 9
    root, m, inst, app = open_lite()
    try:
        all_cmds = app.commands()
        titles = [c.title for c in all_cmds]
        assert len(titles) == len(set(titles)) and all(callable(c.run) for c in all_cmds)
        for needle in ("Go to Auto Crest", "Open Appearance", "Open Keyboard shortcuts", "Start Crest on the selected emulator", "Stop everything",
                       "Look: Neon", "Mode: Light", "Accent: Rose", "Density: Compact", "Copy a status summary", "Import palace pictures from GS Companion"):
            assert needle in titles, needle
        assert next(c for c in all_cmds if c.title == "Stop everything").hint == "Ctrl+."
        app.open_palette()
        app.update()
        pal = app._palette
        pal.var.set("look neon")
        app.update()
        assert [c.title for c in pal.shown] == ["Look: Neon"]
        pal.entry.event_generate("<Return>")
        assert wait_until(app, lambda: app._look.look == "neon")                              # Enter ran it: the whole window changed
        assert not pal.winfo_exists() and not app.errors, app.errors
        app.open_palette()
        app.update()
        app._palette.entry.event_generate("<Escape>")
        app.update()
        assert not app._palette.winfo_exists()
    finally:
        theme.apply(ap.Appearance("ahri"))
        close(app, root)


# ------------------------------------------------------------------------------------------------ menus, filter, undo, copy
def test_right_click_menus_the_template_filter_undo_and_copy():
    from rerun_lite import quality as q
    insts = [{"name": "A", "serial": "127.0.0.1:5555", "script": "crest"}, {"name": "B", "serial": "127.0.0.1:5565", "script": "crest"}]
    root, m, inst, app = open_lite(insts)
    try:
        # --- the instance menu: the same actions as the buttons, disabled when they do not apply
        shown = []
        app._popup = lambda menu, e: shown.append(menu) or "break"
        app._instance_menu(SimpleNamespace(x_root=0, y_root=0), "B")
        assert app.selected() == "B"
        menu = shown[-1]
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
        assert labels == ["Start Crest", "Dry run", "Pause / resume", "Stop", "Copy address", "Edit address…", "Remove…"]
        assert menu.entrycget(0, "state") == "normal" and menu.entrycget(2, "state") == "disabled"   # idle: can start, cannot pause
        menu.invoke(menu.index("Copy address"))
        assert app.clipboard_get() == "127.0.0.1:5565"
        assert all(w.bind("<Button-3>") for w in app.inst_list._rows["A"]["paint"])                  # every part of the row answers
        # --- undo for removing an emulator
        ios.confirm = lambda *a, **k: True
        app.remove_instance()
        app.update()
        assert "B" not in m.instances and app._snack.winfo_exists()
        link = next(w for w in app._snack.winfo_children() if str(w.cget("text")) == "Undo")
        link.event_generate("<Button-1>")
        app.update()
        assert "B" in m.instances and [i["name"] for i in app._instance_items()] == ["A", "B"]
        assert not app._snack.winfo_exists()
        # --- the template filter
        tree = app.tpl_tree
        total = len(tree.get_children())
        assert total > 20
        app._tpl_query.set("palace")
        app.refresh_checklist()
        some = tree.get_children()
        assert 0 < len(some) < total and all("palace" in i for i in some)
        app._tpl_query.set("")
        app.refresh_checklist()
        assert len(tree.get_children()) == total                                                    # clearing brings every row back
        tags = {i: "missing" in tree.item(i, "tags") for i in tree.get_children()}
        app._tpl_missing.set(True)
        app.refresh_checklist()
        assert set(tree.get_children()) == {i for i, miss in tags.items() if miss}        # only the ones that are missing
        app._tpl_missing.set(False)
        app.refresh_checklist()
        assert len(tree.get_children()) == total and not app._tpl_hidden
        # --- copy a status summary
        app.copy_status()
        text = app.clipboard_get()
        assert text.startswith("ReRun LITE status") and "- A (127.0.0.1:5555)" in text and "- B (127.0.0.1:5565)" in text
        assert q.Command and not app.errors, app.errors
    finally:
        close(app, root)


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
