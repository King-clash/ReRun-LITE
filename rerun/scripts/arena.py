"""Arena farming, following ReStart's Arena routine:

Home -> Arena -> Arena Battle (find opponent) -> Ready -> Battle -> VS ->
(battle on auto) -> win screen / Match Results -> OK -> next battle.
When the orbs run out it waits for them to refill (or restores them with
crystals if you allow it, up to a limit)."""
from __future__ import annotations

import random

from .base import BaseScript, Done, Setting, T


class ArenaScript(BaseScript):
    ID = "arena"
    NAME = "Arena"
    BETA = True
    DESCRIPTION = "Fights Arena battles on repeat and waits for orbs to refill."
    INSTRUCTIONS = """ARENA (BETA - not yet run on your game)
Finds an opponent, readies up, fights on auto and repeats.

SETUP
1. Build a proper Arena team and AI in-game first.
2. Open the Arena lobby (or the Home screen).
3. Choose the number of battles and what to do when orbs run out.
4. Press Start.

ORBS
- Default: when the orbs run out it cancels the dialog and waits 150-200
  seconds for them to refill, like ReStart.
- Restore orbs with crystals is off unless you turn it on, and then only up
  to your limit.
"""
    SETTINGS = [
        Setting("runs", "Number of battles (0 = no limit)", "int", 0),
        Setting("wait_orbs", "Wait for orbs to refill when they run out", "bool", True,
                help="Off = stop and notify you instead."),
        Setting("restore_orbs", "Restore orbs with crystals", "bool", False),
        Setting("restore_limit", "Max crystal restores per session (0 = no limit)", "int", 1),
        Setting("mode_247", "24/7 mode (recover crashes, survive daily reset)", "bool", False),
    ]
    TEMPLATES = [
        T("arena_home_button", "Arena entry (the 'Arena VS' banner) on the Home screen.", optional=True),
        T("arena_find_battle", "'Arena Battle' button in the Arena lobby."),
        T("arena_ready", "'Ready' button after an opponent is found."),
        T("arena_battle_button", "'Battle' button on the Arena party screen."),
        T("arena_vs_screen", "The 'VS' emblem shown before a battle."),
        T("arena_win_fighter", "'Fighters SS' win emblem.", optional=True),
        T("arena_win_master", "'Masters' win emblem.", optional=True),
        T("arena_match_results", "'Match Results' title.", optional=True),
        T("arena_ok_button", "Blue OK on Arena result screens."),
        T("arena_no_orbs_cancel", "Blue 'Cancel' on the out-of-orbs dialog."),
        T("arena_restore_all", "Orange 'Restore all' on the out-of-orbs dialog."),
        T("ok_button", "Generic orange OK button.", optional=True),
    ]
    STATES = [
        # The orbs dialog is the only place 'Cancel' sits next to 'Restore all'.
        ("no_orbs", ["arena_no_orbs_cancel"], ["arena_restore_all"]),
        ("match_results", ["arena_match_results"]),
        ("win", ["arena_win_fighter", "arena_win_master"]),
        ("vs", ["arena_vs_screen"]),
        ("arena_ok", ["arena_ok_button"]),
        ("ready", ["arena_ready"]),
        ("battle", ["arena_battle_button"]),
        ("lobby", ["arena_find_battle"]),
        ("home", ["arena_home_button"]),
        ("ok_button", ["ok_button"]),
    ]
    TAPS = {
        "arena_ok": ("arena_ok_button", "OK button. Dismissing.", 1.0),
        "ready": ("arena_ready", "Arena ready screen. Confirming.", 1.5),
        "battle": ("arena_battle_button", "Battle. Tapping.", 2.0),
        "home": ("arena_home_button", "Home screen. Entering arena.", 3.0),
        "ok_button": ("ok_button", "OK button. Dismissing.", 1.0),
    }
    WAITING_STATES = BaseScript.WAITING_STATES | {"vs"}

    def on_start(self) -> None:
        self.target = int(self.cfg.get("runs") or 0)
        self.restores = 0
        self.wins = 0
        self.log(f"Battles: {self.target or 'no limit'} | Wait for orbs: {self.cfg['wait_orbs']} | "
                 f"Crystal restores: {'on' if self.cfg['restore_orbs'] else 'off'}")

    def finish(self) -> None:
        msg = f"Arena finished: {self.session_runs} battle(s), {self.wins} win(s)."
        self.record("finished", msg)
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)

    def handle_lobby(self, screen):
        if self.target and self.session_runs >= self.target:
            self.finish()
        self.log("Arena lobby. Finding battle.")
        self.tap_template("arena_find_battle", screen, settle=2.0)

    def handle_vs(self, screen):
        if self.prev_state != "vs":
            self.session_runs += 1
            self.count("runs")
            self.progress()
            cap = f"/{self.target}" if self.target else ""
            self.log(f"VS screen. Battle {self.session_runs}{cap}.")
        self.tap_base(360, 640, settle=1.5)

    def handle_win(self, screen):
        if self.prev_state != "win":
            self.wins += 1
            self.count("wins")
            self.record("arena", f"Won battle {self.session_runs}")
        self.log("Battle win screen. Dismissing.")
        self.tap_base(360, 640, settle=1.5)
        self.progress()

    def handle_match_results(self, screen):
        self.log("Match Results. Confirming.")
        if not self.tap_template("arena_ok_button", screen, settle=1.5):
            self.tap_base(360, 1100, settle=1.5)

    def handle_no_orbs(self, screen):
        limit = int(self.cfg.get("restore_limit") or 0)
        if self.cfg.get("restore_orbs") and not (limit and self.restores >= limit):
            self.tap_template("arena_restore_all", screen, settle=1.5)
            self.restores += 1
            self.count("crystal_refreshes")
            self.record("energy", f"Restored arena orbs with crystals ({self.restores})")
            self.log(f"Restored orbs with crystals ({self.restores} this session)")
            return
        if not self.cfg.get("wait_orbs", True):
            self.tap_template("arena_no_orbs_cancel", screen)
            self.notify(f"Arena: out of orbs after {self.session_runs} battle(s). Stopped.", ping=False)
            raise Done("out of arena orbs")
        self.log("No arena orbs. Dismissing cancel dialog.")
        self.tap_template("arena_no_orbs_cancel", screen, settle=1.0)
        wait = random.uniform(150, 200)
        self.log(f"Waiting {wait:.0f} seconds for orb refresh.")
        self.sleep(wait)
        self.progress()
