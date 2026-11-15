"""Mines event farming, following ReStart's Mines routine:

Home -> Mines -> Go to the Mines -> Go Mining -> Select Support Unit (none)
-> Auto-Advance options -> Challenge -> battles advance on their own ->
dialogues / Drop Info / Next / OK -> again. Omega bosses are handled the way
you choose: stand by for you, fight, or change boss."""
from __future__ import annotations

from .base import BaseScript, Done, Finished, Setting, T
from .energy import ENERGY_SETTINGS, ENERGY_TEMPLATES, EnergyMixin

OMEGA_CHOICES = ["Standby (stop and tell me)", "Proceed (fight it)", "Change boss"]


class MinesScript(EnergyMixin, BaseScript):
    ID = "mines"
    NAME = "Mines"
    BETA = True
    DESCRIPTION = "Farms the Mines event: support pick, auto-advance, battles, results."
    INSTRUCTIONS = """MINES (BETA - not yet run on your game)
Automates the Mines event loop: navigation, support unit (none), the
Auto-Advance start, battle results and the dialogues in between.

SETUP
1. Set up your Mines party in-game and turn Auto on in the Auto-Advance
   options once (Rerun warns if it isn't).
2. Open the Mines screen (or Home), choose the Omega boss option, energy
   refill and run count in Settings, and press Start.

OMEGA BOSSES
- Standby: Rerun stops tapping and pings you so you can decide.
- Proceed: it fights the Omega boss.
- Change boss: it abandons the quest so the Keeper finds another area.
"""
    SETTINGS = [
        Setting("runs", "Number of runs (0 = no limit)", "int", 0),
        Setting("omega", "Omega boss", "choice", OMEGA_CHOICES[0], OMEGA_CHOICES),
        *ENERGY_SETTINGS,
        Setting("mode_247", "24/7 mode (recover crashes, survive daily reset)", "bool", False),
    ]
    TEMPLATES = [
        T("mines_button", "'Mines' banner on the Home screen.", optional=True),
        T("mines_go_to_mines", "'Go to the Mines' button."),
        T("mines_go_mining", "'Go Mining' button."),
        T("mines_select_support_unit_header", "'Select Support Unit' header."),
        T("mines_no_support_unit", "'No Support Unit' option."),
        T("mines_auto_advance_title", "'Auto-Advance' title of the options dialog."),
        T("mines_auto_checked", "The ticked Auto checkbox in that dialog.", optional=True),
        T("mines_challenge_button", "Orange 'Challenge' button."),
        T("mines_abandon_quest_button", "Orange 'Abandon Quest' button."),
        T("mines_omega_dialogue", "The 'enemy seems quite strong' Omega dialogue."),
        T("mines_omega_standby", "Blue 'Standby' Omega option."),
        T("mines_omega_proceed", "Purple 'Proceed' Omega option."),
        T("mines_omega_change_boss", "Yellow 'Change Boss' Omega option."),
        T("mines_arcana_dialogue", "'Arcana' dialogue title.", optional=True),
        T("mines_area_change_dialogue", "The Keeper's 'find you a different area' line.", optional=True),
        T("mines_clear_time_failed", "'--:--.--' clear time of a failed advance.", optional=True),
        T("mines_date_changed", "'Date has changed. Returning to title.' message.", optional=True),
        T("mines_not_enough_energy", "'Not enough Energy' text of the refill dialog."),
        T("mines_close_button", "Orange 'Close' button.", optional=True),
        T("drop_info", "'Drop Info' title on the results screen."),
        T("next_button", "'Next' button on results.", optional=True),
        T("ok_button", "Generic orange OK button."),
        *ENERGY_TEMPLATES,
    ]
    STATES = [
        ("date_changed", ["mines_date_changed"]),
        ("omega_choice", ["mines_omega_standby", "mines_omega_proceed", "mines_omega_change_boss"]),
        ("omega_dialogue", ["mines_omega_dialogue"]),
        ("abandon", ["mines_abandon_quest_button"]),
        ("energy", ["mines_not_enough_energy"]),
        ("crystal_dialog", ["crystal_dialog"]),
        ("arcana", ["mines_arcana_dialogue"]),
        ("area_change", ["mines_area_change_dialogue"]),
        ("drop_info", ["drop_info"]),
        ("support", ["mines_select_support_unit_header"]),
        ("auto_advance", ["mines_auto_advance_title"]),
        ("challenge", ["mines_challenge_button"]),
        ("go_mining", ["mines_go_mining"]),
        ("go_to_mines", ["mines_go_to_mines"]),
        ("next", ["next_button"]),
        ("close", ["mines_close_button"]),
        ("home", ["mines_button"]),
        ("ok_button", ["ok_button"]),
    ]
    TAPS = {
        "go_mining": ("mines_go_mining", "Go Mining.", 2.0),
        "go_to_mines": ("mines_go_to_mines", "Go to the Mines screen.", 2.0),
        "next": ("next_button", "Next.", 1.5),
        "close": ("mines_close_button", "Close.", 1.5),
        "home": ("mines_button", "Home screen - entering the Mines.", 3.0),
        "ok_button": ("ok_button", "Tapping OK.", 1.0),
    }
    WAITING_STATES = BaseScript.WAITING_STATES | {"support", "drop_info"}

    def on_start(self) -> None:
        self.target = int(self.cfg.get("runs") or 0)
        self.potions_used = self.crystals_used = 0
        self.auto_warned = False
        self.last_drop = False
        self.log(f"Runs: {self.target or 'no limit'} | Omega: {self.cfg['omega']} | "
                 f"Refill: {self.cfg.get('potion')}")

    def detect_state(self, screen):
        state = super().detect_state(screen)
        drop = state == "drop_info"
        if drop and not self.last_drop:
            self.session_runs += 1
            self.count("runs")
            self.progress()
            self.log(f"Run complete. {self.session_runs}{f'/{self.target}' if self.target else ''}")
        self.last_drop = drop
        return state

    def finish(self) -> None:
        msg = f"Mines finished: {self.session_runs} run(s)."
        self.record("finished", msg)
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)

    def handle_date_changed(self, screen):
        self.log("The game's date rolled over - back to title.")
        self.tap_base(360, 640, settle=3.0)

    def handle_omega_dialogue(self, screen):
        self.log("Omega dialogue - tapping on.")
        self.tap_base(360, 1000, settle=1.5)

    def handle_omega_choice(self, screen):
        choice = self.cfg.get("omega", OMEGA_CHOICES[0])
        if choice.startswith("Proceed"):
            self.log("Omega setting is Proceed - fighting it.")
            self.tap_template("mines_omega_proceed", screen, settle=2.0)
        elif choice.startswith("Change"):
            self.log("Set to change boss - abandoning this one.")
            self.tap_template("mines_omega_change_boss", screen, settle=2.0)
        else:
            self.record("mines", "Omega boss found - standing by for you", screen)
            self.notify("Mines: Omega boss found. Standing by - nothing will be tapped until "
                        "you deal with it.")
            raise Finished("omega boss - standby")

    def handle_abandon(self, screen):
        if self.cfg.get("omega", "").startswith("Change"):
            self.log("Set to change boss - tapping Abandon Quest.")
            self.tap_template("mines_abandon_quest_button", screen, settle=2.0)
        elif self.tap_template("mines_challenge_button", screen, settle=2.0):
            self.log("Proceeding - tapping Challenge.")

    def handle_energy(self, screen):
        self.use_potion(screen)

    def handle_crystal_dialog(self, screen):
        self.use_crystals(screen)

    def handle_arcana(self, screen):
        self.log("Arcana dialogue.")
        self.tap_base(360, 1000, settle=1.2)

    def handle_area_change(self, screen):
        self.log("Keeper is finding a different area - tapping on.")
        self.tap_base(360, 1000, settle=1.2)

    def handle_drop_info(self, screen):
        if self.find("mines_clear_time_failed", screen):
            self.count("failures")
            self.record("failure", "Advance ended with no clear time")
        self.log("Drop info - tapping.")
        self.tap_base(360, 640, settle=1.5)

    def handle_support(self, screen):
        if self.tap_template("mines_no_support_unit", screen, settle=1.5):
            self.log("Taking no support unit.")
        else:
            self.log("No Support Unit not on screen yet - waiting.")

    def handle_auto_advance(self, screen):
        if self.has_template("mines_auto_checked") and not self.find("mines_auto_checked", screen) \
                and not self.auto_warned:
            self.auto_warned = True
            self.notify("Mines: Auto looks off in the Auto-Advance options - turn it on in-game "
                        "for unattended runs. Starting anyway.", ping=False)
        if self.tap_template("mines_challenge_button", screen, settle=2.0):
            self.log("Starting the advance.")

    def handle_challenge(self, screen):
        if self.target and self.session_runs >= self.target:
            self.finish()
        self.log("Tapping Challenge.")
        self.tap_template("mines_challenge_button", screen, settle=2.0)
        self.progress()
