"""Crest on the Equip Crest screen that has a 'Confirm' button instead of OK (a crest that was already waiting in the game
when Crest started), run end to end against the simulated game, with the real text reader finding the button.
Run:  py tests/test_crest_confirm.py"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun.ocr import OcrUnavailable, get_ocr  # noqa: E402
from rerun_lite.crest import LiteCrest  # noqa: E402
from tests.test_scripts import Screen, Sim, crest_equip_screen, fast, make_ctx, run  # noqa: E402

BUTTON = (230, 1062, 490, 1135)               # x0, y0, x1, y1 of the Confirm button


class ConfirmScreen(Screen):
    """The Equip Crest screen with one orange 'Confirm' button (written text, which only the text reader can find)."""

    def render(self):
        img = super().render()
        x0, y0, x1, y1 = BUTTON
        cv2.rectangle(img, (x0, y0), (x1, y1), (25, 90, 175), -1)
        (tw, th), _ = cv2.getTextSize("Confirm", cv2.FONT_HERSHEY_DUPLEX, 1.2, 2)
        org = ((x0 + x1) // 2 - tw // 2, (y0 + y1) // 2 + th // 2)
        cv2.putText(img, "Confirm", org, cv2.FONT_HERSHEY_DUPLEX, 1.2, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, "Confirm", org, cv2.FONT_HERSHEY_DUPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
        return img

    def hit(self, tx, ty):
        x0, y0, x1, y1 = BUTTON
        return "confirm_button" if x0 <= tx <= x1 and y0 <= ty <= y1 else super().hit(tx, ty)


def test_crest_taps_the_confirm_button_and_gets_past_the_screen():
    try:
        reader = get_ocr(None)
    except OcrUnavailable:
        print("SKIP: no text reader on this PC")
        return

    class Real(LiteCrest):
        ocr = reader

    fast()
    base = crest_equip_screen("crest_icon_lv3")
    equip = ConfirmScreen([e for e in base.elements if e[0] == "crest_checkbox"], orange=base.orange, extra=base.extra)
    screens = {"equip": equip, "confirm": Screen([("select_crest_ok2", 300, 800)]), "quest_list": Screen([])}
    on_tap = {("equip", "confirm_button"): "confirm", ("confirm", "select_crest_ok2"): "quest_list"}
    dev = Sim(screens, "equip", on_tap)
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, Real)
        s = Real(ctx, {"runs": 1, "start_home": False, "verify_text": False})
        s.on_start = (lambda orig: (lambda: (orig(), setattr(s, "session_runs", 1))))(s.on_start)
        result = run(s)
        logs = list(ctx.logs)
    assert result.startswith("finished"), (result, logs)
    assert "confirm_button" in dev.tapped and dev.tapped[-1] == "select_crest_ok2", dev.tapped
    assert any("Confirm button found" in m for m in logs), logs
    assert dev.history[-1] == "quest_list" and "stuck" not in result, dev.history


def test_a_screen_whose_buttons_cannot_be_found_stops_instead_of_looping():
    try:
        reader = get_ocr(None)
    except OcrUnavailable:
        print("SKIP: no text reader on this PC")
        return

    class Real(LiteCrest):
        ocr = reader

    fast()
    base = crest_equip_screen("crest_icon_lv3")
    dead = Screen([e for e in base.elements if e[0] == "crest_checkbox"], orange=base.orange, extra=base.extra)   # no button at all
    dev = Sim({"equip": dead}, "equip", {})
    with tempfile.TemporaryDirectory() as d:
        ctx = make_ctx(Path(d), dev, Real)
        s = Real(ctx, {"runs": 0, "start_home": False, "verify_text": False})
        s.STUCK_RESET_S = 10 ** 9
        result = run(s)
        notes = list(ctx.notes)
    assert result.startswith("finished") and "stuck" in result, result
    assert any("stuck on the Equip Crest screen" in n for n in notes), notes


if __name__ == "__main__":
    failed = 0
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
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
