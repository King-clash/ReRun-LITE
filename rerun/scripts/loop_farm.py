"""Shared flow for scripts built on the game's Auto-Loop system.

Quest page (Solo/Challenge) -> party screen (Past Party, Include AI, Apply)
-> Battle -> Auto-Loop screen (turn on potion refill, Start Looping)
-> runs are counted each time "Drop Info" appears
-> loop results -> Redeploy (same quest, same party) or OK.
"""
from __future__ import annotations

import time
from datetime import datetime

import numpy as np

from ..loop_count import set_loops
from .. import qol
from .base import BaseScript, Done, Finished, Setting, T
from .energy import ENERGY_SETTINGS, ENERGY_TEMPLATES, NO_POTION, EnergyMixin

LOOP_TEMPLATES = [
    T("solo_quest_button", "The 'Solo-play' card on the Mode Selection screen (Solo-play / Multiplayer)."),
    T("challenge_button", "'Challenge' button on a quest's detail page.", optional=True),
    T("past_party_button", "'Past Party' button on the party screen."),
    T("include_ai_button", "The UNTICKED 'Include AI' checkbox in the Past Party dialog (crop just the empty box)."),
    T("apply_button", "'Apply' button in the Past Party dialog."),
    T("auto_button", "The Auto toggle on the party screen while it is OFF.", optional=True),
    T("battle_button", "'Battle' button on the party screen."),
    T("use_potions_button", "The 'OFF' toggle for 'Refill energy with potions' on the Auto-Loop screen."),
    T("looping_button", "'Start Looping' button on the Auto-Loop screen."),
    T("drop_info", "'Drop Info' title on the results screen after each run."),
    T("results_redeploy", "Green 'Redeploy' button on the loop results screen."),
    T("loops_label", "'Loops' label on the Auto-Loop Settings screen (for setting the loop count).",
      optional=True),
    T("loop_minus_button", "The '-' button left of the Auto-Loop slider.", optional=True),
    T("loop_plus_button", "The '+' button right of the Auto-Loop slider.", optional=True),
    T("ok_button", "Generic orange 'OK' button (results / dialogs)."),
    *ENERGY_TEMPLATES,
    T("continue_box", "'Continue?' title shown when the party is wiped."),
    T("cancel_btn", "'Cancel' on the Continue? dialog."),
    T("restart_btn", "'Restart' button shown after cancelling Continue?.", optional=True),
]

LOOP_SETTINGS = [
    Setting("runs", "Number of runs (0 = no limit)", "int", 0),
    Setting("past_party", "Always re-select Past Party", "bool", True,
            help="On every Start, new quest entry, Resume, crash relaunch and daily-reset relogin: "
                 "Past Party, tick Include AI, Apply - each step checked on screen. Not on Redeploy. "
                 "Off: uses whatever party is set in-game."),
    *ENERGY_SETTINGS,
    Setting("game_refill", "Let the game refill energy mid-loop", "bool", False,
            help="Turns on Auto-Loop's own 'Refill energy with potions'. Fewer interruptions, "
                 "but the game picks the potion and Rerun can't count or cap it."),
    Setting("mode_247", "24/7 mode (recover crashes, survive daily reset)", "bool", False),
    Setting("max_minutes", "Stop after this many minutes (0 = no limit)", "int", 0,
            help="Rerun finishes the batch it is in, then stops instead of starting another."),
    Setting("stop_at", "Stop at this time (HH:MM, optional)", "text", "",
            help="Your PC's clock, 24-hour, e.g. 07:00: the next time it shows that, Rerun finishes the "
                 "current batch and stops. Combined with the minutes above, whichever comes first wins."),
    Setting("energy_floor", "Keep at least this much energy (0 = off)", "int", 0,
            help="Stops (instead of using potions) when the next run would leave you below this, so "
                 "you always have some energy for playing yourself. Checked between batches."),
    Setting("max_restarts_per_day", "Max game restarts per day (0 = no limit)", "int", 0,
            help="Counts restarts after crashes or no progress (not the daily relogin or maintenance). "
                 "Over the limit Rerun stops and tells you instead of restarting again."),
]


class LoopFarmScript(EnergyMixin, BaseScript):
    STATES = [
        ("continue_box", ["continue_box"]),
        ("crystal_dialog", ["crystal_dialog"]),
        ("use_pot_button", ["use_pot_button"]),
        # The Auto-Loop dialog opens on top of the results, whose Redeploy bar
        # stays visible (dimmed) underneath - so it must win over them.
        ("looping_button", ["looping_button"]),
        ("drop_info", ["drop_info"]),
        ("results_redeploy", ["results_redeploy"]),
        ("include_ai_button", ["include_ai_button"]),
        ("apply_button", ["apply_button"]),
        ("battle_button", ["battle_button"]),
        ("solo_quest_button", ["solo_quest_button", "challenge_button"]),
        ("ok_button", ["ok_button"]),
    ]

    DROP_IDLE_S = 12
    last_drop: bool | None = None  # Drop Info seen on the previous frame (None = no frame yet)
    # Seen live: an error popup dimmed the party screen and Battle (brightness
    # 48 vs 153) kept matching, so it was tapped 25 times to no effect.
    LIT_STATES = {"battle_button", "solo_quest_button", "apply_button", "include_ai_button"}

    def on_start(self) -> None:
        self.drop_since = None
        self.target = int(self.cfg.get("runs") or 0)
        self.in_loop = False
        self.time_deadline = self._time_deadline()
        self._floor_checked_at = -1e9
        self.reset_party("start")
        self.past_party_missing_told = False
        self.last_drop = None  # unknown until the first frame
        self.failures = 0
        self.potions_used = self.crystals_used = 0
        cap = int(self.cfg.get("potion_limit") or 0)
        party = "re-select Past Party + Include AI" if self.wants_past_party() else "current party"
        self.log(f"Target runs: {self.target or 'no limit'} | Party: {party} | "
                 f"Refill: {self.cfg.get('potion')}{f' (max {cap})' if cap else ''} | "
                 f"Crystals: {'on' if self.cfg.get('crystal_refresh') else 'off'}")

    # ------------------------------------------------------------ counting
    def detect_state(self, screen: np.ndarray) -> str:
        state = super().detect_state(screen)
        # Count a run on the rising edge of Drop Info, whatever handler runs.
        drop = state == "drop_info"
        if self.last_drop is None:
            # First frame: a Drop Info already on screen belongs to a run that
            # finished before Start (seen live: it was counted, and with a
            # 1-run target the script stopped without playing).
            self.last_drop = drop
            return state
        if drop and not self.last_drop:
            self.count_run()
        self.last_drop = drop
        return state

    def count_run(self) -> None:
        self.session_runs += 1
        self.count("runs")
        self.progress()
        lifetime = self.ctx.stats.get(self.ctx.instance).get(f"{self.ID}.runs", 0)
        target = f"/{self.target}" if self.target else ""
        self.log(f"Run completed. {self.session_runs}{target} | Lifetime: {lifetime}")

    def _time_deadline(self) -> float | None:
        """Epoch seconds when 'Stop after N minutes' / 'Stop at HH:MM' says the farm should end."""
        ends = []
        minutes = int(self.cfg.get("max_minutes") or 0)
        if minutes > 0:
            ends.append(time.time() + minutes * 60)
        stop_at = str(self.cfg.get("stop_at") or "").strip()
        if stop_at:
            nxt = qol.next_time_after(datetime.now(), stop_at)
            if nxt is None:
                self.log(f"Setting 'Stop at': '{stop_at}' is not a 24-hour HH:MM time - ignored")
            else:
                ends.append(nxt.timestamp())
        if ends:
            self.log("Time limit: stops after the batch that is running at "
                     + datetime.fromtimestamp(min(ends)).strftime("%H:%M"))
        return min(ends) if ends else None

    def time_up(self) -> bool:
        return getattr(self, "time_deadline", None) is not None and time.time() >= self.time_deadline

    def target_reached(self) -> bool:
        """Runs target hit, or the time limit passed: the batch in progress finishes, no new one starts."""
        return (bool(self.target) and self.session_runs >= self.target) or self.time_up()

    def energy_gate(self, screen, with_cost: bool = False) -> None:
        """'Keep at least N energy': stop (never drink a potion) when the next run would leave
        less. Reads the energy bar (and the quest's cost on the party screen) with the text reader;
        unreadable = no stop. Looked at most every 20 s."""
        floor = int(self.cfg.get("energy_floor") or 0)
        if floor <= 0 or self.ocr is None:
            return
        now = time.monotonic()
        if now - getattr(self, "_floor_checked_at", -1e9) < 20:
            return
        self._floor_checked_at = now
        from ..ocr import read_energy, read_energy_cost
        e = read_energy(self.ocr, screen)
        if not e:
            self.log("Energy floor: could not read the energy bar on this screen")
            return
        self.ctx.params["energy"] = (e[0], e[1], time.time())
        cost = read_energy_cost(self.ocr, screen) if with_cost else None
        if cost:
            self._quest_cost = cost
        cost = cost or getattr(self, "_quest_cost", 0)
        if e[0] - cost < floor:
            self.out_of_energy(f"energy is {e[0]}/{e[1]}"
                               + (f" and the next run costs {cost}" if cost else "")
                               + f"; you asked to keep at least {floor}")

    def finish(self, why: str = "") -> None:
        if not why and self.time_up():
            why = "Time limit reached."
        msg = f"{self.NAME} finished: {self.session_runs} run(s). {why}".strip()
        self.record("finished", msg)
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)

    # ------------------------------------------------------------ handlers
    def handle_solo_quest_button(self, screen):
        if self.target_reached():
            self.finish()
        self.log("Quest page - tapping Solo")
        self.tap_template("solo_quest_button", screen) or self.tap_template("challenge_button", screen)
        self.reset_party("new quest entry")

    # ------------------------------------------------------------ party
    # Past Party -> Include AI ticked -> Apply, each step checked on a fresh
    # frame. Re-done on Start, quest entry, Resume, relaunch and relogin; never
    # on Redeploy (the game keeps the same party there).
    PARTY_WAIT_TICKS = 6   # frames to wait for the Past Party button / dialog
    MAX_PARTY_TAPS = 3     # Include AI / Apply taps before giving up

    @classmethod
    def migrate_settings(cls, saved: dict) -> dict:
        """Old 'party' choice -> 'Always re-select Past Party' switch."""
        saved = super().migrate_settings(saved)
        has_setting = any(s.key == "past_party" for s in cls.SETTINGS)
        if has_setting and "past_party" not in saved and "party" in saved:
            saved = {**saved, "past_party": cls.past_party_from_old(saved["party"])}
        return saved

    @classmethod
    def past_party_from_old(cls, party: str) -> bool:
        return party == "Last Party"

    def wants_past_party(self) -> bool:
        return bool(self.cfg.get("past_party")) and self.has_template("past_party_button")

    def reset_party(self, why: str) -> None:
        if getattr(self, "party_done", False) and self.wants_past_party():
            self.log(f"Past Party will be re-selected ({why})")
        self.party_done = False
        self.party_phase = None     # None | "opened" (Past Party tapped, waiting for its dialog)
        self.party_wait = 0
        self.ai_taps = 0
        self.apply_taps = 0

    def on_resume(self) -> None:
        super().on_resume()
        self.reset_party("resumed")

    def on_relaunch(self) -> None:
        super().on_relaunch()
        self.reset_party("game relaunched")

    def party_fallback(self, reason: str) -> None:
        """No usable Past Party: carry on with the current party and say so once."""
        self.party_done = True
        self.party_phase = None
        self.log(f"{reason} - using the current party")
        self.record("party", f"{reason} - used the current party")
        if not getattr(self, "past_party_missing_told", False):
            self.past_party_missing_told = True
            self.notify(f"{self.NAME}: {reason}. Continuing with the current party.", ping=False)

    def select_past_party(self, screen) -> bool:
        """On the party screen. True while the Past Party step is still in progress."""
        if self.party_done or not self.wants_past_party():
            return False
        self.party_wait += 1
        if self.party_phase == "opened":
            if self.party_wait <= self.PARTY_WAIT_TICKS:
                return True  # waiting for the Past Party dialog
            self.party_fallback("Tapped Past Party but its dialog never opened")
            return False
        m = self.find("past_party_button", screen)
        if m and not self.dimmed(screen, m):
            self.log("Selecting Past Party")
            self.tap_match(m, settle=1.0)
            self.party_phase, self.party_wait = "opened", 0
            return True
        if self.party_wait < self.PARTY_WAIT_TICKS:
            return True  # the screen may still be sliding in
        self.party_fallback("No Past Party available on the party screen"
                            + (" (button greyed out)" if m else ""))
        return False

    def handle_battle_button(self, screen):
        if self.select_past_party(screen):
            return
        if self.find("auto_button", screen):
            self.log("Turning Auto on")
            self.tap_template("auto_button", screen)
            return
        self.check_energy_for_quest(screen)
        self.energy_gate(screen, with_cost=True)
        self.log("Tapping Battle")
        self.tap_template("battle_button", screen, settle=2.0)
        self.progress()

    def check_energy_for_quest(self, screen) -> None:
        """When no refill may be used, compare energy with the quest's cost first
        and stop with a clear message instead of meeting the refill dialog."""
        no_refill = self.cfg.get("potion") == NO_POTION or (
            int(self.cfg.get("potion_limit") or 0) and
            self.potions_used >= int(self.cfg.get("potion_limit") or 0))
        if not no_refill or self.ocr is None:
            return
        if time.monotonic() - getattr(self, "_cost_checked_at", -1e9) < 30:
            return
        self._cost_checked_at = time.monotonic()
        from ..ocr import read_energy, read_energy_cost
        energy, cost = read_energy(self.ocr, screen), read_energy_cost(self.ocr, screen)
        if energy:
            self.ctx.params["energy"] = (energy[0], energy[1], time.time())
        if energy and cost:
            self.log(f"Energy {energy[0]}/{energy[1]}, this quest costs {cost}")
            if energy[0] < cost:
                self.out_of_energy(f"energy is {energy[0]}/{energy[1]} and the quest costs "
                                   f"{cost}, with no refill allowed")

    def handle_include_ai_button(self, screen):
        # The template is the *unticked* box, so this only ever ticks it.
        self.party_phase = "dialog"
        if self.ai_taps >= self.MAX_PARTY_TAPS:
            self.record("failure", "Include AI could not be ticked in the Past Party dialog", screen)
            self.notify(f"{self.NAME}: tapped Include AI {self.ai_taps} times but it still shows "
                        "unticked. Stopped before applying the party.")
            raise Finished("Include AI could not be ticked")
        self.ai_taps += 1
        self.log("Ticking Include AI")
        self.tap_template("include_ai_button", screen, settle=0.8)

    def handle_apply_button(self, screen):
        self.party_phase = "dialog"
        # Never Apply on the strength of an earlier tap: look again first.
        fresh = self.grab()
        if self.find("include_ai_button", fresh):
            self.log("Include AI is not ticked yet - not applying")
            return
        if self.apply_taps >= self.MAX_PARTY_TAPS:
            self.record("failure", "Past Party dialog stayed open after Apply", fresh)
            self.notify(f"{self.NAME}: tapped Apply {self.apply_taps} times but the Past Party "
                        "dialog stayed open. Stopped.")
            raise Finished("Past Party Apply did not take")
        if not self.tap_template("apply_button", fresh, settle=1.0):
            return
        self.apply_taps += 1
        # Verify: the dialog closes and the party screen (Battle) is back.
        for _ in range(4):
            after = self.grab()
            if not self.find("apply_button", after):
                if self.find("battle_button", after) or self.find("past_party_button", after):
                    self.log("Past Party applied with Include AI - dialog closed, party screen back")
                else:
                    self.log("Past Party applied with Include AI - dialog closed")
                self.party_done = True
                self.party_phase = None
                self.progress()
                return
            self.sleep(0.7)
        self.log("Past Party dialog still open after Apply - checking again")

    def handle_looping_button(self, screen):
        if self.cfg.get("game_refill") and self.cfg.get("potion") != NO_POTION \
                and self.find("use_potions_button", screen):
            self.log("Turning on 'Refill energy with potions'")
            self.tap_template("use_potions_button", screen)
            return
        if self.target and self.has_template("loops_label"):
            remaining = max(1, self.target - self.session_runs)
            got = set_loops(self, remaining)
            if got is not None:
                self.log(f"Loops set to {got}" + ("" if got == remaining else
                                                   f" (wanted {remaining}; game limit)"))
            screen = self.grab()
        self.log("Start Looping")
        self.tap_template("looping_button", screen, settle=2.0)
        self.in_loop = True
        self.progress()

    def handle_drop_info(self, screen):
        # Mid-loop, Drop Info passes by on its own. When the loop has finished,
        # the same screen also carries the Redeploy / OK bar - act on that.
        if self.results_bar_live(screen):
            self.drop_since = None
            self.handle_results_redeploy(screen)
            return
        # When a loop ends, Drop Info waits for a tap before the next screen
        # (fragments popup, Equip Crest, results bar). Mid-loop it moves on
        # by itself within a few seconds, so only tap once it has sat idle.
        now = time.monotonic()
        if self.drop_since is None:
            self.drop_since = now
        elif now - self.drop_since > self.DROP_IDLE_S:
            self.log("Drop Info is waiting - tapping to continue")
            self.tap_base(360, 640, settle=2.0)
            self.drop_since = None

    def results_bar_live(self, screen) -> bool:
        """Redeploy visible and lit - not dimmed under a dialog (energy, fragments,
        Auto-Loop settings). ReStart measures the same thing by brightness."""
        m = self.find("results_redeploy", screen)
        if not m:
            return False
        v = self.ctx.vision
        return v.brightness(screen, m) >= 0.75 * v.template_brightness("results_redeploy")

    def handle_results_redeploy(self, screen):
        """A loop batch finished. Redeploy repeats it with the same party."""
        if not self.results_bar_live(screen):
            return  # dimmed under a popup; that popup's own handler goes first
        self.in_loop = False
        if self.target_reached():
            self.log("Time limit reached - closing results" if self.time_up()
                     else "Target reached - closing results")
            # Seen live: one tap while the bar was still sliding in did nothing,
            # leaving the results open. Tap until the bar is really gone.
            for _ in range(3):
                self.tap_template("ok_button", screen, settle=1.5)
                screen = self.grab()
                if not self.results_bar_live(screen):
                    break
            self.finish()
        self.energy_gate(screen)
        self.log("Loop finished - Redeploy")
        self.tap_template("results_redeploy", screen, settle=2.0)
        self.progress()

    def handle_ok_button(self, screen):
        self.tap_template("ok_button", screen)

    def handle_use_pot_button(self, screen):
        self.use_potion(screen)

    def handle_crystal_dialog(self, screen):
        self.use_crystals(screen)

    def handle_continue_box(self, screen):
        self.failures += 1
        self.count("failures")
        self.record("failure", "Party wiped - restarting the quest")
        self.log("Quest failed (Continue?) - cancelling and restarting the quest")
        self.notify(f"{self.NAME}: a run failed (party wiped). Restarting the quest.", ping=False)
        self.tap_template("cancel_btn", screen, settle=1.5)
        m = self.wait_for(["restart_btn"], 8)
        if m:
            self.tap_match(m, settle=2)
        self.reset_party("quest restarted after a wipe")
        self.in_loop = False
        if self.failures >= 5 and self.failures > self.session_runs:
            self.notify(f"{self.NAME}: {self.failures} failures - your team may not clear this quest. Stopped.")
            raise Finished("too many failures")
