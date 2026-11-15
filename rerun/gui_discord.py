"""Discord tab.

Moved verbatim from rerun/gui.py (class App); App inherits DiscordMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class DiscordMixin:

    # ================================================================ discord
    def _build_discord(self):
        _, page, hdr = self._page("Discord Bot", "Discord", "chat", scroll=True)
        self._d_dot = ios.Dot(hdr, 9)
        self._d_dot.pack(side="left", padx=(0, px(8)))
        self.d_status = self._label(hdr, "Not connected", font="footnote")
        self.d_status.pack(side="left")
        cfg = self.m.config["discord"]
        self.d_vars = {
            "enabled": tk.BooleanVar(value=bool(cfg.get("enabled"))),
            "token": tk.StringVar(value=cfg.get("token", "")),
            "channel_id": tk.StringVar(value=str(cfg.get("channel_id") or "")),
            "ping_user_id": tk.StringVar(value=str(cfg.get("ping_user_id") or "")),
            "allowed_user_ids": tk.StringVar(
                value=", ".join(str(x) for x in cfg.get("allowed_user_ids", []) or [])),
        }
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="x", padx=px(20))
        g = ios.Group(wrap)
        g.pack(fill="x")
        ios.Switch(g.row("Connect When Rerun Starts",
                         "Brings the bot online every time you open Rerun."),
                   self.d_vars["enabled"]).pack()
        g2 = ios.Group(wrap, header="Bot",
                       footer="Keep the token secret - anyone with it controls your bot.")
        g2.pack(fill="x", pady=(px(24), 0))
        for label, key, secret, sub in [
                ("Bot Token", "token", True, None),
                ("Alert Channel ID", "channel_id", False, "Where alerts and screenshots are posted"),
                ("User ID to Ping", "ping_user_id", False, "Mentioned on rare crests and failures"),
                ("Allowed User IDs", "allowed_user_ids", False,
                 "Comma separated - who may control Rerun")]:
            ios.Field(g2.row(label, sub), self.d_vars[key], width=34,
                      show="•" if secret else "").pack()
        bar = tk.Frame(wrap, bg=C["bg"])
        bar.pack(fill="x", pady=(px(16), 0))
        ios.Button(bar, "Save & Connect", self.save_discord, icon="sync").pack(side="left")
        ios.Button(bar, "Disconnect", self.disconnect_discord, kind="gray").pack(side="left", padx=px(8))
        ios.Button(bar, "Send Test Message", self.test_discord, kind="tinted",
                   icon="send").pack(side="left")

        summ = self.m.config.get("summary") or {}
        gsum = ios.Group(wrap, header="Daily Summary",
                         footer="Runs, crests kept and scrapped, refills and problems of the last 24 "
                                "hours, posted to the alert channel. Also any time with /summary.")
        gsum.pack(fill="x", pady=(px(24), 0))
        self.sum_on = tk.BooleanVar(value=bool(summ.get("enabled", True)))
        ios.Switch(gsum.row("Post a daily summary"), self.sum_on).pack()
        self.sum_time = tk.StringVar(value=str(summ.get("time", "21:00")))
        ios.Field(gsum.row("At (24-hour HH:MM)"), self.sum_time, width=6, justify="right").pack()
        inc = summ.get("include") or {}
        self.sum_inc = {}
        for key, label in (("runs", "Runs and time farming"), ("crests", "Crests kept and scrapped"),
                           ("refills", "Energy refills"), ("problems", "Problems")):
            self.sum_inc[key] = tk.BooleanVar(value=bool(inc.get(key, True)))
            ios.Switch(gsum.row(f"Include: {label}"), self.sum_inc[key]).pack()

        quiet = cfg.get("quiet") or {}
        gq = ios.Group(wrap, header="Quiet Hours",
                       footer="Between these times alerts are still posted, but without @mentioning you. "
                              "The window may cross midnight (23:00 to 07:00).")
        gq.pack(fill="x", pady=(px(24), 0))
        self.quiet_on = tk.BooleanVar(value=bool(quiet.get("enabled")))
        ios.Switch(gq.row("No pings during quiet hours"), self.quiet_on).pack()
        self.quiet_start = tk.StringVar(value=str(quiet.get("start", "23:00")))
        ios.Field(gq.row("From (24-hour HH:MM)"), self.quiet_start, width=6, justify="right").pack()
        self.quiet_end = tk.StringVar(value=str(quiet.get("end", "07:00")))
        ios.Field(gq.row("Until (24-hour HH:MM)"), self.quiet_end, width=6, justify="right").pack()

        pings = cfg.get("ping") or {}
        gp = ios.Group(wrap, header="Ping Me For",
                       footer="Switch off the kinds you only want to read, not be mentioned for. "
                              "Alerts are posted either way.")
        gp.pack(fill="x", pady=(px(24), 0))
        self.ping_vars = {}
        for key, label, sub in (("rare", "Rare crests", "Crest 4+, Crest Burst, hyper rare drops"),
                                ("problem", "Stops and problems", "Stuck, failed, out of energy, game messages"),
                                ("finished", "Finished runs", "Run counts reached, mailbox claimed"),
                                ("other", "Everything else", None)):
            self.ping_vars[key] = tk.BooleanVar(value=bool(pings.get(key, True)))
            ios.Switch(gp.row(label, sub), self.ping_vars[key]).pack()

        ios.section_header(wrap, "Setup Guide", pady=(px(28), px(6)))
        gc = ios.Card(wrap)
        gc.pack(fill="x", pady=(0, px(24)))
        guide = tk.Label(gc.body, text=DISCORD_GUIDE, bg=C["card"], fg=C["label"],
                         font=F["footnote"], justify="left", anchor="w", wraplength=px(700))
        guide.pack(fill="x", padx=px(14), pady=px(12))
        gc.body.bind("<Configure>", lambda e: guide.configure(
            wraplength=max(px(200), e.width - px(32))), add="+")

    def _set_d_status(self, text: str):
        self.d_status.configure(text=short(text, 70))
        low = text.lower()
        if "online" in low:
            color = C["green"]
        elif "connecting" in low:
            color = C["orange"]
        elif "could not" in low or "stopped" in low or ":" in text:
            color = C["red"]
        else:
            color = C["gray"]
        self._d_dot.set(color)

    def save_discord(self):
        def to_int(s):
            s = str(s).strip()
            return int(s) if s.isdigit() else 0
        cfg = self.m.config["discord"]
        cfg["enabled"] = bool(self.d_vars["enabled"].get())
        cfg["token"] = self.d_vars["token"].get().strip()
        cfg["channel_id"] = to_int(self.d_vars["channel_id"].get())
        cfg["ping_user_id"] = to_int(self.d_vars["ping_user_id"].get())
        cfg["allowed_user_ids"] = [int(x) for x in self.d_vars["allowed_user_ids"].get().replace(" ", "").split(",") if x.isdigit()]
        t = self.sum_time.get().strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            ios.alert(self, "Write the summary time as HH:MM, e.g. 21:00.", "Daily Summary")
            return
        qs, qe = self.quiet_start.get().strip(), self.quiet_end.get().strip()
        if self.quiet_on.get() and not (qol.parse_hhmm(qs) and qol.parse_hhmm(qe)):
            ios.alert(self, "Write the quiet hours as HH:MM (24-hour), e.g. 23:00 and 07:00.", "Quiet Hours")
            return
        cfg["quiet"] = {"enabled": bool(self.quiet_on.get()), "start": qs or "23:00", "end": qe or "07:00"}
        cfg["ping"] = {k: bool(v.get()) for k, v in self.ping_vars.items()}
        self.m.config["summary"] = {"enabled": bool(self.sum_on.get()), "time": t,
                                    "include": {k: bool(v.get()) for k, v in self.sum_inc.items()}}
        self.m.save_config()
        self.connect_discord()

    def connect_discord(self):
        from .discord_bot import DiscordBot
        self.disconnect_discord()
        try:
            self.bot = DiscordBot(self.m)
        except RuntimeError as e:
            self._set_d_status(f"Not connected: {e}")
            return
        if not self.m.config["discord"].get("channel_id"):
            self._set_d_status("Set the alert channel ID first.")
            return
        self.bot.start()
        self._set_d_status("Connecting...")

    def disconnect_discord(self):
        if self.bot:
            self.bot.stop()
            self.bot = None
            self._set_d_status("Disconnected")

    def test_discord(self):
        if not self.bot or not self.bot.ready.is_set():
            self.flash("The bot is not connected yet", "warn")
            return
        self.m.notify("Rerun", "Test message - alerts will arrive here.", ping=True)
        self.flash("Test message sent", "ok")
