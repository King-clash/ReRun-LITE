"""Templates tab: capture, test and import template pictures.

Moved verbatim from rerun/gui.py (class App); App inherits TemplatesMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class TemplatesMixin:

    # ================================================================ templates
    def _build_templates(self):
        _, page, hdr = self._page("Templates", "Templates", "photo")
        ios.Button(hdr, "Import from ReStart", self.tpl_import_restart, kind="tinted",
                   icon="download").pack(side="right")
        body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=px(20), pady=(0, px(14)))

        left = tk.Frame(body, bg=C["bg"], width=px(350))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        g = ios.Group(left)
        g.pack(fill="x")
        self.tpl_script = ios.Select(g.row("Checklist for"), command=self.refresh_checklist)
        self.tpl_script.pack()
        h = ios.section_header(left, "Templates", pady=(px(14), px(6)))
        self.tpl_count = self._label(h, "")
        self.tpl_count.pack(side="right")
        tc = ios.Card(left, pad=6, stretch=True)
        tc.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(tc.body, orient="vertical", style="IOS.Vertical.TScrollbar")
        self.tpl_tree = ttk.Treeview(tc.body, columns=("have",), show="tree",
                                     style="IOS.Treeview", selectmode="browse",
                                     yscrollcommand=sb.set)
        sb.configure(command=self.tpl_tree.yview)
        self.tpl_tree.column("#0", width=px(220), stretch=True)
        self.tpl_tree.column("have", width=px(76), stretch=False, anchor="e")
        self.tpl_tree.tag_configure("missing", foreground=C["red"])
        self.tpl_tree.tag_configure("optional", foreground=C["secondary"])
        self.tpl_tree.tag_configure("weak", foreground=C["orange"])
        sb.pack(side="right", fill="y", pady=px(4))
        self.tpl_tree.pack(side="left", fill="both", expand=True)
        self.tpl_tree.bind("<<TreeviewSelect>>", lambda e: self._on_tpl_select())
        self.tpl_desc = self._label(left, wraplength=px(320), justify="left", anchor="w")
        self.tpl_desc.pack(fill="x", padx=px(16), pady=(px(8), 0))

        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(px(18), 0))
        bar = tk.Frame(right, bg=C["bg"])
        bar.pack(fill="x")
        self._label(bar, "Instance", secondary=False, font="body").pack(side="left")
        self.tpl_inst = ios.Select(bar, accent=True)
        self.tpl_inst.pack(side="left", padx=(px(8), px(18)))
        ios.Button(bar, "Screenshot", self.tpl_screenshot, icon="camera").pack(side="left")
        ios.Button(bar, "Open Image…", self.tpl_open, kind="tinted",
                   icon="folder").pack(side="left", padx=px(8))
        self._label(right, wraplength=px(760), justify="left", anchor="w", text=(
            "Take a screenshot with the game on the right screen, pick a template on the left, "
            "drag a box tightly around the element, then Save Selection. Test shows how well it "
            "matches the current image (green = found).")).pack(fill="x", pady=(px(10), px(8)))
        cc = ios.Card(right, pad=6, stretch=True, color=C["viewer"])
        cc.pack(fill="both", expand=True)
        self.tpl_canvas = tk.Canvas(cc.body, bg=C["viewer"], highlightthickness=0, bd=0,
                                    cursor="crosshair")
        self.tpl_canvas.pack(fill="both", expand=True)
        self.tpl_canvas.bind("<ButtonPress-1>", self._drag_start)
        self.tpl_canvas.bind("<B1-Motion>", self._drag_move)
        self.tpl_canvas.bind("<Configure>", lambda e: self._draw_tpl_image())
        bot = tk.Frame(right, bg=C["bg"])
        bot.pack(fill="x", pady=(px(10), 0))
        ios.Button(bot, "Save Selection", self.tpl_save, icon="save").pack(side="left")
        ios.Button(bot, "Suggest Crop", self.tpl_suggest, kind="tinted", icon="search").pack(side="left", padx=px(8))
        ios.Button(bot, "Test", self.tpl_test, kind="tinted", icon="search").pack(side="left", padx=px(8))
        ios.Button(bot, "Delete", self.tpl_delete, kind="tinted", color="red",
                   icon="delete").pack(side="left")
        ios.Button(bot, "Read Text", self.tpl_read_text, kind="tinted",
                   icon="edit").pack(side="right")
        self.tpl_img: np.ndarray | None = None
        self.tpl_scale = 1.0
        self.tpl_photo = None
        self.sel_rect = None  # canvas coords
        self._drag_origin = (0, 0)
        self._tpl_info: dict[str, str] = {}
        self.tpl_script["values"] = list(self.m.scripts_available().values())
        self.tpl_script.current(1)
        self.after(50, self.refresh_checklist)

    def refresh_checklist(self):
        sid = self._script_id(self.tpl_script.get())
        keep = self.tpl_tree.selection()
        self.tpl_tree.delete(*self.tpl_tree.get_children())
        if not sid:
            return
        self._tpl_info = {}
        have_n = need_n = 0
        health = self.m.vision.health()
        for name, desc, optional, have in self.m.template_checklist(sid):
            kind = "ok" if have else ("optional" if optional else "missing")
            mark = "" if have else ("Optional" if optional else "Missing")
            hh = health.get(name)
            if have and hh and hh["weak"]:
                kind, mark = "weak", f"Weak {hh['median']:.2f}"
                desc = (f"Matching weakly lately (median {hh['median']:.2f}, needs "
                        f"{hh['threshold']:.2f}) - usually a game update. Re-capture it, or "
                        f"Import from ReStart if ReStart has updated.\n\n{desc}")
            tag = () if kind == "ok" else ((kind,))
            self.tpl_tree.insert("", "end", iid=name, text=f"  {name}", image=ios.badge(kind),
                                 values=(f"{mark}  ",), tags=tag)
            self._tpl_info[name] = desc
            have_n += bool(have)
            need_n += 1
        self.tpl_count.configure(text=f"{have_n} of {need_n} captured")
        if keep and self.tpl_tree.exists(keep[0]):
            self.tpl_tree.selection_set(keep[0])

    def _on_tpl_select(self):
        sel = self.tpl_tree.selection()
        if sel:
            self.tpl_desc.configure(text=f"{sel[0]}\n{self._tpl_info.get(sel[0], '')}")

    def tpl_screenshot(self):
        name = self.tpl_inst.get()
        if not name:
            return

        def work():
            try:
                self.events.put({"type": "_tpl_img", "img": self.m.screenshot(name)})
            except Exception as e:  # noqa: BLE001
                self.events.put({"type": "_error", "message": f"Screenshot failed: {e}"})
        threading.Thread(target=work, daemon=True).start()

    def tpl_open(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                ios.alert(self, "Could not read that image.")
                return
            self.set_tpl_image(img)

    def set_tpl_image(self, img: np.ndarray):
        self.tpl_img = img
        self.sel_rect = None
        h, w = img.shape[:2]
        if (w, h) != (720, 1280):
            self.flash(f"Note: this image is {w}x{h}. Scripts expect 720x1280 "
                       "(BlueStacks Display set to 1280x720).", "warn")
        self._draw_tpl_image()

    def _draw_tpl_image(self, boxes: list | None = None):
        c = self.tpl_canvas
        c.delete("all")
        if self.tpl_img is None:
            c.create_text(c.winfo_width() // 2, c.winfo_height() // 2, justify="center",
                          fill=C["gray"], font=F["footnote"],
                          text="No image yet\nPress Screenshot or Open Image…")
            return
        self.tpl_photo, self.tpl_scale = to_photo(self.tpl_img, max(50, c.winfo_width()),
                                                  max(50, c.winfo_height()))
        c.create_image(0, 0, image=self.tpl_photo, anchor="nw")
        if self.sel_rect:
            c.create_rectangle(*self.sel_rect, outline=C["blue"], width=2, tags="sel")
        for (x, y, w, h, color, label) in boxes or []:
            s = self.tpl_scale
            c.create_rectangle(x * s, y * s, (x + w) * s, (y + h) * s, outline=color, width=2)
            c.create_text(x * s + 2, y * s - 9, text=label, fill=color, anchor="w",
                          font=F["footnote_semi"])

    def _drag_start(self, e):
        self._drag_origin = (e.x, e.y)
        self.sel_rect = (e.x, e.y, e.x, e.y)
        self._draw_tpl_image()

    def _drag_move(self, e):
        x0, y0 = self._drag_origin
        self.sel_rect = (min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y))
        self.tpl_canvas.delete("sel")
        self.tpl_canvas.create_rectangle(*self.sel_rect, outline=C["blue"], width=2, tags="sel")

    def tpl_suggest(self):
        """Draw the box for the selected template where it belongs (palace tile, quest row, Home
        button) so only Save Selection is left to press. Uses the text reader for the first two."""
        sel = self.tpl_tree.selection()
        if self.tpl_img is None:
            ios.alert(self, "Take a screenshot (or open an image) of the right screen first.")
            return
        if not sel:
            ios.alert(self, "Pick a template on the left first, e.g. crest_palace_target or quest_list_entry.")
            return
        name = sel[0]
        words = []
        if name != "home_nav_button":
            self.flash("Reading the screen…")
            self.update_idletasks()
            try:
                from .ocr import get_ocr
                words = get_ocr(self.m.config.get("tesseract_path", "auto")).screen_words(self.tpl_img, min_conf=40)
            except Exception as e:  # noqa: BLE001 - no text reader: say so
                errlog.note("gui.tpl_suggest", e)
                ios.alert(self, f"This suggestion needs the text reader, which isn't available: {e}")
                return
        prefs = []
        try:
            cfg = self.m.script_settings(self.tpl_inst.get() or next(iter(self.m.instances), ""), "crest")
            prefs = qol.split_names(str(cfg.get("palace_name") or ""))
        except Exception as e:  # noqa: BLE001 - settings are optional here
            errlog.note("gui.tpl_suggest.prefs", e)
        found = textnav.suggest_crop(name, words, prefs)
        if not found:
            self.flash(f"No suggestion for '{name}' on this screen - drag the box yourself.", "warn")
            return
        (x, y, w, h), why = found
        ih, iw = self.tpl_img.shape[:2]
        fx, fy, s = iw / 720, ih / 1280, self.tpl_scale
        self.sel_rect = (x * fx * s, y * fy * s, (x + w) * fx * s, (y + h) * fy * s)
        self._draw_tpl_image()
        self.flash(f"Suggested: {why}. Adjust the box if needed, then Save Selection.", "ok")

    def tpl_save(self):
        sel = self.tpl_tree.selection()
        if self.tpl_img is None or not self.sel_rect:
            ios.alert(self, "Take a screenshot and drag a box first.")
            return
        name = sel[0] if sel else ios.ask_string(self, "New Template", "Template name")
        if not name:
            return
        s = self.tpl_scale
        x0, y0, x1, y1 = (int(v / s) for v in self.sel_rect)
        h, w = self.tpl_img.shape[:2]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 - x0 < 6 or y1 - y0 < 6:
            ios.alert(self, "The box is too small.")
            return
        if self.m.store.has(name) and not ios.confirm(
                self, f"'{name}' already exists.", "Replace Template?", ok="Replace"):
            return
        self.m.store.save(name, self.tpl_img, x0, y0, x1 - x0, y1 - y0)
        self.m.vision.reset_health(name)
        self._weak_seen.discard(name)
        self.flash(f"Saved template '{name}' ({x1 - x0}x{y1 - y0})", "ok")
        self.refresh_checklist()
        if self.selected():
            self._show_instructions(self.m.instances[self.selected()].script)

    def tpl_test(self):
        sel = self.tpl_tree.selection()
        if self.tpl_img is None or not sel:
            return
        name = sel[0]
        if not self.m.store.has(name):
            self.flash(f"'{name}' has not been captured yet", "warn")
            return
        m = self.m.vision.score(self.tpl_img, name)
        thr = self.m.store.threshold(name)
        if not m:
            self.flash(f"'{name}': no match possible on this image", "warn")
            return
        found = m.score >= thr
        self.sel_rect = None
        self._draw_tpl_image([(m.x, m.y, m.w, m.h, C["green"] if found else C["red"],
                               f"{name} {m.score:.2f}")])
        self.flash(f"'{name}': score {m.score:.3f} (needs {thr:.2f}) -> "
                   f"{'FOUND' if found else 'not found'}", "ok" if found else "warn")

    def tpl_read_text(self):
        """OCR the dragged box - shows what scripts would read there."""
        if self.tpl_img is None or not self.sel_rect:
            ios.alert(self, "Take a screenshot and drag a box around some text first.")
            return
        s = self.tpl_scale
        x0, y0, x1, y1 = (int(v / s) for v in self.sel_rect)
        crop = self.tpl_img[max(0, y0):y1, max(0, x0):x1].copy()
        if crop.shape[0] < 6 or crop.shape[1] < 6:
            ios.alert(self, "The box is too small.")
            return
        self.flash("Reading text…")
        path = self.m.config.get("tesseract_path", "auto")

        def work():
            from .ocr import OcrUnavailable, get_ocr
            try:
                r = get_ocr(path).read(crop, line=crop.shape[0] < 80)
                msg = (f"“{r.text}”\n\nConfidence {r.confidence:.0f}%"
                       if r else "No text found in that box.")
                self.events.put({"type": "_alert", "title": "Text Read", "message": msg})
            except OcrUnavailable as e:
                self.events.put({"type": "_error", "message": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def tpl_import_restart(self):
        from .restart_import import default_restart_dir, find_templates_dir, import_templates
        base = default_restart_dir()
        if find_templates_dir(base) is None:
            picked = filedialog.askdirectory(title="Select your ReStart folder")
            if not picked:
                return
            base = Path(picked)
        overwrite = ios.confirm(
            self, "Also replace templates you captured yourself?\n\n"
                  "Keep Mine only fills in the ones you don't have.",
            "Import from ReStart", ok="Replace", cancel="Keep Mine", default_cancel=True)
        try:
            res = import_templates(self.m.store, base, overwrite_own=overwrite)
        except FileNotFoundError as e:
            ios.alert(self, str(e))
            return
        self.m.vision.reset_health()
        self._weak_seen.clear()
        self.refresh_checklist()
        if self.selected():
            self._show_instructions(self.m.instances[self.selected()].script)
        msg = f"Imported {len(res['imported'])} template(s) from ReStart."
        if res["skipped_own"]:
            msg += f"\nKept your own: {', '.join(res['skipped_own'])}"
        if res["not_found"]:
            msg += f"\nNot in this ReStart version: {', '.join(res['not_found'])}"
        ios.alert(self, msg, "Import Complete")

    def tpl_delete(self):
        sel = self.tpl_tree.selection()
        if sel and self.m.store.has(sel[0]) and ios.confirm(
                self, f"'{sel[0]}' will be deleted.", "Delete Template?", ok="Delete",
                destructive=True):
            self.m.store.delete(sel[0])
            self.refresh_checklist()
