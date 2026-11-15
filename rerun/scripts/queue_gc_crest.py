"""Queue: Grand Crusade until its stamina runs out, then Crest for a while,
then back - ReStart's Queue routine.

Each half is the normal script with that instance's own settings, so Crest
still judges every crest. A rare crest (or anything else that stops Crest)
stops the whole queue."""
from __future__ import annotations

import time

from .base import BaseScript, Done, Finished, Setting
from .crest import CrestScript
from .grand_crusade import GrandCrusadeScript, OutOfStamina
from .base import WindowElapsed


class QueueScript(BaseScript):
    ID = "queue"
    NAME = "Queue (GC + Crest)"
    BETA = True
    DESCRIPTION = "Grand Crusade until stamina runs out, then Crest for a set time, repeated."
    INSTRUCTIONS = """QUEUE - GRAND CRUSADE + CREST (BETA - not yet run on your game)
Runs Grand Crusade until its stamina runs out, then farms Crest while it
refills, then goes back to Grand Crusade - over and over.

SETUP
1. Set up the Grand Crusade and Crest settings for this instance first (the
   queue uses them). Crest needs its 24/7 navigation templates (Exploring,
   Crest Palace, your palace tile) because the queue restarts the game to
   switch between the two.
2. Open Grand Crusade (or Home) and press Start.

TIPS
- Set the Crest window close to how long Grand Crusade stamina takes to refill.
- If a rare crest is found while farming Crest, the whole queue stops and
  pings you.
"""
    SETTINGS = [
        Setting("crest_minutes", "Minutes of Crest each time GC runs dry", "int", 60),
        Setting("cycles", "Cycles (0 = no limit)", "int", 0),
    ]
    TEMPLATES = GrandCrusadeScript.TEMPLATES + [
        t for t in CrestScript.TEMPLATES if t.name not in {x.name for x in GrandCrusadeScript.TEMPLATES}]

    def settings_for(self, script_id: str) -> dict:
        getter = self.ctx.params.get("settings_of")
        return dict(getter(script_id)) if getter else {}

    def restart_to_home(self) -> None:
        self.log("Restarting the game to switch farms.")
        self.restart_game(scheduled=True)
        self.sleep(8)

    def run(self) -> None:
        self.log("Script started")
        minutes = max(1, int(self.cfg.get("crest_minutes") or 60))
        cycles = int(self.cfg.get("cycles") or 0)
        done = 0
        while not cycles or done < cycles:
            self.checkpoint()
            gc = GrandCrusadeScript(self.ctx, {**self.settings_for("grand_crusade"),
                                               "no_stamina": "Stop", "mode_247": True})
            self.log("Starting Grand Crusade")
            try:
                gc.run()
            except OutOfStamina:
                self.log("Primary out of energy - switching to Crest.")
            except Finished as e:
                self.log(f"Grand Crusade finished ({e}) - switching to Crest.")
            self.restart_to_home()
            crest = CrestScript(self.ctx, {**self.settings_for("crest"), "mode_247": True})
            crest.deadline = time.monotonic() + minutes * 60
            self.log(f"Now farming Crest for {minutes} minute(s).")
            try:
                crest.run()
            except WindowElapsed:
                self.log("Crest window elapsed - back to Grand Crusade.")
            # A rare crest, burst or any other stop from Crest propagates and
            # ends the whole queue, as in ReStart.
            done += 1
            self.count("cycles")
            self.record("queue", f"Finished cycle {done}")
            self.restart_to_home()
        msg = f"Queue finished: {done} cycle(s)."
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)
