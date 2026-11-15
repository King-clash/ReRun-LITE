"""The sign-in screen: Rerun opens only after a valid key (rerun/license.py).

require_key(root)      before the app starts: the saved key if still valid, else this
                       window; None when you quit.
ask_key(master, ...)   the same as a dialog over the running app (key expired, or
                       "Change key").
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import ImageTk

from . import ios
from .appicon import make_icon
from .ios import C, F, px
from .license import KeyError_, KeyStore, License, check, format_pc, machine_id


class SignIn(tk.Frame):
    """Icon, 'Sign in to Rerun', key box, this PC's ID, Quit / Sign In."""

    def __init__(self, parent, store: KeyStore, reason: str = "", on_done=None,
                 quit_text: str = "Quit"):
        super().__init__(parent, bg=C["bg"])
        self.store, self.on_done = store, on_done
        self.result: License | None = None
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(expand=True, padx=px(32), pady=px(26))
        self._icon = ImageTk.PhotoImage(make_icon(px(84)))
        tk.Label(wrap, image=self._icon, bg=C["bg"]).pack()
        tk.Label(wrap, text="Sign in to Rerun", bg=C["bg"], fg=C["label"],
                 font=F["large"]).pack(pady=(px(10), px(2)))
        tk.Label(wrap, text="Paste the key you were given. It starts with RERUN-",
                 bg=C["bg"], fg=C["secondary"], font=F["footnote"]).pack()

        card = ios.Card(wrap, pad=8, radius=10, color=C["field"])
        card.pack(fill="x", pady=(px(14), px(6)))
        self.text = tk.Text(card.body, height=4, width=46, wrap="char", bd=0, relief="flat",
                            bg=C["field"], fg=C["label"], insertbackground=C["label"],
                            selectbackground=C["blue"], font=F["mono"])
        self.text.pack(fill="x")
        saved = store.saved_key()
        if saved:
            self.text.insert("1.0", saved)
        self.text.bind("<Return>", lambda e: (self.submit(), "break")[1])

        self.msg = tk.Label(wrap, text=reason, bg=C["bg"], fg=C["red"], font=F["footnote"],
                            wraplength=px(420), justify="center")
        self.msg.pack(pady=(0, px(8)))

        pcrow = tk.Frame(wrap, bg=C["bg"])
        pcrow.pack(pady=(0, px(14)))
        self.pc = format_pc(machine_id())
        tk.Label(pcrow, text=f"This PC's ID:  {self.pc}", bg=C["bg"], fg=C["secondary"],
                 font=F["footnote"]).pack(side="left")
        ios.Button(pcrow, "Copy", self.copy_pc, kind="plain", small=True).pack(side="left", padx=(px(10), 0))

        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(fill="x")
        ios.Button(btns, "Sign In", self.submit).pack(side="right")
        ios.Button(btns, quit_text, self.cancel, kind="gray").pack(side="right", padx=(0, px(10)))
        ios.Button(btns, "Paste", self.paste, kind="plain", small=True).pack(side="left")
        self.after(50, self.text.focus_set)

    def key_text(self) -> str:
        return self.text.get("1.0", "end").strip()

    def paste(self):
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", clip.strip())

    def copy_pc(self):
        self.clipboard_clear()
        self.clipboard_append(self.pc)
        self.msg.configure(text="PC ID copied - send it to whoever gives you keys if they "
                                "lock keys to one PC.", fg=C["secondary"])

    def submit(self, now: float | None = None):
        try:
            lic = check(self.key_text(), now, self.store.last_seen)
        except KeyError_ as e:
            self.msg.configure(text=str(e), fg=C["red"])
            return
        self.store.save(lic.key, now)
        self.result = lic
        if self.on_done:
            self.on_done(lic)

    def cancel(self):
        self.result = None
        if self.on_done:
            self.on_done(None)


def _appearance(root: Path) -> str:
    try:
        import yaml
        cfg = yaml.safe_load((Path(root) / "config.yaml").read_text(encoding="utf-8")) or {}
        return str(cfg.get("appearance", "auto"))
    except Exception:  # noqa: BLE001
        return "auto"


def require_key(root: str | Path) -> License | None:
    """Before Rerun starts. Returns the valid License, or None if you quit."""
    store = KeyStore(root)
    try:
        lic = store.current()
        store.touch()
        return lic
    except KeyError_ as e:
        reason = "" if not store.saved_key() else str(e)
    win = tk.Tk()
    ios.init(win, _appearance(root))
    win.title("Rerun - Sign In")
    win.configure(bg=C["bg"])
    win.resizable(False, False)
    icon = ImageTk.PhotoImage(make_icon(64))
    win.iconphoto(True, icon)
    out: dict = {}

    def done(lic):
        out["lic"] = lic
        win.destroy()

    page = SignIn(win, store, reason, on_done=done)
    page.pack(fill="both", expand=True)
    win.protocol("WM_DELETE_WINDOW", lambda: done(None))
    win.after(10, lambda: ios.style_window(win))
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"+{(win.winfo_screenwidth() - w) // 2}+{(win.winfo_screenheight() - h) // 3}")
    win.mainloop()
    return out.get("lic")


def ask_key(master: tk.Misc, store: KeyStore, reason: str = "",
            quit_text: str = "Quit Rerun") -> License | None:
    """Modal sign-in over the running app. None when you choose quit."""
    top = tk.Toplevel(master)
    top.title("Rerun - Sign In")
    top.configure(bg=C["bg"])
    top.resizable(False, False)
    top.transient(master)
    out: dict = {}

    def done(lic):
        out["lic"] = lic
        top.destroy()

    SignIn(top, store, reason, on_done=done, quit_text=quit_text).pack(fill="both", expand=True)
    top.protocol("WM_DELETE_WINDOW", lambda: done(None))
    top.update_idletasks()
    try:
        x = master.winfo_rootx() + (master.winfo_width() - top.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - top.winfo_reqheight()) // 3
        top.geometry(f"+{max(0, x)}+{max(0, y)}")
    except tk.TclError:
        pass
    top.grab_set()
    top.after(10, lambda: ios.style_window(top))
    master.wait_window(top)
    return out.get("lic")


__all__ = ["SignIn", "require_key", "ask_key"]
