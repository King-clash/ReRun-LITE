"""Crest with the daily palace selector.

`LiteCrest` is the original CrestScript. The only thing it changes is HOW the palace tile is found on the Crest
Palace screen, and only while the selector is on (Settings > Palace Selector):

  selector on   today's palace comes from palaces.choose() (the weekday table or the cycle, on the game clock).
                palace_find.py looks for it (its picture, then its name read from the screen, a fresh look, then down the
                list); in the hours the game's schedule screen and the game day disagree the schedule day's palace is a second
                choice, and the user's backup palaces (off by default) come last. Found: that tile is tapped. Not found, or
                nothing is chosen for today: Crest STOPS and says which palace and which file, and keeps a picture of the
                screen. It never opens a palace that is not today's, the second choice or a backup the user turned on.
  selector off  the original code runs untouched.

Everything else (walking Home > Exploring > Crest Palace, the quest, the loop, scrapping, alerts) is the original.
"""
from __future__ import annotations

import time

from rerun import textnav
from rerun.scripts import SCRIPTS, CrestScript
from rerun.scripts.base import Finished

from . import palaces
from .palace_find import (  # noqa: F401 - re-exported: tests and tools import these from here
    MATCH_MIN, SCALES, PalaceFindMixin, find_tile, find_tile_exact, scan_palace_screen, times_playable,
    unknown_banners,
)


class LiteCrest(PalaceFindMixin, CrestScript):
    PALACE_ROOT = None        # set by LiteManager: the app folder (palaces.yaml, images/, data/lite/)

    def _selector_root(self):
        return self.PALACE_ROOT or self.ctx.vision.store.folder.parent

    def selector_choice(self) -> palaces.Choice:
        return palaces.choose(self._selector_root(), self.CLOCK_NOW() if self.CLOCK_NOW else None)

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
        self._tile_taps = 0                                      # the palace opened: the tap count starts again
        self._check_plays_left(screen)
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
        if not choice.ok and choice.palace is None:
            self._stop_for(choice)                               # nothing is chosen for today: never guess
        if choice.palace is not None and choice.path is None and getattr(self, "ocr", None) is None:
            self._stop_for(choice)                               # no picture and no way to read the name
        candidates = [choice]
        alt = palaces.alt_choice(self._selector_root(), self.CLOCK_NOW() if self.CLOCK_NOW else None)
        if alt is not None and alt.palace is not None and alt.palace.name != choice.palace.name:
            candidates.append(alt)
        backups = palaces.backup_choices(self._selector_root(), {c.palace.name for c in candidates})
        candidates.extend(backups)                               # only when the user turned the backup on
        taps = getattr(self, "_tile_taps", 0)
        if taps >= self.TILE_TAP_LIMIT:
            kept = self._keep_frame("palace_tile_stuck", screen)
            self.notify(f"Crest: tapped the {choice.palace.name} tile {taps} times but the game never left the "
                        "Crest Palace screen (a popup over it, or the tile is not tappable). Stopped so it does not repeat for ever."
                        + kept)
            raise Finished("palace tile does not open")
        found = self._find_on_list(screen, candidates)
        if found is None:
            more = [c.palace.name for c in candidates[1:]]
            tried = f" (also tried {', '.join(more)})" if more else ""
            kept = self._keep_frame("palace_not_found", screen)
            self.notify(f"Crest: today ({choice.day}) is {choice.palace.name} ({choice.palace.image}), but that palace is not on the "
                        f"Crest Palace screen (looked at the picture and the name, and scrolled the list){tried}. "
                        "Stopped - no other palace was run." + kept)
            raise Finished(f"{choice.palace.name} not on the Crest Palace screen")
        x, y, how, used = found
        if used is choice:
            note = ""
        elif used.day == "backup":
            note = f" [BACKUP palace, because {choice.palace.name} was not on the Crest Palace screen]"
            self.notify(f"Crest: {choice.palace.name} (today's palace) is not on the Crest Palace screen, so the backup palace "
                        f"{used.palace.name} is being run instead, as you set up.", screenshot=False, ping=False)
        else:
            note = f" [the schedule screen's next day, not {choice.palace.name}]"
        self.log(f"Palace selector: {used.day} = {used.palace.name} ({how}){note}")
        self.palace = f"selector:{used.palace.name}"
        self._tile_taps = taps + 1
        self.tap(x, y, settle=3)


def install() -> None:
    """Make 'crest' in the script table the selector-aware Crest. Idempotent."""
    SCRIPTS["crest"] = LiteCrest
