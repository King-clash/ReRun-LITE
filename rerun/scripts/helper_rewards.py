"""Helper Rewards - ReStart's Helper Reward routine.

Joins multiplayer lobbies hosted by other players that carry the Helper
Reward badge, picks a basic cheese as food, readies up, runs the quest and
leaves. Each host gives the bonus once per day, so hosts already helped
today are skipped. Lobby difficulty and host names are read with OCR."""
from __future__ import annotations

import re
import time
from datetime import date

from .base import BaseScript, Done, Setting, T, game_now

CHEESES = {  # setting label -> template
    "Blue Cheese": "helper_food_blue_cheese",
    "Red Cheese": "helper_food_red_cheese",
    "Camembert Cheese": "helper_food_camembert",
    "Emmental Cheese": "helper_food_emmental",
    "Gorgonzola": "helper_food_gorgonzola",
}
DIFFICULTIES = ["Holy Land of EXP", "Silver Bird", "Golden Cats", "Spirits of the Exploring",
                "Materials", "EX1", "EX2", "SPEX", "SPEX Hyper", "Daily Quest"]


class HelperRewardsScript(BaseScript):
    ID = "helper_rewards"
    NAME = "Helper Rewards"
    BETA = True
    DESCRIPTION = "Joins Helper Reward lobbies, picks a cheese, readies up, runs and leaves."
    INSTRUCTIONS = """HELPER REWARDS (BETA - not yet run on your game; uses text reading)
Joins other players' multiplayer lobbies that show the Helper Reward badge
and match your difficulty filter, picks a cheese, readies up, runs the
quest and leaves. A host gives the bonus once per day, so each host is
helped only once per game day (reset 6 AM UTC-6).

SETUP
1. Set up a multiplayer party in-game.
2. In Settings choose the difficulties to join and the cheese order.
3. Open Join Multi (or the Home screen) and press Start.
"""
    SETTINGS = [
        Setting("runs", "Lobbies to help (0 = no limit)", "int", 0),
        Setting("difficulties", "Difficulties to join", "text", "EX1, EX2, SPEX",
                help="Comma separated. Matches the lobby's quest name or tag, e.g. "
                     + ", ".join(DIFFICULTIES) + ". Leave empty to join any."),
        Setting("cheeses", "Cheese order", "text", "Blue Cheese, Red Cheese, Camembert Cheese",
                help="First one you have is used: " + ", ".join(CHEESES) + "."),
        Setting("host_wait", "Leave if the host hasn't started after (seconds)", "int", 180),
    ]
    TEMPLATES = [
        T("helper_join_multi_button", "'Join Multi' on the Home screen.", optional=True),
        T("helper_refine_search_button", "'Refine Search' on the lobby list."),
        T("helper_update_button", "'Update' (refresh) on the lobby list."),
        T("helper_reward_badge", "The 'Helper Reward' badge on a lobby."),
        T("helper_friends_filter", "'Friends' filter tab (when it is stuck on).", optional=True),
        T("helper_confirm_farm_party_join", "'Join' to confirm joining a lobby."),
        T("helper_full_lobby_button", "'Update' on the lobby-is-full popup."),
        T("helper_select_food", "'Select' food button in the lobby."),
        T("helper_food_list_header", "'Food List' title."),
        T("helper_multiplayer_bonus", "'Multiplayer Bonus' title.", optional=True),
        *[T(t, f"'{label}' in the food list.", optional=True) for label, t in CHEESES.items()],
        T("helper_ready_button", "'Ready' in the lobby."),
        T("helper_cancel_ready_button", "'Cancel Ready' (shown while readied)."),
        T("helper_same_as_host_button", "'Same as host' option.", optional=True),
        T("helper_lobby_back_button", "'Back' in the lobby."),
        T("helper_leave_lobby_ok", "Red OK confirming you leave the lobby."),
        T("helper_back_button", "Big blue 'Back' button.", optional=True),
        T("drop_info", "'Drop Info' title on the results screen."),
        T("next_button", "'Next' button on results.", optional=True),
        T("ok_button", "Generic orange OK button.", optional=True),
    ]
    STATES = [
        ("leave_ok", ["helper_leave_lobby_ok"]),
        ("full_lobby", ["helper_full_lobby_button"]),
        ("confirm_join", ["helper_confirm_farm_party_join"]),
        ("food_list", ["helper_food_list_header", "helper_multiplayer_bonus"]),
        ("drop_info", ["drop_info"]),
        ("next", ["next_button"]),
        ("readied", ["helper_cancel_ready_button"]),
        ("lobby", ["helper_ready_button"]),
        ("lobby_list", ["helper_refine_search_button"]),
        ("home", ["helper_join_multi_button"]),
        ("ok_button", ["ok_button"]),
    ]
    TAPS = {
        "full_lobby": ("helper_full_lobby_button", "Lobby full popup - updating.", 1.5),
        "next": ("next_button", "Results page - Next.", 1.5),
        "home": ("helper_join_multi_button", "Home screen - Join Multi.", 2.5),
        "ok_button": ("ok_button", "OK.", 1.0),
    }
    WAITING_STATES = BaseScript.WAITING_STATES | {"readied", "lobby_list"}
    REFRESH_EVERY_S = 8

    def on_start(self) -> None:
        if self.ocr is None:
            self.notify("Helper Rewards needs the text reader (it comes with ReStart). Stopped.")
            raise Done("no text reader")
        self.target = int(self.cfg.get("runs") or 0)
        self.wanted = [d.strip().lower() for d in str(self.cfg.get("difficulties", "")).split(",")
                       if d.strip()]
        self.cheese_order = [CHEESES[c.strip()] for c in str(self.cfg.get("cheeses", "")).split(",")
                             if c.strip() in CHEESES] or list(CHEESES.values())
        self.helped_day = game_now().date()
        self.hosts_today: set[str] = set()
        self.current_host: str | None = None
        self.food_done = False
        self.readied_at: float | None = None
        self.in_quest = False
        self.last_refresh = 0.0
        self.log(f"Difficulties: {', '.join(self.wanted) or 'any'} | Cheese: "
                 f"{', '.join(c.replace('helper_food_', '') for c in self.cheese_order)}")

    def _new_day(self) -> None:
        if game_now().date() != self.helped_day:
            self.helped_day, self.hosts_today = game_now().date(), set()
            self.log("Daily reset - every host can be helped again")

    # ---------------------------------------------------------------- lobby list
    def lobbies(self, screen) -> list[dict]:
        """Helper Reward lobbies on screen: badge position, row text, host."""
        badges = self.ctx.vision.find_all(screen, "helper_reward_badge")
        if not badges:
            return []
        words = self.ocr.screen_words(screen, min_conf=50)
        out = []
        for b in badges:
            cy = b.center[1]
            row = [w for w in words if abs(w.center[1] - cy) < 70]
            text = " ".join(w.text for w in sorted(row, key=lambda w: (w.y // 20, w.x)))
            host_line = [w for w in row if w.y < cy - 15]
            host = " ".join(w.text for w in host_line[:3]) or text[:20]
            out.append({"badge": b, "text": text, "host": re.sub(r"\W+", " ", host).strip()})
        return out

    def matches(self, text: str) -> bool:
        low = text.lower()
        return not self.wanted or any(d in low for d in self.wanted)

    def handle_lobby_list(self, screen):
        self._new_day()
        if self.target and self.session_runs >= self.target:
            msg = f"Helper Rewards finished: helped {self.session_runs} lobby(ies)."
            self.record("finished", msg)
            self.notify(msg, screenshot=False, ping=False)
            raise Done(msg)
        if self.find("helper_friends_filter", screen):
            self.log("Search filter stuck on Friends - tapping Refine Search")
            self.tap_template("helper_refine_search_button", screen, settle=1.5)
            return
        for lob in self.lobbies(screen):
            if not self.matches(lob["text"]):
                continue
            if lob["host"] in self.hosts_today:
                continue
            self.current_host = lob["host"]
            self.log(f"Found Helper Reward lobby ({lob['text'][:60]}) - joining")
            self.tap_match(lob["badge"], settle=1.5)
            self.food_done = False
            return
        if time.monotonic() - self.last_refresh >= self.REFRESH_EVERY_S:
            self.last_refresh = time.monotonic()
            self.tap_template("helper_update_button", screen, settle=2.0)
        self.progress()  # an empty list is waiting, not stuck

    def handle_confirm_join(self, screen):
        self.tap_template("helper_confirm_farm_party_join", screen, settle=2.5)

    # ---------------------------------------------------------------- lobby
    def handle_lobby(self, screen):
        if self.in_quest:  # back in the lobby after the quest: leave it
            self.log("Quest done - leaving the lobby")
            self.tap_template("helper_lobby_back_button", screen, settle=1.5)
            return
        if not self.food_done and self.tap_template("helper_select_food", screen, settle=1.5):
            self.log("Choosing food")
            return
        self.tap_template("helper_same_as_host_button", screen, settle=1.0)
        self.log("Tapping Ready.")
        self.tap_template("helper_ready_button", screen, settle=1.5)
        self.readied_at = time.monotonic()

    def handle_food_list(self, screen):
        for tpl in self.cheese_order:
            if self.tap_template(tpl, screen, settle=1.5):
                self.log(f"Food: {tpl.replace('helper_food_', '').replace('_', ' ')}")
                self.food_done = True
                return
        self.log("No preferred cheese visible - going on without food")
        self.food_done = True
        self.ctx.device.back()
        self.sleep(1.0)

    def handle_readied(self, screen):
        wait = int(self.cfg.get("host_wait") or 180)
        if self.readied_at is None:
            self.readied_at = time.monotonic()
        if time.monotonic() - self.readied_at > wait:
            self.log(f"Host hasn't started after {wait}s - leaving")
            self.tap_template("helper_cancel_ready_button", screen, settle=1.0)
            self.tap_template("helper_lobby_back_button", self.grab(), settle=1.5)
            self.readied_at = None
            if self.current_host:
                self.hosts_today.add(self.current_host)  # don't wait on this host again
            return
        self.progress()

    def handle_drop_info(self, screen):
        if not self.in_quest:
            self.in_quest = True
            self.session_runs += 1
            self.count("runs")
            if self.current_host:
                self.hosts_today.add(self.current_host)
            self.record("helper", f"Helped {self.current_host or 'a host'}")
            self.log(f"Run complete. ({self.session_runs}"
                     f"{f'/{self.target}' if self.target else ''})")
            self.progress()
        self.tap_base(360, 640, settle=1.5)

    def handle_leave_ok(self, screen):
        self.log("Confirming leave lobby.")
        self.tap_template("helper_leave_lobby_ok", screen, settle=2.0)
        self.in_quest = False
        self.readied_at = None
        self.current_host = None


__all__ = ["HelperRewardsScript", "date"]
