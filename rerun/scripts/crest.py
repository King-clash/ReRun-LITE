"""Crest Palace farming with crest detection.

At the end of each Auto-Loop batch the game shows the Equip Crest screen:
your equipped crests sit in rows with blue checkboxes, and the new crest is
the row highlighted orange. The script ticks the existing rows (keeps them),
identifies the new crest's rarity from its icon, and then either

  * keeps it (wanted rarity): leaves the screen untouched, pings you on
    Discord with a screenshot, and stops, or
  * scraps it (everything else): Redeploy, which turns the unticked crest
    into fragments and starts the next loop with the same party.

A Crest Burst (5+) has its own full-screen overlay and always stops.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
import numpy as np

from .. import qol, textnav
from .base import BASE_H, BASE_W, Finished, Setting, T, game_weekday
from .loop_farm import LOOP_SETTINGS, LOOP_TEMPLATES, LoopFarmScript

RARITY_ORDER = ["lv3", "lv3+", "lv4", "4+"]
ICON_TEMPLATES = {
    "lv3": "crest_icon_lv3",
    "lv3+": "crest_icon_lv3plus",
    "lv4": "crest_icon_lv4",
    "4+": "crest_icon_lv4plus",
}
KEEP_CHOICES = {
    "4+ and Burst only": "4+",
    "Lv4 and better": "lv4",
    "Lv3+ and better": "lv3+",
}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_LV = re.compile(r"L\s*[vV]\s*\.?\s*([345])\s*(\+?)")


def text_rarity(text: str) -> str | None:
    """'Dark Resistance Lv3' -> 'lv3', 'Lv3+' -> 'lv3+', 'Lv4' -> 'lv4', 'Lv4+' -> '4+'."""
    m = _LV.search(text or "")
    if not m:
        return None
    level, plus = m.group(1), m.group(2)
    if level == "3":
        return "lv3+" if plus else "lv3"
    if level == "4":
        return "4+" if plus else "lv4"
    return None  # Lv5 rows don't appear here (Crest Burst has its own screen)


class CrestScript(LoopFarmScript):
    ID = "crest"
    NAME = "Crest"
    DESCRIPTION = "Farms a Crest Palace on Auto-Loop, scraps unwanted crests and stops on rare ones."
    INSTRUCTIONS = """CREST FARMING
Repeats a Crest Palace quest on Auto-Loop and handles the Equip Crest screen
after every batch.

SETUP
1. Have the game open on ANY screen (not mid-way through an Equip Crest decision).
2. In Settings choose the run count, party, and which crests to keep.
3. Press Start. Rerun first gets the game to the Home screen (dismissing popups and
   pressing Back), then walks Exploring > Crest Palace > today's palace > quest.
   Needs the templates exploring_button, crest_palace_icon and quest_list, plus ONE of:
   a palace tile picture (crest_palace_<day> or crest_palace_target) or the Crest setting
   'Palace to farm' (a distinctive part of its name, read with the text reader). The quest is
   opened by its row picture (quest_list_entry, _2/_3/_4), else by 'Quest to farm', else - when
   the palace has exactly one quest - that quest. Settings > Setup check shows what is missing.
   Useful extras: 'Palaces per weekday', 'Stop after N minutes / at HH:MM', 'Keep at least N energy',
   'Max game restarts per day', and what to do if Home can't be reached (Settings tab).
   Turn off "Always start from the Home screen" to start from wherever the game is.

CREST HANDLING
- Your equipped crests (blue boxes) are ticked so they are kept.
- The new crest (orange row) is identified by its rarity icon.
- Wanted rarity: the screen is left as is, you get a Discord ping with a
  screenshot, and the script stops so you can decide.
- Anything else is scrapped into fragments with Redeploy, and the next
  loop starts straight away.
- A Crest Burst (5+) always stops the script and pings you.
- An icon that can't be identified stops the script (safe default).

24/7 MODE
- Relaunches the game after a crash and logs back in at the 6 AM (UTC-6) reset.
- From Home it walks to Exploring > Crest Palace and opens the palace you
  captured (crest_palace_<day> for a weekday, else crest_palace_target).
"""
    SETTINGS = [
        *LOOP_SETTINGS,
        Setting("keep", "Crests to keep (stop + notify)", "choice", "4+ and Burst only",
                list(KEEP_CHOICES)),
        Setting("stop_on_unknown", "Stop if a crest can't be identified", "bool", True),
        Setting("verify_text", "Double-check the crest's level by reading its title", "bool", True,
                help="Reads 'Lv3', 'Lv4+'... from the crest's name. If it disagrees with the icon, "
                     "Rerun stops instead of scrapping. Needs the text reader (comes with ReStart)."),
        Setting("start_home", "Always start from the Home screen", "bool", True,
                help="On Start: reach the Home screen first (closing popups, pressing Back), then "
                     "walk Exploring > Crest Palace > the palace tile > quest. Off: start from "
                     "whatever screen the game is on."),
        Setting("home_fail", "If it can't reach the Home screen", "choice", "Stop and tell me",
                ["Stop and tell me", "Restart the game and try again", "Keep trying until I stop it"],
                help="What 'start from Home' does when Home can't be reached in about two minutes. "
                     "Restart: relaunches the game (up to 2 times, counted by 'Max game restarts per "
                     "day') and tries again. Keep trying: never gives up; you get one message."),
        Setting("allow_back", "Allow the Back key to get to Home", "bool", True,
                help="Off: only closing pop-ups and the on-screen Home button are used. Pressing Back "
                     "in the middle of a battle has not been tested on the real game."),
        Setting("palace_name", "Palaces to farm, in order of preference (optional)", "text", "",
                help="Fallback when no palace picture matches (palaces rotate). Distinctive parts of "
                     "names separated by commas, best first: 'Cursed Claw, Whirlwind'. Crest opens the "
                     "first one that is open today. Needs the text reader."),
        Setting("palace_by_day", "Palaces per weekday (optional)", "text", "",
                help="Overrides the list above on the days written here, e.g. "
                     "'Mon: Cursed Claw, Whirlwind; Sat/Sun: Heavenly Light'. Days not listed use "
                     "the list above. Weekday = the game's day (resets 6 AM UTC-6)."),
        Setting("quest_name", "Quest to farm (name, optional)", "text", "",
                help="Fallback when no quest row picture matches, e.g. 'Experimental Scars'. "
                     "Empty: if the palace has exactly one quest, that one is opened."),
        Setting("save_debug", "Save Equip Crest screenshots to debug_crest/", "bool", False),
    ]
    TEMPLATES = LOOP_TEMPLATES + [
        T("crest_icon_lv5plus", "'Crest Burst' title on the full-screen burst overlay (5+ crest)."),
        T("equip_crest_screen", "'Equip Crest' title at the top of the crest selection screen."),
        T("crest_checkbox", "An EMPTY blue checkbox on an equipped crest row (Equip Crest screen)."),
        T("crest_icon_lv3", "Rarity icon of a Lv3 crest, cropped from its row."),
        T("crest_icon_lv3plus", "Rarity icon of a Lv3+ crest."),
        T("crest_icon_lv4", "Rarity icon of a Lv4 crest."),
        T("crest_icon_lv4plus", "Rarity icon of a 4+ crest."),
        T("redeploy_button", "Green 'Redeploy' button on the Equip Crest screen."),
        T("select_crest_ok", "Orange OK at the bottom of the Equip Crest screen."),
        T("select_crest_ok2", "OK on the scrap confirmation that follows it."),
        T("crest_fragment", "'Crest Fragment' title of the fragments popup."),
        T("crest_fragment_ok", "OK on the Crest Fragment popup."),
        T("quest_list", "Header of a Crest Palace's quest list.", optional=True),
        T("quest_list_entry", "A quest row in that list to tap (e.g. the one you farm).", optional=True),
        T("quest_list_entry2", "Same, for a second palace whose quest looks different (optional).",
          optional=True),
        T("quest_list_entry3", "Same, for a third palace (optional).", optional=True),
        T("quest_list_entry4", "Same, for a fourth palace (optional).", optional=True),
        T("home_nav_button", "The 'Home' button in the bottom bar (shown on most screens but not on "
                             "Home itself); lets 'start from Home' tap it instead of pressing Back.",
          optional=True),
        T("exploring_button", "'Exploring' button on the Home screen (24/7 mode).", optional=True),
        T("crest_palace_icon", "Crest Palace entry on the Exploring screen (24/7 mode).", optional=True),
        T("crest_palace_icon2", "Same entry while a 'Campaign!' badge covers it.", optional=True),
        T("crest_palace_header", "Header of the Crest Palace screen (24/7 mode).", optional=True),
        T("crest_palace_target", "The palace tile to open from the Crest Palace screen (24/7 mode).",
          optional=True),
    ] + [T(f"crest_palace_{d}", f"Palace tile to open on {d.title()} (overrides crest_palace_target).",
           optional=True) for d in WEEKDAYS]

    STATES = [
        ("crest_burst", ["crest_icon_lv5plus"]),
        ("crest_fragment", ["crest_fragment"]),
        ("equip_crest_screen", ["equip_crest_screen"]),
        *LoopFarmScript.STATES[:-1],                      # loop flow, minus generic OK
        # After the loop states: the results bar's OK looks just like this one.
        ("select_crest_ok2", ["select_crest_ok2"]),
        ("crest_palace_screen", ["crest_palace_header"]),
        ("quest_list", ["quest_list"]),
        ("exploring_screen", ["crest_palace_icon", "crest_palace_icon2"]),
        ("home_screen", ["exploring_button"]),
        ("ok_button", ["ok_button"]),
    ]

    # Seen live: the 'Used L Potion' popup dimmed the Equip Crest screen to 65%
    # of its brightness and Crest judged the dimmed row (unidentifiable -> stop).
    # A dimmed Equip Crest screen means a popup is on top: handle that first.
    # A popup over Home dims the Exploring button; that is not the Home screen.
    LIT_STATES = LoopFarmScript.LIT_STATES | {"equip_crest_screen", "home_screen"}
    LIT_RATIO = {"equip_crest_screen": 0.8}

    # Equip Crest screen colour/size, for the 720x1280 frame. Calibrate with save_debug.
    ORANGE_HSV_LOWER = (5, 120, 150)
    ORANGE_HSV_UPPER = (25, 255, 255)
    MIN_BOX_AREA = 6000
    ICON_THRESHOLD = 0.80
    BURST_THRESHOLD = 0.75

    def on_start(self) -> None:
        super().on_start()
        self.keep_from = KEEP_CHOICES.get(self.cfg["keep"], "4+")
        self.crest_handled_at = 0.0
        self.session_kept = 0
        self.crest_session = f"{self.ctx.instance}-{int(time.time())}"
        self.palace = None  # set when 24/7 mode opens a palace tile
        self.nav_active = False
        self.log(f"Keeping crests: {self.cfg['keep']}")
        if self.cfg.get("start_home", True):
            self.go_home()
            self.nav_active = True  # walk Home > Exploring > Crest Palace > quest like 24/7 mode does

    # ------------------------------------------------------------ start from Home
    HOME_TIMEOUT_S = 120
    HOME_MAX_BACKS = 30
    HOME_NEEDS = ("exploring_button", "quest_list")
    # Screens where an undecided crest is on offer: never leave them with Back.
    PENDING_CREST = {"crest_burst", "equip_crest_screen"}

    def navigating(self) -> bool:
        return bool(self.cfg.get("mode_247")) or self.nav_active

    @staticmethod
    def tile_names_today() -> list[str]:
        return [f"crest_palace_{WEEKDAYS[game_weekday()]}", "crest_palace_target"]

    def palace_tile_names(self) -> list[str]:
        return self.tile_names_today()

    @classmethod
    def nav_missing(cls, has, palace_name: str = "", ocr_ok: bool = True) -> list[str]:
        """What the walk Home > Exploring > Crest Palace > palace > quest still needs.
        `has(name)` says whether a template is captured. A palace/quest NAME (read with the text
        reader) can stand in for the tile / row pictures."""
        missing = [n for n in cls.HOME_NEEDS if not has(n)]
        if not (has("crest_palace_icon") or has("crest_palace_icon2")):
            missing.append("crest_palace_icon")
        names = cls.tile_names_today()
        if not any(has(n) for n in names) and not (palace_name.strip() and ocr_ok):
            missing.append(f"crest_palace_target (or {names[0]}, or a 'Palace to farm' name"
                           + ("" if ocr_ok else " - needs the text reader") + ")")
        if not any(has(n) for n in cls.QUEST_ROW_NAMES) and not ocr_ok:
            missing.append("quest_list_entry (or install the text reader)")
        return missing

    def check_nav_templates(self) -> None:
        """Before touching the game: everything the walk to the quest needs is captured."""
        prefs = ";".join(str(self.cfg.get(k) or "") for k in ("palace_name", "palace_by_day")).strip(";")
        missing = self.nav_missing(self.has_template, prefs, self.ocr is not None)
        for problem in qol.table_problems(str(self.cfg.get("palace_by_day") or "")):
            self.log(f"Setting 'Palaces per weekday': {problem}")
        if missing:
            self.notify(f"{self.NAME}: can't start from the Home screen - missing template(s): "
                        f"{', '.join(missing)}. Capture them in the Templates tab, or turn off "
                        "'Always start from the Home screen'.", screenshot=False)
            raise Finished("Home navigation templates missing: " + ", ".join(missing))

    HOME_MAX_NAV_TAPS = 4   # Home-button taps per Start before falling back to the Back key

    def _tap_home_button(self, screen) -> bool:
        """Tap the bottom bar's Home button when it is visible and lit (not dimmed by a popup)."""
        if not self.has_template("home_nav_button"):
            return False
        m = self.find("home_nav_button", screen)
        if not m or self.dimmed(screen, m):
            return False
        self.tap_match(m, settle=1.5)
        return True

    HOME_FAIL_STOP, HOME_FAIL_RESTART, HOME_FAIL_KEEP = (
        "Stop and tell me", "Restart the game and try again", "Keep trying until I stop it")
    MAX_HOME_RESTARTS = 2
    HOME_MAX_WAITS = 8      # with the Back key turned off there is nothing to press: wait briefly

    def go_home(self) -> None:
        """Get the game to the Home screen from wherever it is (see _reach_home). If it can't, do
        what 'If it can't reach the Home screen' says: stop (default), restart the game and try
        again, or keep trying."""
        self.check_nav_templates()
        self.log("Getting to the Home screen first")
        if not self._game_running():
            self.recover_crash()  # relaunches in 24/7 mode, otherwise stops with a clear message
        action = str(self.cfg.get("home_fail") or self.HOME_FAIL_STOP)
        attempt = 0
        while True:
            if self._reach_home():
                return
            attempt += 1
            saved = self.save_frame("no_home")
            close = self.closest_screens(self.screen_img) if self.screen_img is not None else ""
            what = (f"{self.NAME}: couldn't reach the Home screen from where the game is."
                    + (f" Closest known screens: {close}." if close else "")
                    + (f" Frame saved to {saved}." if saved else ""))
            if action == self.HOME_FAIL_RESTART and attempt <= self.MAX_HOME_RESTARTS:
                self.notify(f"{what} Restarting the game and trying again ({attempt}/{self.MAX_HOME_RESTARTS}).",
                            ping=False)
                self.restart_game()
                self.sleep(15)          # the game needs a while to reach its title screen
                continue
            if action == self.HOME_FAIL_KEEP:
                if attempt == 1:
                    self.notify(f"{what} Still trying - stop the script when you want to give up.", ping=False)
                self.sleep(10)
                continue
            self.notify(what + " Stopped.")
            raise Finished("could not reach the Home screen")

    def _reach_home(self) -> bool:
        """One attempt (about two minutes): dismiss known popups with their handlers, tap the
        on-screen Home button, else press Back (unless turned off). True once on the Home screen.
        Home must be lit - a popup over it dims the Exploring button."""
        popups = {e[0] for e in self.COMMON_STATES} | {"ok_button", "crest_fragment", "select_crest_ok2"}
        allow_back = bool(self.cfg.get("allow_back", True))
        limit = self.HOME_MAX_BACKS if allow_back else self.HOME_MAX_WAITS
        end = time.monotonic() + self.HOME_TIMEOUT_S
        backs = home_taps = 0
        while time.monotonic() < end:
            screen = self.grab()
            state = self.detect_state(screen)
            self._watch_unknown(state, screen)
            if state == "home_screen":
                self.state = state
                self.log("On the Home screen")
                self.progress()
                return True
            if state in self.PENDING_CREST:
                self.notify(f"{self.NAME}: the game is on a crest screen ({state}). Not leaving it "
                            "with Back in case that loses the crest - decide it yourself, then Start "
                            "again.")
                raise Finished(f"crest decision pending at start ({state})")
            if state == "unknown" and self._text_safety_net(screen):
                self.sleep(self.TICK)
                continue
            if state in popups:
                self.log(f"Start: closing {state}")
                getattr(self, f"handle_{state}")(screen)
            elif home_taps < self.HOME_MAX_NAV_TAPS and self._tap_home_button(screen):
                home_taps += 1
                self.log(f"Start: on '{state}' - tapped the Home button ({home_taps})")
            else:
                backs += 1
                if backs > limit:
                    break
                if allow_back:
                    self.log(f"Start: on '{state}' - pressing Back ({backs})")
                    self.ctx.device.back()
                else:
                    self.log(f"Start: on '{state}' - the Back key is turned off, waiting ({backs})")
            self.sleep(1.2)
        return False

    def handle_solo_quest_button(self, screen):
        self.nav_active = False  # the walk is over once a quest page is reached
        super().handle_solo_quest_button(screen)

    def handle_battle_button(self, screen):
        self.nav_active = False
        super().handle_battle_button(screen)

    @classmethod
    def past_party_from_old(cls, party: str) -> bool:
        # 'Always re-select Past Party' is on by default for Crest farming, also
        # for configs saved with the old 'Current Party' choice.
        return True

    # ------------------------------------------------------------ crest ledger
    def same_crest_again(self, rarity: str, text: str | None) -> bool:
        """A new crest only appears after a run finishes. Seeing a crest of the
        same rarity (and the same title, when both were read) with no run in
        between means the Equip Crest screen came back after an interruption."""
        prev = getattr(self, "judged", None)
        if not prev or prev["rarity"] != rarity:
            return False
        return not text or not prev["title"] or text == prev["title"]

    def count_run(self) -> None:
        self.judged = None  # the next Equip Crest screen holds a new crest
        super().count_run()
        ledger = getattr(self.ctx, "crests", None)
        if ledger is not None:
            try:
                ledger.add_run(self.ctx.instance, self.session_tag(), self.ID)
            except Exception as e:  # noqa: BLE001 - statistics must never stop farming
                self.log(f"Could not record the run in crest statistics: {e}")

    def session_tag(self) -> str:
        if not getattr(self, "crest_session", None):
            self.crest_session = f"{self.ctx.instance}-{int(time.time())}"
        return self.crest_session

    def ledger_drop(self, rarity: str, action: str, confidence: str = "verified",
                    title: str | None = None) -> None:
        """Every crest seen goes to the append-only ledger (4+ / Burst / Lv4
        counted separately); notable ones keep a full screenshot."""
        ledger = getattr(self.ctx, "crests", None)
        if ledger is None:
            return
        try:
            ledger.add_drop(self.ctx.instance, self.session_tag(), rarity, action, self.ID,
                            image=self.screen_img, palace=getattr(self, "palace", None),
                            confidence=confidence, title=title)
        except Exception as e:  # noqa: BLE001 - statistics must never stop farming
            self.log(f"Could not record crest statistics: {e}")

    # ------------------------------------------------------------ detection
    def detect_state(self, screen: np.ndarray) -> str:
        # Burst overlay uses its own looser threshold (animated background).
        if self.find("crest_icon_lv5plus", screen, threshold=self.BURST_THRESHOLD):
            return "crest_burst"
        return super().detect_state(screen)

    def find_orange_box(self, screen: np.ndarray) -> tuple[int, int, int, int] | None:
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(self.ORANGE_HSV_LOWER), np.array(self.ORANGE_HSV_UPPER))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        scale = (screen.shape[1] * screen.shape[0]) / (BASE_W * BASE_H)
        rects = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w * h >= self.MIN_BOX_AREA * scale and w > 2 * h:
                rects.append((x, y, w, h))
        if not rects:
            return None
        # The OK button is orange too; it's the smaller one at the bottom.
        # The new crest row is the widest orange rectangle.
        return max(rects, key=lambda r: r[2])

    def find_blue_boxes(self, screen: np.ndarray, above_y: int) -> list[tuple[int, int]]:
        tmpl = self.ctx.vision.store.get("crest_checkbox")
        res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= self.ctx.vision.store.threshold("crest_checkbox"))
        th, tw = tmpl.shape[:2]
        points: list[tuple[int, int]] = []
        for x, y in sorted(zip(xs, ys), key=lambda p: -res[p[1], p[0]]):
            cx, cy = int(x + tw // 2), int(y + th // 2)
            if cy >= above_y:
                continue
            if all(abs(cy - py) > th // 2 for _, py in points):
                points.append((cx, cy))
        return sorted(points, key=lambda p: p[1])

    def identify_crest(self, screen: np.ndarray, box) -> tuple[str | None, dict]:
        x, y, w, h = box
        pad = h // 2
        crop = screen[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
        scores = {}
        for rarity, name in ICON_TEMPLATES.items():
            tmpl = self.ctx.vision.store.get(name)
            if crop.shape[0] < tmpl.shape[0] or crop.shape[1] < tmpl.shape[1]:
                scores[rarity] = 0.0
                continue
            _, best, _, _ = cv2.minMaxLoc(cv2.matchTemplate(crop, tmpl, cv2.TM_CCOEFF_NORMED))
            scores[rarity] = round(float(best), 3)
        rarity = max(scores, key=scores.get)
        if scores[rarity] < self.ICON_THRESHOLD:
            return None, scores
        # lv4 vs 4+ icons are close; only call it 4+ when it clearly wins.
        if rarity == "lv4" and scores["4+"] >= scores["lv4"] - 0.02:
            rarity = "4+"
        return rarity, scores

    # The crest's title ("Dark Resistance Lv3") sits on the row's first line,
    # right of the icon. Offsets are within the orange row (720x1280 frame).
    TITLE_BOX = (95, 22, 425, 46)  # x, y, w, h

    def read_crest_text(self, screen: np.ndarray, box) -> tuple[str | None, str]:
        """(rarity from the title text or None, the text read)."""
        x, y, _, _ = box
        tx, ty, tw, th = self.TITLE_BOX
        text = self.read_text(x + tx, y + ty, tw, th, screen=screen, min_conf=70) or ""
        return text_rarity(text), text

    @staticmethod
    def row_image(screen: np.ndarray, box) -> np.ndarray:
        """The new crest's row (with a little margin) for the History tab."""
        x, y, w, h = box
        m = h // 4
        return screen[max(0, y - m):y + h + m, max(0, x - m):x + w + m].copy()

    def wanted(self, rarity: str) -> bool:
        return RARITY_ORDER.index(rarity) >= RARITY_ORDER.index(self.keep_from)

    def save_debug(self, screen: np.ndarray, tag: str) -> None:
        if not self.cfg.get("save_debug"):
            return
        folder = Path(self.ctx.data_dir or ".") / "debug_crest"
        folder.mkdir(exist_ok=True)
        cv2.imwrite(str(folder / f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}.png"), screen)

    # ------------------------------------------------------------ handlers
    def handle_crest_burst(self, screen):
        self.count("burst")
        self.log("CREST BURST (5+) detected - stopping")
        self.save_debug(screen, "burst")
        self.record("crest", "Crest Burst (5+) - kept, script stopped", screen, rarity="5+",
                    action="kept")
        self.ledger_drop("burst", "kept")
        self.notify(f"Crest Burst (5+) found on {self.ctx.instance}! Script stopped - check your emulator.")
        raise Finished("crest burst")

    def handle_equip_crest_screen(self, screen):
        if time.monotonic() - self.crest_handled_at < 5:
            return  # we already acted; wait for the screen to change
        self.in_loop = False
        self.save_debug(screen, "equip")
        box = self.find_orange_box(screen)
        for attempt in range(2):
            if box:
                break
            self.log(f"New crest row not visible - scrolling down (attempt {attempt + 1})")
            h, w = screen.shape[:2]
            self.ctx.device.swipe(w // 2, int(h * 0.65), w // 2, int(h * 0.35), 400)
            self.sleep(1)
            screen = self.grab()
            box = self.find_orange_box(screen)
        if not box:
            self.log("Could not find the new crest row")
            self.save_debug(screen, "no_orange")
            if self.cfg.get("stop_on_unknown", True):
                self.notify("Crest: couldn't find the new crest on the Equip Crest screen. Stopped so nothing is scrapped by mistake.")
                raise Finished("new crest row not found")
            self.scrap(screen)
            return

        rarity, scores = self.identify_crest(screen, box)
        self.log(f"Crest icon scores: {scores}")
        row = self.row_image(screen, box)
        text, confidence = None, "verified"
        if self.cfg.get("verify_text", True) and self.ocr is not None:
            said, text = self.read_crest_text(screen, box)
            self.log(f"Crest title reads: '{text}' -> {said or 'no level found'}")
            if rarity is None and said:
                self.log(f"Icon unclear - using the title's level ({said})")
                rarity = said
            elif rarity and said and said != rarity:
                # Two independent readings disagree: never scrap on a guess.
                self.count("mismatch")
                self.record("crest", f"Icon says {rarity}, title says {said} ('{text}') - "
                            "left on screen", row, rarity="?", action="stopped")
                self.ledger_drop("?", "stopped", "uncertain", title=text)
                self.notify(f"Crest: the icon looks like {rarity} but the title reads '{text}' "
                            f"({said}). Left it on screen and stopped so nothing is scrapped by mistake.")
                raise Finished("crest icon/title disagree")
        if rarity is None:
            self.count("unknown")
            if self.cfg.get("stop_on_unknown", True):
                self.record("crest", f"Unidentified crest - left on screen (scores {scores})", row,
                            rarity="?", action="stopped")
                self.ledger_drop("?", "stopped", "uncertain", title=text)
                self.notify(f"Crest: found a crest I couldn't identify (scores {scores}). Left it on screen and stopped.")
                raise Finished("unknown crest")
            rarity, confidence = "lv3", "assumed"
        # Seen live: Redeploy -> out of energy -> potion -> back on this same
        # Equip Crest screen, and the crest was judged and counted a second time.
        dup = self.same_crest_again(rarity, text)
        if dup:
            self.log(f"Same {rarity} crest as before (no run finished since) - not counted again")
        else:
            self.count(f"crest_{rarity}")
        self.progress()

        if self.wanted(rarity):
            self.session_kept += 1
            self.count("kept")
            self.log(f"{rarity} CREST - keeping it and stopping")
            self.record("crest", f"{rarity} crest - kept, script stopped", row, rarity=rarity,
                        action="kept")
            self.ledger_drop(rarity, "kept", confidence, title=text)
            self.notify(f"{rarity} crest found on {self.ctx.instance}! Left on the Equip Crest screen for you.")
            raise Finished(f"{rarity} crest")

        if not dup:
            self.record("crest", f"{rarity} crest - scrapped into fragments", row, rarity=rarity,
                        action="scrapped")
            self.ledger_drop(rarity, "scrapped", confidence, title=text)
            self.count("scrapped")
            self.judged = {"rarity": rarity, "title": text or ""}
        self.log(f"Crest identified as {rarity} - scrapping")
        # Tick the equipped crests so only the new one is converted.
        for (cx, cy) in self.find_blue_boxes(screen, box[1]):
            self.log(f"Ticking equipped crest at ({cx}, {cy})")
            self.tap(cx, cy, settle=0.4)
        self.crest_handled_at = time.monotonic()
        self.scrap(self.grab())

    def scrap(self, screen) -> None:
        """Redeploy (scrap + next loop) when runs remain; otherwise OK + confirm."""
        if not self.target_reached():
            m = self.find("redeploy_button", screen)
            v = self.ctx.vision
            if m and v.brightness(screen, m) >= 0.75 * v.template_brightness("redeploy_button"):
                self.energy_gate(screen)
                self.log("Redeploying")
                self.tap_match(m, settle=2.5)
                return
            self.log("Redeploy missing or greyed out - scrapping with OK")
        if self.tap_template("select_crest_ok", screen, settle=1.5):
            ok2 = self.wait_for(["select_crest_ok2"], 6)
            if ok2:
                self.tap_match(ok2, settle=1.5)
        if self.target_reached():
            self.finish()

    def handle_select_crest_ok2(self, screen):
        if self.find("results_redeploy", screen) or self.find("looping_button", screen):
            return  # that's the results bar's OK, not a scrap confirmation
        self.tap_template("select_crest_ok2", screen, settle=1.5)

    def handle_crest_fragment(self, screen):
        self.log("Crest Fragment popup - OK")
        self.tap_template("crest_fragment_ok", screen, settle=1.0)

    QUEST_ROW_NAMES = ("quest_list_entry", "quest_list_entry2", "quest_list_entry3", "quest_list_entry4")
    QUEST_ROW_MISS_LIMIT = 5

    def handle_quest_list(self, screen):
        if self.target_reached():
            self.finish()
        for name in self.QUEST_ROW_NAMES:
            if self.has_template(name) and self.tap_template(name, screen, settle=2):
                self.quest_row_misses = 0
                self.log(f"Quest list - opening the quest ({name})")
                self.reset_party("new quest entry")
                return
        # No picture matched: read the list. A quest NAME wins; otherwise a list with exactly one
        # quest is unambiguous.
        words = self.ocr.screen_words(screen, min_conf=40) if self.ocr is not None else []
        qn = str(self.cfg.get("quest_name") or "").strip()
        target, why = None, ""
        if words and qn:
            hit = textnav.find_name(words, qn, (560, 1100))
            if hit:
                target, why = (300, hit.y), f"by name '{qn}'"
        elif words:
            rows = textnav.quest_rows(words)
            if len(rows) == 1:
                target, why = (300, rows[0]["y"]), f"the only quest on the list ('{rows[0]['title']}')"
        if target:
            self.quest_row_misses = 0
            self.log(f"Quest list - opening the quest {why}")
            self.tap(*target, settle=2)
            self.reset_party("new quest entry")
            return
        self.quest_row_misses = getattr(self, "quest_row_misses", 0) + 1
        self.log("Quest list - no quest row picture or name matches this list "
                 f"({self.quest_row_misses}/{self.QUEST_ROW_MISS_LIMIT})")
        if self.quest_row_misses >= self.QUEST_ROW_MISS_LIMIT:
            saved = self.save_frame("quest_row_missing", screen)
            titles = "; ".join(r["title"] for r in textnav.quest_rows(words)) if words else ""
            self.notify(f"{self.NAME}: reached the quest list but couldn't tell which quest to farm "
                        "(each palace's quest looks different, so a quest_list_entry picture from "
                        "another palace never matches). "
                        + (f"I can see: {titles}. " if titles else "")
                        + "Set 'Quest to farm' in the Crest settings, or capture the quest's title row "
                        "as quest_list_entry (quest_list_entry2/3/4 for other palaces). Stopped."
                        + (f" Frame saved to {saved}." if saved else ""))
            raise Finished("quest row not recognised")

    def handle_home_screen(self, screen):
        if not self.navigating():
            return
        self.log("Home screen - entering Exploring")
        self.tap_template("exploring_button", screen, settle=3)

    def handle_exploring_screen(self, screen):
        if not self.navigating():
            return
        self.log("Exploring - entering Crest Palace")
        self.tap_template("crest_palace_icon", screen, settle=3) or \
            self.tap_template("crest_palace_icon2", screen, settle=3)

    def handle_crest_palace_screen(self, screen):
        if not self.navigating():
            return
        for name in self.palace_tile_names():
            if self.tap_template(name, screen, settle=3):
                self.log(f"Opened palace ({name})")
                self.palace = name
                return
        names = qol.names_for_day(game_weekday(), str(self.cfg.get("palace_by_day") or ""),
                                  str(self.cfg.get("palace_name") or ""))
        words = self.ocr.screen_words(screen, min_conf=40) if self.ocr is not None else []
        shown = textnav.sample_text(words, 300, 1000)
        if names and words:
            for rank, name in enumerate(names, 1):
                hit = textnav.find_name(words, name, (300, 1000))
                if hit:
                    self.log(f"Opened palace by name '{name}' (choice {rank} of {len(names)}; "
                             f"read: {', '.join(hit.matched)})")
                    self.palace = f"name:{name}"
                    self.tap(hit.x, hit.y, settle=3)
                    return
            self.notify("Crest: none of your palaces is on the Crest Palace screen today ("
                        + ", ".join(names) + "; palaces rotate), or two palaces look alike. "
                        + (f"I can read: {shown}. " if shown else "")
                        + "Change 'Palaces to farm' or capture a tile. Stopped.")
            raise Finished("palace not on the list")
        self.notify("Crest: on the Crest Palace screen but no palace tile picture matched today and no "
                    "'Palaces to farm' name is set. " + (f"I can read: {shown}. " if shown else "")
                    + "Capture crest_palace_target or set the names. Stopped.")
        raise Finished("palace not found")
