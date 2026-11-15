"""Compendium Counter / unit scan - ReStart's compendium scan.

On the Units list grid Rerun opens each card, reads the unit's page (name,
element, race, quest clears - see rerun/unit_screens.py), goes back, and
scrolls on until the end of the list. Results go to the Unit Roster
(units/roster.json + a scan record) and compendium_report.csv. Stopping early
still saves what was read."""
from __future__ import annotations

import csv
import time
from pathlib import Path

import cv2
import numpy as np

from ..engine import StopRoutine
from .base import BaseScript, Done, Finished, Setting, T


class CompendiumCounterScript(BaseScript):
    ID = "compendium_counter"
    NAME = "Compendium Counter"
    BETA = True
    DESCRIPTION = "Scans the Units compendium and reports each unit's quest clear count."
    INSTRUCTIONS = """COMPENDIUM COUNTER / UNIT SCAN (BETA - uses text reading)
Opens every unit in your Units list, reads its name, element, race and quest
clear count, and saves them to the Units tab (and compendium_report.csv).
It only taps unit cards and Back - nothing is upgraded or spent.

SETUP
1. Stop any farming on this instance.
2. Open Units in-game (the grid of your unit cards) and scroll to the top.
3. Press Start. Stopping early keeps everything read so far.

Names the reader isn't sure about are marked uncertain (frame saved to
debug/); fix them in the Units tab and Rerun remembers the correction.
"""
    SETTINGS = [Setting("max_units", "Stop after this many units (0 = all)", "int", 0)]
    TEMPLATES = [
        T("compendium_grid_header", "'Units' title of the compendium grid."),
        T("compendium_card_lv", "The 'Lv' corner of a unit card on the grid."),
        T("compendium_card_lv_rainbow", "The rainbow 'Lv' corner (higher rarity).", optional=True),
        T("compendium_detail_marker", "The 'Achievements' tab of a unit's page."),
    ]
    STATES = [
        ("detail", ["compendium_detail_marker"]),
        ("grid", ["compendium_grid_header"]),
    ]
    MAX_SCROLLS = 80
    VIEW_CHANGED = 6.0   # mean grey difference (0-255) of the grid thumbnail = a different view
    MAX_DUPES = 6        # already-read units in a row before forcing a scroll
    SETTLED_DIFF = 3.0   # mean pixel change between two frames 0.6 s apart = page still moving

    def on_start(self) -> None:
        if self.ocr is None:
            self.notify("Compendium Counter needs the text reader (it comes with ReStart). Stopped.")
            raise Done("no text reader")
        self.rows: dict[str, int] = {}
        self.seen: set[str] = set()
        self.observed: list[dict] = []   # roster observations (rerun/units.py)
        self.done_cards: set[tuple[int, int]] = set()  # card spots already opened on this view
        self.opened: tuple[int, int] | None = None
        self.scrolls = 0
        self.limit = int(self.cfg.get("max_units") or 0)
        self.view_sig = None
        self._saved = False
        self.force_scroll = False
        self.dupe_streak = 0
        self.skipped = 0

    def run(self) -> None:
        try:
            super().run()
        except StopRoutine:
            # Stopped (by you or a watchdog): keep what was read, then stop as asked.
            if getattr(self, "observed", None) and not self._saved:
                self.save_roster()
            raise

    def save_roster(self, complete: bool = False) -> str:
        self._saved = True
        roster = getattr(self.ctx, "units", None)
        if roster is None or not self.observed:
            return ""
        s = roster.apply_scan(self.observed, "units_list", complete=complete)
        return (f" Roster: {s['seen']} read, {len(s['new'])} new"
                + (f", {len(s['uncertain'])} uncertain" if s["uncertain"] else "") + ".")

    def report(self, why: str, complete: bool = False) -> None:
        why = f"{why}{self.save_roster(complete)}"
        if self.skipped:
            why += f" {self.skipped} unreadable page(s) skipped (frames in debug/)."
        path = Path(self.ctx.data_dir or ".") / "compendium_report.csv"
        if self.rows:
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["unit", "quest clears"])
                for name, n in sorted(self.rows.items(), key=lambda r: -r[1]):
                    w.writerow([name, n])
            msg = f"Compendium Counter: {len(self.rows)} unit(s) counted - saved to {path.name}. {why}"
        else:
            msg = f"Compendium Counter: nothing found - keeping the previous report. {why}"
        self.record("compendium", msg)
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)

    # Seen live: units without achievements (Rekyuon) show the Achievements button
    # GREY. The colour match drops to 0.71, so the page went unrecognised and the
    # scan stopped. Its shape still matches in greyscale (0.85; other screens <= 0.38).
    DETAIL_GREY_MIN = 0.78
    DETAIL_REGION = (230, 1140, 720, 1280)  # x0, y0, x1, y1 around the button

    def detect_state(self, screen):
        state = super().detect_state(screen)
        if state == "unknown" and self.has_template("compendium_detail_marker"):
            x0, y0, x1, y1 = self.DETAIL_REGION
            h, w = screen.shape[:2]
            if (w, h) == (720, 1280):
                region = cv2.cvtColor(screen[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
                t = cv2.cvtColor(self.ctx.vision.store.get("compendium_detail_marker"), cv2.COLOR_BGR2GRAY)
                if region.shape[0] >= t.shape[0] and region.shape[1] >= t.shape[1]:
                    best = cv2.minMaxLoc(cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED))[1]
                    if best >= self.DETAIL_GREY_MIN:
                        return "detail"
        return state

    # ---------------------------------------------------------------- grid
    def cards(self, screen) -> list[tuple[int, int]]:
        # Fixed 5-column grid, every cell checked (badge matching alone missed
        # ~25% of cards on real captures). See rerun/unit_screens.py.
        from ..unit_screens import grid_cards
        return grid_cards(screen, self.ctx.vision)

    def handle_grid(self, screen):
        if self.limit and len(self.rows) >= self.limit:
            self.report("Unit limit reached.")
        # Same view or a new one? Seen live: the Units screen is animated, so an
        # exact pixel signature never matched and card 1 was reopened forever.
        # Compare small thumbnails with a tolerance instead (same view: ~0.03,
        # one scroll: far above VIEW_CHANGED).
        thumb = cv2.resize(cv2.cvtColor(screen[300:1100], cv2.COLOR_BGR2GRAY), (72, 80),
                           interpolation=cv2.INTER_AREA).astype(np.int16)
        if self.view_sig is None or np.abs(thumb - self.view_sig).mean() > self.VIEW_CHANGED:
            self.view_sig, self.done_cards = thumb, set()
        todo = [] if self.force_scroll else \
            [c for c in self.cards(screen) if c not in self.done_cards]
        if todo:
            self.opened = todo[0]
            self.done_cards.add(todo[0])
            self.tap(*todo[0], settle=1.5)
            return
        # every card on this view done: scroll; if nothing moves, the list has ended
        self.scrolls += 1
        if self.scrolls > self.MAX_SCROLLS:
            self.report("Scroll limit reached.")
        before = screen
        self.ctx.device.swipe(360, 1000, 360, 560, 600)
        self.sleep(1.2)
        after = self.grab()
        if np.abs(after[300:1100].astype(int) - before[300:1100].astype(int)).mean() < 2:
            self.report("Reached the end of the list.", complete=True)
        self.force_scroll = False
        self.view_sig, self.done_cards = None, set()  # new view: every card is new
        self.log("Scrolled")

    # ---------------------------------------------------------------- unit page
    def handle_detail(self, screen):
        from ..unit_screens import read_profile
        # Seen live: a page was read while still fading in (background showing through).
        # Only read once two frames a moment apart agree.
        self.sleep(0.6)
        again = self.grab()
        if np.abs(again.astype(np.int16) - screen.astype(np.int16)).mean() > self.SETTLED_DIFF:
            self.log("Unit page still appearing - waiting")
            return
        screen = again
        ob = read_profile(self.ocr, screen)
        if ob["fields"]["element"]["value"] is None and ob["name_votes"] < 2:
            # No element icon and no agreed name: not a readable unit page (seen live: a
            # nameless unicorn page). Never invent a unit from it; keep the frame to review.
            shot = self.save_frame(f"unit_unreadable_{len(self.seen) + 1}", screen)
            self.log(f"Unit page without a readable name or element - skipped (frame {shot})")
            self.skipped += 1
            self.ctx.device.back()
            self.sleep(1.2)
            return
        roster = getattr(self.ctx, "units", None)
        name = ob["name"]
        if roster is not None and name:
            name = roster.resolve_name(name, ob["name_conf"])[0]
        count = ob["fields"]["quest_clears"]["value"]
        if not name:
            self.log("Couldn't read the unit's name - skipped.")
        elif name in self.rows or name in self.seen:
            self.log(f"{name} already read (seen again after scrolling)")
            self.dupe_streak += 1
            if self.dupe_streak >= self.MAX_DUPES:
                # Backstop: units keep coming back already read - move the list on.
                self.log(f"{self.dupe_streak} already-read units in a row - scrolling on")
                self.force_scroll, self.dupe_streak = True, 0
        else:
            self.dupe_streak = 0
            self.seen.add(name)
            el = ob["fields"]["element"]["value"] or "?"
            unsure = " (name uncertain)" if ob["name_votes"] < 2 else ""
            if count is None:
                self.log(f"{name} [{el}]{unsure}: no quest count on the page")
            else:
                self.rows[name] = count
                self.log(f"{name} [{el}]{unsure}: {count} clears")
            if ob["name_votes"] < 2:
                ob["shot"] = self.save_frame(f"unit_uncertain_{len(self.seen)}", screen)
            self.observed.append(ob)
            self.count("units")
            self.progress()
        self.ctx.device.back()
        self.sleep(1.2)

    def handle_unknown(self, screen):
        # A card that opened neither its page nor stayed on the grid.
        if self.opened and self._unknown_since and time.monotonic() - self._unknown_since > 15:
            self.notify("Compendium Counter: a card opened neither its page nor the grid - stopped.")
            raise Finished("unexpected screen")


__all__ = ["CompendiumCounterScript"]
