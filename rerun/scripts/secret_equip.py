"""Secret Equipment farming - ReStart's Secret Equip routine.

A secret equipment quest is farmed exactly like any Auto-Loop quest, so this
reuses the Any Quest flow with its own name, counters and instructions."""
from __future__ import annotations

from .any_quest import AnyQuestScript


class SecretEquipScript(AnyQuestScript):
    ID = "secret_equip"
    NAME = "Secret Equip"
    BETA = True
    DESCRIPTION = "Repeats a secret equipment quest on Auto-Loop."
    INSTRUCTIONS = """SECRET EQUIP (BETA - not yet run on your game)
Repeats a secret equipment quest with the in-game Auto-Loop and Redeploys
after every batch, like Any Quest, but keeps its own run counter.

SETUP
1. Open the secret equipment quest and pick its difficulty.
2. Stop on the party screen (Battle button) or the quest page (Solo).
3. Set the run count, party and energy refill in Settings.
4. Press Start.

Energy, potion limits, crystals and 24/7 mode work exactly as in Any Quest.
"""
