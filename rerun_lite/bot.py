"""ReRun LITE's Discord bot: the original bot (alerts with screenshots, the status board and its buttons,
slash commands) without the two commands that read the unit roster, which LITE does not have."""
from __future__ import annotations

from rerun import errlog
from rerun.discord_bot import DiscordBot

ROSTER_COMMANDS = ("units", "compendium")


class LiteBot(DiscordBot):

    def _build_client(self):
        client = super()._build_client()
        # discord.py keeps the command tree on the client's connection state
        tree = getattr(getattr(client, "_connection", None), "_command_tree", None)
        for name in ROSTER_COMMANDS:
            try:
                if tree is not None:
                    tree.remove_command(name)
            except Exception as e:  # noqa: BLE001 - a command LITE cannot hide is harmless: it says "no units"
                errlog.note("lite.discord_commands", e)
        return client
