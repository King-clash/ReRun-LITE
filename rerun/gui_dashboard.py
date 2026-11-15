"""Dashboard tab: instances, stats tiles, Live View.

Moved verbatim from rerun/gui.py (class App); App inherits DashboardMixin."""
from __future__ import annotations

from .gui_common import *  # noqa: F401,F403 - the names the moved methods use
from .gui_common import __all__ as _common_names  # noqa: F401


class DashboardMixin:

    # ================================================================ dashboard
    def _build_dashboard(self):
        _, page, hdr = self._page("Dashboard", "Dashboard", "home")
        ios.Button(hdr, "Stop All", self.stop_all_clicked, kind="tinted", color="red",
                   icon="stop").pack(side="right", padx=(px(8), 0))
        ios.Button(hdr, "Start All", self.start_all, kind="tinted", icon="play").pack(side="right")
        # Countdown of the signed-in key's time left (empty when Rerun runs without a key check)
        self.key_timer = tk.Label(hdr, text="", bg=C["bg"], fg=C["secondary"], font=F["body_semi"])
        self.key_timer.pack(side="right", padx=(0, px(18)))

        body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=px(20), pady=(0, px(14)))
        body.columnconfigure(0, weight=3, uniform="col")
        body.columnconfigure(1, weight=2, uniform="col")
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, px(18)))
        right = tk.Frame(body, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")

        h = ios.section_header(left, "Instances", pady=(0, px(6)))
        ios.Button(h, "Add", self.add_instance, kind="plain", icon="add",
                   small=True).pack(side="right", padx=(px(16), 0))
        ios.Button(h, "Detect BlueStacks", self.detect_instances, kind="plain", icon="search",
                   small=True).pack(side="right")
        card = ios.Card(left)
        card.pack(fill="x")
        self.inst_list = InstanceList(card.body, self._on_select)
        self.inst_list.pack(fill="x")

        g = ios.Group(left)
        g.pack(fill="x", pady=(px(12), 0))
        self.script_var = tk.StringVar()
        self.script_box = ios.Select(g.row("Script", "What the selected instance runs"),
                                     variable=self.script_var, command=self._on_script_change)
        self.script_box.pack()

        bar = tk.Frame(left, bg=C["bg"])
        bar.pack(fill="x", pady=(px(12), 0))
        ios.Button(bar, "Start", self.start_sel, icon="play").pack(side="left")
        ios.Button(bar, "Dry Run", self.dry_run_sel, kind="gray", icon="search").pack(side="left", padx=(px(8), 0))
        self.pause_btn = ios.Button(bar, "Pause", self.pause_sel, kind="tinted", icon="pause")
        self.pause_btn.pack(side="left", padx=px(8))
        ios.Button(bar, "Stop", self.stop_sel, kind="tinted", color="red", icon="stop").pack(side="left")
        ios.Button(bar, "Remove", self.remove_instance, kind="plain", color="red",
                   icon="delete", small=True).pack(side="right")
        ios.Button(bar, "Edit", self.edit_instance, kind="plain", icon="edit",
                   small=True).pack(side="right", padx=(0, px(16)))

        h = ios.section_header(left, "Totals", pady=(px(16), px(6)))
        ios.Button(h, "Reset", self.reset_stats, kind="plain", color="red",
                   small=True).pack(side="right")
        tiles = tk.Frame(left, bg=C["bg"])
        tiles.pack(fill="x")
        self.tiles: dict[str, StatTile] = {}
        for i, (key, cap) in enumerate([("runs", "Runs"), ("kept", "Crests kept"),
                                        ("scrapped", "Scrapped"), ("potions", "Potions"),
                                        ("seconds", "Run time")]):
            t = StatTile(tiles, cap)
            t.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else px(8), 0))
            tiles.columnconfigure(i, weight=1, uniform="tile")
            self.tiles[key] = t

        ios.section_header(left, "Crests", pady=(px(16), px(6)))
        ctiles = tk.Frame(left, bg=C["bg"])
        ctiles.pack(fill="x")
        self.crest_tiles: dict[str, StatTile] = {}
        for i, (key, cap) in enumerate([("4+", "4+ crests"),
                                        ("burst", "Crest Burst"),
                                        ("lv4", "Lv4 (not 4+)"),
                                        ("since", "Runs since last 4+"),
                                        ("rate", "4+ observed rate")]):
            t = StatTile(ctiles, cap)
            t.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else px(8), 0))
            ctiles.columnconfigure(i, weight=1, uniform="ctile")
            self.crest_tiles[key] = t
        self.crest_note = self._label(left, "", anchor="w", justify="left")
        self.crest_note.pack(fill="x", pady=(px(4), 0))
        self._crest_cache_key = None

        # Compendium summary: one line, so the Instructions box keeps its room
        self.comp_line = self._label(left, "", anchor="w", justify="left", secondary=False)
        self.comp_line.pack(fill="x", pady=(px(8), 0))
        self._comp_cache_key = None

        ios.section_header(left, "Instructions", pady=(px(16), px(6)))
        _, self.instr = ios.text_box(left)
        self.instr.tag_configure("warn", foreground=C["orange"], font=F["footnote_semi"])
        self.instr.configure(state="disabled")

        h = ios.section_header(right, "Live View", pady=(0, px(6)))
        ios.Button(h, "Screenshot", self.preview_shot, kind="plain", icon="camera",
                   small=True).pack(side="right")
        self.live_auto = tk.BooleanVar(value=bool(self.m.config.get("live_view_auto", True)))
        ios.Switch(h, self.live_auto, command=self._save_live_auto).pack(side="right", padx=(0, px(14)))
        self._label(h, "Auto").pack(side="right", padx=(0, px(6)))
        self.live_rate = self._label(h, "")   # "30 fps" while the video stream runs
        self.live_rate.pack(side="right", padx=(0, px(12)))
        pc = ios.Card(right, pad=6, stretch=True, color=C["viewer"])
        pc.pack(fill="both", expand=True)
        self.preview = tk.Canvas(pc.body, bg=C["viewer"], highlightthickness=0, bd=0)
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Configure>", lambda e: self._draw_preview())
        self._preview_img: np.ndarray | None = None
        self._preview_photo = None
        self._preview_src = None   # last frame object drawn (skip redraws of the same frame)
        self._preview_busy = False
        self._preview_last_idle = 0.0
        self._stream = None          # LiveStream (rerun/live_stream.py) while it runs
        self._stream_serial = None
        self._stream_seq = -1
        self._stream_failed: dict[str, float] = {}  # serial -> when video failed (retry later)
        self._live_loop_on = False
        self._idle_energy: dict[str, tuple[int, int, float]] = {}

    def selected(self) -> str | None:
        sel = self.inst_list.sel
        return sel if sel in self.m.instances else None

    def refresh_instances(self):
        scripts = self.m.scripts_available()
        self.script_box["values"] = list(scripts.values())
        items = []
        for name, inst in self.m.instances.items():
            stats = self.m.stats.get(name)
            runs = stats.get(f"{inst.script}.runs", "")
            up = fmt_duration(self.m.stats.uptime(name)) if inst.status in ("running", "paused") else ""
            meta = []
            e = self.energy_of(name)
            if e and time.time() - e[2] < 15 * 60:
                meta.append(f"Energy {e[0]}/{e[1]}")
            if runs != "":
                meta.append(f"{runs} run{'' if runs == 1 else 's'}")
            if up:
                meta.append(up)
            items.append({
                "name": name, "title": name, "state": inst.status,
                "sub": f"{inst.serial}  ·  {scripts.get(inst.script, inst.script)}",
                "detail": short(inst.detail or "Ready", 78),
                "status": STATUS_TEXT.get(inst.status, inst.status),
                "meta": "  ·  ".join(meta)})
        self.inst_list.set_rows(items)
        if not self.selected() and self.m.instances:
            self.inst_list.select(next(iter(self.m.instances)), user=True)
        name = self.selected()
        want = "Resume" if name and self.m.instances[name].status == "paused" else "Pause"
        if self.pause_btn._text != want:
            self.pause_btn.set_text(want)
        self._refresh_totals()
        self._refresh_instance_lists()

    def _refresh_totals(self):
        name = self.selected()
        t = self.m.totals(name) if name else {}
        for key, tile in self.tiles.items():
            v = t.get(key, 0)
            tile.set(fmt_duration(v) if key == "seconds" else f"{v:,}")
        self._refresh_crests(name)
        self._refresh_compendium_tiles()

    def _refresh_compendium_tiles(self, force: bool = False):
        """Dashboard: last full scan, units near / at target (recomputed when scans change)."""
        c = getattr(self.m, "compendium", None)
        if c is None or not hasattr(self, "comp_line"):
            return
        p = c.r.scans_path
        try:
            mt = p.stat().st_mtime
        except OSError:
            mt = 0
        key = (mt, len(c.r.units), int(time.time() // 600))
        if key == self._comp_cache_key and not force:
            return
        self._comp_cache_key = key
        s = c.summary()
        last = s["last_complete"]
        text = "Compendium:  last full scan " + (
            datetime.fromtimestamp(last).strftime("%d %b %H:%M") if last else "none yet")
        if s["units"]:
            text += f"  ·  {s['units']:,} units"
        if s["with_target"]:
            text += f"  ·  near target {s['near']:,}  ·  at target {s['done']:,}"
        elif s["units"]:
            text += "  ·  no targets set"
        if self.comp_line.cget("text") != text:
            self.comp_line.configure(text=text)

    def _refresh_crests(self, name: str | None):
        """Crest 4+ / Burst / Lv4 tiles from the crest ledger (recomputed only when it changes)."""
        led = getattr(self.m, "crests", None)
        if led is None or not hasattr(self, "crest_tiles"):
            return
        key = (name, len(led.records), int(time.time() // 600))
        if key == self._crest_cache_key:
            return
        self._crest_cache_key = key
        s = led.summary(name)
        for cls in ("4+", "burst", "lv4"):
            self.crest_tiles[cls].set(" · ".join(
                f"{s[w]['drops'][cls]:,}" for w in ("today", "session", "all")))
        self.crest_tiles["since"].set(f"{s['since_4+']:,}")
        n = s["all"]["drops"]["4+"]
        self.crest_tiles["rate"].set(f"1/{s['avg_runs_4+']:,.0f}" if n else "–")
        last = s["last_notable"]
        parts = [f"{s['rate_4+'][0].upper()}{s['rate_4+'][1:]} (4+)", f"{s['rate_burst']} (Burst)"]
        parts.append("Last 4+/Burst: " + (time.strftime("%d %b %H:%M", time.localtime(last["t"]))
                                          + f" ({last['rarity']})" if last else "none yet"))
        note = ("Counts: today · this session · all-time.  " + "  ·  ".join(parts)
                + "\nObserved results only, not a prediction.")
        if s["baseline_runs"]:
            note += f" {s['baseline_runs']:,} earlier runs have no dates."
        if s["uncertain"]:
            note += f" {s['uncertain']} uncertain."
        if self.crest_note.cget("text") != note:
            self.crest_note.configure(text=note)

    def reset_stats(self):
        name = self.selected()
        if not name:
            return
        if ios.confirm(self, f"Runs, crests, potions and run time for {name} go back to zero. "
                             "History is kept.", "Reset Stats?", ok="Reset", destructive=True):
            self.flash(self.m.reset_stats(name), "ok")
            self.refresh_instances()

    def _on_select(self):
        name = self.selected()
        if not name:
            return
        inst = self.m.instances[name]
        self.script_var.set(self.m.scripts_available().get(inst.script, ""))
        self._show_instructions(inst.script)
        self._preview_src = None
        self._refresh_totals()

    def _show_instructions(self, script: str):
        cls = SCRIPTS.get(script)
        text = cls.INSTRUCTIONS if cls else "Custom routine - see routines/README.md."
        missing = self.m.missing_templates(script)
        self.instr.configure(state="normal")
        self.instr.delete("1.0", "end")
        if missing:
            self.instr.insert("1.0", f"Setup needed: {len(missing)} template(s) still to capture "
                              f"in the Templates tab:\n", "warn")
            self.instr.insert("end", "  " + "\n  ".join(missing) + "\n\n", "warn")
        self.instr.insert("end", text)
        self.instr.configure(state="disabled")

    def _script_id(self, label: str) -> str | None:
        for k, v in self.m.scripts_available().items():
            if v == label:
                return k
        return None

    def _on_script_change(self):
        name = self.selected()
        sid = self._script_id(self.script_var.get())
        if name and sid:
            if self.m.instances[name].status not in ("idle", "error"):
                ios.alert(self, "Stop the instance before changing its script.")
                self._on_select()
                return
            self.m.set_instance_script(name, sid)
            self._show_instructions(sid)
            self.refresh_instances()

    def start_sel(self):
        name = self.selected()
        if not name:
            return
        script = self.m.instances[name].script
        missing = self.m.missing_templates(script)
        if missing:
            ios.alert(self, "Capture these in the Templates tab first:\n\n" + "\n".join(missing[:20]),
                      "Templates Missing")
            return
        cls = SCRIPTS.get(script)
        if cls and cls.BETA and not ios.confirm(
                self, f"{cls.NAME} was built from ReStart's routine but hasn't been run on your game "
                      "yet. Watch the first runs and stop it (F12) if anything looks wrong.",
                "Beta Script", ok="Start"):
            return
        self.flash(self._start_checked(name))

    def stop_sel(self):
        if self.selected():
            self.flash(self.m.stop(self.selected()))

    def pause_sel(self):
        name = self.selected()
        if not name:
            return
        inst = self.m.instances[name]
        self.flash(self.m.resume(name) if inst.status == "paused" else self.m.pause(name))

    def start_all(self):
        self.flash(" | ".join(self.m.start_all()))

    def stop_all_clicked(self):
        """The on-screen button: asks first when 'Confirm before Stop All' is on. The F12 hotkey and
        the tray menu call stop_all() directly - an emergency stop never asks."""
        running = [n for n, i in self.m.instances.items() if i.status in ("running", "paused", "starting")]
        if running and (self.m.config.get("ui") or {}).get("confirm_stop_all") and not ios.confirm(
                self, f"Stop {len(running)} running script(s)?", "Stop All", ok="Stop All", destructive=True):
            return
        self.stop_all()

    def stop_all(self):
        self.flash(" | ".join(self.m.stop_all()) or "Nothing running")

    def _instance_items(self) -> list[dict]:
        return [dict(i) for i in self.m.config["instances"]]

    def add_instance(self):
        name = ios.ask_string(self, "Add Instance", "Name",
                              initial=f"Instance {len(self.m.instances) + 1}")
        if not name:
            return
        if name in self.m.instances:
            ios.alert(self, "That name is already used.")
            return
        serial = ios.ask_string(self, "Add Instance", "ADB address\n(BlueStacks: 127.0.0.1:<port>)",
                                initial="127.0.0.1:5555")
        if not serial:
            return
        items = self._instance_items() + [{"name": name, "serial": serial, "script": "crest"}]
        self.m.set_instances(items)
        self.refresh_instances()

    def edit_instance(self):
        name = self.selected()
        if not name:
            return
        if self.m.instances[name].status not in ("idle", "error"):
            ios.alert(self, "Stop the instance first.")
            return
        serial = ios.ask_string(self, "Edit Instance", f"ADB address for {name}",
                                initial=self.m.instances[name].serial)
        if not serial:
            return
        items = self._instance_items()
        for i in items:
            if i["name"] == name:
                i["serial"] = serial
        self.m.set_instances(items)
        self.refresh_instances()

    def remove_instance(self):
        name = self.selected()
        if not name:
            return
        if self.m.instances[name].status not in ("idle", "error"):
            ios.alert(self, "Stop the instance first.")
            return
        if not ios.confirm(self, f"{name} will be removed from Rerun.", "Remove Instance?",
                           ok="Remove", destructive=True):
            return
        self.m.set_instances([i for i in self._instance_items() if i["name"] != name])
        self.inst_list.sel = None
        self.refresh_instances()

    def detect_instances(self):
        found = discover_bluestacks_instances()
        if not found:
            ios.alert(self, "No BlueStacks 5 instances found in bluestacks.conf.")
            return
        items = self._instance_items()
        have = {i["serial"] for i in items}
        added = []
        for inst in found:
            if inst["serial"] not in have:
                name = inst["name"]
                while any(i["name"] == name for i in items):
                    name += "+"
                items.append({"name": name, "serial": inst["serial"], "script": "crest"})
                added.append(f"{name} ({inst['serial']})")
        self.m.set_instances(items)
        self.refresh_instances()
        msg = ("Added:\n" + "\n".join(added)) if added else "All BlueStacks instances are already listed."
        if not found[0]["adb_enabled"]:
            msg += ("\n\nADB is OFF in BlueStacks. Turn it on: BlueStacks Settings > Advanced > "
                    "Android Debug Bridge (ADB). Also set Display to 1280x720 "
                    "(the game then runs at 720x1280 portrait).")
        ios.alert(self, msg, "BlueStacks")

    # live view -------------------------------------------------------------
    def preview_shot(self, quiet: bool = False):
        name = self.selected()
        if not name or self._preview_busy:
            return
        self._preview_busy = True

        def work():
            try:
                img = self.m.screenshot(name)
                self.events.put({"type": "_preview", "img": img})
                self._read_idle_energy(name, img)
            except Exception as e:  # noqa: BLE001
                if not quiet:
                    self.events.put({"type": "_error", "message": f"Screenshot failed: {e}"})
            finally:
                self._preview_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _energy_shot(self, name: str) -> None:
        """A full-size screenshot just for the idle energy reading (worker thread)."""
        def work():
            try:
                self._read_idle_energy(name, self.m.screenshot(name))
            except Exception as e:  # noqa: BLE001 - energy is optional
                errlog.note("gui.idle_energy", e)
        threading.Thread(target=work, daemon=True).start()

    def _read_idle_energy(self, name: str, img: np.ndarray) -> None:
        """Energy for an idle instance, from its preview frame (worker thread;
        at most once a minute per instance)."""
        last = self._idle_energy.get(name)
        if last and time.time() - last[2] < 60:
            return
        try:
            from .ocr import get_ocr, read_energy
            e = read_energy(get_ocr(self.m.config.get("tesseract_path", "auto")), img)
        except Exception as e:  # noqa: BLE001 - no OCR: simply not shown
            errlog.note("gui.read_idle_energy", e)
            return
        if e:
            self._idle_energy[name] = (e[0], e[1], time.time())

    def energy_of(self, name: str) -> tuple[int, int, float] | None:
        inst = self.m.instances.get(name)
        e = inst.ctx.params.get("energy") if inst and inst.ctx else None
        return e or self._idle_energy.get(name)

    def _save_live_auto(self):
        self.m.config["live_view_auto"] = bool(self.live_auto.get())
        self.m.save_config()

    # Smooth live view: a video stream of the emulator (rerun/live_stream.py) shown at
    # live_view_fps (default 30) while the Dashboard is on screen; 0 turns it off.
    def _live_fps(self) -> int:
        try:
            return max(0, min(60, int(self.m.config.get("live_view_fps", 30))))
        except (TypeError, ValueError):
            return 30

    def _stop_stream(self):
        if self._stream is not None:
            self._stream.stop()
        self._stream, self._stream_serial = None, None
        if self.live_rate.cget("text"):
            self.live_rate.configure(text="")

    def _manage_stream(self, name: str | None) -> bool:
        """Start / stop the video stream for the shown instance. True while it runs."""
        want = (name is not None and self._live_fps() > 0 and self.live_auto.get()
                and self._dashboard_in_view() and self.state() not in ("withdrawn", "iconic"))
        serial = self.m.instances[name].serial if want else None
        failed_at = self._stream_failed.get(serial) if serial else None
        if not want or (failed_at and time.monotonic() - failed_at < STREAM_RETRY_S):
            self._stop_stream()
            return False
        s = self._stream
        if s is not None and s.failed:
            self.m.log(name, f"Live View: video stream unavailable ({s.error}) - using screenshots, "
                             f"retrying in {STREAM_RETRY_S // 60} min")
            self._stream_failed[serial] = time.monotonic()
            self._stop_stream()
            return False
        if s is None or self._stream_serial != serial or not s.alive:
            self._stop_stream()
            from .live_stream import LiveStream
            img = self._preview_img
            portrait = img is None or img.shape[0] >= img.shape[1]
            try:
                self._stream = LiveStream(self.m.adb_path(), serial, portrait=portrait).start()
            except Exception as e:  # noqa: BLE001 - fall back to screenshots
                self.m.log(name, f"Live View: video stream could not start ({e}) - using screenshots")
                self._stream_failed[serial] = time.monotonic()
                return False
            self._stream_serial, self._stream_seq = serial, -1
        if not self._live_loop_on:
            self._live_loop_on = True
            self.after(10, self._live_loop)
        return True

    def _live_loop(self):
        """Draws the newest stream frame up to live_view_fps times a second."""
        s = self._stream
        if s is None:
            self._live_loop_on = False
            return
        started = time.perf_counter()
        if s.seq != self._stream_seq and s.frame is not None:
            self._stream_seq = s.seq
            self._preview_img = s.frame
            self._draw_preview()
        fps = self._live_fps() or 30
        rate = f"{min(fps, round(s.fps())):d} fps" if s.seq > 0 else "starting…"
        if self.live_rate.cget("text") != rate:
            self.live_rate.configure(text=rate)
        # next frame one period after this one started (drawing time included)
        spent = (time.perf_counter() - started) * 1000
        self.after(max(1, int(1000 / fps - spent)), self._live_loop)

    def _auto_preview(self):
        """Live View. With the video stream (default): smooth frames at live_view_fps.
        Otherwise, while a script runs, show the frames it already captures (no extra
        ADB work); when idle, take a screenshot every few seconds - and only while the
        Dashboard is actually on screen."""
        name = self.selected() if self.live_auto.get() else None
        if self._manage_stream(name):
            inst = self.m.instances[name]
            # idle energy still comes from a full screenshot (at most once a minute)
            last = self._idle_energy.get(name)
            if inst.status in ("idle", "error") and inst.ctx is None and \
                    (not last or time.time() - last[2] >= 60) and \
                    time.monotonic() - self._preview_last_idle >= 60:
                self._preview_last_idle = time.monotonic()
                self._energy_shot(name)
            return
        if not self.live_auto.get() or not self._dashboard_in_view() or self.state() == "withdrawn":
            return
        if not name:
            return
        inst = self.m.instances[name]
        frame = inst.ctx.last_screen if inst.ctx is not None else None
        if frame is not None:
            if frame is not self._preview_src:
                self._preview_img = frame
                self._draw_preview()
            return
        if inst.status in ("idle", "error") and \
                time.monotonic() - self._preview_last_idle >= IDLE_PREVIEW_EVERY_S:
            self._preview_last_idle = time.monotonic()
            self.preview_shot(quiet=True)

    def _draw_preview(self):
        c = self.preview
        W, H = c.winfo_width(), c.winfo_height()
        if self._preview_img is None:
            c.delete("all")
            self._preview_item = None
            c.create_text(W // 2, H // 2, justify="center", fill=C["gray"], font=F["footnote"],
                          text="No screenshot yet\nTurn on Auto or press Screenshot")
            return
        self._preview_src = img = self._preview_img
        h, w = img.shape[:2]
        scale = min(max(50, W) / w, max(50, H) / h, 1.0)
        size = (max(1, int(w * scale)), max(1, int(h * scale)))
        small = img if scale == 1.0 else cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        pil = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        photo = self._preview_photo
        item = getattr(self, "_preview_item", None)
        if item is not None and photo is not None and (photo.width(), photo.height()) == size \
                and c.coords(item) == [float(W // 2), float(H // 2)]:
            photo.paste(pil)   # same size and place: update in place (30 fps friendly)
            return
        c.delete("all")
        self._preview_photo = ImageTk.PhotoImage(pil)
        self._preview_item = c.create_image(W // 2, H // 2, image=self._preview_photo, anchor="center")
