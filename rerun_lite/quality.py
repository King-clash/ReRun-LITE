"""Everyday workflow features: a command palette, shortcuts you can change, right-click menus, a template filter,
"copy status", and an Undo for removing an emulator.

Each one is a shortcut to something the app already does, not a new way to do it: the palette runs the same methods the
buttons run; the menus call the same methods as the buttons next to the list; undo puts back the list the removal replaced.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

from rerun import errlog, ios
from rerun.ios import C, F, px

from . import appearance as ap
from . import palaces, shortcuts


# ================================================================================ the palette
@dataclass(frozen=True)
class Command:
    title: str
    group: str
    run: object                      # a no-argument callable
    hint: str = ""                   # shown on the right (a key, a state)
    keywords: str = ""


def search(commands: list[Command], query: str, limit: int = 9) -> list[Command]:
    """Commands whose title, group or keywords contain every word of `query`, best first (title prefix, then position)."""
    words = query.lower().split()
    if not words:
        return list(commands)[:limit]
    scored = []
    for i, c in enumerate(commands):
        title = c.title.lower()
        hay = f"{title} {c.group.lower()} {c.keywords.lower()}"
        if not all(w in hay for w in words):
            continue
        score = sum((0 if title.startswith(w) else 1 if f" {w}" in f" {title}" else 2 if w in title else 3) for w in words)
        scored.append((score, title.find(words[0]) if words[0] in title else 99, i, c))
    scored.sort(key=lambda t: t[:3])
    return [t[3] for t in scored[:limit]]


class CommandPalette(tk.Toplevel):
    """Ctrl+K: type a few letters, press Enter. Esc, a click elsewhere, or running a command closes it."""

    def __init__(self, app, commands: list[Command]):
        super().__init__(app)
        self.app, self.commands, self.shown, self.sel = app, commands, [], 0
        self.overrideredirect(True)
        self.configure(bg=C["sep"])
        w = px(560)
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + px(70)
        self.geometry(f"{w}x{px(60)}+{x}+{y}")
        inner = tk.Frame(self, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        top = tk.Frame(inner, bg=C["card"])
        top.pack(fill="x", padx=px(14), pady=(px(12), px(8)))
        tk.Label(top, text=ios.icon_text("search") or "⌕", bg=C["card"], fg=C["secondary"],
                 font=F["icon"] if ios.ICON_FONT else F["body"]).pack(side="left", padx=(0, px(10)))
        self.var = tk.StringVar()
        self.entry = tk.Entry(top, textvariable=self.var, bg=C["card"], fg=C["label"], insertbackground=C["label"],
                              relief="flat", bd=0, highlightthickness=0, font=F["body"])
        self.entry.pack(side="left", fill="x", expand=True)
        tk.Label(top, text="Esc", bg=C["fill"], fg=C["secondary"], font=F["caption"], padx=px(5)).pack(side="right")
        tk.Frame(inner, height=1, bg=C["sep"]).pack(fill="x")
        self.rows = tk.Frame(inner, bg=C["card"])
        self.rows.pack(fill="x", pady=px(4))
        self.empty = tk.Label(inner, text="Nothing matches. Try a tab, a setting, or a look.", bg=C["card"], fg=C["secondary"],
                              font=F["footnote"])
        self.var.trace_add("write", lambda *a: self.refresh())
        self.entry.bind("<Escape>", lambda e: (self.close(), "break")[1])
        self.entry.bind("<Return>", lambda e: (self.run_selected(), "break")[1])
        self.entry.bind("<Down>", lambda e: (self.move(1), "break")[1])
        self.entry.bind("<Up>", lambda e: (self.move(-1), "break")[1])
        self.bind("<FocusOut>", lambda e: self.after(120, self._lost_focus))
        self.refresh()
        self.update_idletasks()
        self.entry.focus_force()

    def _lost_focus(self):
        try:
            if self.winfo_exists() and self.focus_get() is None:
                self.close()
        except (KeyError, tk.TclError):
            self.close()

    def refresh(self):
        for w in self.rows.winfo_children():
            w.destroy()
        self.shown = search(self.commands, self.var.get())
        self.sel = min(self.sel, max(len(self.shown) - 1, 0))
        self.empty.pack_forget()
        if not self.shown:
            self.empty.pack(pady=(px(6), px(14)))
        group = None
        for i, c in enumerate(self.shown):
            row = tk.Frame(self.rows, bg=C["card"], cursor="hand2")
            row.pack(fill="x", padx=px(6))
            if c.group != group and not self.var.get().strip():
                group = c.group
            tk.Label(row, text=c.title, bg=C["card"], fg=C["label"], font=F["body"], anchor="w").pack(
                side="left", padx=(px(10), 0), pady=px(5))
            tk.Label(row, text=c.group, bg=C["card"], fg=C["tertiary"], font=F["caption"]).pack(side="left", padx=(px(10), 0))
            if c.hint:
                tk.Label(row, text=c.hint, bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="right", padx=px(10))
            for w in (row, *row.winfo_children()):
                w.bind("<Button-1>", lambda e, i=i: self._click(i))
        self._paint()
        self.update_idletasks()
        self.geometry(f"{px(560)}x{self.winfo_reqheight()}")

    def _paint(self):
        for i, row in enumerate(self.rows.winfo_children()):
            bg = C["select"] if i == self.sel else C["card"]
            row.configure(bg=bg)
            for w in row.winfo_children():
                w.configure(bg=bg)

    def move(self, d: int):
        if self.shown:
            self.sel = (self.sel + d) % len(self.shown)
            self._paint()

    def _click(self, i: int):
        self.sel = i
        self.run_selected()

    def run_selected(self):
        if not self.shown:
            return
        cmd = self.shown[self.sel]
        self.close()
        self.app.after(30, cmd.run)

    def close(self):
        try:
            self.destroy()
        except tk.TclError:
            pass


# ================================================================================ the mixin
class QualityMixin:
    # ------------------------------------------------------------ commands
    def commands(self) -> list[Command]:
        sc = self._shortcuts
        out: list[Command] = []

        def hint(action: str) -> str:
            return shortcuts.describe(sc.get(action)) if sc.get(action) else ""
        go = [("Auto Crest", 0, "tab_crest"), ("History", 1, "tab_history"), ("Templates", 2, "tab_templates"), ("Settings", 3, "tab_settings")]
        for name, i, act in go:
            out.append(Command(f"Go to {name}", "Go", lambda i=i: self._go_tab(i), hint(act)))
        for key, label in (("crest", "Auto Crest settings"), ("palaces", "Palace Selector"), ("discord", "Discord alerts"),
                           ("appearance", "Appearance"), ("shortcuts", "Keyboard shortcuts"), ("app", "General settings"), ("log", "Log")):
            out.append(Command(f"Open {label}", "Settings", lambda k=key: self._open_section(k), keywords="settings"))
        out += [
            Command("Start Crest on the selected emulator", "Run", self._toggle_run, hint("start"), "play begin"),
            Command("Stop everything", "Run", self._stop_run, hint("stop"), "halt"),
            Command("Dry run (rehearse without tapping)", "Run", self.dry_run_sel, hint("dry_run"), "test"),
            Command("Pause or resume the selected emulator", "Run", self.pause_sel, "", "resume"),
            Command("Take a screenshot (Live View)", "Run", lambda: self.preview_shot(), "", "capture"),
            Command("Detect BlueStacks emulators", "Emulators", self.detect_instances, "", "add find"),
            Command("Add an emulator by hand", "Emulators", self.add_instance, "", "new"),
            Command("Copy a status summary", "Window", self.copy_status, hint("copy_status"), "clipboard"),
            Command("Keep the window on top (Pin)", "Window", self._toggle_pin, hint("pin"), "always on top float"),
            Command("Compact mode (small window)", "Window", self.toggle_compact, hint("compact"), "small mini minimal"),
            Command("Show the keyboard shortcuts", "Window", self.show_shortcuts, hint("help")),
            Command("Find older versions of ReRun LITE", "Window", self.show_old_versions, "", "remove delete clean up uninstall past previous"),
            Command("Open the data folder", "Window", self._open_data_folder, "", "files"),
            Command("Open the palace list", "Window", self._open_palace_file, "", "palaces.yaml"),
            Command("Import palace pictures from GS Companion", "Palaces", self._pal_import_from_palette, "", "banner images"),
            Command("Check for updates", "App", self.check_updates, "", "version"),
        ]
        cur = self._look
        for key, name in ap.LOOKS.items():
            out.append(Command(f"Look: {name}", "Appearance", lambda k=key: self.set_look(k), "now" if cur.look == key else "",
                               "theme style"))
        for key, name in ap.MODES.items():
            out.append(Command(f"Mode: {name}", "Appearance", lambda k=key: self.set_mode(k), "now" if cur.mode == key else "",
                               "dark light system theme"))
        for name, hexv in ap.ACCENTS.items():
            out.append(Command(f"Accent: {name}", "Appearance", lambda h=hexv: self.set_accent(h), hexv, "colour color"))
        out.append(Command("Accent: the look's own", "Appearance", lambda: self.set_accent(""), "", "reset colour"))
        for key, name in ap.DENSITIES.items():
            out.append(Command(f"Density: {name}", "Appearance", lambda k=key: self._ap_set(density=k), "now" if cur.density == key else "",
                               "spacing compact"))
        out.append(Command("Background: switch the video off", "Appearance", lambda: self._ap_set(background="off"), "", "animation"))
        return out

    def open_palette(self):
        old = getattr(self, "_palette", None)
        if old is not None:
            try:
                if old.winfo_exists():
                    old.close()
                    return "break"
            except tk.TclError:
                pass
        self._palette = CommandPalette(self, self.commands())
        return "break"

    def _open_section(self, key: str):
        self.nb.select(self._tab_settings)
        self._set_nav.select(key)

    def _pal_import_from_palette(self):
        self._open_section("palaces")
        self.after(80, self._pal_import)

    # ------------------------------------------------------------ shortcuts
    def _build_quality(self):
        """After the pages exist: the keys, the right-click menus, the template filter."""
        if getattr(self, "_shortcuts", None) is None:
            self._shortcuts = shortcuts.Shortcuts(self._ui_state().get("shortcuts"))
        self._bind_shortcuts()
        self._bind_context_menus()
        self._build_template_filter()

    def _shortcut_handlers(self) -> dict:
        return {
            "palette": self.open_palette, "tab_crest": lambda: self._go_tab(0), "tab_history": lambda: self._go_tab(1),
            "tab_templates": lambda: self._go_tab(2), "tab_settings": lambda: self._go_tab(3),
            "settings": lambda: self._go_tab(self._tab_settings), "next_tab": lambda: self._cycle_tab(1),
            "prev_tab": lambda: self._cycle_tab(-1), "start": self._toggle_run, "stop": self._stop_run,
            "dry_run": self.dry_run_sel, "pin": self._toggle_pin, "compact": self.toggle_compact, "copy_status": self.copy_status, "help": self.show_shortcuts,
        }

    def _bind_shortcuts(self):
        """(Re)bind every action's key. Called after the keys change, and after the window is rebuilt."""
        for seq in getattr(self, "_bound_keys", ()):
            self.unbind_all(seq)
        self._bound_keys = []
        handlers = self._shortcut_handlers()
        for action, fn in handlers.items():
            seq = shortcuts.to_tk(self._shortcuts.get(action))
            if not seq:
                continue
            self.bind_all(seq, lambda e, fn=fn: (fn(), "break")[1])
            self._bound_keys.append(seq)

    def save_shortcuts(self):
        self._bg_save(shortcuts=self._shortcuts.changed())
        self._bind_shortcuts()

    def show_shortcuts(self):
        sc = self._shortcuts
        rows = [f"{shortcuts.describe(sc.get(a.id)):<18} {a.label}" for a in shortcuts.ACTIONS]
        rows += ["", *(f"{g.split(' ', 1)[0]:<18} {g.split(' ', 1)[1]}" for g in shortcuts.GLOBAL_HOTKEYS),
                 "", "Change any of these in Settings > Keyboard shortcuts."]
        ios.alert(self, "\n".join(rows), "Keyboard shortcuts")

    # ------------------------------------------------------------ copy
    def status_summary(self) -> str:
        lines = ["ReRun LITE status"]
        for name, inst in self.m.instances.items():
            lines.append(f"- {name} ({inst.serial}): {inst.status}")
        try:
            t = self.m.totals()
            lines.append(f"Runs {t.get('runs', 0)}, crests kept {t.get('kept', 0)}, scrapped {t.get('scrapped', 0)}")
        except Exception as e:  # noqa: BLE001 - a summary must never fail
            errlog.note("lite.summary", e)
        c = palaces.choose(self.m.root)
        if c.mode != "off" and c.palace is not None:
            lines.append(f"Palace today ({c.day}): {c.palace.name}" + ("" if c.ok else " - picture missing"))
        return "\n".join(lines)

    def copy_status(self):
        text = self.status_summary()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.flash("Status copied to the clipboard", "ok")

    # ------------------------------------------------------------ right-click menus
    def _menu(self, items: list) -> tk.Menu:
        """A menu in the window's colours. items: (label, callable) or None for a divider."""
        m = tk.Menu(self, tearoff=0, bg=C["menu"], fg=C["label"], activebackground=C["select"], activeforeground=C["label"],
                    bd=0, relief="flat", font=F["body"], activeborderwidth=0)
        for it in items:
            if it is None:
                m.add_separator()
            else:
                label, fn = it[0], it[1]
                m.add_command(label=label, command=fn, state=("normal" if len(it) < 3 or it[2] else "disabled"))
        return m

    def _popup(self, menu: tk.Menu, e):
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _bind_context_menus(self):
        self._bind_instance_menu()
        for w in (getattr(self, "log_box", None),):
            if w is not None:
                w.bind("<Button-3>", self._log_menu)
        tree = getattr(self, "hist_tree", None)
        if tree is not None:
            tree.bind("<Button-3>", self._history_menu)
        tpl = getattr(self, "tpl_tree", None)
        if tpl is not None:
            tpl.bind("<Button-3>", self._template_menu)

    def _bind_instance_menu(self):
        lst = getattr(self, "inst_list", None)
        if lst is None:
            return
        if not getattr(lst, "_menu_wrapped", False):          # rows are rebuilt when the list changes: bind again each time
            lst._menu_wrapped = True
            plain = lst.set_rows

            def set_rows(items, _plain=plain):
                _plain(items)
                self._bind_instance_menu()
            lst.set_rows = set_rows
        for name, r in lst._rows.items():
            for w in (r["dot"], *r["paint"]):
                w.bind("<Button-3>", lambda e, n=name: self._instance_menu(e, n))

    def _instance_menu(self, e, name: str):
        self.inst_list.select(name, user=True)
        inst = self.m.instances.get(name)
        if inst is None:
            return "break"
        idle = inst.status in ("idle", "error")
        items = [("Start Crest", self.start_sel, idle), ("Dry run", self.dry_run_sel, idle),
                 ("Pause / resume", self.pause_sel, not idle), ("Stop", self.stop_sel, not idle), None,
                 ("Copy address", lambda: self._copy(inst.serial)), ("Edit address…", self.edit_instance, idle),
                 ("Remove…", self.remove_instance, idle)]
        return self._popup(self._menu(items), e)

    def _copy(self, text: str, what: str = "Copied"):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.flash(f"{what}: {text[:60]}", "ok")

    def _log_menu(self, e):
        box = self.log_box
        try:
            selected = box.get("sel.first", "sel.last")
        except tk.TclError:
            selected = ""
        items = [("Copy selection", lambda: self._copy(selected, "Copied"), bool(selected)),
                 ("Copy everything shown", lambda: self._copy(box.get("1.0", "end").strip(), "Copied the log"))]
        return self._popup(self._menu(items), e)

    def _history_menu(self, e):
        tree = self.hist_tree
        iid = tree.identify_row(e.y)
        if iid:
            tree.selection_set(iid)
        vals = tree.item(iid, "values") if iid else ()
        items = [("Copy this entry", lambda: self._copy("  ".join(str(v) for v in vals).strip()), bool(vals))]
        return self._popup(self._menu(items), e)

    def _template_menu(self, e):
        tree = self.tpl_tree
        iid = tree.identify_row(e.y)
        if iid:
            tree.selection_set(iid)
        items = [("Copy template name", lambda: self._copy(iid, "Copied"), bool(iid)),
                 ("Take a screenshot to capture it", self.tpl_screenshot, bool(iid))]
        return self._popup(self._menu(items), e)

    # ------------------------------------------------------------ templates: search and "missing only"
    def _build_template_filter(self):
        tree = getattr(self, "tpl_tree", None)
        if tree is None:
            return
        card = tree.master.master                              # the list's card
        bar = tk.Frame(card.master, bg=C["bg"])
        self._tpl_query = tk.StringVar()
        self._tpl_missing = tk.BooleanVar(value=False)
        self._tpl_hidden: list[str] = []
        fld = ios.Field(bar, self._tpl_query, width=14)
        fld.pack(side="left", fill="x", expand=True)
        tk.Label(bar, text="Missing only", bg=C["bg"], fg=C["secondary"], font=F["footnote"]).pack(side="left", padx=(px(10), px(6)))
        ios.Switch(bar, self._tpl_missing, command=self.refresh_checklist).pack(side="left")
        bar.pack(before=card, fill="x", pady=(0, px(6)))
        fld.entry.bind("<KeyRelease>", lambda e: self.refresh_checklist())
        self._tpl_note = tk.Label(card.master, text="", bg=C["bg"], fg=C["secondary"], font=F["footnote"], anchor="w")

    def refresh_checklist(self):
        tree = getattr(self, "tpl_tree", None)
        hidden = getattr(self, "_tpl_hidden", None)
        if tree is not None and hidden:                        # bring back what the last filter hid, so the original rebuilds all
            for iid in hidden:
                try:
                    tree.reattach(iid, "", "end")
                except tk.TclError:
                    pass
            self._tpl_hidden = []
        super().refresh_checklist()
        if tree is None or not hasattr(self, "_tpl_query"):
            return
        q = self._tpl_query.get().strip().lower()
        only_missing = bool(self._tpl_missing.get())
        if not q and not only_missing:
            return
        for iid in tree.get_children():
            missing = "missing" in tree.item(iid, "tags")
            if (q and q not in iid.lower()) or (only_missing and not missing):
                tree.detach(iid)
                self._tpl_hidden.append(iid)

    # ------------------------------------------------------------ buttons that do not apply look switched off
    def _refresh_status(self):
        super()._refresh_status()
        self._sync_run_buttons()

    def _sync_run_buttons(self):
        """Start and Dry Run work on an idle emulator; Pause and Stop on a busy one. The others look switched off."""
        pause = getattr(self, "pause_btn", None)
        if pause is None or not pause.winfo_exists():
            return
        inst = self.m.instances.get(self.selected() or "")
        idle = inst is None or inst.status in ("idle", "error")
        for b in pause.master.winfo_children():
            if isinstance(b, ios.Button):
                want = (idle and inst is not None) if b._text in ("Start", "Dry Run") else (not idle) if b._text in ("Pause", "Resume", "Stop") else None
                if want is not None and b._enabled != want:
                    b.set_enabled(want)

    # ------------------------------------------------------------ undo for removing an emulator
    def remove_instance(self):
        name = self.selected()
        before = list(self._instance_items()) if name else []
        super().remove_instance()
        if name and name not in self.m.instances and before:
            self.snack(f"Removed {name}", "Undo", lambda: self._restore_instances(before, name))

    def _restore_instances(self, items: list, name: str):
        if name in self.m.instances:
            return
        self.m.set_instances(items)
        self.refresh_instances()
        self.flash(f"Put {name} back", "ok")

    def snack(self, text: str, action: str, command, seconds: float = 8.0):
        """A bar at the bottom of the window with one action (Undo). It goes by itself."""
        old = getattr(self, "_snack", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        bar = tk.Frame(self, bg=C["menu"], highlightthickness=1, highlightbackground=C["sep"])
        tk.Label(bar, text=text, bg=C["menu"], fg=C["label"], font=F["body"]).pack(side="left", padx=(px(14), px(10)), pady=px(8))
        link = tk.Label(bar, text=action, bg=C["menu"], fg=C["blue"], font=F["body_semi"], cursor="hand2")
        link.pack(side="left", padx=(0, px(14)))

        def run(_e=None):
            bar.destroy()
            command()
        link.bind("<Button-1>", run)
        bar.place(relx=0.5, rely=1.0, y=-px(52), anchor="s")
        bar.lift()
        self._snack = bar
        self.after(int(seconds * 1000), lambda: bar.winfo_exists() and bar.destroy())
