"""Energy refills with a chosen item and spending caps.

The game's energy dialog lists S, M and L Potions and the Rekyuon Cupcake,
each with an identical "Use" button, so matching "Use" alone would pick
whichever row happened to score highest. Rerun finds the chosen item's icon
and taps the Use button on that row, and stops instead of spending past the
caps you set.
"""
from __future__ import annotations

from .base import Done, Finished, Setting, T

POTIONS = {
    "L Potion": "potion_l",
    "M Potion": "potion_m",
    "S Potion": "potion_s",
    "Rekyuon Cupcake": "potion_cupcake",
}
NO_POTION = "Don't use potions"
ROW_TOLERANCE = 70  # px between an icon's centre and its row's Use button (rows are ~165 apart)

ENERGY_SETTINGS = [
    Setting("potion", "Energy refill", "choice", "L Potion", [*POTIONS, NO_POTION],
            "Which item to use when energy runs out. Rerun taps the Use button on that "
            "item's row, so it never uses a different one by mistake."),
    Setting("potion_limit", "Max potions per session (0 = no limit)", "int", 0,
            help="Rerun stops and tells you when the limit is reached."),
    Setting("crystal_refresh", "Use crystals when potions run out", "bool", False,
            help="Off = stop and notify you instead of spending crystals."),
    Setting("crystal_limit", "Max crystal refills per session (0 = no limit)", "int", 0),
]

ENERGY_TEMPLATES = [
    T("use_pot_button", "'Use' button on the energy refill dialog (any row)."),
    T("potion_l", "L Potion icon in the energy refill dialog.", optional=True),
    T("potion_m", "M Potion icon in the energy refill dialog.", optional=True),
    T("potion_s", "S Potion icon in the energy refill dialog.", optional=True),
    T("potion_cupcake", "Rekyuon Cupcake icon in the energy refill dialog.", optional=True),
    T("crystal_dialog", "Something only on the 'refill with crystals' dialog (title or crystal icon).",
      optional=True),
    T("crystal_use_button", "The button that spends crystals in that dialog.", optional=True),
]


class EnergyMixin:
    """Mixed into scripts that farm energy-costing quests (needs BaseScript)."""

    potions_used = 0
    crystals_used = 0

    def out_of_energy(self, why: str) -> None:
        self.log(f"Out of energy: {why}")
        self.record("energy", f"Stopped: {why}")
        self.notify(f"{self.NAME}: out of energy - {why}. Stopped.")
        raise Done(f"out of energy ({why})")

    def use_potion(self, screen) -> None:
        choice = self.cfg.get("potion", "L Potion")
        if choice not in POTIONS:
            self.out_of_energy("potions are turned off in Settings")
        limit = int(self.cfg.get("potion_limit") or 0)
        if limit and self.potions_used >= limit:
            self.out_of_energy(f"reached your limit of {limit} potion(s) this session")
        tpl = POTIONS[choice]
        if not self.has_template(tpl):
            self.out_of_energy(f"the {choice} icon template is missing (Templates tab)")
        icon = self.find(tpl, screen)
        if not icon:
            self.out_of_energy(f"no {choice} in the energy dialog (none left?)")
        _, iy = icon.center
        row = [u for u in self.ctx.vision.find_all(screen, "use_pot_button")
               if abs(u.center[1] - iy) <= ROW_TOLERANCE]
        if not row:
            self.out_of_energy(f"couldn't find the Use button next to {choice}")
        self.tap_match(row[0], settle=1.0)
        self.potions_used += 1
        self.count("potions_used")
        self.count(f"used_{tpl}")
        cap = f"/{limit}" if limit else ""
        self.log(f"Used {choice} ({self.potions_used}{cap} this session)")
        self.record("energy", f"Used {choice} ({self.potions_used}{cap})")
        self.confirm_potion_used()
        self.progress()

    def confirm_potion_used(self) -> None:
        """Seen live: the game then shows 'Used L Potion to restore your energy.'
        with a BLUE OK. Tap it and make sure the popup is really gone."""
        for _ in range(3):
            m = self.wait_for(["potion_used_ok", "ok_button"], 4)
            if not m:
                return
            if m.name == "potion_used_ok" and not self.find("potion_used_text"):
                return  # a blue OK, but not this popup's
            self.log("'Used potion' popup - OK")
            self.tap_match(m, settle=1.5)
            if not self.find("potion_used_ok", self.grab()):
                return

    def use_crystals(self, screen) -> None:
        if not self.cfg.get("crystal_refresh"):
            self.out_of_energy("no potions left and crystal refills are off")
        limit = int(self.cfg.get("crystal_limit") or 0)
        if limit and self.crystals_used >= limit:
            self.out_of_energy(f"reached your limit of {limit} crystal refill(s)")
        if not self.tap_template("crystal_use_button", screen, settle=1.0):
            self.notify(f"{self.NAME}: could not find the crystal refill button. Stopped.")
            raise Finished("crystal button missing")
        self.crystals_used += 1
        self.count("crystal_refreshes")
        self.log(f"Refilled energy with crystals ({self.crystals_used} this session)")
        self.record("energy", f"Crystal refill ({self.crystals_used})")
        self.progress()
