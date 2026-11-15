"""End-to-end tests of the scripts against a simulated game.

Each UI element is a unique random-texture patch; templates are captured from
those patches exactly as a user would with the Templates tab. A fake device
renders the current screen and moves between screens when an element is tapped.
Run:  python -m pytest -q tests   (or: python tests/test_scripts.py)
"""
from __future__ import annotations

import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rerun.adb import FakeDevice  # noqa: E402
from rerun.engine import Context, StopRoutine  # noqa: E402
from rerun.scripts import AnyQuestScript, CrestScript, LoginMailScript  # noqa: E402
from rerun.scripts.base import BaseScript, Finished  # noqa: E402
from rerun.stats import Stats  # noqa: E402
from rerun.vision import TemplateStore, Vision  # noqa: E402

W, H = 720, 1280
PATCH = (110, 44)  # w, h
ORANGE = (0, 140, 255)  # BGR


def patch(name: str, size=PATCH) -> np.ndarray:
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    w, h = size
    # Blocky texture (survives the half-resolution matching pass).
    small = rng.integers(0, 256, (max(1, h // 4), max(1, w // 4), 3), dtype=np.uint8)
    p = np.kron(small, np.ones((4, 4, 1), dtype=np.uint8))[:h, :w]
    p[..., 0] = np.clip(p[..., 0], 0, 200)  # keep patches away from pure orange
    p[..., 2] = np.clip(p[..., 2], 0, 120)
    return np.ascontiguousarray(p)


def background() -> np.ndarray:
    rng = np.random.default_rng(1)
    return rng.integers(20, 50, (H, W, 3), dtype=np.uint8)


class Screen:
    def __init__(self, elements: list[tuple[str, int, int]], orange: tuple | None = None,
                 extra: list[tuple[str, int, int]] | None = None):
        self.elements = elements  # (template, x, y)
        self.orange = orange      # (x, y, w, h) orange crest row
        self.extra = extra or []  # patches that are not tappable targets

    def render(self) -> np.ndarray:
        img = background()
        if self.orange:
            x, y, w, h = self.orange
            img[y:y + h, x:x + w] = ORANGE
        for name, x, y in self.elements + self.extra:
            p = patch(name)
            img[y:y + p.shape[0], x:x + p.shape[1]] = p
        return img

    def hit(self, tx: int, ty: int) -> str | None:
        for name, x, y in self.elements:
            if x <= tx < x + PATCH[0] and y <= ty < y + PATCH[1]:
                return name
        return None


class Sim(FakeDevice):
    """screens: name -> Screen; on_tap: (screen, element) -> next screen;
    auto: screen -> next screen after it has been seen once."""

    def __init__(self, screens, start, on_tap, auto=None):
        super().__init__(frames=[])
        self.screens, self.current = screens, start
        self.on_tap_map, self.auto = on_tap, auto or {}
        self.history = [start]
        self.tapped: list[str] = []
        self.swipes = 0

    def go(self, name):
        self.current = name
        self.history.append(name)

    def screencap(self):
        img = self.screens[self.current].render()
        if self.current in self.auto:
            self.go(self.auto[self.current])
        return img

    def tap(self, x, y):
        el = self.screens[self.current].hit(x, y)
        self.tapped.append(el or f"({x},{y})")
        nxt = self.on_tap_map.get((self.current, el))
        if nxt:
            self.go(nxt)

    def swipe(self, *a, **k):
        self.swipes += 1


def make_ctx(store_dir: Path, device: Sim, script_cls) -> Context:
    store = TemplateStore(store_dir)
    for t in script_cls.all_templates():
        if not store.has(t.name):
            canvas = background()
            p = patch(t.name)
            canvas[100:100 + p.shape[0], 100:100 + p.shape[1]] = p
            store.save(t.name, canvas, 100, 100, p.shape[1], p.shape[0])
    logs: list[str] = []
    notes: list[str] = []
    ctx = Context(
        instance="Test", device=device, vision=Vision(store), stats=Stats(),
        routines={}, base_resolution=(W, H),
        log=lambda i, m: logs.append(m),
        notify=lambda i, m, image=None, ping=False: notes.append(m),
        data_dir=store_dir,  # debug frames go to the temp folder, not the project
    )
    ctx.logs, ctx.notes = logs, notes  # type: ignore[attr-defined]
    return ctx


def fast(monkey_cls=BaseScript):
    """Remove real-time waits so tests run instantly (loop guard keeps them finite)."""
    calls = {"n": 0}

    def sleep(self, seconds, jitter=0.0):
        self.checkpoint()
        calls["n"] += 1
        if calls["n"] > 5000:
            raise RuntimeError("script did not finish (stuck in a loop)")
    monkey_cls.sleep = sleep


def run(script) -> str:
    try:
        script.run()
    except Finished as e:
        return f"finished: {e}"
    except StopRoutine as e:
        return f"stopped: {e}"
    return "returned"


# ---------------------------------------------------------------- Any Quest
def test_any_quest_loops_and_redeploys():
    fast()
    screens = {
        "party": Screen([("battle_button", 500, 960)]),
        "autoloop_off": Screen([("use_potions_button", 400, 640), ("looping_button", 450, 960)]),
        "autoloop_on": Screen([("looping_button", 450, 960)]),
        "battle": Screen([]),
        "drop": Screen([], extra=[("drop_info", 280, 96)]),
        "results": Screen([("results_redeploy", 450, 992), ("ok_button", 300, 992)]),
        "quest_page": Screen([("solo_quest_button", 450, 960)]),
    }
    on_tap = {
        ("party", "battle_button"): "autoloop_off",
        ("autoloop_off", "use_potions_button"): "autoloop_on",
        ("autoloop_on", "looping_button"): "battle",
        ("results", "results_redeploy"): "autoloop_on",
        ("results", "ok_button"): "quest_page",
    }
    # A loop batch of 2 runs: battle -> drop -> battle -> drop -> results
    state = {"runs_in_batch": 0}

    class LoopSim(Sim):
        def screencap(self):
            img = self.screens[self.current].render()
            if self.current == "battle":
                self.go("drop")
            elif self.current == "drop":
                state["runs_in_batch"] += 1
                if state["runs_in_batch"] % 2 == 0:
                    self.go("results")
                else:
                    self.go("battle")
            return img

    dev = LoopSim(screens, "party", on_tap)
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, AnyQuestScript)
        # game_refill on: exercises turning on Auto-Loop's own potion refill.
        s = AnyQuestScript(ctx, {"runs": 4, "party": "Current Party", "game_refill": True})
        result = run(s)
    assert result.startswith("finished"), result
    assert s.session_runs == 4, s.session_runs
    assert dev.tapped.count("results_redeploy") == 1, dev.tapped
    assert dev.tapped[:3] == ["battle_button", "use_potions_button", "looping_button"], dev.tapped
    assert dev.tapped[-1] == "ok_button", dev.tapped
    assert ctx.stats.get("Test")["any_quest.runs"] == 4


def test_any_quest_last_party_flow_and_failure():
    fast()
    screens = {
        "party": Screen([("past_party_button", 150, 960), ("battle_button", 500, 960)]),
        "past_dialog": Screen([("include_ai_button", 250, 640), ("apply_button", 350, 800)],
                              extra=[("battle_button", 500, 960)]),
        "past_dialog_ticked": Screen([("apply_button", 350, 800)], extra=[("battle_button", 500, 960)]),
        "party_ready": Screen([("past_party_button", 150, 960), ("battle_button", 500, 960)]),
        "autoloop": Screen([("looping_button", 450, 960)]),
        "wiped": Screen([("cancel_btn", 250, 800)], extra=[("continue_box", 280, 320)]),
        "restart": Screen([("restart_btn", 300, 800)]),
        "quest_page": Screen([("solo_quest_button", 450, 960)]),
    }
    on_tap = {
        ("party", "past_party_button"): "past_dialog",
        ("past_dialog", "include_ai_button"): "past_dialog_ticked",
        ("past_dialog_ticked", "apply_button"): "party_ready",
        ("party_ready", "battle_button"): "autoloop",
        ("autoloop", "looping_button"): "wiped",
        ("wiped", "cancel_btn"): "restart",
        ("restart", "restart_btn"): "quest_page",
        ("quest_page", "solo_quest_button"): "party",
    }
    dev = Sim(screens, "party", on_tap)
    stop_after = {"n": 0}
    orig = Sim.tap

    def tap(self, x, y):
        orig(self, x, y)
        if self.tapped[-1] == "solo_quest_button":
            stop_after["n"] += 1
            if stop_after["n"] >= 1:
                ctx.stop_event.set()
    dev.tap = tap.__get__(dev)
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, AnyQuestScript)
        s = AnyQuestScript(ctx, {"runs": 0, "party": "Last Party"})
        result = run(s)
    assert result == "stopped: stopped by user", result
    assert dev.tapped[:5] == ["past_party_button", "include_ai_button", "apply_button",
                              "battle_button", "looping_button"], dev.tapped
    assert "cancel_btn" in dev.tapped and "restart_btn" in dev.tapped, dev.tapped
    assert s.failures == 1
    assert any("failed" in n for n in ctx.notes), ctx.notes


# ---------------------------------------------------------------- Crest
def crest_equip_screen(icon: str) -> Screen:
    ox, oy, ow, oh = 20, 700, 680, 90
    return Screen(
        [("crest_checkbox", 120, 240), ("crest_checkbox", 120, 432),
         ("redeploy_button", 500, 1024), ("select_crest_ok", 350, 1024)],
        orange=(ox, oy, ow, oh),
        extra=[("equip_crest_screen", 280, 32), (icon, 200, oy + 23)],
    )


def run_crest(icon: str, keep: str = "4+ and Burst only", runs: int = 0):
    fast()
    screens = {
        "equip": crest_equip_screen(icon),
        "autoloop": Screen([("looping_button", 450, 960)]),
    }
    on_tap = {("equip", "redeploy_button"): "autoloop"}
    dev = Sim(screens, "equip", on_tap)
    orig = Sim.tap

    def tap(self, x, y):
        orig(self, x, y)
        if self.tapped[-1] == "looping_button":
            ctx.stop_event.set()
    dev.tap = tap.__get__(dev)
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, CrestScript)
        s = CrestScript(ctx, {"keep": keep, "runs": runs, "start_home": False})
        result = run(s)
    return result, dev, ctx


def test_crest_scraps_low_rarity_and_redeploys():
    result, dev, ctx = run_crest("crest_icon_lv3")
    assert result == "stopped: stopped by user", result
    assert dev.tapped[:3] == ["crest_checkbox", "crest_checkbox", "redeploy_button"], dev.tapped
    st = ctx.stats.get("Test")
    assert st["crest.crest_lv3"] == 1 and st["crest.scrapped"] == 1, st


def test_crest_keeps_4plus_and_stops_without_touching():
    result, dev, ctx = run_crest("crest_icon_lv4plus")
    assert result == "finished: 4+ crest", result
    assert dev.tapped == [], dev.tapped
    assert any("4+ crest found" in n for n in ctx.notes), ctx.notes


def test_crest_keep_setting_lv4():
    result, dev, ctx = run_crest("crest_icon_lv4", keep="Lv4 and better")
    assert result == "finished: lv4 crest", result
    result, dev, ctx = run_crest("crest_icon_lv4", keep="4+ and Burst only")
    assert result == "stopped: stopped by user" and "redeploy_button" in dev.tapped, (result, dev.tapped)


def test_crest_unknown_icon_stops_safely():
    result, dev, ctx = run_crest("some_unknown_icon")
    assert result == "finished: unknown crest", result
    assert dev.tapped == [], dev.tapped


def test_crest_burst_stops():
    fast()
    screens = {"burst": Screen([], extra=[("crest_icon_lv5plus", 250, 480)])}
    dev = Sim(screens, "burst", {})
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, CrestScript)
        result = run(CrestScript(ctx, {"start_home": False}))
    assert result == "finished: crest burst", result
    assert any("Burst" in n for n in ctx.notes)


def test_crest_target_reached_uses_ok_not_redeploy():
    fast()
    screens = {
        "equip": crest_equip_screen("crest_icon_lv3"),
        "confirm": Screen([("select_crest_ok2", 300, 800)]),
        "quest_list": Screen([]),
    }
    on_tap = {("equip", "select_crest_ok"): "confirm", ("confirm", "select_crest_ok2"): "quest_list"}
    dev = Sim(screens, "equip", on_tap)
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, CrestScript)
        s = CrestScript(ctx, {"runs": 1, "start_home": False})
        s.on_start = (lambda orig: (lambda: (orig(), setattr(s, "session_runs", 1))))(s.on_start)
        result = run(s)
    assert result.startswith("finished"), result
    assert "redeploy_button" not in dev.tapped, dev.tapped
    assert dev.tapped[-2:] == ["select_crest_ok", "select_crest_ok2"], dev.tapped


# ---------------------------------------------------------------- Login & Mail
def test_login_mail_claims_until_empty():
    fast()
    screens = {
        "title": Screen([], extra=[("game_start_screen", 290, 1040)]),
        "bonus": Screen([], extra=[("total_sign_in_bonus", 280, 160)]),
        "home": Screen([("mail_chest", 550, 192)]),
        "mail_full": Screen([("claim_all_button", 450, 992), ("mail_close_button", 575, 64)]),
        "claimed": Screen([("claim_ok_button", 300, 800)]),
        "mail_empty": Screen([("claim_all_button_dim", 450, 992), ("mail_close_button", 575, 64)]),
    }
    taps_center = {"n": 0}

    class LoginSim(Sim):
        def tap(self, x, y):
            if self.current in ("title", "bonus"):
                self.tapped.append(self.current)
                self.go("bonus" if self.current == "title" else "home")
                return
            super().tap(x, y)

    on_tap = {
        ("home", "mail_chest"): "mail_full",
        ("mail_full", "claim_all_button"): "claimed",
        ("claimed", "claim_ok_button"): "mail_empty",
        ("mail_empty", "mail_close_button"): "home",
    }
    dev = LoginSim(screens, "title", on_tap)
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, LoginMailScript)
        result = run(LoginMailScript(ctx, {"mode_247": False}))
    assert result == "finished: mailbox empty", result
    assert dev.tapped == ["title", "bonus", "mail_chest", "claim_all_button", "claim_ok_button",
                          "mail_close_button"], dev.tapped


def test_missing_template_is_reported():
    fast()
    dev = Sim({"x": Screen([])}, "x", {})
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, AnyQuestScript)
        ctx.vision.store.delete("battle_button")
        from rerun.vision import MissingTemplate
        try:
            AnyQuestScript(ctx, {}).run()
        except MissingTemplate as e:
            assert "battle_button" in str(e)
        else:
            raise AssertionError("expected MissingTemplate")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

