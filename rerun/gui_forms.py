"""Small shared GUI helpers for the Account Manager and Macro Farming workspaces: a form dialog that stays open
until the input is valid, and time formatting."""
from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime

from . import ios
from .ios import C, F, px


def ago(t: float | None, now: float | None = None) -> str:
    if not t:
        return "never"
    s = max(0, int((now or time.time()) - t))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


def stamp(t: float | None) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "-"


def parse_datetime(text: str) -> float:
    """'2026-11-20' or '2026-11-20 18:30' (local time) -> timestamp. Raises ValueError with a readable message."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a date. Use YYYY-MM-DD or YYYY-MM-DD HH:MM.")


def form_dialog(app, title: str, fields: list[dict], submit, ok: str = "Save", intro: str = "") -> bool:
    """Modal form. fields: dicts with key, label, kind (text|number|select|check|multiline), value, options, hint.
    `submit(values)` returns None when accepted or an error sentence - the dialog then stays open and shows it.
    Returns True when accepted."""
    win = tk.Toplevel(app, bg=C["bg"])
    win.title(title)
    win.transient(app)
    win.iconphoto(False, app._icon)
    win.geometry(f"{px(520)}x{px(min(700, 150 + 62 * len(fields) + (90 if intro else 0)))}")
    win.minsize(px(440), px(260))
    app.after(10, lambda: ios.style_window(win))
    tk.Label(win, text=title, bg=C["bg"], fg=C["label"], font=F["title"], anchor="w").pack(fill="x", padx=px(20), pady=(px(16), px(4)))
    if intro:
        ios.wrapped_label(win, intro).pack(fill="x", padx=px(20), pady=(0, px(6)))
    body = tk.Frame(win, bg=C["bg"])
    body.pack(fill="both", expand=True, padx=px(20), pady=px(6))
    vars_: dict[str, tk.Variable] = {}
    texts: dict[str, tk.Text] = {}
    first = None
    for f in fields:
        row = tk.Frame(body, bg=C["bg"])
        row.pack(fill="x", pady=px(4))
        tk.Label(row, text=f["label"], bg=C["bg"], fg=C["label"], font=F["footnote_semi"], anchor="w").pack(fill="x")
        kind = f.get("kind", "text")
        if kind == "check":
            v = tk.BooleanVar(value=bool(f.get("value")))
            ios.Switch(row, v).pack(anchor="w", pady=px(2))
        elif kind == "select":
            v = tk.StringVar(value=str(f.get("value", "")))
            sel = ios.Select(row, values=list(f.get("options", [])), variable=v, accent=True)
            sel.pack(anchor="w", pady=px(2))
        elif kind == "multiline":
            v = None
            card, tx = ios.text_box(row, wrap="word")      # packs itself
            tx.configure(height=4)
            tx.insert("1.0", str(f.get("value", "")))
            texts[f["key"]] = tx
        else:
            v = tk.StringVar(value="" if f.get("value") is None else str(f.get("value", "")))
            fld = ios.Field(row, v, width=36)
            fld.pack(fill="x")
            first = first or fld.entry
        if v is not None:
            vars_[f["key"]] = v
        if f.get("hint"):
            ios.wrapped_label(row, f["hint"], font="caption").pack(fill="x")
    err = tk.Label(win, text="", bg=C["bg"], fg=C["red"], font=F["footnote"], anchor="w", justify="left")
    err.pack(fill="x", padx=px(20))
    err.bind("<Configure>", lambda e: err.configure(wraplength=max(200, e.width - 8)))
    done = {"ok": False}

    def values() -> dict:
        out = {k: v.get() for k, v in vars_.items()}
        out.update({k: t.get("1.0", "end").strip() for k, t in texts.items()})
        return out

    def go(_e=None):
        msg = submit(values())
        if msg:
            err.configure(text=msg)
            return
        done["ok"] = True
        win.destroy()

    bar = tk.Frame(win, bg=C["bg"])
    bar.pack(fill="x", padx=px(20), pady=(px(6), px(16)))
    ios.Button(bar, ok, go, icon="save").pack(side="right")
    ios.Button(bar, "Cancel", win.destroy, kind="gray").pack(side="right", padx=px(8))
    win.bind("<Escape>", lambda e: win.destroy())
    if not texts:
        win.bind("<Return>", go)
    try:
        win.grab_set()
    except tk.TclError:
        pass
    (first or win).focus_set()
    app.wait_window(win)
    return done["ok"]
