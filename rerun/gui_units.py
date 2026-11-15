"""Units + Compendium tab and the GS Companion tab.

Moved verbatim from rerun/gui.py (class App); App inherits UnitsMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class UnitsMixin:

    # ================================================================ units (roster + compendium)
    def _build_units(self):
        """One Units tab: the unit roster from your scans and the Compendium (quest clear
        targets, progress, change since the last scan)."""
        from .compendium import FILTERS
        _, page, hdr = self._page("Units", "Units", "people")
        ios.Button(hdr, "Export CSV", self.units_export, kind="tinted",
                   icon="download").pack(side="right")
        for text, cmd, icon, color in (("Global Target", self.comp_global, "edit", None),
                                       ("Set Target", self.comp_target, "edit", None),
                                       ("Correct Name", self.units_correct, "edit", None),
                                       ("Remove", self.units_remove, "delete", "red"),
                                       ("GS Companion", self.units_gsc, "link", None)):
            kw = {"color": color} if color else {}
            ios.Button(hdr, text, cmd, kind="plain", icon=icon, small=True,
                       **kw).pack(side="right", padx=(0, px(14)))
        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", padx=px(20), pady=(0, px(10)))
        self.units_q = tk.StringVar()
        ios.Field(bar, self.units_q, width=20).pack(side="left")
        self.units_q.trace_add("write", lambda *a: self.refresh_units())
        self.units_el = ios.Select(bar, values=["All elements", "Fire", "Water", "Earth", "Light", "Dark"],
                                   accent=True, command=self.refresh_units)
        self.units_el.set("All elements")
        self.units_el.pack(side="left", padx=(px(16), 0))
        self.comp_show = ios.Select(bar, values=list(FILTERS), accent=True, command=self.refresh_units)
        self.comp_show.set(FILTERS[0])
        self.comp_show.pack(side="left", padx=px(16))
        self._label(bar, "Near target from").pack(side="left")
        self.comp_near = ios.Select(bar, values=["75%", "80%", "90%", "95%"], accent=True,
                                    command=self._comp_near_changed)
        self.comp_near.set(f"{self.m.compendium.targets.get('near_pct') or 90}%")
        self.comp_near.pack(side="left", padx=(px(6), 0))
        self.units_summary = self._label(page, "", anchor="w", justify="left")
        self.units_summary.pack(fill="x", padx=px(24), pady=(0, px(6)))

        lc = ios.Card(page, pad=6, stretch=True)
        lc.pack(fill="both", expand=True, padx=px(20), pady=(0, px(14)))
        cols = ("name", "element", "race", "clears", "target", "pct", "remaining", "delta")
        heads = ("Unit", "Element", "Race", "Clears", "Target", "Progress", "Remaining", "Change")
        sb = ttk.Scrollbar(lc.body, orient="vertical", style="IOS.Vertical.TScrollbar")
        # Taller rows with the unit's picture (GS Companion's thumbnail) in the first column.
        ttk.Style(self).configure("Units.IOS.Treeview", rowheight=px(44), indent=0)
        self.units_tree = ttk.Treeview(lc.body, columns=cols, show="tree headings",
                                       style="Units.IOS.Treeview", selectmode="browse",
                                       yscrollcommand=sb.set)
        self.units_tree.heading("#0", text="")
        self.units_tree.column("#0", width=px(52), minwidth=px(52), stretch=False, anchor="center")
        self._unit_pics: dict[str, object] = {}   # name -> PhotoImage (or None: no picture)
        sb.configure(command=self.units_tree.yview)
        self._units_sort = ("name", False)
        for c, h, w in zip(cols, heads, (240, 76, 84, 84, 100, 160, 90, 130)):
            self.units_tree.heading(c, text=h, command=lambda c=c: self._units_sort_by(c))
            self.units_tree.column(c, width=px(w), stretch=(c == "name"),
                                   anchor="w" if c in ("name", "race", "pct") else "center")
        self.units_tree.tag_configure("uncertain", foreground=C["orange"])
        self.units_tree.tag_configure("done", foreground=C["green"])
        self.units_tree.tag_configure("near", foreground=C["blue"])
        sb.pack(side="right", fill="y", pady=px(4))
        self.units_tree.pack(side="left", fill="both", expand=True)
        self.units_tree.bind("<Double-1>", lambda e: self.comp_target())
        self.units_empty = tk.Label(lc.body, bg=C["card"], fg=C["secondary"], font=F["footnote"],
                                    justify="center",
                                    text="No units yet\nOpen Units in-game and run the Compendium Counter "
                                         "script:\nit reads each unit's page and fills this list.")
        self.after(120, self.refresh_units)

    def _units_sort_by(self, col: str):
        cur, desc = self._units_sort
        self._units_sort = (col, not desc if cur == col else col in ("clears", "pct", "delta", "last_seen"))
        self.refresh_units()

    def _comp_near_changed(self):
        try:
            self.m.compendium.set_near(int(self.comp_near.get().rstrip("%")))
        except ValueError:
            return
        self.refresh_units()
        self._refresh_compendium_tiles(force=True)

    def refresh_units(self):
        from .compendium import bar
        c = self.m.compendium
        el = self.units_el.get()
        rows = c.rows(search=self.units_q.get(), sort=self._units_sort[0], desc=self._units_sort[1],
                      show=self.comp_show.get() or "All units",
                      element=None if el in ("", "All elements") else el)
        self.units_tree.delete(*self.units_tree.get_children())
        for r in rows:
            tgt = "" if not r["target"] else (f"{r['target']:,}" + (" (all)" if r["target_kind"] == "global" else ""))
            clears = "–" if r["clears"] is None else f"{r['clears']:,}" + ("?" if r["status"] == "uncertain" else "")
            el_txt = "–" if not r["element"] else r["element"] + ("?" if r["element_unsure"] else "")
            tags = ("uncertain",) if r["uncertain"] else ((r["state"],) if r["state"] in ("done", "near") else ())
            pic = self._unit_pic(r["name"], r["element"])
            self.units_tree.insert("", "end", iid=r["name"], tags=tags, image=pic or "",
                                   values=("  " + r["name"] + (" ?" if r["uncertain"] else ""), el_txt,
                                           r["race"] or "–", clears, tgt, bar(r["pct"]),
                                           "" if r["remaining"] is None else f"{r['remaining']:,}",
                                           c.change_text(r)))
        if rows:
            self.units_empty.place_forget()
        else:
            self.units_empty.place(relx=0.5, rely=0.45, anchor="center")
        text = self.m.units.summary_text().replace("**", "") + "   ·   " + \
            c.summary_text().replace("**", "").replace("\n", "   ·   ")
        if self.units_summary.cget("text") != text:
            self.units_summary.configure(text=text)

    # kept for callers of the former Compendium tab
    refresh_compendium = refresh_units

    def _unit_pic(self, name: str, element: str | None = None):
        """The unit's thumbnail from GS Companion's saved pictures
        (data/gscompanion/images/unit_thumbnail_<id>.png), matched by name - units carry
        GS Companion's name after a clear match. None when there is no picture (story
        units the site doesn't list, or no local data)."""
        key = f"{name}|{element}"
        if key in self._unit_pics:
            return self._unit_pics[key]
        photo = None
        g = getattr(self.m, "gsc", None)
        if g is not None:
            try:
                u = next((x for x in g.units if x["name"] == name), None)
                if u is None:
                    u = (g.match_unit(f"{name} ({element})") if element else None) or g.match_unit(name)
                if u and u.get("unit_id"):
                    p = g.dir / "images" / f"unit_thumbnail_{u['unit_id']}.png"
                    if p.exists():
                        size = px(38)
                        with Image.open(p) as im:
                            photo = ImageTk.PhotoImage(im.convert("RGBA").resize((size, size), Image.LANCZOS))
            except Exception as e:  # noqa: BLE001 - a missing picture never breaks the list
                errlog.note("gui.unit_picture", e)
                photo = None
        self._unit_pics[key] = photo
        return photo

    def _units_selected(self) -> str | None:
        sel = self.units_tree.selection()
        return sel[0] if sel else None

    def units_export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv",
                                            initialfile="rerun_units.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            Path(path).write_text(self.m.units.to_csv(), encoding="utf-8", newline="")
            self.flash(f"Saved {Path(path).name}", "ok")

    def units_correct(self):
        name = self._units_selected()
        if not name:
            return ios.alert(self, "Select a unit first.", "Correct Name")
        # GS Companion's spelling, when it knows a close match, is offered (never applied
        # without you pressing OK).
        suggest = self._gsc_suggest(name)
        msg = f"Rerun read this name as '{name}'. Type the correct name - future scans will remember it."
        if suggest and suggest != name:
            msg += f"\n\nGS Companion suggests: {suggest}"
        right = ios.ask_string(self, "Correct Name", msg, suggest or name)
        if right and right.strip() and right.strip() != name:
            self.m.units.correct_name(name, right.strip())
            self.m.compendium.rename(name, right.strip())
            self.flash(f"Saved: '{name}' is {right.strip()}", "ok")
            self.refresh_units()
            self._companion_refresh()

    def units_remove(self):
        name = self._units_selected()
        if not name:
            return ios.alert(self, "Select a unit first.", "Remove Unit")
        if ios.confirm(self, f"Remove '{name}' from the roster? Use this for misreadings. "
                             "Earlier scan records are kept; a later scan adds the unit again "
                             "if it is really on your account.", "Remove Unit?",
                       ok="Remove", destructive=True):
            self.m.units.remove(name)
            self.flash(f"Removed '{name}'", "ok")
            self.refresh_units()
            self._companion_refresh()

    def units_gsc(self):
        """Open the selected unit in the GS Companion tab (or its website when the tab or
        its data is not available)."""
        name = self._units_selected()
        page = getattr(self, "companion", None)
        if page is not None:
            if not name:
                self.nb.select(self._tab_companion)
                return
            if page.show_rerun_unit(name, self._unit_element(name)):
                self.nb.select(self._tab_companion)
                return
            return self.flash(f"GS Companion has no unit matching '{name}' - correct the name "
                              "first if it was misread", "info")
        import webbrowser
        from .units import GSC_UNITS_URL
        if name:
            self.clipboard_clear()
            self.clipboard_append(name)
            self.flash(f"Copied '{name}' - paste it into GSCompanion's search", "info")
        webbrowser.open(GSC_UNITS_URL)

    def _unit_element(self, name: str) -> str | None:
        u = self.m.units.units.get(name)
        return self.m.units.value(u, "element") if u else None

    def _gsc_suggest(self, name: str) -> str | None:
        page = getattr(self, "companion", None)
        if page is None:
            return None
        try:
            return page.match_name(name, self._unit_element(name))
        except Exception as e:  # noqa: BLE001 - a suggestion must never break correcting
            errlog.note("gui.name_suggestion", e)
            return None

    @staticmethod
    def _parse_count(text: str | None) -> int | None | bool:
        """'' -> None (clear), '500' / '1,000' -> int, anything else -> False."""
        t = (text or "").replace(",", "").strip()
        if not t:
            return None
        return int(t) if t.isdigit() else False

    def comp_target(self):
        name = self._units_selected()
        if not name:
            return ios.alert(self, "Select a unit first.", "Set Target")
        c = self.m.compendium
        cur = c.targets["units"].get(name)
        text = ios.ask_string(self, "Set Target",
                              f"Quest clear target for {name}. Leave empty to use the global "
                              "target instead.", str(cur or ""))
        if text is None:
            return
        n = self._parse_count(text)
        if n is False:
            return ios.alert(self, "Type a whole number, e.g. 500.", "Set Target")
        c.set_target(name, n)
        self.flash(f"{name}: target {n:,}" if n else f"{name}: uses the global target", "ok")
        self.refresh_units()
        self._refresh_compendium_tiles(force=True)
        self._companion_refresh()

    def comp_global(self):
        c = self.m.compendium
        text = ios.ask_string(self, "Global Target",
                              "Quest clear target for every unit without its own target. "
                              "Leave empty for none.", str(c.targets.get("global") or ""))
        if text is None:
            return
        n = self._parse_count(text)
        if n is False:
            return ios.alert(self, "Type a whole number, e.g. 100.", "Global Target")
        c.set_global(n)
        self.flash(f"Global target {n:,}" if n else "Global target removed", "ok")
        self.refresh_units()
        self._refresh_compendium_tiles(force=True)
        self._companion_refresh()

    # ================================================================ GS Companion
    def _build_companion(self):
        """GS Companion (gsc_app/): Crest Palace guides, crests, units, team checker and farm
        planner, linked to your roster both ways. Last tab, so the others keep their index.
        Left out when gsc_app/ is missing."""
        self.companion = None
        try:
            from gsc_app.page import GSCompanionPage
        except ImportError:
            return
        page = GSCompanionPage(self.nb.content, self.m.root, flash=self.flash,
                               rerun=RerunLink(self))
        self.nb.add(page, "Companion", "search")
        self.companion = page
        self._tab_companion = len(self.nb._pages) - 1

    def _companion_refresh(self):
        page = getattr(self, "companion", None)
        if page is not None:
            try:
                page.rerun_changed()
            except Exception as e:  # noqa: BLE001 - never let the companion break Rerun
                self.m.log("app", f"GS Companion refresh failed: {e}", level="error")

    def show_in_units(self, name: str) -> bool:
        """Select a roster unit in the Units tab (from GS Companion)."""
        if name not in self.m.units.units:
            return False
        self.units_q.set("")
        self.units_el.set("All elements")
        self.comp_show.set("All units")
        self.refresh_units()
        self.nb.select(self._tab_accounts)          # Units live inside the Account Manager now
        self._am_nav.select("units")
        if self.units_tree.exists(name):
            self.units_tree.selection_set(name)
            self.units_tree.see(name)
        return True
