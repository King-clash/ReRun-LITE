"""Crest with the daily palace selector.

`LiteCrest` is the original CrestScript. The only thing it changes is HOW the palace tile is found on the Crest
Palace screen, and only while the selector is on (Settings > Palace Selector):

  selector on   today's palace comes from palaces.choose() (the weekday table or the cycle, on the game clock).
                Its picture is looked for on the Crest Palace screen at any size from 60% to 160% (the pictures
                from GS Companion are not the game's own pixels). Found: that tile is tapped. Not found, or the
                picture file is missing, or nothing is chosen for today: Crest STOPS and says which palace and
                which file. It never opens a different palace.
  selector off  the original code runs untouched.

Everything else (walking Home > Exploring > Crest Palace, the quest, the loop, scrapping, alerts) is the original.
"""
from __future__ import annotations

import cv2
import numpy as np

from rerun.scripts import SCRIPTS, CrestScript
from rerun.scripts.base import Finished

from . import palaces

MATCH_MIN = 0.62          # normalised match score needed to accept a tile (a wrong palace scores about 0.35)
SCALES = np.concatenate([np.arange(0.6, 1.0, 0.04), np.arange(1.0, 1.62, 0.02)])


def find_tile(screen: np.ndarray, picture: np.ndarray) -> tuple[float, int, int, float]:
    """Best match of `picture` on `screen` over a range of sizes: (score, centre x, centre y, scale)."""
    g = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    t0 = cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY)
    best = (0.0, 0, 0, 1.0)
    for sc in SCALES:
        t = cv2.resize(t0, None, fx=float(sc), fy=float(sc), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
        if t.shape[0] >= g.shape[0] or t.shape[1] >= g.shape[1] or min(t.shape) < 12:
            continue
        r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx > best[0]:
            best = (float(mx), loc[0] + t.shape[1] // 2, loc[1] + t.shape[0] // 2, float(sc))
    return best


class LiteCrest(CrestScript):
    PALACE_ROOT = None        # set by LiteManager: the app folder (palaces.yaml, images/, data/lite/)

    def _selector_root(self):
        return self.PALACE_ROOT or self.ctx.vision.store.folder.parent

    def selector_choice(self) -> palaces.Choice:
        return palaces.choose(self._selector_root())

    def selector_on(self) -> bool:
        return palaces.load_schedule(self._selector_root()).mode != "off"

    # With the selector on, the palace picture is not a template in templates/, so the start-up check must not
    # insist on crest_palace_target. (It still checks Home, Exploring, the Crest Palace icon and the quest rows.)
    def check_nav_templates(self) -> None:
        if not self.selector_on():
            return super().check_nav_templates()
        saved = self.cfg.get("palace_name")
        self.cfg["palace_name"] = saved or "(palace selector)"
        try:
            super().check_nav_templates()
        finally:
            self.cfg["palace_name"] = saved
        choice = self.selector_choice()
        if not choice.ok:
            self._stop_for(choice)

    def _stop_for(self, choice: palaces.Choice):
        msg = f"Crest: the palace selector can't run today ({choice.day}): {choice.problem} Stopped - no other palace was run."
        self.notify(msg, screenshot=False)
        raise Finished("palace selector: " + choice.problem)

    def handle_crest_palace_screen(self, screen):
        if not self.navigating() or not self.selector_on():
            return super().handle_crest_palace_screen(screen)
        choice = self.selector_choice()
        if not choice.ok:
            self._stop_for(choice)
        picture = cv2.imdecode(np.fromfile(str(choice.path), np.uint8), cv2.IMREAD_COLOR)
        if picture is None:
            choice.problem = f"{choice.day} is {choice.palace.name}, but its picture can't be read: {choice.palace.image}"
            self._stop_for(choice)
        score, x, y, scale = find_tile(screen, picture)
        if score < MATCH_MIN:
            self.notify(f"Crest: today ({choice.day}) is {choice.palace.name} ({choice.palace.image}), but that palace is not on the "
                        f"Crest Palace screen (best match {score:.2f}, needs {MATCH_MIN:.2f}). Stopped - no other palace was run.")
            raise Finished(f"{choice.palace.name} not on the Crest Palace screen")
        self.log(f"Palace selector: {choice.day} = {choice.palace.name} (picture {choice.palace.image}, match {score:.2f} at {scale:.2f}x)")
        self.palace = f"selector:{choice.palace.name}"
        self.tap(x, y, settle=3)


def install() -> None:
    """Make 'crest' in the script table the selector-aware Crest. Idempotent."""
    SCRIPTS["crest"] = LiteCrest
