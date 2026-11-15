"""Raid routines, following ReStart's Raid Tickets, Raid Host and Raid Guest."""
from __future__ import annotations

import time

from .base import BaseScript, Done, Setting, T

RAID_RESULT_TEMPLATES = [
    T("raid_defeated", "'Defeated!' banner after a raid boss falls.", optional=True),
    T("raid_defeat_rewards", "'Defeat Rewards' button/title on the raid results."),
    T("raid_small_next", "'NEXT' button on raid results."),
]


class _RaidBase(BaseScript):
    BETA = True

    def on_start(self) -> None:
        self.target = int(self.cfg.get("raids") or 0)

    def done(self) -> bool:
        return bool(self.target) and self.session_runs >= self.target

    def finish(self, what: str) -> None:
        msg = f"{self.NAME} finished: {self.session_runs} {what}."
        self.record("finished", msg)
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)

    def handle_defeated(self, screen):
        self.log("Raid boss defeated.")
        self.tap_base(360, 640, settle=1.5)
        self.progress()

    def handle_defeat_rewards(self, screen):
        self.log("Defeat rewards. Tapping.")
        self.tap_template("raid_defeat_rewards", screen, settle=1.5)
        self.progress()


# ---------------------------------------------------------------- tickets
class RaidTicketsScript(_RaidBase):
    ID = "raid_tickets"
    NAME = "Raid Tickets"
    DESCRIPTION = "Buys raid tickets from the raid exchange."
    INSTRUCTIONS = """RAID TICKETS (BETA - not yet run on your game)
Buys raid tickets from the exchange until it has bought the number you set.

SETUP
1. In the Templates tab capture 'raid_ticket_target': the ticket you want
   (SR, Rare or Normal) as it appears in the exchange list.
2. Navigate to the raid exchange screen.
3. Set how many tickets to buy, then press Start.
"""
    SETTINGS = [Setting("raids", "Tickets to buy (0 = until the exchange runs out)", "int", 10)]
    TEMPLATES = [
        T("raid_ticket_target", "The ticket you want to buy, as shown in the exchange list."),
        T("raid_expand_btn", "Blue 'Expand' button in the raid exchange.", optional=True),
        T("raid_ticket_btn", "'Raid Ticket' button/tab in the exchange."),
        T("raid_exchange_btn", "Small teal 'Exchange' button on an item."),
        T("raid_exchange_btn2", "Big orange 'Exchange' confirmation button."),
        T("raid_ticket_ok_btn", "Blue OK after a purchase."),
    ]
    STATES = [
        ("ticket_ok", ["raid_ticket_ok_btn"]),
        ("exchange_confirm", ["raid_exchange_btn2"]),
        ("exchange", ["raid_exchange_btn"]),
        ("ticket_tab", ["raid_ticket_btn"]),
        ("expand", ["raid_expand_btn"]),
    ]
    TAPS = {
        "exchange_confirm": ("raid_exchange_btn2", "Tapping Exchange confirmation.", 1.5),
        "ticket_tab": ("raid_ticket_btn", "Raid ticket button. Tapping.", 1.5),
        "expand": ("raid_expand_btn", "Expand button. Tapping.", 1.5),
    }

    def on_start(self) -> None:
        super().on_start()
        self.log(f"Tickets to buy: {self.target or 'until the exchange runs out'}")

    def handle_ticket_ok(self, screen):
        self.session_runs += 1
        self.count("tickets")
        self.progress()
        self.log(f"Ticket purchased ({self.session_runs}{f'/{self.target}' if self.target else ''}).")
        self.tap_template("raid_ticket_ok_btn", screen, settle=1.5)
        if self.done():
            self.finish("ticket(s) bought")

    def handle_exchange(self, screen):
        if self.done():
            self.finish("ticket(s) bought")
        # Exchange the wanted ticket: the Exchange button on the same row as it.
        target = self.find("raid_ticket_target", screen)
        if not target:
            self.log("Wanted ticket not visible - scrolling the list.")
            self.ctx.device.swipe(360, 900, 360, 500, 400)
            self.sleep(1.0)
            return
        ty = target.center[1]
        rows = [b for b in self.ctx.vision.find_all(screen, "raid_exchange_btn")
                if abs(b.center[1] - ty) <= 80]
        if not rows:
            self.log("Selecting the ticket.")
            self.tap_match(target, settle=1.0)
            return
        self.log("Tapping Exchange button.")
        self.tap_match(rows[0], settle=1.5)


# ---------------------------------------------------------------- host
class RaidHostScript(_RaidBase):
    ID = "raid_host"
    NAME = "Raid Host"
    DESCRIPTION = "Creates raid lobbies, sends SOS and fights the raid."
    INSTRUCTIONS = """RAID HOST (BETA - not yet run on your game)
Creates a raid party, sends an SOS, starts the raid and collects the rewards,
then does it again.

SETUP
1. Make sure you have enough raid tickets.
2. Optional: capture 'raid_boss_target' (the boss to pick from the list);
   without it the boss already selected is used.
3. Navigate to the raid home screen and press Start.
"""
    SETTINGS = [
        Setting("raids", "Raids to host (0 = no limit)", "int", 5),
        Setting("friends_only", "Friends only lobby", "bool", False),
        Setting("send_sos", "Send an SOS for every raid", "bool", True),
    ]
    TEMPLATES = [
        T("raid_home", "The 'Raid' entry that opens the raid home.", optional=True),
        T("raid_boss_target", "The boss to host, on the raid boss list.", optional=True),
        T("raid_create", "'Create Raid party' button."),
        T("raid_friend_only_btn", "'Friend Only' toggle in the lobby settings.", optional=True),
        T("raid_start", "'Start Raid' button in the lobby."),
        T("raid_sos_btn", "Orange SOS (speaker) button in the lobby."),
        T("raid_green_sos", "Green SOS confirmation button."),
        T("raid_ok_btn", "Blue OK in raid dialogs."),
        *RAID_RESULT_TEMPLATES,
    ]
    STATES = [
        ("defeated", ["raid_defeated"]),
        ("defeat_rewards", ["raid_defeat_rewards"]),
        ("next", ["raid_small_next"]),
        ("green_sos", ["raid_green_sos"]),
        ("ok", ["raid_ok_btn"]),
        ("lobby", ["raid_start"]),
        ("create", ["raid_create"]),
        ("boss", ["raid_boss_target"]),
        ("home", ["raid_home"]),
    ]
    TAPS = {
        "next": ("raid_small_next", "Small next. Tapping.", 1.5),
        "ok": ("raid_ok_btn", "OK button. Tapping.", 1.2),
        "boss": ("raid_boss_target", "Selecting boss.", 1.5),
        "home": ("raid_home", "Raid home detected. Tapping.", 2.0),
    }

    def on_start(self) -> None:
        super().on_start()
        self.sos_sent = False
        self.friend_set = False
        self.log(f"Raids to host: {self.target or 'no limit'}")

    def handle_create(self, screen):
        if self.done():
            self.finish("raid(s) hosted")
        if self.cfg.get("friends_only") and not self.friend_set \
                and self.tap_template("raid_friend_only_btn", screen):
            self.log("Friend only button. Tapping once.")
            self.friend_set = True
            return
        self.log("Create raid party. Tapping.")
        self.tap_template("raid_create", screen, settle=2.0)
        self.sos_sent = False

    def handle_green_sos(self, screen):
        self.log("Green SOS. Tapping.")
        self.tap_template("raid_green_sos", screen, settle=1.5)
        self.sos_sent = True

    def handle_lobby(self, screen):
        if self.cfg.get("send_sos", True) and not self.sos_sent:
            if self.tap_template("raid_sos_btn", screen, settle=1.5):
                self.log("SOS button. Tapping.")
                return
            self.sos_sent = True  # no SOS button on this lobby
        self.session_runs += 1
        self.count("raids")
        self.progress()
        self.log(f"Start raid. ({self.session_runs}{f'/{self.target}' if self.target else ''})")
        self.record("raid", f"Hosted raid {self.session_runs}")
        self.tap_template("raid_start", screen, settle=3.0)
        self.sos_sent = False


# ---------------------------------------------------------------- guest
class RaidGuestScript(_RaidBase):
    ID = "raid_guest"
    NAME = "Raid Guest"
    DESCRIPTION = "Joins SOS raids and collects the rewards."
    INSTRUCTIONS = """RAID GUEST (BETA - not yet run on your game)
Joins raids from the SOS tab, fights them and collects the rewards. When no
SOS raids are listed it refreshes the list and tries again.

SETUP
1. Navigate to the raid screen.
2. Set the number of raids to join, then press Start.
"""
    SETTINGS = [Setting("raids", "Raids to join (0 = no limit)", "int", 5)]
    TEMPLATES = [
        T("raid_home", "The 'Raid' entry that opens the raid home.", optional=True),
        T("raid_join", "'Join Raid' button on the raid home."),
        T("raid_sos_tab", "The SOS tab while NOT selected (dark)."),
        T("raid_sos_tab2", "The SOS tab while selected (bright)."),
        T("raid_refresh_btn", "Green refresh button on the SOS list."),
        T("raid_sos_join_btn", "Orange 'Join' button on an SOS raid."),
        T("raid_orange_ok_btn", "Orange OK confirming a join."),
        T("raid_orange_ok_btn2", "Second orange OK variant.", optional=True),
        T("raid_btn", "Big red 'Raid' button in the raid lobby."),
        T("battle_button", "'Battle' button on the party screen."),
        *RAID_RESULT_TEMPLATES,
    ]
    STATES = [
        ("defeated", ["raid_defeated"]),
        ("defeat_rewards", ["raid_defeat_rewards"]),
        ("next", ["raid_small_next"]),
        ("orange_ok", ["raid_orange_ok_btn", "raid_orange_ok_btn2"]),
        ("battle", ["battle_button"]),
        ("raid_lobby", ["raid_btn"]),
        ("sos_join", ["raid_sos_join_btn"]),
        ("sos_list", ["raid_sos_tab2"]),
        ("sos_inactive", ["raid_sos_tab"]),
        ("join_raid", ["raid_join"]),
        ("home", ["raid_home"]),
    ]
    TAPS = {
        "next": ("raid_small_next", "Results next. Tapping.", 1.5),
        "raid_lobby": ("raid_btn", "Raid button. Tapping.", 2.0),
        "sos_inactive": ("raid_sos_tab", "SOS tab not active. Tapping.", 1.5),
        "home": ("raid_home", "Raid home detected.", 2.0),
    }
    WAITING_STATES = BaseScript.WAITING_STATES | {"sos_list"}
    REFRESH_EVERY_S = 10

    def on_start(self) -> None:
        super().on_start()
        self.last_refresh = 0.0
        self.log(f"Raids to join: {self.target or 'no limit'}")

    def handle_join_raid(self, screen):
        if self.done():
            self.finish("raid(s) joined")
        self.log("Join Raid button. Tapping.")
        self.tap_template("raid_join", screen, settle=2.0)

    def handle_sos_join(self, screen):
        if self.done():
            self.finish("raid(s) joined")
        self.log("SOS Join button. Tapping.")
        self.tap_template("raid_sos_join_btn", screen, settle=1.5)

    def handle_orange_ok(self, screen):
        self.log("Orange OK button. Confirming.")
        self.tap_template("raid_orange_ok_btn", screen, settle=1.5) or \
            self.tap_template("raid_orange_ok_btn2", screen, settle=1.5)

    def handle_battle(self, screen):
        self.session_runs += 1
        self.count("raids")
        self.progress()
        self.record("raid", f"Joined raid {self.session_runs}")
        self.log(f"Battle button. Tapping. Raid started "
                 f"({self.session_runs}{f'/{self.target}' if self.target else ''}).")
        self.tap_template("battle_button", screen, settle=3.0)

    def handle_sos_list(self, screen):
        if time.monotonic() - self.last_refresh < self.REFRESH_EVERY_S:
            return
        self.log("SOS tab active, no raids. Refreshing.")
        self.tap_template("raid_refresh_btn", screen, settle=2.0)
        self.last_refresh = time.monotonic()
        self.progress()  # an empty SOS list is waiting, not stuck
