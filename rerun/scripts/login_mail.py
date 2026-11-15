from __future__ import annotations

import numpy as np

from .base import BaseScript, Done, Finished, Setting, T


class LoginMailScript(BaseScript):
    ID = "login_mail"
    NAME = "Login & Mail"
    DESCRIPTION = "Logs in from the Game Start screen, clears login popups and claims all mail."
    INSTRUCTIONS = """DAILY LOGIN & MAIL CLAIM
Logs in, clears the sign-in bonus and pop-ups, then claims every gift in
the mailbox. Run it once a day, or before a farming script.

SETUP
1. Open Grand Summoners on the Game Start screen (Transfer Device, Info and
   Restore at the bottom) - or the Home screen if you are already logged in.
2. Press Start.

WORKFLOW
- Taps past the Game Start screen.
- Closes the Information dialog, sign-in bonus and surprise pop-ups.
- Opens the mailbox and taps Claim All until nothing is left, then closes it.

CRASH RECOVERY
- With 24/7 mode on, a crash relaunches the game and the flow starts over.
"""
    SETTINGS = [
        Setting("mode_247", "Relaunch the game if it crashes", "bool", True),
        Setting("claim_limit", "Max Claim All presses", "int", 30,
                help="Safety limit in case the dim 'Claim All' is never recognised."),
    ]
    TEMPLATES = [
        T("game_start_screen", "A button only on the Game Start screen, e.g. 'Transfer Device'."),
        T("mail_chest", "Mailbox / gift chest icon on the Home screen."),
        T("claim_all_button", "Bright green 'Claim All' button in the mailbox (gifts waiting)."),
        T("claim_all_button_dim", "Greyed-out 'Claim All' button (no unclaimed gifts)."),
        T("claim_ok_button", "OK on the 'gifts claimed' confirmation."),
        T("mail_close_button", "Close button of the mailbox panel."),
        T("mail_empty_text", "The text 'You have no unclaimed gifts.' in the empty mailbox.",
          optional=True),
    ]
    STATES = [
        ("claim_ok_button", ["claim_ok_button"]),
        ("mail_empty", ["mail_empty_text"]),
        ("claim_all", ["claim_all_button", "claim_all_button_dim"]),
        ("mail_close_button", ["mail_close_button"]),
        ("mail_chest", ["mail_chest"]),
    ]
    NO_PROGRESS_RESTART_S = 6 * 60

    def on_start(self) -> None:
        self.claimed = False
        self.claims = 0

    def handle_claim_ok_button(self, screen):
        self.log("Claim confirmation - OK")
        self.tap_template("claim_ok_button", screen)
        self.progress()

    def close_mailbox(self, screen) -> None:
        if not self.tap_template("mail_close_button", screen):
            self.ctx.device.back()
        self.sleep(1)

    def handle_mail_empty(self, screen):
        self.log("Mailbox says: no unclaimed gifts")
        self.claimed = True
        self.close_mailbox(screen)

    def handle_claim_all(self, screen: np.ndarray):
        v = self.ctx.vision
        bright = v.find(screen, "claim_all_button") or v.find(screen, "claim_all_button_dim")
        if bright is None:
            return
        # Both templates match the same button; brightness tells enabled from greyed out.
        if v.closest_by_brightness(screen, bright, ["claim_all_button", "claim_all_button_dim"]) \
                == "claim_all_button_dim":
            self.log("Claim All is greyed out - no unclaimed gifts")
            self.claimed = True
            self.close_mailbox(screen)
            return
        if self.claims >= int(self.cfg["claim_limit"]):
            self.log("Claim All limit reached without the mailbox emptying - stopping")
            self.close_mailbox(screen)
            self.notify(f"Login & Mail pressed Claim All {self.claims} times but the mailbox never "
                        "showed as empty. Stopped - please check the mailbox.")
            raise Finished("claim limit reached")
        self.claims += 1
        self.log(f"Tapping Claim All ({self.claims})")
        self.tap_match(bright, settle=2.0)
        self.count("claims")
        self.progress()

    def handle_mail_close_button(self, screen):
        # Mailbox open but Claim All not visible yet (still loading): wait a beat.
        if self.claimed:
            self.tap_template("mail_close_button", screen)

    def handle_mail_chest(self, screen):
        if self.claimed:
            msg = (f"Login & Mail done: claimed {self.claims} time(s), mailbox empty."
                   if self.claims else "Login & Mail done: the mailbox was already empty.")
            self.notify(msg, screenshot=False, ping=False)
            raise Done("mailbox empty")
        self.log("Home screen - opening the mailbox")
        self.tap_template("mail_chest", screen, settle=2)
        self.progress()
