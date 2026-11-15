"""Discord companion: alerts with screenshots, remote control, and stats.

Slash commands (only users in discord.allowed_user_ids may use control commands):
  /status                      every instance and what it is doing
  /start   instance [script]   start a script (Any Quest, Crest, Login & Mail...)
  /stop    instance|all        stop
  /pause   instance            pause / resume
  /resume  instance
  /screenshot instance         live screenshot
  /stats   [instance]          runs, crests, errors, uptime
  /resetstats instance|all     zero an instance's counters
  /history [instance] [count]  recent crests, refills and problems
  /summary                     the last 24 hours (also posted daily)
  /crests  [instance]          4+ / Burst / Lv4 today, session, all-time, observed rates
  /units   [search]            unit roster from your scans (newest first)
  /compendium [search] [show]  quest clear targets, progress, change since the last scan
  /energy  [instance]          energy of each instance
  /scripts                     list scripts

Alerts are embeds: gold = Crest 4+ / Burst / rare drop, green = finished, red = needs you,
with the screenshot and Stop / Resume / Screenshot / Start Crest buttons. A live status board
(one pinned message per instance, edited about once a minute when something changed) shows
status, script, quest, mode, runs, energy, targets, last action and errors
(discord.status_board: false turns it off). Every button press and control command is
checked against discord.allowed_user_ids.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import threading
import time
from typing import TYPE_CHECKING

import cv2

from .stats import fmt_duration

if TYPE_CHECKING:
    from .manager import Manager

try:
    import discord
    from discord import app_commands
except ImportError:  # pragma: no cover
    discord = None


STATUS_ICON = {"idle": "⚪", "starting": "🟡", "running": "🟢", "paused": "🟠", "error": "🔴"}

# Alert colours (Phase 6): gold = Crest 4+ / Burst (and other rare drops), green = finished,
# red = a problem, blue = anything else.
COLORS = {"gold": 0xF1C40F, "green": 0x2ECC71, "red": 0xE74C3C, "info": 0x3498DB}
TITLES = {"gold": "Rare drop!", "green": "Finished", "red": "Needs attention", "info": "Rerun"}
_GOLD = re.compile(r"burst|\b4\+|lv\s*4\+|hyper rare", re.I)
_RED = re.compile(r"stopped|stuck|fail|couldn't|could not|crash|error|maintenance|no progress|"
                  r"needs you|out of (energy|stamina|orbs)|wiped|not find|unexpected", re.I)
_GREEN = re.compile(r"finished|complete|done|counted|reached|saved|claimed|summary|all clear", re.I)
BOARD_EVERY_S = 60          # status board edit interval (well inside Discord's rate limits)
ACTIONS = {"stop": "Stop", "resume": "Resume", "shot": "Screenshot", "crest": "Start Crest"}


def alert_kind(message: str) -> str:
    """gold | green | red | info for an alert text (rare drops win over 'stopped')."""
    if _GOLD.search(message):
        return "gold"
    if _RED.search(message):
        return "red"
    if _GREEN.search(message):
        return "green"
    return "info"


def board_fields(m: "Manager", name: str) -> list[tuple[str, str]]:
    """What the live status board shows for one instance (plain text, testable)."""
    inst = m.instances[name]
    scripts = m.scripts_available()
    stats = m.stats.get(name)
    runs = stats.get(f"{inst.script}.runs", 0)
    up = fmt_duration(m.stats.uptime(name)) if inst.status in ("running", "paused") else "-"
    e = m.energy(name)
    quest = ""
    if inst.ctx is not None:
        quest = str(inst.ctx.params.get("quest") or inst.ctx.params.get("palace") or "")
    errors = sum(1 for x in m.history.recent(200, name) if x.get("kind") in ("failure", "error")
                 and time.time() - x.get("t", 0) < 86400)
    try:
        mode = "24/7" if m.script_settings(name, inst.script).get("mode_247") else "normal"
    except Exception:  # noqa: BLE001 - custom routines have no settings
        mode = "normal"
    out = [("Status", f"{STATUS_ICON.get(inst.status, '❔')} {inst.status}"),
           ("Script", scripts.get(inst.script, inst.script)),
           ("Quest", quest or "-"),
           ("Mode", mode),
           ("Runs", f"{runs:,}"),
           ("Energy", f"{e[0]}/{e[1]}" if e else "-"),
           ("Up", up)]
    comp = getattr(m, "compendium", None)
    if comp is not None and comp.r.units:
        s = comp.summary()
        out.append(("Targets", f"{s['done']} reached · {s['near']} near" if s["with_target"] else "none set"))
    out.append(("Last action", (inst.detail or "-")[:200]))
    out.append(("Errors (24 h)", str(errors)))
    return out


class DiscordBot:
    def __init__(self, manager: "Manager"):
        if discord is None:
            raise RuntimeError("discord.py is not installed (pip install discord.py)")
        self.m = manager
        cfg = manager.config["discord"]
        self.token: str = cfg.get("token", "")
        self.channel_id = int(cfg.get("channel_id") or 0)
        self.ping_user_id = int(cfg.get("ping_user_id") or 0)
        self.allowed = {int(x) for x in cfg.get("allowed_user_ids", []) or []}
        if not self.token:
            raise RuntimeError("Discord token is empty")
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: discord.Client | None = None
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="discord", daemon=True)
        self.thread.start()
        self.m.discord = self

    def stop(self) -> None:
        if self.m.discord is self:
            self.m.discord = None
        if self.loop and self.client:
            asyncio.run_coroutine_threadsafe(self.client.close(), self.loop)

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.client = self._build_client()
        try:
            self.loop.run_until_complete(self.client.start(self.token))
        except Exception as e:  # noqa: BLE001
            self.m.log("discord", f"Discord bot stopped: {e}")
        finally:
            self.ready.clear()

    # ------------------------------------------------------------ sending
    def send(self, text: str, png: bytes | None = None, ping: bool = False) -> None:
        """Thread-safe: queue a message to the alert channel."""
        if not self.loop or not self.client or not self.ready.is_set():
            return
        asyncio.run_coroutine_threadsafe(self._send(text, png, ping), self.loop)

    async def _channel(self):
        return self.client.get_channel(self.channel_id) or await self.client.fetch_channel(self.channel_id)

    async def _send(self, text: str, png: bytes | None, ping: bool) -> None:
        """Plain messages (the daily summary): a blue embed."""
        try:
            ch = await self._channel()
            embed = discord.Embed(title="Daily summary" if "summary" in text.lower()[:60] else "Rerun",
                                  description=text[:4000], color=COLORS["info"])
            file = discord.File(io.BytesIO(png), "screen.png") if png else None
            if file:
                embed.set_image(url="attachment://screen.png")
            await ch.send(content=f"<@{self.ping_user_id}>" if ping and self.ping_user_id else None,
                          embed=embed, file=file)
        except Exception as e:  # noqa: BLE001
            self.m.log("discord", f"Could not send alert: {e}")

    def alert(self, instance: str, message: str, png: bytes | None = None, ping: bool = False) -> None:
        """Thread-safe: a colour-coded alert (gold / green / red) with control buttons."""
        if not self.loop or not self.client or not self.ready.is_set():
            return
        asyncio.run_coroutine_threadsafe(self._alert(instance, message, png, ping), self.loop)

    async def _alert(self, instance: str, message: str, png: bytes | None, ping: bool) -> None:
        try:
            ch = await self._channel()
            kind = alert_kind(message)
            embed = discord.Embed(title=TITLES[kind], description=message[:4000], color=COLORS[kind],
                                  timestamp=discord.utils.utcnow())
            embed.set_footer(text=instance)
            file = discord.File(io.BytesIO(png), "screen.png") if png else None
            if file:
                embed.set_image(url="attachment://screen.png")
            kw = {"embed": embed, "view": self.controls(instance)}
            if file:
                kw["file"] = file
            if ping and self.ping_user_id:
                kw["content"] = f"<@{self.ping_user_id}>"
            await ch.send(**kw)
        except Exception as e:  # noqa: BLE001
            self.m.log("discord", f"Could not send alert: {e}")

    # ------------------------------------------------------------ buttons
    def controls(self, instance: str):
        """Stop / Resume / Screenshot / Start Crest for one instance. The buttons carry
        'rerun:<action>:<instance>' and are handled in on_interaction (so they keep working
        after Rerun restarts). Must be built inside the bot's event loop."""
        view = discord.ui.View(timeout=None)
        style = {"stop": discord.ButtonStyle.danger, "resume": discord.ButtonStyle.success,
                 "shot": discord.ButtonStyle.secondary, "crest": discord.ButtonStyle.primary}
        for action, label in ACTIONS.items():
            view.add_item(discord.ui.Button(label=label, style=style[action],
                                            custom_id=f"rerun:{action}:{instance}"[:100]))
        return view

    async def on_button(self, inter) -> None:
        """Every button press is checked against allowed_user_ids before anything happens."""
        cid = (inter.data or {}).get("custom_id", "")
        try:
            _, action, instance = cid.split(":", 2)
        except ValueError:
            return
        if inter.user.id not in self.allowed:
            await inter.response.send_message(
                "You are not allowed to control Rerun. Add your Discord user ID to "
                "discord.allowed_user_ids (Rerun › Discord tab or config.yaml).", ephemeral=True)
            self.m.log("discord", f"Refused button '{action}' from {inter.user} (not allowed)")
            return
        m = self.m
        if instance not in m.instances:
            await inter.response.send_message(f"No instance named '{instance}'", ephemeral=True)
            return
        if action == "shot":
            await inter.response.defer(thinking=True)
            try:
                img = await asyncio.to_thread(m.screenshot, instance)
                ok, buf = cv2.imencode(".png", img)
                await inter.followup.send(f"{instance} now:",
                                          file=discord.File(io.BytesIO(buf.tobytes()), "screen.png"))
            except Exception as e:  # noqa: BLE001
                await inter.followup.send(f"Screenshot failed: {e}")
            return
        if action == "stop":
            msg = m.stop(instance)
        elif action == "resume":
            inst = m.instances[instance]
            msg = m.resume(instance) if inst.status == "paused" else m.start(instance)
        elif action == "crest":
            msg = m.start(instance, "crest")
        else:
            return
        m.log("discord", f"{inter.user} pressed {ACTIONS[action]} for {instance}: {msg}")
        await inter.response.send_message(f"{ACTIONS[action]} → {msg}")
        await self.update_board(force=True)

    # ------------------------------------------------------------ live status board
    @property
    def _board_path(self):
        return self.m.root / "discord_board.json"

    def _board_ids(self) -> dict:
        try:
            d = json.loads(self._board_path.read_text(encoding="utf-8"))
            return d.get(str(self.channel_id), {}) if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_board_ids(self, ids: dict) -> None:
        try:
            d = json.loads(self._board_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d[str(self.channel_id)] = ids
        self._board_path.write_text(json.dumps(d, indent=1), encoding="utf-8")

    def board_embed(self, name: str):
        fields = board_fields(self.m, name)
        status = self.m.instances[name].status
        color = {"running": COLORS["green"], "paused": 0xE67E22, "error": COLORS["red"]}.get(status, 0x95A5A6)
        e = discord.Embed(title=f"{name} - live status", color=color, timestamp=discord.utils.utcnow())
        for k, v in fields:
            e.add_field(name=k, value=v or "-", inline=k not in ("Last action",))
        e.set_footer(text=f"Updated about every {BOARD_EVERY_S} s by Rerun")
        return e

    async def update_board(self, force: bool = False) -> None:
        """One pinned message per instance, edited only when something changed."""
        if not self.m.config["discord"].get("status_board", True):
            return
        ch = await self._channel()
        ids = self._board_ids()
        last = self.__dict__.setdefault("_board_last", {})
        changed = False
        for name in list(self.m.instances):
            sig = repr(board_fields(self.m, name))
            if not force and last.get(name) == sig and name in ids:
                continue
            embed = self.board_embed(name)
            msg = None
            if name in ids:
                try:
                    msg = await ch.fetch_message(int(ids[name]))
                    await msg.edit(embed=embed, view=self.controls(name))
                except Exception:  # noqa: BLE001 - deleted: post a new one
                    msg = None
            if msg is None:
                msg = await ch.send(embed=embed, view=self.controls(name))
                ids[name] = str(msg.id)
                changed = True
                try:
                    await msg.pin()
                except Exception:  # noqa: BLE001 - needs Manage Messages; the board works unpinned
                    self.m.log("discord", "Status board: could not pin (give the bot Manage Messages)")
            last[name] = sig
        if changed:
            self._save_board_ids(ids)

    async def _board_loop(self) -> None:
        while not self.client.is_closed():
            try:
                await self.update_board()
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                self.m.log("discord", f"Status board update failed: {e}")
            await asyncio.sleep(BOARD_EVERY_S)

    # ------------------------------------------------------------ commands
    def _build_client(self):
        bot = self
        m = self.m
        intents = discord.Intents.none()
        intents.guilds = True
        client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(client)

        def allowed(inter: discord.Interaction) -> bool:
            return inter.user.id in bot.allowed

        async def deny(inter: discord.Interaction) -> None:
            await inter.response.send_message(
                "You are not allowed to control this bot. Add your user ID to "
                "discord.allowed_user_ids in config.yaml.", ephemeral=True)

        async def instance_ac(inter, current: str):
            return [app_commands.Choice(name=n, value=n)
                    for n in list(m.instances) + ["all"] if current.lower() in n.lower()][:25]

        async def script_ac(inter, current: str):
            return [app_commands.Choice(name=label[:100], value=k)
                    for k, label in m.scripts_available().items()
                    if current.lower() in label.lower()][:25]

        @tree.command(description="Show every instance and what it is doing")
        async def status(inter: discord.Interaction):
            lines = []
            for n, i in m.instances.items():
                up = fmt_duration(m.stats.uptime(n)) if i.status in ("running", "paused") else "-"
                lines.append(f"{STATUS_ICON.get(i.status, '❔')} **{n}** - {i.status} "
                             f"({m.scripts_available().get(i.script, i.script)}, {i.serial}) up {up} "
                             f"{i.detail if i.status in ('error', 'idle') else ''}")
            await inter.response.send_message("\n".join(lines) or "No instances configured")

        @tree.command(description="Start a script on an instance")
        @app_commands.autocomplete(instance=instance_ac, script=script_ac)
        async def start(inter: discord.Interaction, instance: str, script: str | None = None):
            if not allowed(inter):
                return await deny(inter)
            if instance == "all":
                msg = "\n".join(m.start_all())
            else:
                msg = m.start(instance, script)
            await inter.response.send_message(msg)

        @tree.command(description="Stop an instance (or all)")
        @app_commands.autocomplete(instance=instance_ac)
        async def stop(inter: discord.Interaction, instance: str):
            if not allowed(inter):
                return await deny(inter)
            msg = "\n".join(m.stop_all()) if instance == "all" else m.stop(instance)
            await inter.response.send_message(msg)

        @tree.command(description="Pause an instance")
        @app_commands.autocomplete(instance=instance_ac)
        async def pause(inter: discord.Interaction, instance: str):
            if not allowed(inter):
                return await deny(inter)
            await inter.response.send_message(m.pause(instance))

        @tree.command(description="Resume a paused instance")
        @app_commands.autocomplete(instance=instance_ac)
        async def resume(inter: discord.Interaction, instance: str):
            if not allowed(inter):
                return await deny(inter)
            await inter.response.send_message(m.resume(instance))

        @tree.command(description="Live screenshot of an instance")
        @app_commands.autocomplete(instance=instance_ac)
        async def screenshot(inter: discord.Interaction, instance: str):
            if not allowed(inter):
                return await deny(inter)
            await inter.response.defer()
            try:
                img = await asyncio.to_thread(m.screenshot, instance)
                ok, buf = cv2.imencode(".png", img)
                await inter.followup.send(file=discord.File(io.BytesIO(buf.tobytes()), "screen.png"))
            except Exception as e:  # noqa: BLE001
                await inter.followup.send(f"Screenshot failed: {e}")

        @tree.command(description="Runs, crests, errors and uptime")
        @app_commands.autocomplete(instance=instance_ac)
        async def stats(inter: discord.Interaction, instance: str | None = None):
            data = m.stats.all()
            names = [instance] if instance and instance != "all" else list(data)
            embed = discord.Embed(title="Rerun stats")
            for n in names:
                d = data.get(n, {})
                total = d.get("seconds_run", 0) + m.stats.uptime(n)
                body = "\n".join(f"{k.replace('_', ' ')}: **{v}**" for k, v in sorted(d.items())
                                 if k != "seconds_run") or "nothing yet"
                embed.add_field(name=f"{n} (run time {fmt_duration(total)})", value=body[:1000])
            if not names:
                embed.description = "No stats yet"
            await inter.response.send_message(embed=embed)

        @tree.command(description="Reset an instance's stats (runs, crests, potions, run time)")
        @app_commands.autocomplete(instance=instance_ac)
        async def resetstats(inter: discord.Interaction, instance: str):
            if not allowed(inter):
                return await deny(inter)
            await inter.response.send_message(m.reset_stats(None if instance == "all" else instance))

        @tree.command(description="Recent crests, refills and problems")
        @app_commands.autocomplete(instance=instance_ac)
        async def history(inter: discord.Interaction, instance: str | None = None, count: int = 10):
            name = None if not instance or instance == "all" else instance
            items = m.history.recent(max(1, min(count, 25)), name)
            if not items:
                return await inter.response.send_message("No history yet")
            lines = [f"`{time.strftime('%m-%d %H:%M', time.localtime(e['t']))}` **{e['instance']}** "
                     f"{e['detail']}" for e in items]
            s = m.history.crest_summary(name)
            head = f"Crests kept **{s.get('kept', 0)}**, scrapped **{s.get('scrapped', 0)}**\n"
            await inter.response.send_message((head + "\n".join(lines))[:1900])

        @tree.command(description="Summary of the last 24 hours")
        async def summary(inter: discord.Interaction):
            text = await asyncio.to_thread(m.daily_summary, False)
            await inter.response.send_message(text[:1900])

        @tree.command(description="Crest 4+ / Burst / Lv4 drops: today, session, all-time, rates")
        @app_commands.autocomplete(instance=instance_ac)
        async def crests(inter: discord.Interaction, instance: str | None = None):
            from .crest_stats import format_summary
            name = None if not instance or instance == "all" else instance
            led = getattr(m, "crests", None)
            if led is None:
                return await inter.response.send_message("Crest tracking is not available")
            s = await asyncio.to_thread(led.summary, name)
            embed = discord.Embed(title=f"Crests - {name or 'all instances'}",
                                  description=format_summary(s, "Crest drops")[:4000],
                                  color=0xF1C40F)
            shot = led.shot_path(s["last_notable"])
            if shot:
                embed.set_image(url=f"attachment://{shot.name}")
                await inter.response.send_message(embed=embed, file=discord.File(str(shot), shot.name))
            else:
                await inter.response.send_message(embed=embed)

        @tree.command(description="Your unit roster: totals, newest units, search by name")
        async def units(inter: discord.Interaction, search: str | None = None):
            r = getattr(m, "units", None)
            if r is None or not r.units:
                return await inter.response.send_message(
                    "No units scanned yet - run the Compendium Counter on the Units list.")
            rows = r.rows(search=search or "", sort="first_seen", desc=True)
            lines = []
            for u in rows[:15]:
                el = r.value(u, "element") or "?"
                qc = r.value(u, "quest_clears")
                lines.append(f"**{u['name']}**{' (?)' if u.get('name_status') == 'uncertain' else ''}"
                             f" · {el}" + (f" · {qc:,} clears" if qc is not None else ""))
            head = r.summary_text()
            if search:
                head += f"\nMatching '{search}': {len(rows)}"
            more = f"\n…and {len(rows) - 15} more" if len(rows) > 15 else ""
            embed = discord.Embed(title="Units", description=(head + "\n\n" + "\n".join(lines) + more)[:4000],
                                  color=0x2ECC71)
            await inter.response.send_message(embed=embed)

        @tree.command(description="Quest clear targets: progress, near/at target, change since last scan")
        @app_commands.choices(show=[app_commands.Choice(name=f, value=f) for f in
                                    ("All units", "With a target", "Near target", "At target")])
        async def compendium(inter: discord.Interaction, search: str | None = None,
                             show: str | None = None):
            from .compendium import bar
            c = getattr(m, "compendium", None)
            if c is None or not c.r.units:
                return await inter.response.send_message(
                    "No units scanned yet - run the Compendium Counter on the Units list.")
            show = show or ("With a target" if c.summary()["with_target"] else "All units")
            rows = await asyncio.to_thread(c.rows, search or "", "pct" if show != "All units" else "clears",
                                           True, show)
            lines = []
            for r in rows[:15]:
                line = f"**{r['name']}**{' (?)' if r['uncertain'] else ''} · "
                line += "? clears" if r["clears"] is None else f"{r['clears']:,} clears"
                if r["target"]:
                    line += f" / {r['target']:,} `{bar(r['pct'])}` · {r['remaining']:,} to go" \
                        if r["pct"] is not None else f" / {r['target']:,}"
                ch = c.change_text(r)
                if ch:
                    line += f" · {ch}"
                lines.append(line)
            head = c.summary_text() + f"\n{show}" + (f" matching '{search}'" if search else "") + f": {len(rows)}"
            more = f"\n…and {len(rows) - 15} more" if len(rows) > 15 else ""
            embed = discord.Embed(title="Compendium", color=0x2ECC71,
                                  description=(head + "\n\n" + "\n".join(lines) + more)[:4000])
            await inter.response.send_message(embed=embed)

        @tree.command(description="Energy of each instance (reads the screen of idle ones)")
        @app_commands.autocomplete(instance=instance_ac)
        async def energy(inter: discord.Interaction, instance: str | None = None):
            await inter.response.defer()
            names = [instance] if instance and instance != "all" else list(m.instances)
            lines = []
            for n in names:
                if n not in m.instances:
                    lines.append(f"**{n}**: no such instance")
                    continue
                e = await asyncio.to_thread(m.energy, n, True)
                if e:
                    age = int(time.time() - e[2]) if len(e) > 2 else 0
                    when = "now" if age < 60 else f"{age // 60} min ago"
                    lines.append(f"⚡ **{n}**: {e[0]}/{e[1]} ({when})")
                else:
                    lines.append(f"⚡ **{n}**: couldn't read it (is the game on a screen that shows energy?)")
            embed = discord.Embed(title="Energy", description="\n".join(lines) or "No instances",
                                  color=COLORS["info"])
            await inter.followup.send(embed=embed)

        @tree.command(description="List available scripts")
        async def scripts(inter: discord.Interaction):
            lines = [f"`{k}` - {label}" for k, label in m.scripts_available().items()]
            await inter.response.send_message("\n".join(lines) or "No scripts")

        @client.event
        async def on_interaction(inter: discord.Interaction):
            if inter.type == discord.InteractionType.component and \
                    str((inter.data or {}).get("custom_id", "")).startswith("rerun:"):
                try:
                    await bot.on_button(inter)
                except Exception as e:  # noqa: BLE001
                    m.log("discord", f"Button failed: {e}")

        @client.event
        async def on_ready():
            try:
                await tree.sync()
            except Exception as e:  # noqa: BLE001
                m.log("discord", f"Could not register slash commands: {e}")
            bot.ready.set()
            m.log("discord", f"Discord bot online as {client.user}")
            if not getattr(bot, "_board_task", None):
                bot._board_task = asyncio.create_task(bot._board_loop())

        return client
