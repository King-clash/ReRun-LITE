"""Settings > Palace Selector: the page for the daily Crest Palace selector (logic in palaces.py)."""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog

from rerun import errlog, ios
from rerun.ios import C, F, px

from . import crest as lite_crest
from . import palaces, schedule_reader

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
                             "not at your PC's midnight). Your time zone only changes how the times below are shown: the "
                             "palace for each game day never changes. Off: Crest uses its own palace settings as before.")
        g.pack(fill="x", pady=(px(14), 0))
        self._pal_mode = ios.Select(g.row("Mode"), values=list(palaces.MODES.values()), command=self._pal_save)
        self._pal_mode.set(palaces.MODES[sched.mode])
        self._pal_mode.pack()
        self._pal_tz_labels = dict(palaces.tz_choices())               # saved value -> label
        self._pal_tz_values = {v: k for k, v in self._pal_tz_labels.items()}
        self._pal_tz = ios.Select(g.row("My time zone", "The palace times below are shown in this zone. 'This computer' "
                                        "follows your PC, daylight saving included."),
                                  values=list(self._pal_tz_labels.values()), command=self._pal_tz_changed, accent=True)
        self._pal_tz.set(self._pal_tz_labels.get(sched.timezone, self._pal_tz_labels[palaces.TZ_COMPUTER]))
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

        gk = ios.Group(wrap, header="Check the game now",
                       footer="Each button takes ONE screenshot of the selected emulator and reads it here. Nothing is tapped. Open "
                              "Exploring > Crest Palace in the game first. 'Add' cuts the picture of a banner that matches none of "
                              "your palaces out of that screenshot and adds it to the list (it never replaces a picture or a line).")
        gk.pack(fill="x", pady=(px(24), 0))
        ios.Button(gk.row("Check the Crest Palace screen", "Which of your palaces are on the screen, and today's."),
                   "Check now", self._pal_check_now, kind="tinted", small=True).pack()
        ios.Button(gk.row("Add a palace that is not in your list", "For a new or limited-time palace."),
                   "Add from screen…", self._pal_add_from_screen, kind="tinted", small=True).pack()
        ios.Button(gk.row("Read the game's schedule", "Checks each day's palace against the game's own Schedule. Taps menus."),
                   "Read…", self._pal_read_schedule, kind="tinted", small=True).pack()

        if sched.mode != "off" and names:
            gs = ios.Group(wrap, header=f"Next 7 days in your time zone ({palaces.zone_name(sched.timezone)})",
                           footer="Each palace is open for one game day, from the 6 AM UTC-6 reset to the next one. These are "
                                  "those slots in your own days and times, so you can see when the palace changes.")
            gs.pack(fill="x", pady=(px(24), 0))
            for slot in palaces.slots(root, 7):
                who = slot.palace.name if slot.palace else (slot.problem or "no palace")
                right = gs.row(who, f"{slot.local_day} {slot.start.strftime('%H:%M')} to "
                                    f"{slot.end.strftime('%a %H:%M')}   ·   game {slot.day}"
                               + (f"   ·   {slot.problem}" if slot.palace and slot.problem else ""))
                tk.Label(right, text=slot.start.strftime("%d %b"), bg=C["card"], fg=C["secondary"],
                         font=F["footnote_semi"]).pack()

        gw = ios.Group(wrap, header="Weekday table",
                       footer="Used in Weekday table mode: the palace that runs on each game weekday. The grey line under each "
                              "day is when that day's slot starts and ends in your time zone.")
        gw.pack(fill="x", pady=(px(24), 0))
        self._pal_week = {}
        for day in palaces.DAYS:
            slot = palaces.next_slot_for_day(root, day)
            sel = ios.Select(gw.row(day, f"your time: {palaces.fmt_slot(slot.start, slot.end, sched.timezone)}"),
                             values=[NONE] + names, command=self._pal_save, accent=True)
            sel.set(sched.week.get(day) if sched.week.get(day) in names else NONE)
            sel.pack()
            self._pal_week[day] = sel

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

        gb = ios.Group(wrap, header="If today's palace is not on the screen",
                       footer="Off by default: Crest then stops and says so, and never runs another palace. Turn it on to let Crest "
                              "try these palaces in order (names separated by commas, as in the palace list) and run the first one "
                              "that is on the Crest Palace screen. The Log and a Discord message say when a backup was used.")
        gb.pack(fill="x", pady=(px(24), 0))
        self._pal_backup_on = tk.BooleanVar(value=sched.backup_on)
        ios.Switch(gb.row("Run a backup palace", "Only when today's palace is nowhere on the Crest Palace screen."),
                   self._pal_backup_on, command=self._pal_save).pack()
        self._pal_backup_var = tk.StringVar(value=", ".join(sched.backup))
        ios.Field(gb.row("Backup palaces, in order"), self._pal_backup_var, width=34).pack()
        self._pal_backup_var.trace_add("write", lambda *a: self._pal_only_typed())

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
        tz = self._pal_tz_values.get(self._pal_tz.get(), old.timezone)
        backup = [n.strip() for n in self._pal_backup_var.get().split(",") if n.strip()]
        return palaces.Schedule(mode, week, old.cycle_start, old.cycle_anchor, only, tz,
                                bool(self._pal_backup_on.get()), backup)

    def _pal_save(self, *_a, rebuild: bool = True):
        s = self._pal_schedule()
        if s.mode == "cycle" and not s.cycle_anchor:
            s.cycle_start, s.cycle_anchor = self._pal_start.get(), palaces.game_date().isoformat()
        unknown = [n for n in s.backup if palaces.find([pl for pl in self._pal_palaces()], n) is None]
        try:
            palaces.save_schedule(self.m.root, s)
        except OSError as e:
            errlog.note("lite.palace_save", e)
            self.flash(f"Could not save the palace schedule: {e}", "warn")
            return
        self._pal_refresh_today()
        self._status_sig = None            # the chip and badges re-check the palace at once
        if unknown:
            self.flash("Saved. Not in the palace list, so ignored: " + ", ".join(unknown), "warn")
        else:
            self.flash("Palace selector saved", "ok")
        if rebuild:                        # the "next 7 days" and weekday labels follow the new choices
            self.after_idle(self._pal_build)

    def _pal_palaces(self) -> list:
        try:
            return palaces.read_list(self.m.root)
        except ValueError:
            return []

    # ------------------------------------------------------------ check the game now / add from the screen
    _pal_sync = False                      # tests turn this on to run the screenshot step on the calling thread

    def _pal_pictures(self) -> list:
        import cv2
        import numpy as np
        out = []
        for p in self._pal_palaces():
            path = palaces.image_path(self.m.root, p)
            img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR) if path.is_file() else None
            if img is not None:
                out.append((p.name, img))
        return out

    def _pal_grab(self, then):
        """One screenshot of the selected emulator (or the first one), off the window's thread; then(name, shot, error)."""
        name = self.selected() or next(iter(self.m.instances), None)
        if name is None:
            ios.alert(self, "Add an emulator on the Auto Crest tab first.", "Palace check")
            return

        def work():
            try:
                shot, err = self.m.screenshot(name), ""
            except Exception as e:  # noqa: BLE001 - say it in words, never a traceback
                errlog.note("lite.palace_grab", e)
                shot, err = None, str(e) or e.__class__.__name__
            if self._pal_sync:
                then(name, shot, err)
                return
            try:
                self.after(0, lambda: then(name, shot, err))
            except (tk.TclError, RuntimeError):
                pass
        if self._pal_sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _pal_check_now(self):
        self._pal_grab(self._pal_check_done)

    def _pal_check_done(self, name, shot, err):
        if shot is None:
            ios.alert(self, f"Could not get a screenshot from {name}: {err}\nIs BlueStacks open with ADB turned on?", "Palace check")
            return
        found, unknown = lite_crest.scan_palace_screen(shot, self._pal_pictures())
        lines = [f"Screenshot of {name}:"]
        if not found:
            lines.append("None of your palaces is on this screen. Open Exploring > Crest Palace in the game and check again.")
        for pname, score, _y in found:
            lines.append(f"  on screen: {pname}  (match {score:.2f})")
        if unknown:
            lines.append(f"{len(unknown)} banner(s) match none of your pictures: a new palace? Press 'Add from screen…'.")
        c = palaces.choose(self.m.root)
        if c.palace is not None and found:
            lines.append(f"Today's palace ({c.day}): {c.palace.name} - "
                         + ("on this screen." if any(f[0] == c.palace.name for f in found)
                            else "NOT on this screen (scroll the list, or it is not open today)."))
        ios.alert(self, "\n".join(lines), "Palace check")

    def _pal_read_schedule(self):
        """Open the game's Schedule, read about a week of palaces, put everything back, and say what matches (see schedule_reader.py)."""
        if self._busy_any():
            ios.alert(self, "Stop Crest first: reading the schedule taps menus in the game.", "Read the game's schedule")
            return
        name = self.selected() or next(iter(self.m.instances), None)
        if name is None:
            ios.alert(self, "Add an emulator on the Auto Crest tab first.", "Read the game's schedule")
            return
        if not ios.confirm(self, f"This opens Exploring > Schedule in the game on {name}, reads about a week of palaces, then puts "
                                 "the schedule's filter buttons back and closes the window. It taps menus but starts, buys and "
                                 "changes nothing on your account.\n\nStart with the game on the Home screen. Takes about a minute.",
                           "Read the game's schedule", ok="Read it"):
            return
        self.flash("Reading the game's schedule…", "info")

        def work():
            try:
                from rerun.ocr import get_ocr
                dev = self.m.device(name)
                if not dev.is_connected():
                    dev.connect()
                res = schedule_reader.read_schedule(dev, get_ocr(self.m.config.get("tesseract_path", "auto")), self.m.vision,
                                                    [p.name for p in self._pal_palaces()])
                text, title = "\n".join(schedule_reader.describe(res, self.m.root)), "The game's palace schedule"
            except schedule_reader.ScheduleError as e:
                text, title = str(e), "Read the game's schedule"
            except Exception as e:  # noqa: BLE001 - say it in words, never a traceback
                errlog.note("lite.palace_schedule", e)
                text, title = f"Could not read the schedule: {e}", "Read the game's schedule"
            if self._pal_sync:
                self._pal_show(text, title)
                return
            try:
                self.after(0, lambda: self._pal_show(text, title))
            except (tk.TclError, RuntimeError):
                pass
        if self._pal_sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _pal_show(self, text: str, title: str):
        ios.alert(self, text, title)

    def _pal_add_from_screen(self):
        self._pal_grab(self._pal_add_done)

    def _pal_add_done(self, name, shot, err):
        if shot is None:
            ios.alert(self, f"Could not get a screenshot from {name}: {err}\nIs BlueStacks open with ADB turned on?", "Add a palace")
            return
        found, unknown = lite_crest.scan_palace_screen(shot, self._pal_pictures())
        if not found:
            ios.alert(self, "None of your palaces is on this screen, so there is nothing to measure from. Open Exploring > "
                            "Crest Palace in the game (with at least one palace from your list showing) and try again.", "Add a palace")
            return
        if not unknown:
            ios.alert(self, "Every banner fully on this screen matches a picture in your list. If a palace is missing, scroll the "
                            "list in the game so it is fully visible and try again.", "Add a palace")
            return
        added = []
        for y in unknown:
            text = ios.ask_string(self, "Add a palace", f"A banner (height {y}) matches none of your palaces. Type its name as the "
                                  "game shows it, for example 'Shrine of Subspace'. Cancel to skip it.")
            if not text:
                continue
            try:
                p = palaces.add_palace(self.m.root, text, palaces.cut_banner(shot, y))
            except (ValueError, OSError) as e:
                ios.alert(self, str(e), "Add a palace")
                continue
            added.append(p.name)
        if added:
            self.flash("Added to the palace list: " + ", ".join(added), "ok")
            self._status_sig = None
            self.after_idle(self._pal_build)

    def _pal_tz_changed(self, *_a):
        self._pal_save()

    def _pal_start_changed(self):
        s = self._pal_schedule()
        s.cycle_start, s.cycle_anchor = self._pal_start.get(), palaces.game_date().isoformat()
        palaces.save_schedule(self.m.root, s)
        self._pal_refresh_today()
        self._status_sig = None

    def _pal_only_typed(self):
        if getattr(self, "_pal_job", None):
            self.after_cancel(self._pal_job)
        self._pal_job = self.after(700, lambda: self._pal_save(rebuild=False))   # typing: don't rebuild the field you are in

    def _pal_refresh_today(self):
        c = palaces.choose(self.m.root)
        gd = c.game_date.strftime("%a %d %b")
        tz = palaces.load_schedule(self.m.root).timezone
        switch = (f"\nChanges at {palaces.fmt_when(c.ends, tz)} your time ({palaces.zone_name(tz)}), "
                  f"in {palaces.fmt_left(palaces.until_switch())}.") if c.ends else ""
        if c.mode == "off":
            text, fg = "Selector is off. Crest uses its own palace settings.", C["secondary"]
        elif c.ok:
            text, fg = (f"Today is {c.day} ({gd}, game clock): {c.palace.name}\n{c.palace.image}  -  picture found{switch}",
                        C["green"])
        else:
            text, fg = (f"Today is {c.day} ({gd}, game clock). {c.problem}\nCrest will stop instead of running another "
                        f"palace.{switch}"), C["red"]
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
