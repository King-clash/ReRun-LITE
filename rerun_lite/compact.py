"""Compact mode: a small window with just what you need while Crest runs - the status, what it is doing, the run
count and time, a warning if something needs you, and Start / Pause / Stop.

It is NOT a second controller. It reads the same Manager the big window reads and presses the same Manager buttons
(start, pause, resume, stop), so switching between the two never interrupts a run, starts a second one, or shows a
different status. The big window is only hidden, never closed; "Full window" brings it back.

Remembered in data/lite/ui.json: "compact" (which window you were in) and "compact_geometry" (its size and place).
"""
from __future__ import annotations

from rerun.gui_common import *  # noqa: F401,F403 - tk, ios, C, F, px, errlog

from rerun import qol

from . import APP_NAME, phases, readiness
from .compact_logic import PAUSABLE, compact_summary, pick_emulator, runs_text  # noqa: F401

class CompactMixin:
    COMPACT_SIZE = (360, 200)
    COMPACT_MIN = (300, 170)

    # ================================================================ labels the big window shares
    def _status_label(self, inst) -> str:
        """The Instances list shows the phase ('Waiting for the game', 'Recovering'...) in place of the five status words."""
        try:
            return phases.LABEL[self.m.phase(inst.name)[0]]
        except Exception as e:  # noqa: BLE001 - a label must never break the list
            errlog.note("lite.status_label", e)
            return inst.status.title()

    # ================================================================ switching windows
    def _compact_alive(self) -> bool:
        w = getattr(self, "_compact", None)
        try:
            return w is not None and bool(w.winfo_exists())
        except tk.TclError:
            return False

    def toggle_compact(self):
        if self._compact_alive():
            self.leave_compact()
        else:
            self.enter_compact()
        return "break"

    def enter_compact(self, remember: bool = True):
        if self._compact_alive():
            return
        self._save_ui_state()
        w = tk.Toplevel(self)
        self._compact = w
        w.title(f"{APP_NAME} - compact")
        w.configure(bg=C["bg"])
        w.minsize(px(self.COMPACT_MIN[0]), px(self.COMPACT_MIN[1]))
        w.geometry(self._compact_geometry())
        try:
            w.attributes("-topmost", bool(self._pin_var.get()))
            w.iconphoto(True, self._icon)
        except tk.TclError as e:
            errlog.note("lite.compact_icon", e)
        w.protocol("WM_DELETE_WINDOW", self._compact_close)
        self._build_compact(w)
        self.after(30, lambda: ios.style_window(w))
        self.withdraw()                                   # the big window is hidden, not closed: nothing running stops
        if remember:
            self._bg_save(compact=True)
        self._compact_refresh()

    def leave_compact(self, remember: bool = True):
        w = getattr(self, "_compact", None)
        job = getattr(self, "_compact_job", None)
        if job:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
            self._compact_job = None
        if w is not None:
            self._compact_save_geometry()
            try:
                w.destroy()
            except tk.TclError as e:
                errlog.note("lite.compact_destroy", e)
        self._compact = None
        if remember:
            self._bg_save(compact=False)
        self.deiconify()
        self.lift()
        self.refresh_instances()

    def _restore_compact(self, minimized: bool = False):
        """At start: back into compact mode if that is where you left off (not when starting minimized to the tray,
        which stays hidden; Show then opens the compact window)."""
        if self._ui_state().get("compact") and not minimized:
            self.after(250, self.enter_compact)

    def show_window(self):
        """Tray 'Show': the compact window if that is the mode you are in, else the big one."""
        if self._compact_alive():
            self._compact.deiconify()
            self._compact.lift()
            self._compact_refresh()
            return
        if self._ui_state().get("compact"):
            self.enter_compact()
            return
        super().show_window()

    def _tray_action(self, action: str):
        if action == "compact":
            self.toggle_compact()
        else:
            super()._tray_action(action)

    def _compact_close(self):
        """The compact window's X: same rules as the big window's - hide to the tray if that is on, else quit."""
        self._compact_save_geometry()
        if self._tray_on and self.close_to_tray.get():
            self._compact.withdraw()
            return
        running = [n for n, i in self.m.instances.items() if i.status in ("running", "paused", "starting")]
        if running:
            self.leave_compact(remember=False)           # the "stop and quit?" question belongs on the big window
        self.quit_app()

    def _compact_geometry(self) -> str:
        saved = qol.clamp_geometry(str(self._ui_state().get("compact_geometry") or ""), self.winfo_screenwidth(),
                                   self.winfo_screenheight(), min_w=px(self.COMPACT_MIN[0]), min_h=px(self.COMPACT_MIN[1]))
        return saved or f"{px(self.COMPACT_SIZE[0])}x{px(self.COMPACT_SIZE[1])}"

    def _compact_save_geometry(self):
        try:
            w = self._compact
            if w is not None and w.state() == "normal":
                self._bg_save(compact_geometry=w.winfo_geometry())
        except tk.TclError as e:
            errlog.note("lite.compact_geometry", e)

    # ================================================================ the window
    def _build_compact(self, w):
        pad = px(14)
        top = tk.Frame(w, bg=C["bg"])
        top.pack(fill="x", padx=pad, pady=(pad, px(2)))
        self._cp_dot = tk.Label(top, text="●", bg=C["bg"], fg=C["gray"], font=F["body_semi"])
        self._cp_dot.pack(side="left")
        self._cp_phase = tk.Label(top, text="", bg=C["bg"], fg=C["label"], font=F["body_semi"], anchor="w")
        self._cp_phase.pack(side="left", padx=(px(6), 0))
        ios.Button(top, "Full window", self.leave_compact, kind="plain", small=True).pack(side="right")

        self._cp_detail = tk.Label(w, text="", bg=C["bg"], fg=C["secondary"], font=F["footnote"], anchor="w",
                                   justify="left")
        self._cp_detail.pack(fill="x", padx=pad)
        self._cp_stats = tk.Label(w, text="", bg=C["bg"], fg=C["label"], font=F["body"], anchor="w")
        self._cp_stats.pack(fill="x", padx=pad, pady=(px(6), 0))
        self._cp_more = tk.Label(w, text="", bg=C["bg"], fg=C["secondary"], font=F["footnote"], anchor="w")
        self._cp_more.pack(fill="x", padx=pad)
        self._cp_warn = tk.Label(w, text="", bg=C["bg"], fg=C["orange"], font=F["footnote_semi"], anchor="w",
                                 justify="left")
        self._cp_warn.pack(fill="x", padx=pad, pady=(px(4), 0))
        for lbl in (self._cp_detail, self._cp_warn):
            lbl.bind("<Configure>", lambda e, l=lbl: l.configure(wraplength=max(px(120), e.width - 4)))

        bar = tk.Frame(w, bg=C["bg"])
        bar.pack(side="bottom", fill="x", padx=pad, pady=pad)
        self._cp_start = ios.Button(bar, "Start", self._compact_start, icon="play")
        self._cp_start.pack(side="left")
        self._cp_pause = ios.Button(bar, "Pause", self._compact_pause, kind="tinted", icon="pause")
        self._cp_pause.pack(side="left", padx=px(8))
        self._cp_stop = ios.Button(bar, "Stop", self._compact_stop, kind="tinted", color="red", icon="stop")
        self._cp_stop.pack(side="left")
        w.bind("<Escape>", lambda e: self.leave_compact())

    def _compact_name(self) -> str | None:
        return pick_emulator(self.m, self.selected())

    def _compact_refresh(self):
        """Redraw from the Manager (once a second while the window exists)."""
        self._compact_job = None
        if not self._compact_alive():
            return
        try:
            name = self._compact_name()
            sel = name if name in self.m.instances else None
            problems = getattr(self, "_problems", None) or []
            s = compact_summary(self.m, sel, problems)
            self._cp_dot.configure(fg=C.get(s["color"], C["gray"]))
            self._cp_phase.configure(text=s["label"] + (f"  ·  {sel}" if sel and len(self.m.instances) > 1 else ""))
            self._cp_detail.configure(text=s["detail"])
            self._cp_stats.configure(text=s["stats"])
            self._cp_more.configure(text=s["more"])
            self._cp_warn.configure(text=getattr(self, "_cp_note", "") or s["warning"])
            self._cp_start.set_enabled(s["can_start"] and sel is not None)
            self._cp_pause.set_enabled(s["can_pause"])
            self._cp_pause.set_text(s["pause_text"])
            self._cp_stop.set_enabled(s["can_stop"])
            title = f"{APP_NAME} - {s['label']}"
            if self._compact.title() != title:
                self._compact.title(title)
        except Exception as e:  # noqa: BLE001 - a status window must never raise into Tk
            errlog.note("lite.compact_refresh", e)
        self._compact_job = self.after(1000, self._compact_refresh)

    # ================================================================ the buttons: the same Manager calls as the big window
    def _compact_note(self, text: str):
        self._cp_note = text
        self.after(8000, lambda: setattr(self, "_cp_note", "") if getattr(self, "_cp_note", "") == text else None)

    def _compact_start(self):
        name = self._compact_name()
        if not name:
            return
        msg = self.m.start(name)
        if not msg.startswith(("Started", "Dry run")):
            self._compact_note(msg)                      # e.g. which account is logged in: answer it in the full window
        self.m.refresh_phases()
        self._compact_refresh_soon()

    def _compact_pause(self):
        name = self._compact_name()
        if not name:
            return
        if self.m.instances[name].status == "paused":
            self.m.resume(name)
        else:
            self.m.pause(name)
        self._compact_refresh_soon()

    def _compact_stop(self):
        name = self._compact_name()
        if name:
            self.m.stop(name)
        self._compact_refresh_soon()

    def _compact_refresh_soon(self):
        job = getattr(self, "_compact_job", None)
        if job:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._compact_job = self.after(150, self._compact_refresh)
