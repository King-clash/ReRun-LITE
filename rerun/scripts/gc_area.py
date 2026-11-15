"""GC Area - farm one Grand Crusade area of your choice (ReStart's GC Area Farm).

Grand Crusade's normal flow moves on to the next area when one is cleared.
Here, instead, Rerun opens the map menu > Areas, reads the "Area NNN" labels
with OCR (paging through the list) and heads back to your area each time."""
from __future__ import annotations

import re
import time

from .base import Done, Setting, T
from .grand_crusade import GrandCrusadeScript

_AREA_NUM = re.compile(r"^(\d{1,4})$")


class GcAreaScript(GrandCrusadeScript):
    ID = "gc_area"
    NAME = "GC Area"
    BETA = True
    DESCRIPTION = "Farms one Grand Crusade area of your choice for a set number of runs."
    INSTRUCTIONS = """GC AREA (BETA - not yet run on your game; uses text reading)
Farms one Grand Crusade area over and over. After each clear Rerun opens the
map menu > Areas, finds 'Area <your number>' by reading the labels, and heads
back there instead of moving on.

SETUP
1. Open Grand Crusade on any area's map.
2. In Settings set the area number and the number of runs.
3. Press Start.

Yuna Chance, Load Team, stamina handling and 24/7 mode work as in Grand Crusade.
If the destination grid asks you to pick a tile, Rerun pings you and waits.
"""
    SETTINGS = [
        Setting("area", "Area number to farm", "int", 1),
        *GrandCrusadeScript.SETTINGS,
    ]
    TEMPLATES = GrandCrusadeScript.TEMPLATES + [
        T("gc_map_menu_button", "'MENU' button on the Grand Crusade map."),
        T("gc_menu_areas_button", "'Areas' entry in the map menu."),
        T("gc_area_list_button", "'Area List' button.", optional=True),
        T("gc_area_list_end_arrow", "'>>' next-page arrow of the area list."),
        T("gc_area_page_first", "'<<' first-page arrow of the area list.", optional=True),
        T("gc_destination_prompt", "'Tap to set destination' prompt.", optional=True),
    ]
    STATES = [
        ("destination", ["gc_destination_prompt"]),
        *[s for s in GrandCrusadeScript.STATES if s[0] != "next_area"],
        ("next_area", ["gc_next_area_btn"]),
        ("area_list", ["gc_area_list_end_arrow", "gc_area_page_first"]),
        ("map_menu", ["gc_menu_areas_button"]),
    ]
    WAITING_STATES = GrandCrusadeScript.WAITING_STATES | {"destination"}
    MAX_PAGES = 12

    def on_start(self) -> None:
        super().on_start()
        self.area = int(self.cfg.get("area") or 1)
        self.need_travel = True   # go to the chosen area first
        self.pages_seen = 0
        self.dest_since: float | None = None
        self.log(f"Farming Area {self.area}")
        if self.ocr is None:
            self.notify("GC Area needs the text reader to find the area (it comes with ReStart). "
                        "Stopped.")
            raise Done("no text reader")

    # an area cleared: go back to our area instead of the next one
    def handle_next_area(self, screen):
        self.count("areas")
        self.record("grand_crusade", f"Area {self.area} cleared")
        self.log(f"Area {self.area} cleared - heading back to it")
        self.need_travel = True
        self.pages_seen = 0
        if not self.tap_template("gc_map_menu_button", screen, settle=1.5):
            self.tap_template("gc_close_btn", screen, settle=1.5)  # results first

    def handle_map(self, screen):
        if self.need_travel and self.tap_template("gc_map_menu_button", screen, settle=1.5):
            self.log(f"Heading to Area {self.area}")
            return
        super().handle_map(screen)

    def handle_map_menu(self, screen):
        if not self.need_travel:
            self.tap_template("gc_close_btn", screen, settle=1.0)
            return
        self.tap_template("gc_menu_areas_button", screen, settle=1.5)

    def find_area_label(self, screen) -> tuple[int, int] | None:
        """Centre of the 'Area <n>' label for our area, read with OCR."""
        words = self.ocr.screen_words(screen, min_conf=55)
        for i, w in enumerate(words):
            if w.text.lower().startswith("area") and i + 1 < len(words):
                nxt = words[i + 1]
                m = _AREA_NUM.match(re.sub(r"[^\d]", "", nxt.text))
                if m and int(m.group(1)) == self.area and abs(nxt.y - w.y) < 15:
                    return (w.x + nxt.x + nxt.w) // 2, w.y + w.h // 2
            m = re.match(r"area\s*(\d{1,4})$", w.text.lower())
            if m and int(m.group(1)) == self.area:
                return w.center
        return None

    def handle_area_list(self, screen):
        if not self.need_travel:
            self.tap_template("gc_close_btn", screen, settle=1.0)
            return
        spot = self.find_area_label(screen)
        if spot:
            self.log(f"Found Area {self.area} - selecting it")
            self.tap(*spot, settle=2.0)
            self.need_travel = False
            self.progress()
            return
        self.pages_seen += 1
        if self.pages_seen > self.MAX_PAGES:
            self.notify(f"GC Area: couldn't find Area {self.area} in the area list. Stopped.")
            raise Done(f"area {self.area} not found")
        if self.pages_seen == 1 and self.tap_template("gc_area_page_first", screen, settle=1.5):
            self.log("Area list - back to the first page")
            return
        self.log(f"Area {self.area} not on this page - next page")
        self.tap_template("gc_area_list_end_arrow", screen, settle=1.5)

    def handle_destination(self, screen):
        now = time.monotonic()
        if self.dest_since is None:
            self.dest_since = now
            self.notify(f"GC Area: Area {self.area} wants a destination tile - pick one in-game; "
                        "Rerun carries on after.", ping=False)
        self.progress()  # waiting for you, not stuck
