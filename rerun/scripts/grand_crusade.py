"""Grand Crusade auto-advance, following ReStart's Grand Crusade routine:

Home -> Grand Crusade -> (optional team load) -> Auto-Advance -> confirm ->
the game advances on its own -> area cleared -> Next Area -> Fight -> ...
It takes the Yuna Chance minigames when offered and handles the item and
error popups. Choosing a specific area needs text reading (ReStart's GC Area
routine), which Rerun doesn't do - pick the area in-game first."""
from __future__ import annotations

import time

from .base import BaseScript, Done, Setting, T

NO_STAMINA = ["Stop", "Wait and retry"]


class OutOfStamina(Done):
    """Grand Crusade has no stamina left (Queue switches to Crest on this)."""


class GrandCrusadeScript(BaseScript):
    ID = "grand_crusade"
    NAME = "Grand Crusade"
    BETA = True
    DESCRIPTION = "Runs Grand Crusade auto-advance, next areas and Yuna Chance."
    INSTRUCTIONS = """GRAND CRUSADE (BETA - not yet run on your game)
Keeps Grand Crusade's auto-advance going: starts it, moves to the next area
when one is cleared, fights, closes popups and takes Yuna Chance.

SETUP
1. Open Grand Crusade on the map of the area you want (or Home with 24/7).
2. Optional: turn on Load Team to load party slot 1-1 when entering.
3. Choose what happens when stamina runs out, then press Start.
"""
    SETTINGS = [
        Setting("runs", "Auto-advances to start (0 = no limit)", "int", 0),
        Setting("yuna", "Take Yuna Chance", "bool", True),
        Setting("no_stamina", "When stamina runs out", "choice", NO_STAMINA[0], NO_STAMINA),
        Setting("wait_minutes", "Minutes to wait before retrying", "int", 30),
        Setting("load_team", "Load Team (slot 1-1) when entering", "bool", False),
        Setting("mode_247", "24/7 mode (recover crashes, survive daily reset)", "bool", False),
    ]
    TEMPLATES = [
        T("gc_icon", "Grand Crusade entry on the Home screen.", optional=True),
        T("gc_icon2", "'Grand Crusade' banner variant.", optional=True),
        T("gc_auto_advance_btn", "'Auto-Advance' button on the map."),
        T("gc_auto_advance_btn2", "'Auto-Advance' confirmation on the second screen."),
        T("gc_end_advance_button", "Teal 'End Advance' button.", optional=True),
        T("gc_results_end_advance", "Red 'End Advance' on the advance results.", optional=True),
        T("gc_next_area_btn", "'Next Area' button after clearing an area."),
        T("gc_fight_btn", "Small orange 'Fight' button."),
        T("gc_fight_btn2", "Large orange 'Fight' button.", optional=True),
        T("gc_area_select", "'Area Select' title.", optional=True),
        T("gc_close_btn", "Blue 'Close' button."),
        T("gc_item_cancel", "Blue 'Cancel' on the item dialog."),
        T("gc_ap_standby_recover", "Green 'Recover' on the no-stamina dialog."),
        T("gc_no_stamina_ok", "Blue OK on the no-stamina dialog."),
        T("gc_game_error", "'An unexpected error has occurred.' text.", optional=True),
        T("gc_yuna_chance", "'Yuna Chance' banner offered during the advance.", optional=True),
        T("gc_yuna_lets_go", "Yuna Chance 'LET'S GO'.", optional=True),
        T("gc_yuna_regalia_pick", "'Pick a card for a chance at tons of Regalia EXP!' title.", optional=True),
        T("gc_yuna_card_back", "Back of a Yuna Chance card.", optional=True),
        T("gc_yuna_slots_start", "Slots 'Tap to Start'.", optional=True),
        T("gc_yuna_slots_stop", "Slots 'Tap to Stop'.", optional=True),
        T("gc_yuna_slots_touch", "Slots 'TOUCH'.", optional=True),
        T("gc_party_button", "'Party' button on the map (Load Team).", optional=True),
        T("gc_save_load_button", "'Save/Load' button (Load Team).", optional=True),
        T("gc_party_load_slot", "'Load' button of slot 1-1 (Load Team).", optional=True),
        T("gc_party_load_confirm", "'Confirm Load' button (Load Team).", optional=True),
        T("gc_party_list_back", "'Back' button of the party list (Load Team).", optional=True),
        T("gc_party_ready", "'Ready' button after loading (Load Team).", optional=True),
        T("ok_button", "Generic orange OK button.", optional=True),
    ]
    STATES = [
        ("game_error", ["gc_no_stamina_ok"], ["gc_game_error"]),
        ("no_stamina", ["gc_ap_standby_recover"]),
        ("yuna_regalia", ["gc_yuna_regalia_pick"]),
        ("yuna_lets_go", ["gc_yuna_lets_go"]),
        ("yuna_slots_stop", ["gc_yuna_slots_stop"]),
        ("yuna_slots_start", ["gc_yuna_slots_start"]),
        ("yuna_slots_touch", ["gc_yuna_slots_touch"]),
        ("yuna_offer", ["gc_yuna_chance"]),
        ("item_cancel", ["gc_item_cancel"]),
        ("close", ["gc_close_btn"]),
        ("party_confirm", ["gc_party_load_confirm"]),
        ("party_slot", ["gc_party_load_slot"]),
        ("results_end", ["gc_results_end_advance"]),
        ("next_area", ["gc_next_area_btn"]),
        ("fight", ["gc_fight_btn", "gc_fight_btn2"]),
        ("advance_confirm", ["gc_auto_advance_btn2"]),
        ("map", ["gc_auto_advance_btn"]),
        ("area_select", ["gc_area_select"]),
        ("home", ["gc_icon", "gc_icon2"]),
        ("ok_button", ["ok_button"]),
    ]
    TAPS = {
        "yuna_lets_go": ("gc_yuna_lets_go", "Yuna Chance: LET'S GO.", 2.0),
        "yuna_slots_start": ("gc_yuna_slots_start", "Yuna Chance: Slots - spinning.", 1.0),
        "yuna_slots_stop": ("gc_yuna_slots_stop", "Yuna Chance: Slots - stopping.", 1.0),
        "yuna_slots_touch": ("gc_yuna_slots_touch", "Yuna Chance: Slots - collecting the prizes.", 1.5),
        "item_cancel": ("gc_item_cancel", "Item cancel dialog detected. Dismissing.", 1.0),
        "close": ("gc_close_btn", "Close button detected. Dismissing.", 1.0),
        "party_confirm": ("gc_party_load_confirm", "Confirm load.", 1.5),
        "fight": ("gc_fight_btn", "Fight button detected. Tapping.", 2.0),
        "ok_button": ("ok_button", "OK.", 1.0),
    }
    WAITING_STATES = BaseScript.WAITING_STATES | {"area_select"}

    def on_start(self) -> None:
        self.target = int(self.cfg.get("runs") or 0)
        self.team_loaded = not self.cfg.get("load_team")
        self.taking_yuna = False
        self.area_select_since: float | None = None
        self.log(f"Advances: {self.target or 'no limit'} | Yuna Chance: {self.cfg['yuna']} | "
                 f"No stamina: {self.cfg['no_stamina']} | Load Team: {self.cfg['load_team']}")

    def finish(self, why: str) -> None:
        msg = f"Grand Crusade finished: {self.session_runs} advance(s). {why}".strip()
        self.record("finished", msg)
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)

    # ------------------------------------------------------------ handlers
    def handle_game_error(self, screen):
        self.log("The game reported an unexpected error - dismissing.")
        self.tap_template("gc_no_stamina_ok", screen, settle=2.0)

    def handle_no_stamina(self, screen):
        self.log("No stamina. Dismissing.")
        if not self.tap_template("gc_no_stamina_ok", screen, settle=1.0):
            self.tap_template("gc_item_cancel", screen, settle=1.0)
        self.record("energy", "Grand Crusade out of stamina")
        if self.cfg.get("no_stamina") == "Wait and retry":
            mins = max(1, int(self.cfg.get("wait_minutes") or 30))
            self.log(f"Waiting {mins} minute(s) for stamina.")
            end = time.monotonic() + mins * 60
            while time.monotonic() < end:
                self.sleep(min(30, end - time.monotonic()))
                self.progress()  # waiting on purpose is not "stuck"
            self.log("Cooldown complete. Retrying auto-advance.")
            return
        self.notify(f"Grand Crusade: out of stamina after {self.session_runs} advance(s). Stopped.",
                    ping=False)
        raise OutOfStamina("out of stamina")

    def handle_yuna_offer(self, screen):
        if not self.cfg.get("yuna", True):
            return
        self.log("Yuna Chance offered - ending the advance to take it.")
        self.taking_yuna = True
        if not self.tap_template("gc_end_advance_button", screen, settle=2.0):
            self.tap_template("gc_yuna_chance", screen, settle=2.0)

    def handle_yuna_regalia(self, screen):
        self.log("Yuna Chance: picking a card.")
        if not self.tap_template("gc_yuna_card_back", screen, settle=2.0):
            self.tap_base(360, 760, settle=2.0)
        self.record("yuna", "Took a Yuna Chance card pick")

    def handle_results_end(self, screen):
        self.log("Ending the advance" + (" for the Yuna Chance." if self.taking_yuna else "."))
        self.tap_template("gc_results_end_advance", screen, settle=2.0)
        self.taking_yuna = False

    def handle_next_area(self, screen):
        self.log("Area cleared. Tapping next area.")
        self.count("areas")
        self.record("grand_crusade", "Area cleared")
        self.tap_template("gc_next_area_btn", screen, settle=2.5)
        self.progress()

    def handle_party_slot(self, screen):
        self.log("Loading slot 1-1.")
        self.tap_template("gc_party_load_slot", screen, settle=1.5)
        self.team_loaded = True

    def handle_map(self, screen):
        self.area_select_since = None
        if not self.team_loaded:
            for tpl, msg in (("gc_party_list_back", None), ("gc_party_ready", "Party loaded."),
                             ("gc_save_load_button", "Save/Load tapped - waiting for the list."),
                             ("gc_party_button", "Opening party.")):
                if self.find(tpl, screen):
                    if msg:
                        self.log(msg)
                    self.tap_template(tpl, screen, settle=1.5)
                    return
            self.log("Party button never appeared - skipping Load Team.")
            self.team_loaded = True
        if self.target and self.session_runs >= self.target:
            self.finish("")
        self.log("Auto-advance button detected. Tapping.")
        self.tap_template("gc_auto_advance_btn", screen, settle=2.0)

    def handle_advance_confirm(self, screen):
        self.session_runs += 1
        self.count("runs")
        self.progress()
        self.log(f"Second auto-advance screen. Tapping. "
                 f"({self.session_runs}{f'/{self.target}' if self.target else ''})")
        self.tap_template("gc_auto_advance_btn2", screen, settle=3.0)

    def handle_area_select(self, screen):
        now = time.monotonic()
        if self.area_select_since is None:
            self.area_select_since = now
            self.log("Area select screen - pick the area in-game (Rerun can't read area numbers).")
        elif now - self.area_select_since > 120:
            self.area_select_since = now
            self.notify("Grand Crusade: waiting on the Area Select screen - pick an area.", ping=False)

    def handle_home(self, screen):
        self.log("Home screen - entering Grand Crusade.")
        self.tap_template("gc_icon", screen, settle=3.0) or self.tap_template("gc_icon2", screen, settle=3.0)
