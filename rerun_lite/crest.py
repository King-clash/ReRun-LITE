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

import time

import cv2
import numpy as np

from rerun import textnav
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

    # What the window reads while Crest runs (rerun_lite/phases.py, stuck.py): the screen state, when Crest last made progress,
    # and whether it is recovering. They live in ctx.params, so the engine itself is untouched; the base class's own
    # attributes (self.state, self.last_progress) simply write through to it.
    @property
    def state(self):
        return self.ctx.params.get("script_state", "unknown")

    @state.setter
    def state(self, value):
        self.ctx.params["script_state"] = value

    @property
    def last_progress(self):
        return self.ctx.params.get("last_progress", 0.0)

    @last_progress.setter
    def last_progress(self, value):
        self.ctx.params["last_progress"] = value

    def _recovering(self, what, fn, *a, **k):
        self.ctx.params["recovering"] = what
        try:
            return fn(*a, **k)
        finally:
            self.ctx.params.pop("recovering", None)

    def restart_game(self, scheduled: bool = False) -> None:
        return self._recovering("restarting the game", super().restart_game, scheduled)

    def recover_crash(self) -> None:
        return self._recovering("relaunching the game", super().recover_crash)

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

    # A crest that was already waiting in the game when Crest started (it dropped before the script began) shows up on the
    # Equip Crest screen with no Redeploy bar, so the original scraps it with OK. If that OK does nothing, the original
    # judges the same crest again and again, for ever. This watches for that: a few tries the original way, then a
    # looser look for the OK button, then a stop that says what happened and keeps a picture of the screen.
    STUCK_RELAXED_TRY = 3
    STUCK_STOP_TRY = 5
    STUCK_RESET_S = 45

    def confirm_word(self, screen):
        """Where a 'Confirm' button is, read from the screen text (the game shows it in place of OK when the crest was
        already waiting before Crest started). (x, y) of the word, or None. Looked for only in the bottom third."""
        if self.ocr is None:
            return None
        words = self.ocr.screen_words(screen, min_conf=35)
        h = screen.shape[0]
        best = None
        for w in words:
            cy = w.y + w.h // 2
            if cy < h * 0.62 or w.h > 120:
                continue
            if textnav.word_score("confirm", w.text) >= 0.8 and (best is None or cy > best[1]):
                best = (w.x + w.w // 2, cy)
        return best

    def tap_confirm(self, screen) -> bool:
        """Tap the Confirm button, then the scrap confirmation that follows it. True when a Confirm was found."""
        spot = self.confirm_word(screen)
        if spot is None:
            return False
        self.log(f"Confirm button found - tapping it at {spot}")
        self.tap(spot[0], spot[1], settle=1.5)
        ok2 = self.wait_for(["select_crest_ok2"], 6)
        if ok2:
            self.tap_match(ok2, settle=1.5)
        return True

    def scrap(self, screen) -> None:
        # With neither a Redeploy bar nor the usual OK, the screen is the other kind: a 'Confirm' button.
        if not self.find("redeploy_button", screen) and not self.find("select_crest_ok", screen) and self.tap_confirm(screen):
            if self.target_reached():
                self.finish()
            return None
        now = time.monotonic()
        if now - getattr(self, "_scrap_last", 0.0) > self.STUCK_RESET_S:
            self._scrap_tries = 0
        self._scrap_last = now
        self._scrap_tries = getattr(self, "_scrap_tries", 0) + 1
        tries = self._scrap_tries
        if tries < self.STUCK_RELAXED_TRY:
            return super().scrap(screen)
        if tries == self.STUCK_RELAXED_TRY:
            self._stuck_frame = self.save_frame("equip_crest_stuck", screen)
        saved = getattr(self, "_stuck_frame", None)
        if tries >= self.STUCK_STOP_TRY:
            self.notify("Crest: stuck on the Equip Crest screen. The same crest was seen again and again and OK did not scrap it. "
                        "Stopped so it does not repeat for ever. Scrap or keep it yourself, then press Start."
                        + (f" A picture of the screen was saved to {saved}." if saved else " See the newest picture in the debug folder."))
            raise Finished("stuck on the Equip Crest screen")
        self.log(f"Equip Crest screen did not clear after {tries - 1} tries - looking for OK more loosely"
                 + (f" (screen saved to {saved})" if saved else ""))
        m = self.find("select_crest_ok", screen, threshold=0.5)
        if not m:
            self.log("No OK button found even loosely")
            self.tap_confirm(screen)
            return None
        self.log(f"OK found (match {getattr(m, 'score', 0):.2f}) - tapping it")
        self.tap_match(m, settle=1.5)
        ok2 = self.wait_for(["select_crest_ok2"], 8)
        if ok2:
            self.tap_match(ok2, settle=1.5)
        return None

    def handle_quest_list(self, screen):
        """A palace has several quests (Subject in Trance [PRO], [ADV], [INT]...). The original needs a picture of one quest
        row, which only fits one palace, or a quest name. With neither, and more than one quest on the list, it stopped
        with "quest row not recognised". LITE runs the daily palace selector, so a different palace comes up each day:
        when no picture and no name applies, take the TOP quest (the hardest, listed first). A name in 'Quest to farm'
        or a captured row picture still wins."""
        qn = str(self.cfg.get("quest_name") or "").strip()
        if not qn and not any(self.has_template(n) and self.find(n, screen) for n in self.QUEST_ROW_NAMES):
            words = self.ocr.screen_words(screen, min_conf=40) if self.ocr is not None else []
            rows = textnav.quest_rows(words) if words else []
            if len(rows) >= 2:
                if self.target_reached():
                    self.finish()
                self.quest_row_misses = 0
                self.log(f"Quest list - opening the top quest ('{rows[0]['title']}'); set 'Quest to farm' in the Crest settings to pick another")
                self.tap(300, rows[0]["y"], settle=2)
                self.reset_party("new quest entry")
                return
        return super().handle_quest_list(screen)

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
