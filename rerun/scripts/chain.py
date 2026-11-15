"""Chain: run several scripts one after another on one instance, e.g.

    login_mail; crest 90m; arena

Each step uses that instance's own settings for the script. A step ends when
the script completes (runs done, out of energy, mailbox empty) or when its
time limit ("90m") is up; then the game is restarted to Home and the next
step starts. If a step stops because something needs you (a rare crest left
on screen, an Omega boss, a stuck screen...), the whole chain stops.

Only scripts that can find their own way from the Home screen can be chained.
"""
from __future__ import annotations

import re
import time

from .base import BaseScript, Done, Finished, Setting, WindowElapsed

# Scripts that navigate from Home (with 24/7 mode on, which the chain forces).
CHAINABLE = ("login_mail", "crest", "grand_crusade", "arena", "mines")
_STEP = re.compile(r"^([a-z_]+)(?:\s+(\d+)\s*m(?:in)?)?$")


def parse_steps(text: str) -> list[tuple[str, int | None]]:
    """'login_mail; crest 90m' -> [('login_mail', None), ('crest', 90)]. Raises ValueError."""
    steps = []
    for raw in re.split(r"[;\n,]+", text or ""):
        raw = raw.strip().lower()
        if not raw:
            continue
        m = _STEP.match(raw)
        if not m:
            raise ValueError(f"Can't read the step '{raw}'. Write it like 'crest' or 'crest 90m'.")
        sid, minutes = m.group(1), m.group(2)
        if sid not in CHAINABLE:
            raise ValueError(f"'{sid}' can't be chained. Chainable: {', '.join(CHAINABLE)}.")
        steps.append((sid, int(minutes) if minutes else None))
    if not steps:
        raise ValueError("The chain has no steps.")
    return steps


class ChainScript(BaseScript):
    ID = "chain"
    NAME = "Chain"
    BETA = True
    DESCRIPTION = "Runs several scripts in a row (e.g. Login & Mail, then Crest for 90 min, then Arena)."
    INSTRUCTIONS = """CHAIN (BETA)
Runs scripts one after another on this instance, each with its own settings.

STEPS (in Settings), separated by ';':
    login_mail; crest 90m; arena
- 'crest 90m' = farm Crest for at most 90 minutes.
- Without a time, a step runs until the script completes (its run count
  is reached, energy runs out, the mailbox is empty...).
- Chainable: login_mail, crest, grand_crusade, arena, mines.

Between steps Rerun restarts the game so the next script starts from Home
(24/7 navigation is turned on for every step). If a step stops because
something needs you - a rare crest, an Omega boss, a stuck screen - the
whole chain stops and pings you.

Combine with a schedule (Settings > Schedule) to run the chain every day.
"""
    SETTINGS = [
        Setting("steps", "Steps", "text", "login_mail; crest 90m",
                help="Scripts in order, separated by ';'. Add '90m' to limit a step's time."),
        Setting("repeat", "Repeat the chain", "bool", False,
                help="Start again from the first step when the last one is done."),
    ]
    TEMPLATES: list = []

    @classmethod
    def all_templates(cls):
        return []  # each step checks its own templates when it starts

    def settings_for(self, sid: str) -> dict:
        getter = self.ctx.params.get("settings_of")
        return dict(getter(sid)) if getter else {}

    def run(self) -> None:
        from . import SCRIPTS
        steps = parse_steps(self.cfg.get("steps", ""))
        self.log("Chain: " + " -> ".join(f"{s}{f' ({m} min)' if m else ''}" for s, m in steps))
        rounds = 0
        while True:
            for i, (sid, minutes) in enumerate(steps, 1):
                self.checkpoint()
                cls = SCRIPTS[sid]
                child = cls(self.ctx, {**self.settings_for(sid), "mode_247": True})
                if minutes:
                    child.deadline = time.monotonic() + minutes * 60
                self.log(f"Step {i}/{len(steps)}: {cls.NAME}" + (f" for up to {minutes} min" if minutes else ""))
                try:
                    child.run()
                except WindowElapsed:
                    self.log(f"{cls.NAME}: time is up")
                except Done as e:
                    self.log(f"{cls.NAME} completed ({e})")
                # Finished (something needs you), stuck, user stop... end the chain.
                self.record("chain", f"Step {i} ({cls.NAME}) done")
                if i < len(steps) or self.cfg.get("repeat"):
                    self.log("Restarting the game for the next step")
                    self.restart_game(scheduled=True)
                    self.sleep(8)
            rounds += 1
            if not self.cfg.get("repeat"):
                break
        msg = f"Chain finished ({rounds} round(s))."
        self.notify(msg, screenshot=False, ping=False)
        raise Done(msg)


__all__ = ["ChainScript", "parse_steps", "CHAINABLE", "Finished"]
