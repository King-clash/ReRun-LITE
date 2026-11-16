"""Settings > Sessions: what each Crest session did, with totals and two graphs.

Reads only the saved session summaries (data/lite/sessions.jsonl, see runs.py). A session still running is shown
live at the top. Nothing here changes how Crest runs."""
from __future__ import annotations

from rerun.gui_common import *  # noqa: F401,F403 - tk, ios, C, F, px, errlog, filedialog, Path

from . import analytics
from .charts import BarChart, LineChart
from .runs import fmt_secs

ALL = "All emulators"


class SessionsMixin:

    def _build_sessions_page(self):
        _, page, hdr = self._page("Sessions", "Sessions", "list", scroll=True)
        ios.Button(hdr, "Export CSV…", self._sess_export, kind="tinted").pack(side="right")
        ios.Button(hdr, "Clear history", self._sess_clear, kind="tinted", color="red",
                   icon="delete").pack(side="right", padx=(0, px(8)))
        ios.Button(hdr, "Refresh", self._sess_refresh, kind="tinted").pack(side="right", padx=(0, px(8)))

        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", padx=px(20), pady=(0, px(8)))
        self._sess_range = ios.Select(bar, values=[r[0] for r in analytics.RANGES], accent=True,
                                      command=lambda *_: self._sess_refresh())
        self._sess_range.set(analytics.RANGES[0][0])
        self._sess_range.pack(side="left")
        self._sess_inst = ios.Select(bar, values=[ALL], accent=True, command=lambda *_: self._sess_refresh())
        self._sess_inst.set(ALL)
        self._sess_inst.pack(side="left", padx=px(10))

        self._sess_live = self._label(page, "", secondary=False, font="body_semi", anchor="w")
        self._sess_live.pack(fill="x", padx=px(20), pady=(0, px(4)))
        self._sess_totals = self._label(page, "", secondary=False, font="body", anchor="w", justify="left")
        self._sess_totals.pack(fill="x", padx=px(20))
        self._sess_note = self._label(page, "", anchor="w", justify="left")
        self._sess_note.pack(fill="x", padx=px(20), pady=(px(2), px(8)))

        self._label(page, "Runs per day", font="footnote_semi", anchor="w").pack(fill="x", padx=px(20))
        self._sess_bars = BarChart(page, px(150), "No runs in this period yet")
        self._sess_bars.pack(fill="x", padx=px(20), pady=(0, px(8)))
        self._label(page, "Time per run (seconds), oldest to newest", font="footnote_semi",
                    anchor="w").pack(fill="x", padx=px(20))
        self._sess_line = LineChart(page, px(150), "Needs at least two timed runs")
        self._sess_line.pack(fill="x", padx=px(20), pady=(0, px(8)))

        self._label(page, "Sessions", font="footnote_semi", anchor="w").pack(fill="x", padx=px(20))
        _, self._sess_box = ios.text_box(page, mono=False, wrap="none", padx=px(20), pady=(0, px(14)))
        self._sess_box.configure(height=14, state="disabled")
        self._sess_box.tag_configure("failed", foreground=C["red"])
        self._sess_box.tag_configure("stopped", foreground=C["secondary"])
        self._sess_rows: list[dict] = []
        self._sess_refresh()

    # ---------------------------------------------------------------- data
    def _sess_selection(self) -> tuple[list[dict], int]:
        days = dict(analytics.RANGES).get(self._sess_range.get(), 7)
        inst = self._sess_inst.get()
        inst = None if inst in ("", ALL) else inst
        rows = analytics.in_range(self.m.runs.sessions(limit=1000), days, instance=inst)
        return rows, days

    def _sess_refresh(self, *_a):
        try:
            self._sess_inst["values"] = [ALL, *self.m.instances]
            rows, days = self._sess_selection()
            self._sess_rows = rows
            t = analytics.totals(rows)
            live = [(n, self.m.runs.live(n)) for n in self.m.instances if self.m.runs.live(n)]
            self._sess_live.configure(text="Running now: " + "; ".join(
                f"{n}: {d['runs']} runs, {fmt_secs(d['active_s'])}" for n, d in live) if live else "")
            if not rows:
                self._sess_totals.configure(text="No finished sessions in this period.")
            else:
                self._sess_totals.configure(text=(
                    f"{t['sessions']} session(s)  ·  {t['runs']} runs  ·  {fmt_secs(t['active_s'])} running"
                    f"  ·  {t['runs_per_hour'] if t['runs_per_hour'] is not None else '-'} runs/hour\n"
                    f"Time per run: average {fmt_secs(t['avg_cycle_s'])}, median {fmt_secs(t['median_cycle_s'])}, "
                    f"fastest {fmt_secs(t['fastest_s'])}, slowest {fmt_secs(t['slowest_s'])}\n"
                    f"Failures counted: {t['failures']}  ·  game restarts: {t['restarts']}"
                    f" (followed by a counted run: {t['recovered']})"))
            self._sess_note.configure(text="Only runs the script counted are included. A run in progress when a session "
                                           "ended is not counted as a success.")
            per = analytics.per_day(rows, days)
            self._sess_bars.set([n for _, n in per], [d[5:] for d, _ in per])
            self._sess_line.set(analytics.cycle_series(rows))
            box = self._sess_box
            box.configure(state="normal")
            box.delete("1.0", "end")
            for s in reversed(rows):
                title, detail, state = analytics.session_line(s)
                box.insert("end", f"{title}\n", ("failed",) if state == "failed" else ())
                box.insert("end", f"    {detail}\n", ("stopped",))
            if not rows:
                box.insert("end", "Sessions appear here when they end.\n")
            box.configure(state="disabled")
        except Exception as e:  # noqa: BLE001 - a statistics page must never break the window
            errlog.note("lite.sessions_page", e)

    def _sess_export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="reRun-sessions.csv")
        if path:
            Path(path).write_text(analytics.to_csv(self._sess_selection()[0]), encoding="utf-8", newline="")
            self.flash("Sessions exported", "ok")

    def _sess_clear(self):
        if ios.confirm(self, "Delete the saved session history? Totals and graphs on this page go back to empty. "
                             "This does not touch your settings or the log.", "Clear history?", ok="Delete"):
            n = self.m.runs.clear()
            self._sess_refresh()
            self.flash(f"Deleted {n} saved session(s)", "ok")
