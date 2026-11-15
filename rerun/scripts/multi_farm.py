"""Multiplayer farming - ReStart's Multi Farm routine.

You sit in a multiplayer lobby (hosting with friends, or joined); Rerun
readies up, starts the battle, taps through the results and handles the
Equip Crest screen exactly like the Crest script - except that in
multiplayer there is no Redeploy, so unwanted crests are scrapped with OK."""
from __future__ import annotations

from .base import Setting, T
from .crest import KEEP_CHOICES, CrestScript
from .energy import ENERGY_SETTINGS, ENERGY_TEMPLATES

_NOT_IN_MULTI = {
    "redeploy_button", "results_redeploy", "looping_button", "use_potions_button",
    "past_party_button", "include_ai_button", "apply_button", "solo_quest_button",
    "challenge_button", "quest_list", "quest_list_entry", "exploring_button",
    "loops_label", "loop_minus_button", "loop_plus_button"}


def _merge(a: list[T], b: list[T]) -> list[T]:
    names = {t.name for t in a}
    return a + [t for t in b if t.name not in names]


class MultiFarmScript(CrestScript):
    ID = "multi_farm"
    NAME = "Multiplayer Farm"
    BETA = True
    DESCRIPTION = "Readies up in a multiplayer lobby, fights and handles crests and results."
    INSTRUCTIONS = """MULTIPLAYER FARM (BETA - not yet run on your game)
For multiplayer crest, event and alchemy farming. Rerun taps Ready and
Battle in the lobby, taps through the results, and judges every crest like
the Crest script (keeps and stops on the rarity you choose, scraps the rest).

SETUP
1. Set up a multiplayer party and enter a lobby.
2. Choose the run count, crests to keep and energy refill in Settings.
3. Press Start.

Hyper rare drops are reported on Discord with a screenshot.
"""
    SETTINGS = [
        Setting("runs", "Number of runs (0 = no limit)", "int", 0),
        Setting("keep", "Crests to keep (stop + notify)", "choice", "4+ and Burst only",
                list(KEEP_CHOICES)),
        Setting("stop_on_unknown", "Stop if a crest can't be identified", "bool", True),
        Setting("party", "Party", "choice", "Current Party", ["Current Party"]),
        *ENERGY_SETTINGS,
        Setting("save_debug", "Save Equip Crest screenshots to debug_crest/", "bool", False),
    ]
    TEMPLATES = [t for t in CrestScript.TEMPLATES
                 if t.name not in _NOT_IN_MULTI and not t.name.startswith("crest_palace_")] + [
        T("ready_button", "'Ready' button in the multiplayer lobby."),
        T("next_button", "'Next' button on the results screens."),
        T("small_next_button", "Small 'Next' button on results.", optional=True),
        T("hyper_rare", "'Hyper Rare' drop banner.", optional=True),
    ]
    TEMPLATES = _merge(TEMPLATES, ENERGY_TEMPLATES)  # energy templates listed exactly once
    STATES = [
        ("crest_burst", ["crest_icon_lv5plus"]),
        ("crest_fragment", ["crest_fragment"]),
        ("equip_crest_screen", ["equip_crest_screen"]),
        ("continue_box", ["continue_box"]),
        ("crystal_dialog", ["crystal_dialog"]),
        ("use_pot_button", ["use_pot_button"]),
        ("hyper_rare", ["hyper_rare"]),
        ("drop_info", ["drop_info"]),
        ("select_crest_ok2", ["select_crest_ok2"]),
        ("next_button", ["next_button", "small_next_button"]),
        ("ready_button", ["ready_button"]),
        ("battle_button", ["battle_button"]),
        ("ok_button", ["ok_button"]),
    ]

    def scrap(self, screen) -> None:
        """No Redeploy in multiplayer: OK, then confirm the scrap."""
        self.log("Tapping Confirm.")
        if self.tap_template("select_crest_ok", screen, settle=1.5):
            ok2 = self.wait_for(["select_crest_ok2"], 6)
            if ok2:
                self.tap_match(ok2, settle=1.5)

    def handle_select_crest_ok2(self, screen):
        self.log("Select Crest dialog")
        self.tap_template("select_crest_ok2", screen, settle=1.5)

    def handle_drop_info(self, screen):
        self.log("Tapping drop info button.")
        self.tap_base(360, 640, settle=1.5)

    def handle_next_button(self, screen):
        self.log("Results page, tapping next button.")
        self.tap_template("next_button", screen, settle=1.5) or \
            self.tap_template("small_next_button", screen, settle=1.5)

    def handle_hyper_rare(self, screen):
        if self.prev_state != "hyper_rare":
            self.count("hyper_rare")
            self.record("drop", "Hyper rare drop", screen)
            self.notify(f"Hyper rare drop on {self.ctx.instance}!", ping=True)
        self.tap_base(360, 640, settle=1.5)

    def handle_ready_button(self, screen):
        if self.target_reached():
            self.finish()
        self.log("Tapping Ready button.")
        self.tap_template("ready_button", screen, settle=2.0)
        self.progress()

    def handle_battle_button(self, screen):
        self.log("Tapping Battle button.")
        self.tap_template("battle_button", screen, settle=2.0)
        self.progress()
