"""The "Bring your data over?" window a new Rerun copy shows before sign-in when it has no
data of its own but an older Rerun folder has (rerun/migrate.py)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from PIL import ImageTk

from . import ios
from .appicon import make_icon
from .ios import C, F, px
from .migrate import describe, find_previous, has_user_data, import_data, mark_declined, \
    richness, summary, was_declined


class ImportPage(tk.Frame):
    def __init__(self, parent, root: Path, candidates: list[Path], on_done):
        super().__init__(parent, bg=C["bg"])
        self.root, self.on_done = Path(root), on_done
        self.choice = tk.StringVar(value=str(max(candidates, key=richness)) if candidates else "")
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(expand=True, fill="both", padx=px(28), pady=px(22))
        self._icon = ImageTk.PhotoImage(make_icon(px(64)))
        tk.Label(wrap, image=self._icon, bg=C["bg"]).pack()
        tk.Label(wrap, text="Bring your data over?", bg=C["bg"], fg=C["label"],
                 font=F["large"]).pack(pady=(px(8), px(2)))
        tk.Label(wrap, bg=C["bg"], fg=C["secondary"], font=F["footnote"], justify="center",
                 wraplength=px(520),
                 text="This copy of Rerun has no data yet. Copy your settings, stats, crest log, "
                      "History, units, key and templates from your previous Rerun? "
                      "The old folder is not changed.").pack()
        g = ios.Card(wrap, pad=10, radius=10)
        g.pack(fill="x", pady=(px(14), px(8)))
        self.list = g.body
        for c in candidates:
            self._add(c)
        self.msg = tk.Label(wrap, text="", bg=C["bg"], fg=C["red"], font=F["footnote"],
                            wraplength=px(520))
        self.msg.pack()
        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(fill="x", pady=(px(10), 0))
        ios.Button(btns, "Import", self.do_import).pack(side="right")
        ios.Button(btns, "Start fresh", self.fresh, kind="gray").pack(side="right", padx=(0, px(10)))
        ios.Button(btns, "Choose folder…", self.choose, kind="plain", small=True).pack(side="left")

    def _add(self, folder: Path):
        row = tk.Frame(self.list, bg=C["card"])
        row.pack(fill="x", pady=px(3))
        tk.Radiobutton(row, variable=self.choice, value=str(folder), bg=C["card"],
                       activebackground=C["card"], selectcolor=C["card"], fg=C["label"],
                       highlightthickness=0, bd=0).pack(side="left", anchor="n")
        txt = tk.Frame(row, bg=C["card"])
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=str(folder), bg=C["card"], fg=C["label"], font=F["body"],
                 anchor="w").pack(fill="x")
        tk.Label(txt, text=describe(folder), bg=C["card"], fg=C["secondary"], font=F["footnote"],
                 anchor="w").pack(fill="x")

    def choose(self):
        d = filedialog.askdirectory(parent=self, title="Folder of your previous Rerun")
        if not d:
            return
        p = Path(d)
        if not has_user_data(p):
            self.msg.configure(text="That folder has no Rerun data (no stats, History, units or key).")
            return
        self._add(p)
        self.choice.set(str(p))
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
    win.title("Rerun - Bring your data over")
    win.configure(bg=C["bg"])
    win.resizable(False, False)
    icon = ImageTk.PhotoImage(make_icon(64))
    win.iconphoto(True, icon)
    out: dict = {}

    def done(result):
        out["r"] = result
        win.destroy()

    ImportPage(win, root, candidates, done).pack(fill="both", expand=True)
    win.protocol("WM_DELETE_WINDOW", lambda: done(None))   # closing = ask again next time
    win.after(10, lambda: ios.style_window(win))
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"+{(win.winfo_screenwidth() - w) // 2}+{(win.winfo_screenheight() - h) // 3}")
    win.mainloop()
    return out.get("r")


__all__ = ["ImportPage", "offer_import"]
