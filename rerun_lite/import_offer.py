"""The "Bring your data over?" window, before sign-in, for a new ReRun LITE folder that finds older data.

Same job as rerun/migrate_ui.py (and it uses the same copying code), but easier to read at a glance:

  * only the MOST RECENT data is shown, already chosen: press Import and you are done;
  * every older folder is tucked into an "Older data (N)" drop-down that stays closed until you open it;
  * "Choose folder…" adds a folder of your own to that drop-down and selects it.

The window is drawn in the chosen theme (Ahri, Dark, Light), like the rest of ReRun LITE.
"""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from PIL import ImageTk

from rerun import ios
from rerun.ios import C, F, px
from rerun.migrate import (data_time, describe, find_previous, has_user_data, import_data, mark_declined, summary,
                           was_declined)

from . import APP_NAME
from .icon import make_lite_icon


def ago(stamp: float, now: float | None = None) -> str:
    """'today', 'yesterday', '5 days ago', '3 weeks ago', 'over a year ago' for a file time."""
    if not stamp:
        return "unknown"
    days = int(((now or time.time()) - stamp) // 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    if days < 365:
        return f"{days // 30} months ago"
    return "over a year ago"


class ImportPage(tk.Frame):
    def __init__(self, parent, root: Path, candidates: list[Path], on_done):
        super().__init__(parent, bg=C["bg"])
        self.root, self.on_done = Path(root), on_done
        ordered = sorted(candidates, key=data_time, reverse=True)           # newest data first
        self.newest = ordered[0] if ordered else None
        self.older: list[Path] = ordered[1:]
        self.choice = tk.StringVar(value=str(self.newest) if self.newest else "")
        self.open = False
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(expand=True, fill="both", padx=px(30), pady=px(24))
        self._icon = ImageTk.PhotoImage(make_lite_icon(px(64)))
        tk.Label(wrap, image=self._icon, bg=C["bg"]).pack()
        tk.Label(wrap, text="Bring your data over?", bg=C["bg"], fg=C["label"], font=F["large"]).pack(pady=(px(8), px(2)))
        tk.Label(wrap, bg=C["bg"], fg=C["secondary"], font=F["footnote"], justify="center", wraplength=px(540),
                 text=f"This copy of {APP_NAME} has no data yet. Copy your settings, stats, crest log, History and key "
                      "from your most recent ReRun? The old folder is not changed.").pack()

        tk.Label(wrap, text="MOST RECENT", bg=C["bg"], fg=C["secondary"], font=F["caption"], anchor="w").pack(
            fill="x", pady=(px(16), px(4)), padx=px(4))
        top = ios.Card(wrap, pad=10, radius=10)
        top.pack(fill="x")
        self.top_body = top.body
        if self.newest is not None:
            self._row(top.body, self.newest, headline=True)

        self.toggle = tk.Label(wrap, text="", bg=C["bg"], fg=C["blue"], font=F["body_semi"], cursor="hand2", anchor="w")
        self.older_host = tk.Frame(wrap, bg=C["bg"])
        self.older_card = ios.Card(self.older_host, pad=10, radius=10)
        self.older_card.pack(fill="x", pady=(px(6), 0))
        self.toggle.bind("<Button-1>", lambda e: self.toggle_older())
        for folder in self.older:
            self._row(self.older_card.body, folder)
        self._refresh_toggle()
        if self.older:
            self.toggle.pack(fill="x", pady=(px(12), 0), padx=px(4))

        self.msg = tk.Label(wrap, text="", bg=C["bg"], fg=C["red"], font=F["footnote"], wraplength=px(540))
        self.msg.pack(pady=(px(6), 0))
        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(fill="x", pady=(px(10), 0))
        ios.Button(btns, "Import", self.do_import).pack(side="right")
        ios.Button(btns, "Start fresh", self.fresh, kind="gray").pack(side="right", padx=(0, px(10)))
        ios.Button(btns, "Choose folder…", self.choose, kind="plain", small=True).pack(side="left")

    # ------------------------------------------------------------ rows
    def _row(self, parent, folder: Path, headline: bool = False):
        if parent.winfo_children():
            tk.Frame(parent, height=1, bg=C["sep"]).pack(fill="x", pady=px(4))
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=px(2))
        tk.Radiobutton(row, variable=self.choice, value=str(folder), bg=C["card"], activebackground=C["card"],
                       selectcolor=C["card"], fg=C["label"], highlightthickness=0, bd=0).pack(side="left", anchor="n")
        txt = tk.Frame(row, bg=C["card"])
        txt.pack(side="left", fill="x", expand=True)
        when = ago(data_time(folder))
        head = tk.Frame(txt, bg=C["card"])
        head.pack(fill="x")
        tk.Label(head, text=folder.name or str(folder), bg=C["card"], fg=C["label"], font=F["body_semi"], anchor="w").pack(side="left")
        tk.Label(head, text=f"  last used {when}", bg=C["card"], fg=C["green"] if headline else C["secondary"],
                 font=F["footnote"], anchor="w").pack(side="left")
        tk.Label(txt, text=str(folder), bg=C["card"], fg=C["secondary"], font=F["footnote"], anchor="w").pack(fill="x")
        tk.Label(txt, text=describe(folder).split("  (last used")[0] or "your data", bg=C["card"], fg=C["secondary"],
                 font=F["footnote"], anchor="w").pack(fill="x")

    def _refresh_toggle(self):
        n = len(self.older)
        self.toggle.configure(text=f"{'▾' if self.open else '▸'}  Older data ({n})")

    def toggle_older(self, force: bool | None = None):
        self.open = (not self.open) if force is None else force
        if self.open:
            self.older_host.pack(fill="x", after=self.toggle)
        else:
            self.older_host.pack_forget()
        self._refresh_toggle()
        top = self.winfo_toplevel()
        x, y = top.winfo_x(), top.winfo_y()
        top.geometry("")                                          # grow or shrink to fit ...
        top.update_idletasks()
        top.geometry(f"+{x}+{y}")                                 # ... and stay where it is

    # ------------------------------------------------------------ actions
    def choose(self):
        d = filedialog.askdirectory(parent=self, title="Folder of your previous ReRun")
        if not d:
            return
        p = Path(d)
        if not has_user_data(p):
            self.msg.configure(text="That folder has no ReRun data (no stats, History or key).")
            return
        known = {str(self.newest)} | {str(o) for o in self.older}
        if str(p) not in known:
            self.older.append(p)
            self._row(self.older_card.body, p)
            if not self.toggle.winfo_manager():
                self.toggle.pack(fill="x", pady=(px(12), 0), padx=px(4))
            self._refresh_toggle()
        self.choice.set(str(p))
        if str(p) != str(self.newest):
            self.toggle_older(True)
        self.msg.configure(text="")

    def do_import(self):
        src = self.choice.get()
        if not src:
            self.msg.configure(text="Pick a folder first (or Start fresh).")
            return
        try:
            done = import_data(src, self.root)
        except (OSError, ValueError) as e:
            self.msg.configure(text=f"Could not import: {e}")
            return
        self.on_done(f"Copied from {src}: {summary(done)}.")

    def fresh(self):
        mark_declined(self.root)
        self.on_done(None)


def offer_import(root: str | Path, appearance: str = "auto") -> str | None:
    """Before sign-in. Returns a summary of what was copied, or None."""
    root = Path(root)
    if has_user_data(root) or was_declined(root):
        return None
    candidates = find_previous(root)
    if not candidates:
        return None
    win = tk.Tk()
    ios.init(win, appearance)
    win.title(f"{APP_NAME} - Bring your data over")
    win.configure(bg=C["bg"])
    win.resizable(False, False)
    icon = ImageTk.PhotoImage(make_lite_icon(64))
    win.iconphoto(True, icon)
    out: dict = {}

    def done(result):
        out["r"] = result
        win.destroy()

    ImportPage(win, root, candidates, done).pack(fill="both", expand=True)
    win.protocol("WM_DELETE_WINDOW", lambda: done(None))          # closing = ask again next time
    win.after(10, lambda: ios.style_window(win))
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"+{(win.winfo_screenwidth() - w) // 2}+{(win.winfo_screenheight() - h) // 3}")
    win.mainloop()
    return out.get("r")


__all__ = ["ImportPage", "offer_import", "ago"]
