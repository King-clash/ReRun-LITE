from __future__ import annotations

from .base import Finished, Setting, T
from .loop_farm import LOOP_SETTINGS, LOOP_TEMPLATES, LoopFarmScript


class AnyQuestScript(LoopFarmScript):
    ID = "any_quest"
    NAME = "Any Quest"
    DESCRIPTION = "Farms whichever quest you have open using the game's Auto-Loop, then Redeploys."
    INSTRUCTIONS = """ANY QUEST
Farms whichever quest you have open with the in-game Auto-Loop: event
quests, story quests, anything that has Auto-Loop. When a loop ends it
presses Redeploy, which replays the same quest with the same party.
Your team must be able to clear the quest on auto.

SETUP
1. Open the quest and pick its difficulty.
2. Stop on the party screen (Battle button) or the quest page (Solo/Challenge).
3. Set the run count and party option in Settings.
4. Press Start.

TIPS
- When energy runs out Rerun uses the item you picked in Settings (L Potion
  by default) and stops at your potion limit. Turn on "Let the game refill
  energy mid-loop" if you'd rather the game refill by itself (uncapped).
- Crystals are only spent if crystal refresh is on, up to your crystal limit.
- For Crest Palaces use the Crest script; it also judges the crests.
- Runs are counted each time Drop Info appears.
"""
    SETTINGS = [
        *LOOP_SETTINGS[:1],
        Setting("past_party", "Always re-select Past Party", "bool", False,
                help="Off (recommended here) uses the party set for the quest. On: Past Party + "
                     "Include AI + Apply on every Start, quest entry, Resume and relaunch."),
        *LOOP_SETTINGS[2:],
    ]
    TEMPLATES = LOOP_TEMPLATES + [
        T("exploring_button", "'Exploring' button on the Home screen (to notice the game went Home).",
          optional=True),
    ]
    # Seen live: a game error sent it back to the title screen and then Home.
    # Any Quest can't know which quest you had open, so it stops and tells you
    # straight away instead of idling until the 20-minute watchdog.
    STATES = LoopFarmScript.STATES[:-1] + [
        ("home_screen", ["exploring_button"]),
        LoopFarmScript.STATES[-1],
    ]

    def handle_home_screen(self, screen):
        self.record("failure", "Game returned to Home - the quest needs reopening")
        self.notify(f"{self.NAME}: the game went back to the Home screen (after "
                    f"{self.session_runs} run(s)). Open the quest again and press Start.")
        raise Finished("game returned to Home")
