"""The Anime Artwork System, part two: the places artwork appears in the window, and Settings > Artwork.

What is drawn where (all of it behind or beside the controls, never over them):

  A  Background   the still picture behind the whole window, through the same colour-keyed backdrop window the looks'
                  videos use (background.py). Opacity, blur and position are settings. It replaces the look's video only
                  while an artwork background is chosen. It never touches the Live View, which is the emulator's own video.
  B  Header       a banner strip under the Auto Crest title row; its height is a setting.
  C  Instance     a small portrait at the left of each emulator row (off by default).
  D  Panels       a thin decorative strip under the Totals tiles. It sits beside the numbers, never under them.
  E  Previews     every anime card in the Artwork page is a small picture of the real window drawn with that anime's art.

Rules this file keeps: artwork is loaded and drawn on a worker thread (the window only turns the finished picture into a
Tk image); the same artwork is never decoded twice (artwork.ImageCache); a missing or damaged picture means "show
nothing" and never an error; a change is applied in place, without rebuilding the window and without touching the
emulators or Crest, so it cannot interrupt a running session.
"""
from __future__ import annotations

import gc
import os
import queue
import sys
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog
from typing import NamedTuple

from PIL import ImageTk

from rerun import errlog, ios
from rerun.ios import C, F, px

from . import artwork as art
from .artwork import Prefs, Settings

ASK_RIGHTS = ("Only add pictures you own or are allowed to use. They are kept on this PC (in data/lite/artwork) and are "
              "never uploaded, shared or put in a release. ReRun LITE ships no anime artwork of its own.")
POSITION_NAMES = {"center": "Center", "top": "Top", "bottom": "Bottom", "left": "Left", "right": "Right"}


class ArtBackground(NamedTuple):
    path: Path
    opacity: float
    blur: float
    anchor: tuple


class _State:
    """Everything the artwork system keeps for the life of the window (it survives a change of look)."""

    def __init__(self, app):
        self.lib = art.Library(app.m.root)
        self.resolver = art.Resolver(self.lib)
        self.cache = art.ImageCache(app.m.root)
        self.prefs = art.prefs_from_ui(app._ui_state())
        self.loader = ArtLoader(app)
        self.rev = 0                       # goes up on every change; lets cheap checks skip work
        self.portrait_rev = -1
        self.portrait = None
        self.search = ""
        self.favourites_only = False
        self.shown_notice = False


class ArtLoader:
    """One worker thread that makes pictures ready, with the results handed back to the Tk thread by a polled queue
    (Tk is not safe to call from another thread).

    Tk images and variables free themselves from `__del__`, and Python may run that on whichever thread happens to trigger a
    garbage collection. On the worker that would call Tk from the wrong thread (a crash on some Tk builds). So while any job
    is queued or running, automatic collection is paused, and the Tk thread turns it back on when the last result is in."""

    def __init__(self, app):
        self.app = app
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._done: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._pending = 0
        self._polling = False
        self._paused = False

    def submit(self, fn, callback) -> None:
        """Run fn() on the worker; then callback(result) on the Tk thread (result is None if fn failed)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, daemon=True, name="art-loader")
            self._thread.start()
        if not self._paused and gc.isenabled():
            gc.disable()
            self._paused = True
        self._pending += 1
        self._jobs.put((fn, callback))
        if not self._polling:
            self._polling = True
            self.app.after(30, self._poll)

    def _work(self) -> None:
        while True:
            fn, cb = self._jobs.get()
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001 - a bad picture must never take the worker down
                errlog.note("lite.art_job", e)
                result = None
            self._done.put((cb, result))

    def _poll(self) -> None:
        try:
            while True:
                cb, result = self._done.get_nowait()
                self._pending -= 1
                try:
                    cb(result)
                except tk.TclError:
                    pass                                         # the widget went away while the picture was being made
                except Exception as e:  # noqa: BLE001
                    errlog.note("lite.art_cb", e)
        except queue.Empty:
            pass
        try:
            if self._pending > 0:
                self.app.after(40, self._poll)
            else:
                self._polling = False
                self._resume_gc()
        except tk.TclError:
            self._polling = False
            self._resume_gc()

    def _resume_gc(self) -> None:
        if self._paused:
            self._paused = False
            gc.enable()


def _stamp(p: Path) -> tuple:
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return ()


# ================================================================================================ B and D: strips
class ArtStrip(tk.Frame):
    """A wide, short picture: the header banner (role "header") or the decoration under the Totals tiles (role "panel").
    It is only on screen while there is a picture to show; otherwise it takes no space at all."""

    def __init__(self, parent, app, role: str, anchor: tk.Widget, pad: dict):
        super().__init__(parent, bg=ios.bg_of(parent))
        self.app, self.role, self.anchor, self.pad = app, role, anchor, pad
        self.pack_propagate(False)
        self.cv = tk.Canvas(self, bg=C["card"], highlightthickness=0, bd=0)       # not the page colour: that one is see-through
        self.cv.pack(fill="both", expand=True)
        self._on_screen = False
        self._want = None
        self._photo = None
        self._debounce = None
        self.cv.bind("<Configure>", self._resized)
        self.refresh()

    def _resized(self, e) -> None:
        if self._debounce is not None:
            self.after_cancel(self._debounce)
        self._debounce = self.after(140, self._render)

    def refresh(self) -> None:
        """Show, hide or redraw for the artwork choices in force now."""
        c = self.app._art_state()
        s = self.app._art_settings()
        pic = c.resolver.header(s) if self.role == "header" else c.resolver.panel(s)
        if pic is None or not pic.path.is_file():
            if self._on_screen:
                self.pack_forget()
                self._on_screen = False
            self._want = None
            return
        self.configure(height=px(s.header_height) if self.role == "header" else px(36))
        if not self._on_screen:
            self.pack(after=self.anchor, fill="x", **self.pad)
            self._on_screen = True
        self._render()

    def _render(self) -> None:
        self._debounce = None
        if not self._on_screen:
            return
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        if w < 60 or h < 10:
            return                                               # not laid out yet; <Configure> will call again
        c, s = self.app._art_state(), self.app._art_settings()
        pic = c.resolver.header(s) if self.role == "header" else c.resolver.panel(s)
        if pic is None:
            return
        col = s.collection
        who = col.character(s.character_id) if col else None
        header = self.role == "header"
        caption = (f"{col.name}  ·  {who.name}" if who and s.show_character and c.resolver.character(s) else col.name) if col else ""
        spec = art.StripSpec(w, h, str(pic.path), _stamp(pic.path), s.anchor, C["card"], col.accent if col else C["blue"],
                             0.92 if header else 0.38, 0.0, caption if header else "", C["label"])
        if spec == self._want:
            return
        self._want = spec
        hit = c.cache.get(("strip", spec))
        if hit is not None:
            self._show(spec, hit)
            return
        c.loader.submit(lambda: c.cache.make(("strip", spec), lambda: art.render_strip(spec, c.cache)),
                        lambda im: self._show(spec, im))

    def _show(self, spec, im) -> None:
        if im is None or spec != self._want:
            return                                               # unreadable picture, or a newer one has been asked for
        self._photo = ImageTk.PhotoImage(im)
        self.cv.delete("all")
        self.cv.create_image(0, 0, anchor="nw", image=self._photo)


# ================================================================================================ E: gallery cards
class AnimeTile(tk.Frame):
    """One anime in the gallery: a small picture of the real window with its artwork, its title and the chosen character."""
    W, H = 204, 116

    def __init__(self, parent, col: art.Collection, selected: bool, favourite: bool, line: str, command):
        super().__init__(parent, bg=C["card"], cursor="hand2")
        w, h = px(self.W), px(self.H)
        self.cv = tk.Canvas(self, width=w, height=h, bg=C["card"], highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack()
        self._photo = None
        self._edge = C["blue"] if selected else C["sep"]
        self._edge_w = px(2 if selected else 1)
        self._frame()
        name = tk.Label(self, text=("★ " if favourite else "") + col.name, bg=C["card"], fg=C["label"], font=F["footnote_semi"],
                        anchor="w", wraplength=w)
        name.pack(fill="x", pady=(px(5), 0))
        sub = tk.Label(self, text=line, bg=C["card"], fg=C["secondary"], font=F["caption"], anchor="w", wraplength=w, justify="left")
        sub.pack(fill="x")
        for x in (self, self.cv, name, sub):
            x.bind("<Button-1>", lambda e: command())

    def _frame(self) -> None:
        self.cv.delete("edge")
        w, h = px(self.W), px(self.H)
        self.cv.create_rectangle(1, 1, w - 1, h - 1, outline=self._edge, width=self._edge_w, tags="edge")

    def set_image(self, im) -> None:
        if im is None:
            return
        self._photo = ImageTk.PhotoImage(im)
        self.cv.delete("pic")
        self.cv.create_image(0, 0, anchor="nw", image=self._photo, tags="pic")
        self.cv.tag_lower("pic")


# ================================================================================================ the window mixin
class ArtworkMixin:
    # ------------------------------------------------------------ state
    def _art_state(self) -> _State:
        st = getattr(self, "_art", None)
        if st is None:
            st = self._art = _State(self)
        return st

    def _art_settings(self, cid: str | None = None) -> Settings:
        c = self._art_state()
        return art.effective(c.prefs, c.lib.collections, cid)

    def _art_save(self) -> None:
        c = self._art_state()
        c.rev += 1
        self._bg_save(artwork=c.prefs.to_dict())

    # ------------------------------------------------------------ A: background
    def _art_background_spec(self) -> ArtBackground | None:
        c = self._art_state()
        s = self._art_settings()
        pic = c.resolver.background(s)
        if pic is None or not pic.path.is_file():
            return None
        return ArtBackground(pic.path, s.opacity, s.blur, s.anchor)

    def _build_backdrop(self):
        super()._build_backdrop()
        self.backdrop.art_source = self._art_background_spec      # before its first start (200 ms later)

    def _art_apply_backdrop(self) -> None:
        """Make the window's background match the choices: the same picture is only retuned (no restart); a different
        one, or going between a picture and the look's video, restarts the backdrop (a thread; the window is untouched)."""
        bd = getattr(self, "backdrop", None)
        if bd is None:
            return
        spec = self._art_background_spec()
        if spec is None and bd.art is None:
            return
        pl = bd.player
        if spec is not None and bd.art is not None and bd.art.path == spec.path and pl is not None and bd.active:
            pl.dim, pl.blur, pl.anchor = spec.opacity, spec.blur, spec.anchor
            bd.art = spec
            return
        bd.restart()
        self._bg_refresh_label()

    # ------------------------------------------------------------ B and D: the strips; C: the instance portraits
    def _build_crest(self):
        super()._build_crest()
        try:
            page, hdr = self._last_page, self.key_timer.master
            self._art_header = ArtStrip(page, self, "header", hdr.master, {"padx": px(20), "pady": (0, px(8))})
            tiles = self.tiles["runs"].master
            self._art_panel = ArtStrip(tiles.master, self, "panel", tiles, {"pady": (px(8), 0)})
        except Exception as e:  # noqa: BLE001 - decoration must never stop the window from building
            errlog.note("lite.art_build", e)

    def refresh_instances(self):
        super().refresh_instances()
        try:
            self._art_portraits()
        except Exception as e:  # noqa: BLE001
            errlog.note("lite.art_portraits", e)

    def _art_portraits(self) -> None:
        c = self._art_state()
        rows = getattr(self.inst_list, "_rows", {})
        if all(r.get("art_rev") == c.rev for r in rows.values()):
            return                                               # nothing changed since the last look: no work at all
        if c.portrait_rev != c.rev:
            c.portrait, c.portrait_rev = c.resolver.portrait(self._art_settings()), c.rev
        pic, s = c.portrait, self._art_settings()
        size = px(36)
        for name, r in rows.items():
            r["art_rev"] = c.rev
            lab = r.get("art")
            if pic is None or not pic.path.is_file():
                if lab is not None:
                    if lab in r["paint"]:                        # other code walks this list (right-click menus): keep it true
                        r["paint"].remove(lab)
                    lab.destroy()
                    r["art"] = None
                continue
            accent = s.collection.accent if s.collection else C["blue"]
            key = ("portrait", str(pic.path), _stamp(pic.path), size, accent)

            def show(im, name=name, r=r, rev=c.rev):
                if im is None or self.inst_list._rows.get(name) is not r or r.get("art_rev") != rev:
                    return
                photo = ImageTk.PhotoImage(im)
                lab = r.get("art")
                if lab is None:
                    lab = tk.Label(r["paint"][0], bd=0, highlightthickness=0, bg=C["card"], cursor="hand2")
                    lab.pack(side="left", before=r["dot"], padx=(px(10), 0))
                    lab.bind("<Button-1>", lambda e, n=name: self.inst_list.select(n, user=True))
                    r["art"] = lab
                    r["paint"].append(lab)
                lab.configure(image=photo)
                lab.image = photo
            hit = c.cache.get(key)
            if hit is not None:
                show(hit)
            else:
                c.loader.submit(lambda key=key, pic=pic, accent=accent: c.cache.make(
                    key, lambda: art.render_portrait(pic.path, size, accent, c.cache)), show)

    # ------------------------------------------------------------ applying a change everywhere
    def _art_changed(self, library: bool = True) -> None:
        """Save, then update every place artwork shows. Nothing here touches the emulators or Crest."""
        self._art_save()
        self._art_apply_backdrop()
        for strip in (getattr(self, "_art_header", None), getattr(self, "_art_panel", None)):
            if strip is not None:
                try:
                    strip.refresh()
                except tk.TclError:
                    pass
        try:
            self._art_portraits()
        except tk.TclError:
            pass
        if library and getattr(self, "_art_grid", None) is not None:
            self._art_fill_grid()
            self._art_fill_detail()
            self._art_fill_status()

    # ================================================================ Settings > Artwork
    def _build_artwork_page(self):
        c = self._art_state()
        _, page, _hdr = self._page("Artwork", "Settings", "settings", scroll=True)
        wrap = tk.Frame(page, bg=C["bg"])
        wrap.pack(fill="x", padx=px(20))
        # ---- on / off and reset
        g = ios.Group(wrap, header="Anime artwork",
                      footer="Artwork goes behind and beside the controls and never over them. It works with any look: pick "
                             "Gojo on Jujutsu colours, or on Plain, or on any other. Changing it never changes the layout, the "
                             "controls or Crest, and it applies at once, even while Crest is running.")
        g.pack(fill="x", pady=(px(8), 0))
        self._art_on = tk.BooleanVar(value=c.prefs.enabled)
        ios.Switch(g.row("Artwork", "Turns every place artwork appears on or off."), self._art_on,
                   command=lambda: self._art_set_enabled(bool(self._art_on.get()))).pack()
        row = g.row("Status", "")
        self._art_status = tk.Label(row, text="", bg=C["card"], fg=C["secondary"], font=F["footnote"])
        self._art_status.pack()
        row = g.row("Files", "Your own pictures are kept in data/lite/artwork.")
        ios.Button(row, "Open folder", self._art_open_folder, kind="tinted", small=True).pack(side="left")
        ios.Button(row, "Import a folder…", self._art_import_folder, kind="tinted", small=True).pack(side="left", padx=(px(8), 0))
        ios.Button(row, "Reset all artwork", self._art_reset_all, kind="plain", color="red", small=True).pack(side="left", padx=(px(8), 0))
        # ---- the gallery
        g = ios.Group(wrap, header="Collections",
                      footer="Click an anime to use it. Its card is a small picture of the real window with that anime's "
                             "artwork in each place it can appear.")
        g.pack(fill="x", pady=(px(20), 0))
        bar = tk.Frame(g.card.body, bg=C["card"])
        bar.pack(fill="x", padx=px(12), pady=(px(10), 0))
        self._art_q = tk.StringVar(value=c.search)
        ios.Field(bar, self._art_q, width=30).pack(side="left")
        tk.Label(bar, text="Search anime and characters", bg=C["card"], fg=C["secondary"], font=F["footnote"]).pack(side="left", padx=(px(8), 0))
        self._art_fav_var = tk.StringVar(value="Favourites" if c.favourites_only else "All")
        ios.Segmented(bar, ["All", "Favourites"], self._art_fav_var, command=self._art_filter_changed).pack(side="right")
        self._art_q.trace_add("write", self._art_search_typed)
        self._art_grid = tk.Frame(g.card.body, bg=C["card"])
        self._art_grid.pack(fill="x", padx=px(8), pady=px(8))
        self._art_detail_host = tk.Frame(wrap, bg=C["bg"])
        self._art_detail_host.pack(fill="x")
        self._art_fill_status()
        self._art_fill_grid()
        self._art_fill_detail()
        tk.Frame(wrap, height=px(24), bg=C["bg"]).pack()

    def _art_fill_status(self) -> None:
        lab = getattr(self, "_art_status", None)
        if lab is None:
            return
        c = self._art_state()
        s = self._art_settings()
        if not c.prefs.enabled:
            text = "Off"
        elif s.collection is None:
            text = "No anime chosen"
        else:
            who = s.collection.character(s.character_id)
            text = s.collection.name + (f" · {who.name}" if who else "") + ("" if c.lib.has_any(s.collection.id) else " · no pictures yet")
        try:
            lab.configure(text=text)
        except tk.TclError:
            self._art_status = None

    # ------------------------------------------------------------ the gallery
    def _art_search_typed(self, *_a) -> None:
        c = self._art_state()
        c.search = self._art_q.get()
        if getattr(self, "_art_search_job", None) is not None:
            self.after_cancel(self._art_search_job)
        self._art_search_job = self.after(250, self._art_fill_grid)

    def _art_filter_changed(self) -> None:
        self._art_state().favourites_only = self._art_fav_var.get() == "Favourites"
        self._art_fill_grid()

    def _art_fill_grid(self) -> None:
        self._art_search_job = None
        grid = getattr(self, "_art_grid", None)
        if grid is None:
            return
        c = self._art_state()
        try:
            for w in grid.winfo_children():
                w.destroy()
        except tk.TclError:
            return
        results = art.search(c.lib, c.prefs, c.search, c.favourites_only)
        if not results:
            tk.Label(grid, text="Nothing matches." if (c.search or c.favourites_only) else "No anime collections were found.",
                     bg=C["card"], fg=C["secondary"], font=F["body"]).pack(pady=px(18))
            return
        pal = (C["bg"], C["card"], C["bar"], C["label"], C["secondary"], C["sep"], C["blue"])
        for i, (col, hits) in enumerate(results):
            s = replace(self._art_settings(col.id), enabled=True, collection=col)
            who = col.character(s.character_id)
            have = c.lib.has_any(col.id)
            line = ("Matches: " + ", ".join(hits[:3]) if hits else (f"Character: {who.name}" if who else "")) + \
                   ("" if have else ("\n" if hits or who else "") + "No artwork installed")
            fav = any(f.startswith(col.id + "|") for f in c.prefs.favourites)
            tile = AnimeTile(grid, col, col.id == c.prefs.collection, fav, line, lambda cid=col.id: self._art_choose_collection(cid))
            tile.grid(row=i // 3, column=i % 3, padx=px(8), pady=px(8), sticky="n")
            self._art_tile_image(tile, col, s, pal)

    def _art_tile_image(self, tile: AnimeTile, col: art.Collection, s: Settings, pal: tuple) -> None:
        c = self._art_state()
        r = c.resolver
        bg, hd, pt, pn = r.background(s), r.header(s), r.portrait(s) or r.character(s), r.panel(s)
        paths = tuple(str(x.path) if x else "" for x in (bg, hd, pt, pn))
        spec = art.PreviewSpec(px(AnimeTile.W), px(AnimeTile.H), pal, col.accent, col.monogram, paths[0], paths[1],
                               paths[2] if s.show_instance else "", paths[3], s.opacity, s.blur, s.anchor,
                               tuple(_stamp(Path(p)) if p else () for p in paths))
        hit = c.cache.get(("preview", spec))
        if hit is not None:
            tile.set_image(hit)
            return
        c.loader.submit(lambda: c.cache.make(("preview", spec), lambda: art.render_preview(spec, c.cache)), tile.set_image)

    def _art_choose_collection(self, cid: str) -> None:
        c = self._art_state()
        if c.prefs.collection == cid:
            return
        c.prefs.collection = cid
        self._art_changed()

    # ------------------------------------------------------------ the chosen anime
    def _art_fill_detail(self) -> None:
        host = getattr(self, "_art_detail_host", None)
        if host is None:
            return
        try:
            for w in host.winfo_children():
                w.destroy()
        except tk.TclError:
            return
        c = self._art_state()
        col = c.lib.collections.get(c.prefs.collection)
        if col is None:
            ios.Banner(host, "Choose an anime above to pick a character, a background and how artwork looks.", "orange").pack(
                fill="x", pady=(px(20), 0))
            return
        s = self._art_settings(col.id)
        cid = col.id
        # ---- characters
        g = ios.Group(host, header=f"{col.name}: characters", footer=ASK_RIGHTS)
        g.pack(fill="x", pady=(px(20), 0))
        for ch in col.characters:
            imgs = c.lib.images(cid, "characters", ch.id)
            chosen = ch.id == s.character_id
            sub = ("Selected. " if chosen else "") + (f"{len(imgs)} picture{'s' if len(imgs) != 1 else ''}." if imgs else
                                                       "No artwork installed. Add your own picture.")
            right = g.row(ch.name, sub)
            fk = art.fav_key(cid, "characters", ch.id)
            if len(imgs) > 1:
                names = [i.label for i in imgs]
                cur = next((i.label for i in imgs if i.key == s.variant), names[0]) if chosen else names[0]
                sel = ios.Select(right, values=names, accent=True)
                sel.set(cur)
                sel._cmd = lambda sel=sel, imgs=imgs, ch=ch: self._art_pick_variant(
                    ch.id, next((i for i in imgs if i.label == sel.get()), None))
                sel.pack(side="left", padx=(0, px(8)))
            ios.Button(right, "Selected" if chosen else "Use", lambda ch=ch: self._art_pick_character(ch.id),
                       kind="filled" if chosen else "tinted", small=True).pack(side="left")
            ios.Button(right, "★" if fk in c.prefs.favourites else "☆", lambda fk=fk: self._art_toggle_fav(fk), kind="plain",
                       small=True).pack(side="left", padx=(px(6), 0))
            ios.Button(right, "Add picture…", lambda ch=ch: self._art_add(cid, "characters", ch.id), kind="plain",
                       small=True).pack(side="left", padx=(px(6), 0))
            own = next((i for i in imgs if i.is_user and (i.key == s.variant or len(imgs) == 1)), None)
            if own is not None:
                ios.Button(right, "Remove", lambda a=own: self._art_remove(a), kind="plain", color="red", small=True).pack(
                    side="left", padx=(px(6), 0))
        # ---- background and banner
        g = ios.Group(host, header=f"{col.name}: background and banner")
        g.pack(fill="x", pady=(px(20), 0))
        for kind, title, sub, current in (("backgrounds", "Background", "The picture behind the whole window.", s.background),
                                          ("banners", "Header banner", "The strip under the Auto Crest title. With none, the "
                                           "character's picture is used.", s.banner)):
            imgs = c.lib.images(cid, kind)
            right = g.row(title, sub if imgs else sub + " None installed yet.")
            values = ["Default", "None"] + [i.label for i in imgs]
            cur = "None" if current == "none" else next((i.label for i in imgs if i.key == current), "Default")
            sel = ios.Select(right, values=values, accent=True)
            sel.set(cur)
            sel._cmd = (lambda sel=sel, imgs=imgs, kind=kind: self._art_pick_image(cid, kind, sel.get(), imgs))
            sel.pack(side="left", padx=(0, px(8)))
            ios.Button(right, "Add picture…", lambda kind=kind: self._art_add(cid, kind), kind="plain", small=True).pack(side="left")
            hit = next((i for i in imgs if i.key == current), None)
            if hit is not None:
                fk = art.fav_key(cid, kind, hit.key)
                ios.Button(right, "★" if fk in c.prefs.favourites else "☆", lambda fk=fk: self._art_toggle_fav(fk), kind="plain",
                           small=True).pack(side="left", padx=(px(6), 0))
                if hit.is_user:
                    ios.Button(right, "Remove", lambda a=hit: self._art_remove(a), kind="plain", color="red", small=True).pack(
                        side="left", padx=(px(6), 0))
        # ---- how it looks
        g = ios.Group(host, header=f"{col.name}: how it looks",
                      footer="Opacity is kept between 5% and 60% so text always stays readable. Blur is a light CPU blur, "
                             "made once when you change it, so it costs nothing while Crest runs.")
        g.pack(fill="x", pady=(px(20), 0))
        self._art_vars: dict[str, tk.Variable] = {}
        for key, title, sub in (("showBackground", "Background image", "The picture behind the window."),
                                ("showCharacterArtwork", "Character artwork", "Character pictures in the banner and the instance portrait."),
                                ("showHeaderArtwork", "Header artwork", "The banner under the Auto Crest title."),
                                ("showInstanceArtwork", "Instance portrait", "A small character portrait on each emulator row."),
                                ("showPanelArtwork", "Panel decoration", "A thin strip beside the Totals numbers.")):
            var = tk.BooleanVar(value=getattr(s, {"showBackground": "show_background", "showCharacterArtwork": "show_character",
                                                  "showHeaderArtwork": "show_header", "showInstanceArtwork": "show_instance",
                                                  "showPanelArtwork": "show_panel"}[key]))
            ios.Switch(g.row(title, sub), var, command=lambda key=key, var=var: self._art_set(key, bool(var.get()))).pack()
        self._art_number(g, "Background opacity (%)", "How strongly the background shows.", "opacity", round(s.opacity * 100), 5, 60,
                         lambda v: v / 100)
        self._art_number(g, "Background blur", "0 is sharp.", "blur", round(s.blur), 0, 12, float)
        self._art_number(g, "Header banner height", "In pixels at 100% size.", "headerHeight", s.header_height, 40, 140, int)
        pos = ios.Select(g.row("Image position", "Which part of a picture stays in view when it is cropped."),
                         values=list(POSITION_NAMES.values()), accent=True)
        pos.set(POSITION_NAMES[s.position])
        pos._cmd = lambda: self._art_set("position", next((k for k, v in POSITION_NAMES.items() if v == pos.get()), "center"))
        pos.pack()
        row = g.row("Defaults", "Put this anime back to how it first looked (your pictures stay).")
        ios.Button(row, "Reset " + col.name, lambda: self._art_reset(cid), kind="tinted", small=True).pack()

    def _art_number(self, g, title: str, sub: str, key: str, value: int, lo: int, hi: int, convert) -> None:
        var = tk.StringVar(value=str(value))
        ios.Stepper(g.row(title, sub), var, lo, hi).pack()
        job = {"id": None}

        def changed(*_a):
            if job["id"] is not None:
                self.after_cancel(job["id"])

            def apply():
                job["id"] = None
                try:
                    v = max(lo, min(hi, int(str(var.get()).strip())))
                except ValueError:
                    return
                self._art_set(key, convert(v), rebuild=False)
            job["id"] = self.after(350, apply)
        var.trace_add("write", changed)

    # ------------------------------------------------------------ the changes (each applies at once, none rebuilds the window)
    def _art_set_enabled(self, on: bool) -> None:
        self._art_state().prefs.enabled = on
        self._art_changed()

    def _art_set(self, key: str, value, rebuild: bool = True) -> None:
        c = self._art_state()
        cid = c.prefs.collection
        if not cid:
            return
        c.prefs.set(cid, **{key: value})
        self._art_changed(library=rebuild)
        if not rebuild:
            self._art_fill_grid()                                # the cards show the new look; the form stays as it is
            self._art_fill_status()

    def _art_pick_character(self, char_id: str) -> None:
        c = self._art_state()
        c.prefs.set(c.prefs.collection, character=char_id, variant=None)
        self._art_changed()

    def _art_pick_variant(self, char_id: str, image) -> None:
        if image is None:
            return
        c = self._art_state()
        c.prefs.set(c.prefs.collection, character=char_id, variant=image.key)
        self._art_changed()

    def _art_pick_image(self, cid: str, kind: str, label: str, imgs) -> None:
        c = self._art_state()
        field = "background" if kind == "backgrounds" else "banner"
        choice = "default" if label == "Default" else "none" if label == "None" else next((i.key for i in imgs if i.label == label), "default")
        c.prefs.set(cid, **{field: None if choice == "default" else choice})
        self._art_changed()

    def _art_toggle_fav(self, key: str) -> None:
        self._art_state().prefs.toggle_favourite(key)
        self._art_changed()

    def _art_reset(self, cid: str) -> None:
        self._art_state().prefs.reset_collection(cid)
        self._art_changed()
        self.flash("Artwork put back to its defaults", "ok")

    def _art_reset_all(self) -> None:
        if not ios.confirm(self, "Put all artwork settings back to their defaults? Your own pictures and favourites are kept.",
                           "Reset artwork", ok="Reset", destructive=True):
            return
        self._art_state().prefs.reset_all()
        self._art_on.set(True)
        self._art_changed()
        self.flash("Artwork reset", "ok")

    # ------------------------------------------------------------ the user's own pictures
    def _art_add(self, cid: str, kind: str, character: str = "") -> None:
        c = self._art_state()
        if not self._ui_state().get("artwork_rights_seen"):
            if not ios.confirm(self, ASK_RIGHTS, "Add your own artwork", ok="I understand"):
                return
            self._bg_save(artwork_rights_seen=True)
        path = filedialog.askopenfilename(title="Choose a picture", filetypes=[
            ("Pictures", " ".join("*" + t for t in art.IMPORT_TYPES)), ("All files", "*.*")])
        if not path:
            return

        def job():
            try:
                return ("ok", c.lib.add_user_image(cid, kind, path, character))
            except art.ArtError as e:
                return ("err", str(e))

        def done(res):
            if res is None:
                self.flash("The picture could not be added.", "error")
            elif res[0] == "err":
                self.flash(res[1], "error")
            else:
                img = res[1]
                if not c.prefs.collection:
                    c.prefs.collection = cid
                if kind == "characters":
                    c.prefs.set(cid, character=character, variant=img.key)
                else:
                    c.prefs.set(cid, **{"background" if kind == "backgrounds" else "banner": img.key})
                self.flash(f"Added {img.label}", "ok")
                self._art_changed()
        c.loader.submit(job, done)

    def _art_import_folder(self) -> None:
        """Many of the user's own pictures at once: a folder with one sub-folder per anime (see Library.import_folder)."""
        c = self._art_state()
        if not self._ui_state().get("artwork_rights_seen"):
            if not ios.confirm(self, ASK_RIGHTS, "Add your own artwork", ok="I understand"):
                return
            self._bg_save(artwork_rights_seen=True)
        folder = filedialog.askdirectory(title="Choose the folder that holds one sub-folder per anime")
        if not folder:
            return

        def done(res):
            if res is None:
                self.flash("The folder could not be imported.", "error")
                return
            added, notes = res
            if added and not c.prefs.collection:
                c.prefs.collection = added[0].collection
            self.flash(f"Added {len(added)} picture(s)" + (f"; skipped {len(notes)}" if notes else ""), "ok" if added else "warn")
            if notes:
                errlog.note("lite.art_import", RuntimeError("; ".join(notes[:20])))
            self._art_changed()
        c.loader.submit(lambda: c.lib.import_folder(folder), done)

    def _art_remove(self, image) -> None:
        c = self._art_state()
        if not ios.confirm(self, f"Delete '{image.label}' from this PC? The original file you added is not touched.",
                           "Remove picture", ok="Delete", destructive=True):
            return
        if c.lib.remove_user_image(image):
            p = c.prefs.per.get(image.collection, {})
            for k in ("variant", "background", "banner"):
                if p.get(k) == image.key:
                    c.prefs.set(image.collection, **{k: None})
            self._art_changed()
        else:
            self.flash("That picture could not be deleted.", "error")

    def _art_open_folder(self) -> None:
        folder = art.user_dir(self.m.root)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(folder)                                # noqa: S606 - the user's own folder
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(folder)])         # noqa: S603, S607
        except Exception as e:  # noqa: BLE001
            self.flash(f"Could not open the folder: {e}", "error")


__all__ = ["AnimeTile", "ArtBackground", "ArtLoader", "ArtStrip", "ArtworkMixin"]
