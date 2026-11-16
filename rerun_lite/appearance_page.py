"""Settings > Appearance: look, mode, accent colour, contrast, density and the background, all applied at once.

Every control here ends in `LiteApp.apply_appearance()`, which saves the choice and rebuilds the window in the new
colours without a restart. The page is rebuilt with everything else, so it always shows the choice that is in force.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import colorchooser, filedialog

from rerun import ios
from rerun.ios import C, F, px

from . import appearance as ap
from . import background
from .colors import valid_hex


class LookTile(tk.Frame):
    """One look as a small picture of itself (page, panel, accent) with its name; the open one has an accent frame."""

    def __init__(self, parent, key: str, name: str, mode: str, selected: bool, command):
        super().__init__(parent, bg=C["bg"], cursor="hand2")
        pal = ap.resolve(ap.Appearance(key, mode)).palette
        w, h = px(128), px(70)
        edge = C["blue"] if selected else C["sep"]
        cv = tk.Canvas(self, width=w, height=h, bg=C["bg"], highlightthickness=0, bd=0, cursor="hand2")
        cv.pack()
        cv.create_rectangle(0, 0, w - 1, h - 1, fill=pal["bg"], outline=edge, width=px(2 if selected else 1))
        cv.create_rectangle(px(10), px(14), px(78), px(56), fill=pal["card"], outline=pal["sep"])
        cv.create_rectangle(px(16), px(22), px(52), px(26), fill=pal["label"], width=0)
        cv.create_rectangle(px(16), px(32), px(40), px(35), fill=pal["secondary"], width=0)
        cv.create_rectangle(px(16), px(42), px(46), px(50), fill=pal["blue"], width=0)
        cv.create_rectangle(px(86), px(14), w - px(12), px(26), fill=pal["fill"], outline=pal["sep"])
        cv.create_rectangle(px(86), px(32), w - px(12), px(44), fill=pal["fill"], outline=pal["sep"])
        tk.Label(self, text=name, bg=C["bg"], fg=C["label"] if selected else C["secondary"],
                 font=F["footnote_semi" if selected else "footnote"]).pack(pady=(px(4), 0))
        for w_ in (self, cv, *self.winfo_children()):
            w_.bind("<Button-1>", lambda e: command())


class Swatches(tk.Canvas):
    """A row of accent colours. The one in use has a ring; the last circle opens the colour picker."""

    R = 11

    def __init__(self, parent, colors: list[str], current: str, on_pick, on_custom):
        r = px(self.R)
        n = len(colors) + 1
        super().__init__(parent, width=n * (2 * r + px(10)), height=2 * r + px(8), bg=ios.bg_of(parent), highlightthickness=0,
                         bd=0, cursor="hand2")
        self._colors, self._on_pick, self._on_custom = colors, on_pick, on_custom
        for i, col in enumerate(colors):
            cx = i * (2 * r + px(10)) + r + px(4)
            on = current.lower() == col.lower()
            if on:
                self.create_oval(cx - r - px(3), px(1), cx + r + px(3), 2 * r + px(7), outline=C["label"], width=px(2))
            self.create_oval(cx - r, px(4), cx + r, 2 * r + px(4), fill=col, width=0)
        cx = len(colors) * (2 * r + px(10)) + r + px(4)
        self.create_oval(cx - r, px(4), cx + r, 2 * r + px(4), outline=C["secondary"], width=px(1), dash=(2, 2))
        self.create_text(cx, r + px(4), text="+", fill=C["label"], font=F["body_semi"])
        self.bind("<Button-1>", self._click)

    def _click(self, e):
        r = px(self.R)
        i = int(e.x // (2 * r + px(10)))
        if 0 <= i < len(self._colors):
            self._on_pick(self._colors[i])
        elif i == len(self._colors):
            self._on_custom()


class AppearancePageMixin:
    def _build_appearance_page(self):
        _, page, _hdr = self._page("Appearance", "Settings", "settings", scroll=True)
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="x", padx=px(20))
        look = self._look
        themed = look.look in ap.palettes.LOOKS

        # ---- look
        g = ios.Group(wrap, header="Look",
                      footer="Plain is the default: quiet neutrals and your accent colour. Classic is ReRun's own black and "
                             "white. The others bring their own colours and a looping background.")
        g.pack(fill="x", pady=(px(8), 0))
        tiles = tk.Frame(g.card.body, bg=C["card"])
        tiles.pack(fill="x", padx=px(8), pady=px(8))
        mode_for_preview = look.mode
        for i, (key, name) in enumerate(ap.LOOKS.items()):
            t = LookTile(tiles, key, name, mode_for_preview, key == look.look, lambda k=key: self._ap_set(look=k))
            t.grid(row=i // 4, column=i % 4, padx=px(6), pady=px(6))
            t.configure(bg=C["card"])
        # ---- mode
        g = ios.Group(wrap, header="Mode", footer="Follows Windows when set to System." if not themed else
                      f"{ap.LOOKS[look.look]} has its own light or dark; Mode applies to Plain and Classic.")
        g.pack(fill="x", pady=(px(20), 0))
        self._ap_mode = tk.StringVar(value=ap.MODES[look.mode])
        seg = ios.Segmented(g.row("Mode"), list(ap.MODES.values()), self._ap_mode, command=self._ap_mode_changed)
        seg.pack()
        # ---- accent
        shown = look.accent or ap.resolve(look).palette["blue"]
        g = ios.Group(wrap, header="Accent colour",
                      footer="Used for the main button, selection, toggles, focus and links. Text on it switches between white "
                             "and dark so it always reads.")
        g.pack(fill="x", pady=(px(20), 0))
        row = g.row("Colour", f"{shown.upper()}" + ("" if look.accent else "  (this look's own)"))
        Swatches(row, list(ap.ACCENTS.values()), look.accent or "", lambda c: self._ap_set(accent=c), self._ap_pick_custom).pack()
        if look.accent:
            ios.Button(g.row("Use the look's own accent"), "Reset", lambda: self._ap_set(accent=""), kind="tinted", small=True).pack()
        # ---- contrast and density
        g = ios.Group(wrap, header="Readability",
                      footer="High contrast makes text and dividers stronger (Plain only). Compact tightens spacing by about 12%.")
        g.pack(fill="x", pady=(px(20), 0))
        self._ap_contrast = tk.StringVar(value=ap.CONTRASTS[look.contrast])
        ios.Segmented(g.row("Contrast"), list(ap.CONTRASTS.values()), self._ap_contrast, command=self._ap_contrast_changed).pack()
        self._ap_density = tk.StringVar(value=ap.DENSITIES[look.density])
        ios.Segmented(g.row("Density"), list(ap.DENSITIES.values()), self._ap_density, command=self._ap_density_changed).pack()
        # ---- background
        self._ap_background_group(wrap, look)

    # ------------------------------------------------------------ background
    def _ap_background_group(self, wrap, look: ap.Appearance):
        s = self._bg_settings()
        g = ios.Group(wrap, header="Background",
                      footer="Each themed look has its own animation. For Ahri, drop a video into the 'background' folder next to "
                             "ReRun LITE (the first one plays). A small video is enlarged and cleaned up once, then kept. Behind "
                             "buttons and text the video is softened so they stay sharp.")
        g.pack(fill="x", pady=(px(20), px(24)))
        sel = ios.Select(g.row("Video", "Plays behind the window; Off keeps it plain."), values=list(ap.BACKGROUNDS.values()),
                         accent=True, command=lambda: self._ap_background_changed(sel.get()))
        sel.set(ap.BACKGROUNDS[look.background])
        sel.pack()
        if look.background == "custom":
            row = g.row("Your video", look.custom_video.rsplit("\\", 1)[-1] or "none chosen")
            ios.Button(row, "Choose…", self._ap_choose_video, kind="tinted", small=True).pack()
        dim = ios.Select(g.row("Dimming", "Darker is easier to read."), values=list(background.DIMS), accent=True,
                         command=lambda: self._bg_changed(bg_dim=dim.get()))
        dim.set(str(s.get("bg_dim", "Medium")))
        dim.pack()
        scrim = ios.Select(g.row("Behind buttons and text", "Softens the video where controls sit."),
                           values=list(background.SCRIMS), accent=True, command=lambda: self._bg_changed(bg_scrim=scrim.get()))
        scrim.set(str(s.get("bg_scrim", "Soft")))
        scrim.pack()
        names = {v: k for k, v in background.SPEEDS.items()}
        spd = ios.Select(g.row("Smoothness", "Lower uses less of your PC."), values=list(background.SPEEDS), accent=True,
                         command=lambda: self._bg_changed(bg_fps=background.SPEEDS[spd.get()]))
        spd.set(names.get(int(s.get("bg_fps", 20)), "Normal (20 fps)"))
        spd.pack()
        up = tk.BooleanVar(value=bool(s.get("bg_upscale", True)))
        ios.Switch(g.row("Enlarge small videos", "Cleans up and enlarges a small video once (a GIF, say) so it stays sharp."),
                   up, command=lambda: self._bg_changed(bg_upscale=bool(up.get()))).pack()
        pause = tk.BooleanVar(value=bool(s.get("bg_pause_running")))
        ios.Switch(g.row("Pause while Crest is running", "Frees the PC for Crest during long runs."), pause,
                   command=lambda: self._bg_changed(bg_pause_running=bool(pause.get()))).pack()
        row = g.row("Status", "")
        self._bg_label = tk.Label(row, text="", bg=C["card"], fg=C["secondary"], font=F["footnote"])
        self._bg_label.pack()
        self._bg_refresh_label()

    # ------------------------------------------------------------ changes (each applies at once)
    def _ap_set(self, **changes):
        new = replace(self._look, **changes)
        if new.clean() != self._look:
            self.after(10, lambda: self.apply_appearance(new))     # after this click has finished, not inside it

    def _ap_mode_changed(self):
        key = next((k for k, v in ap.MODES.items() if v == self._ap_mode.get()), "system")
        self._ap_set(mode=key)

    def _ap_contrast_changed(self):
        self._ap_set(contrast=next((k for k, v in ap.CONTRASTS.items() if v == self._ap_contrast.get()), "standard"))

    def _ap_density_changed(self):
        self._ap_set(density=next((k for k, v in ap.DENSITIES.items() if v == self._ap_density.get()), "comfortable"))

    def _ap_background_changed(self, label: str):
        key = next((k for k, v in ap.BACKGROUNDS.items() if v == label), "auto")
        if key == "custom" and not self._look.custom_video:
            self._ap_choose_video(then_custom=True)
            return
        self._ap_set(background=key)

    def _ap_choose_video(self, then_custom: bool = False):
        path = filedialog.askopenfilename(title="Choose a background video",
                                          filetypes=[("Video", "*.mp4 *.webm *.mkv *.avi *.mov *.gif"), ("All files", "*.*")])
        if path:
            self._ap_set(custom_video=path, background="custom")

    def _ap_pick_custom(self):
        start = self._look.accent or ap.resolve(self._look).palette["blue"]
        picked = colorchooser.askcolor(color=start, title="Accent colour", parent=self)[1]
        if picked and valid_hex(picked):
            self._ap_set(accent=picked.upper())

    # used by the command palette: the same changes by name
    def set_look(self, key: str):
        self._ap_set(look=key)

    def set_mode(self, key: str):
        self._ap_set(mode=key)

    def set_accent(self, hex_color: str):
        self._ap_set(accent=hex_color)


__all__ = ["AppearancePageMixin", "LookTile", "Swatches"]
