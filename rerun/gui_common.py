"""Shared names for the GUI modules: imports, constants, small widgets (moved verbatim from gui.py).
Each tab module does `from .gui_common import *` so its methods see the same names as before."""
from __future__ import annotations

import queue
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from . import __version__, errlog, ios, qol, textnav, updates
from .adb import discover_bluestacks_instances
from .appicon import make_icon
from .ios import C, F, px
from .manager import Manager
from .scripts import SCRIPTS
from .stats import fmt_duration
from .tray import Tray
from .updates import UpdateError

STATUS_TEXT = {"idle": "Idle", "starting": "Starting", "running": "Running",
               "paused": "Paused", "error": "Error"}
STATUS_COLOR = {"idle": "gray", "starting": "blue", "running": "green",
                "paused": "orange", "error": "red"}
LOG_FILE_LEVELS = {"all": "Everything", "warnings": "Warnings and errors", "errors": "Errors only"}
APPEARANCE = {"auto": "Automatic", "light": "Light", "dark": "Dark"}
ALL_INSTANCES = "All instances"
LOG_LEVELS = {"All": None, "Warnings": {"warn", "error"}, "Errors": {"error"}}
HISTORY_KINDS = {"All": None, "Crests": {"crest"}, "Energy": {"energy"},
                 "Problems": {"failure"}, "Other": {"finished", "session", "drop", "arena", "raid", "mines",
                                                   "grand_crusade", "yuna", "queue"}}
IDLE_PREVIEW_EVERY_S = 3.0
STREAM_RETRY_S = 60     # after the Live View video failed, try it again this much later


def to_photo(img: np.ndarray, max_w: int, max_h: int) -> tuple[ImageTk.PhotoImage, float]:
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    small = img if scale == 1.0 else cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))), scale


def short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class InstanceList(tk.Frame):
    """Inset-grouped rows: status dot, name, address/script, last message, status."""

    def __init__(self, parent, on_select):
        super().__init__(parent, bg=C["card"])
        self._on_select = on_select
        self._rows: dict[str, dict] = {}
        self._order: list[str] = []
        self.sel: str | None = None
        self._painted: tuple | None = None
        self._sel_bg = ios.mix(C["card"], C["blue"], 0.22 if ios.DARK_MODE else 0.12)
        self._rebuild([])

    def set_rows(self, items: list[dict]):
        if [i["name"] for i in items] != self._order or not self._rows and items:
            self._rebuild(items)
        for it in items:
            self._update(it)
        if self.sel not in self._rows:
            self.sel = None
        self._paint()

    def _rebuild(self, items):
        for w in self.winfo_children():
            w.destroy()
        self._rows, self._order, self._painted = {}, [i["name"] for i in items], None
        card = C["card"]
        if not items:
            tk.Label(self, text="No Instances", bg=card, fg=C["label"],
                     font=F["body_semi"]).pack(pady=(px(18), 0))
            tk.Label(self, text="Use Detect BlueStacks or Add to list your emulators.", bg=card,
                     fg=C["secondary"], font=F["footnote"]).pack(pady=(px(2), px(18)))
            return
        for idx, it in enumerate(items):
            if idx:
                tk.Frame(self, height=1, bg=C["sep"]).pack(fill="x", padx=(px(36), 0))
            row = tk.Frame(self, bg=card, cursor="hand2")
            row.pack(fill="x")
            dot = ios.Dot(row, 10)
            dot.pack(side="left", padx=(px(14), px(12)))
            right = tk.Frame(row, bg=card)
            right.pack(side="right", padx=px(14))
            status = tk.Label(right, bg=card, font=F["footnote_semi"], anchor="e")
            status.pack(anchor="e")
            meta = tk.Label(right, bg=card, fg=C["secondary"], font=F["footnote"], anchor="e")
            meta.pack(anchor="e")
            mid = tk.Frame(row, bg=card)
            mid.pack(side="left", fill="x", expand=True, pady=px(9))
            title = tk.Label(mid, bg=card, fg=C["label"], font=F["body_semi"], anchor="w")
            title.pack(fill="x")
            sub = tk.Label(mid, bg=card, fg=C["secondary"], font=F["footnote"], anchor="w")
            sub.pack(fill="x")
            detail = tk.Label(mid, bg=card, fg=C["secondary"], font=F["footnote"], anchor="w")
            detail.pack(fill="x")
            for w in (row, dot, right, status, meta, mid, title, sub, detail):
                w.bind("<Button-1>", lambda e, n=it["name"]: self.select(n, user=True))
            self._rows[it["name"]] = {
                "dot": dot, "status": status, "meta": meta, "title": title, "sub": sub,
                "detail": detail, "color": None,
                "paint": [row, right, status, meta, mid, title, sub, detail]}

    def _update(self, it):
        r = self._rows[it["name"]]
        for key in ("title", "sub", "detail", "status", "meta"):
            if r[key].cget("text") != it[key]:
                r[key].configure(text=it[key])
        color = C[STATUS_COLOR.get(it["state"], "gray")]
        if r["color"] != color:
            r["color"] = color
            r["status"].configure(fg=color)
            r["dot"].set(color)

    def select(self, name: str | None, user: bool = False):
        self.sel = name
        self._paint()
        if user:
            self._on_select()

    def _paint(self):
        key = (self.sel, tuple(self._order))
        if key == self._painted:
            return
        self._painted = key
        for n, r in self._rows.items():
            bg = self._sel_bg if n == self.sel else C["card"]
            for w in r["paint"]:
                w.configure(bg=bg)
            r["dot"].set(bg=bg)


class StatTile(ios.Card):
    """A small card with a big number and a caption."""

    def __init__(self, parent, caption: str):
        super().__init__(parent, pad=4, radius=12)
        self.value = tk.Label(self.body, text="0", bg=C["card"], fg=C["label"], font=F["title"])
        self.value.pack(anchor="w", padx=px(8), pady=(px(4), 0))
        tk.Label(self.body, text=caption, bg=C["card"], fg=C["secondary"],
                 font=F["caption"]).pack(anchor="w", padx=px(8), pady=(0, px(5)))

    def set(self, text: str):
        if self.value.cget("text") != text:
            self.value.configure(text=text)


class RerunLink:
    """What GS Companion may ask of Rerun (gsc_app/page.py, `rerun=`): read-only facts
    about your roster and a way to show a unit in the Units tab. It never writes."""

    def __init__(self, app: "App"):  # noqa: F821 - App lives in gui.py; annotation only
        self.app = app

    @property
    def root(self):
        return self.app.m.root

    def unit_line(self, roster_name: str) -> str | None:
        return self.app.m.compendium.unit_line(roster_name)

    def show_unit(self, roster_name: str) -> bool:
        return self.app.show_in_units(roster_name)


ADB_HELP = ("In BlueStacks open Settings > Advanced and turn on 'Android Debug Bridge (ADB)'. "
            "It shows the address (127.0.0.1:<port>); then use Detect BlueStacks or Edit on the "
            "Dashboard so Rerun has the same address.")

DISPLAY_HELP = ("In BlueStacks open Settings > Display and choose 1280x720 (and DPI 240). "
                "Grand Summoners runs in portrait, so Rerun then sees 720x1280 frames - the size "
                "all templates were made for. Restart BlueStacks after changing it.")

DISCORD_GUIDE = """One-time setup, about 3 minutes:

1.  Go to https://discord.com/developers/applications and click "New Application".
2.  Open "Bot", click "Reset Token" and paste the token into Bot Token above. Keep it secret - anyone with it controls your bot.
3.  Open "OAuth2 > URL Generator": tick "bot" and "applications.commands", then under Bot Permissions tick "Send Messages", "Attach Files" and "Embed Links". Open the generated link and add the bot to your server.
4.  In Discord: Settings > Advanced > turn on Developer Mode. Right-click your alert channel > Copy Channel ID, and right-click your name > Copy User ID.
5.  Paste them above, put your User ID in Allowed User IDs, and press Save & Connect.

Slash commands:  /status  /start  /stop  /pause  /resume  /screenshot  /stats  /resetstats  /history  /summary  /scripts
Only the user IDs you allowed can start, stop, reset stats or take screenshots.

Alerts:  rare crests, Crest Bursts, hyper rare drops, failures, crashes and finished runs are posted to the alert channel, with a screenshot where useful, pinging the user ID above."""

__all__ = [
    "textnav",
    "LOG_FILE_LEVELS",
    "qol",
    "ADB_HELP",
    "ALL_INSTANCES",
    "APPEARANCE",
    "C",
    "DISCORD_GUIDE",
    "DISPLAY_HELP",
    "F",
    "HISTORY_KINDS",
    "IDLE_PREVIEW_EVERY_S",
    "Image",
    "ImageTk",
    "InstanceList",
    "LOG_LEVELS",
    "Manager",
    "Path",
    "RerunLink",
    "SCRIPTS",
    "STATUS_COLOR",
    "STATUS_TEXT",
    "STREAM_RETRY_S",
    "StatTile",
    "Tray",
    "UpdateError",
    "__version__",
    "cv2",
    "datetime",
    "discover_bluestacks_instances",
    "errlog",
    "filedialog",
    "fmt_duration",
    "ios",
    "make_icon",
    "np",
    "px",
    "queue",
    "re",
    "short",
    "threading",
    "time",
    "tk",
    "to_photo",
    "ttk",
    "updates",
]
