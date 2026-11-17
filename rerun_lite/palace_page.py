"""Settings > Palace Selector: the page for the daily Crest Palace selector (logic in palaces.py)."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog

from rerun import errlog, ios
from rerun.ios import C, F, px

from . import palaces

NONE = "(none)"


class PalacePageMixin:
    def _build_palace_page(self):
        _, page, hdr = self._page("Palace Selector", "Settings", "settings", scroll=True)
        ios.Button(hdr, "Import from GS Companion…", self._pal_import, kind="tinted", icon="download",
                   small=True).pack(side="right")
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="x", padx=px(20))
        self._pal_wrap, self._pal_busy = wrap, False
        self._pal_vars: dict[str, ios.Select] = {}
        self._pal_build()

    # ------------------------------------------------------------ build / rebuild
    def _pal_build(self):
        wrap = self._pal_wrap
        for w in wrap.winfo_children():
            w.destroy()
        root = self.m.root
        try:
            plist = palaces.read_list(root)
            err = ""
        except ValueError as e:
            plist, err = [], str(e)
        names = [p.name for p in plist]
        sched = palaces.load_schedule(root)
        self._pal_names = names

        g = ios.Group(wrap, header="Selector",
                      footer="Picks which Crest Palace to open, by the game's day (it turns over at the 6 AM UTC-6 reset, "
                             "not at your PC's midnight). Off: Crest uses its own palace settings as before.")
        g.pack(fill="x", pady=(px(14), 0))
        self._pal_mode = ios.Select(g.row("Mode"), values=list(palaces.MODES.values()), command=self._pal_save)
        self._pal_mode.set(palaces.MODES[sched.mode])
        self._pal_mode.pack()

        gz = ios.Group(wrap, header="Time zone",
                       footer="Only changes how each palace's slot is shown below (its start and end in your day and time). "
                              "Which palace runs is always decided by the game day, so this never changes what Crest does.")
        gz.pack(fill="x", pady=(px(14), 0))
        self._pal_tz_choices = palaces.tz_choices()
        self._pal_tz = ios.Select(gz.row("Show times in"), values=[lbl for _v, lbl in self._pal_tz_choices],
                                  command=self._pal_save)
        self._pal_tz.set(next((lbl for v, lbl in self._pal_tz_choices if v == sched.timezone), "This computer"))
        self._pal_tz.pack()

        card = ios.Card(wrap, pad=10)
        card.pack(fill="x", pady=(px(14), 0))
        self._pal_today = tk.Label(card.body, text="", bg=C["card"], fg=C["label"], font=F["body"], anchor="w",
                                   justify="left")
        self._pal_today.pack(fill="x")
        self._pal_today.bind("<Configure>", lambda e: self._pal_today.configure(wraplength=max(px(200), e.width - 4)))

        if err:
            ios.Banner(wrap, err, "red").pack(fill="x", pady=(px(14), 0))
        if not names:
            ios.Banner(wrap, "The palace list is empty. Press 'Import from GS Companion…', or add lines like "
                             "'Shrine of Cursed Claw: images/shrine_of_cursed_claw.png' to palaces.yaml.",
                       "orange").pack(fill="x", pady=(px(14), 0))

        gw = ios.Group(wrap, header="Weekday table",
                       footer="Used in Weekday table mode: the palace that runs on each game weekday.")
        gw.pack(fill="x", pady=(px(24), 0))
        self._pal_week = {}
        for day in palaces.DAYS:
            sel = ios.Select(gw.row(day), values=[NONE] + names, command=self._pal_save, accent=True)
            sel.set(sched.week.get(day) if sched.week.get(day) in names else NONE)
            sel.pack()
            self._pal_week[day] = sel

        gn = ios.Group(wrap, header="Coming up",
                       footer="The next seven game days. Each slot runs from the 6 AM UTC-6 reset to the next one, shown here in "
                              "the time zone above.")
        gn.pack(fill="x", pady=(px(24), 0))
        for sl in palaces.slots(root, 7, None, sched.timezone):
            right = gn.row(f"{sl.day}" + ("  (today)" if sl is not None and sl.game_date == palaces.game_date() else ""),
                           palaces.fmt_slot(sl.start, sl.end, sched.timezone))
            tk.Label(right, text=sl.palace.name if sl.palace else (sl.problem or "-"), bg=C["card"],
                     fg=C["label"] if sl.palace and not sl.problem else C["red"], font=F["footnote_semi"]).pack()

        gc = ios.Group(wrap, header="Cycle",
                       footer="Used in Cycle mode: one palace per game day in list order, wrapping around. A palace that is not "
                              "open in the game that day is not on the Crest Palace screen, and Crest stops with a message "
                              "instead of running another one. 'Only these' limits the cycle (names separated by commas; "
                              "empty = the whole list).")
        gc.pack(fill="x", pady=(px(24), 0))
        self._pal_start = ios.Select(gc.row("Start with (today)"), values=names, command=self._pal_start_changed,
                                     accent=True)
        order = palaces.cycle_order(plist, sched)
        today = palaces.choose(root)
        self._pal_start.set(today.palace.name if sched.mode == "cycle" and today.palace else
                            (sched.cycle_start if sched.cycle_start in names else (names[0] if names else "")))
        self._pal_start.pack()
        self._pal_only_var = tk.StringVar(value=", ".join(sched.cycle_only))
        ios.Field(gc.row("Only these"), self._pal_only_var, width=34).pack()
        self._pal_only_var.trace_add("write", lambda *a: self._pal_only_typed())
        del order

        gl = ios.Group(wrap, header=f"Palace list ({len(plist)})",
                       footer="Edit palaces.yaml (next to ReRun LITE) to add or change palaces: one line each, "
                              "'Palace name: images/file.png'. Image paths are written only there.")
        gl.pack(fill="x", pady=(px(24), px(24)))
        runs = palaces.runs_on(sched, plist)
        for p in plist:
            path = palaces.image_path(root, p)
            ok = path.is_file()
            days = ", ".join(d[:3] for d in runs.get(p.name, []) if d in palaces.DAYS) or \
                ", ".join(runs.get(p.name, []))
            right = gl.row(p.name, p.image + (f"   ·   runs: {days}" if days else ""))
            tk.Label(right, text="picture found" if ok else "picture MISSING", bg=C["card"],
                     fg=C["green"] if ok else C["red"], font=F["footnote_semi"]).pack()
        self._pal_refresh_today()

    # ------------------------------------------------------------ reading the page / saving
    def _pal_schedule(self) -> palaces.Schedule:
        old = palaces.load_schedule(self.m.root)
        mode = next((k for k, v in palaces.MODES.items() if v == self._pal_mode.get()), "off")
        week = {d: s.get() for d, s in self._pal_week.items() if s.get() in self._pal_names}
        only = [n.strip() for n in self._pal_only_var.get().split(",") if n.strip()]
        tz = next((v for v, lbl in getattr(self, "_pal_tz_choices", []) if lbl == self._pal_tz.get()), old.timezone)
        return palaces.Schedule(mode, week, old.cycle_start, old.cycle_anchor, only, tz)

    def _pal_save(self, *_a):
        s = self._pal_schedule()
        if s.mode == "cycle" and not s.cycle_anchor:
            s.cycle_start, s.cycle_anchor = self._pal_start.get(), palaces.game_date().isoformat()
        try:
            palaces.save_schedule(self.m.root, s)
        except OSError as e:
            errlog.note("lite.palace_save", e)
            self.flash(f"Could not save the palace schedule: {e}", "warn")
            return
        self._pal_refresh_today()
        self._status_sig = None            # the chip and badges re-check the palace at once
        self.flash("Palace selector saved", "ok")

    def _pal_start_changed(self):
        s = self._pal_schedule()
        s.cycle_start, s.cycle_anchor = self._pal_start.get(), palaces.game_date().isoformat()
        palaces.save_schedule(self.m.root, s)
        self._pal_refresh_today()
        self._status_sig = None

    def _pal_only_typed(self):
        if getattr(self, "_pal_job", None):
            self.after_cancel(self._pal_job)
        self._pal_job = self.after(700, self._pal_save)

    def _pal_refresh_today(self):
        c = palaces.choose(self.m.root)
        gd = c.game_date.strftime("%a %d %b") + f", switches in {palaces.fmt_left(palaces.until_switch())}"
        if c.mode == "off":
            text, fg = "Selector is off. Crest uses its own palace settings.", C["secondary"]
        elif c.ok:
            text, fg = (f"Today is {c.day} ({gd}, game clock): {c.palace.name}\n{c.palace.image}  -  picture found",
                        C["green"])
        else:
            text, fg = f"Today is {c.day} ({gd}, game clock). {c.problem}\nCrest will stop instead of running another palace.", C["red"]
        self._pal_today.configure(text=text, fg=fg)

    # ------------------------------------------------------------ import
    def _pal_import(self):
        start = self.m.root / "data" / "gscompanion"
        src = filedialog.askdirectory(title="GS Companion data folder (contains crest_palace.json)",
                                      initialdir=str(start if start.is_dir() else self.m.root))
        if not src:
            return
        try:
            rep = palaces.import_from_gscompanion(src, self.m.root)
        except (OSError, ValueError, FileNotFoundError) as e:
            ios.alert(self, str(e), "Import failed")
            return
        lines = [f"{len(rep.copied)} pictures imported into images/, {len(rep.listed)} palaces added to palaces.yaml."]
        if rep.kept:
            lines.append(f"{len(rep.kept)} picture(s) already existed and are different - left untouched: "
                         + ", ".join(n for n, _ in rep.kept) + ". Replace them yourself if you want the new ones.")
        if rep.no_source:
            lines.append("No picture in the source folder for: " + ", ".join(rep.no_source) + ".")
        ios.alert(self, "\n".join(lines), "Palace import")
        self._pal_build()

    def _open_palace_list(self):
        try:
            os.startfile(str(self.m.root / palaces.LIST_FILE))        # noqa: S606 - the user's own file
        except OSError as e:
            self.flash(f"Could not open it: {e}", "warn")
