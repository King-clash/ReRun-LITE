"""The Anime Artwork System, part one: what artwork exists, what the user chose, and how pictures are made ready.

Nothing here uses Tk, so it can be tested without a window. The window side is `artwork_ui.py`.

Rights come first. ReRun LITE ships NO anime artwork of its own making and makes none: no AI pictures, no invented
characters, no fake posters. Two kinds of picture can ever be shown:

  * Bundled pictures in `assets/anime/<anime>/...`: shown only when `assets/anime/manifest.json` lists the file with its
    source address, its licence, what use is permitted and `"approved": true`. A file with no such entry is ignored.
  * The user's own pictures, added in Settings > Artwork. They are converted to WebP and kept on this PC only, in
    `data/lite/artwork/`; they are never uploaded, bundled or shared.

An anime with no picture of either kind shows a plain placeholder drawn in code (a gradient and the anime's initials),
only inside the Artwork page; the rest of the window shows nothing at all.

The choices live in `data/lite/ui.json` under "artwork" (`Prefs`), apart from the colour theme: any anime's artwork can
sit on any look, and choosing a character never changes layout, controls or automation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from .colors import mix, valid_hex

SCHEMA = 1
KINDS = ("backgrounds", "characters", "banners", "previews")
IMAGE_TYPES = (".webp", ".png", ".jpg", ".jpeg")
IMPORT_TYPES = IMAGE_TYPES + (".bmp", ".gif")
POSITIONS = {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "right": (1.0, 0.5)}
OPACITY_RANGE = (0.05, 0.60)          # a background can never be strong enough to fight the text
BLUR_RANGE = (0.0, 12.0)
HEADER_RANGE = (40, 140)
MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_PIXELS = 60_000_000
MAX_SIDE = {"backgrounds": 2560, "characters": 1600, "banners": 2000, "previews": 1200}
USER_MANIFEST = "user_manifest.json"

# what an anime's appearance is until the user changes it (a collection's own config may override any of these)
DEFAULT_APPEARANCE = {"backgroundOpacity": 0.18, "blur": 2, "position": "center", "showBackground": True,
                      "showCharacterArtwork": True, "showHeaderArtwork": True, "showInstanceArtwork": False,
                      "showPanelArtwork": True, "headerHeight": 64}


class ArtError(Exception):
    """A picture could not be added. The message says why, in plain words."""


# ------------------------------------------------------------------------------------------------ where things are
def app_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def asset_roots(root: str | Path) -> list[Path]:
    """Every folder that may hold `assets/anime`, in the order they are tried: next to the data, next to the app, then
    the copy inside the exe."""
    out = [Path(root) / "assets" / "anime", app_dir() / "assets" / "anime"]
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        out += [Path(bundled) / "seed" / "assets" / "anime", Path(bundled) / "assets" / "anime"]
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return [p for p in uniq if p.is_dir()]


def user_dir(root: str | Path) -> Path:
    return Path(root) / "data" / "lite" / "artwork"


def cache_dir(root: str | Path) -> Path:
    return Path(root) / "data" / "lite" / "cache" / "artwork"


def _read_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def slug(text: str, fallback: str = "image") -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48] or fallback


# ------------------------------------------------------------------------------------------------ collections
@dataclass(frozen=True)
class Character:
    id: str
    name: str
    image: str = ""            # a bundled picture, relative to the collection's folder ("" = none installed)


@dataclass(frozen=True)
class Collection:
    id: str
    name: str
    order: int
    accent: str
    characters: tuple[Character, ...]
    background: str            # the default background (relative to the collection's folder, "" = none)
    header: str                # the default banner
    preview: str               # a picture for the gallery card
    defaults: dict
    folder: str                # where its config was read from ("" when built in)

    def character(self, cid: str) -> Character | None:
        return next((c for c in self.characters if c.id == cid), None)

    @property
    def monogram(self) -> str:
        words = [w for w in re.findall(r"[A-Za-z0-9]+", self.name) if w.lower() not in {"the", "of", "x", "to", "no"}]
        if len(words) >= 2:
            return (words[0][0] + words[1][0]).upper()
        return (words[0][:2] if words else "?").upper()


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _appearance(raw) -> dict:
    """A collection's appearance block, with anything missing or wrong replaced by the default."""
    raw = raw if isinstance(raw, dict) else {}
    d = dict(DEFAULT_APPEARANCE)
    for k in ("showBackground", "showCharacterArtwork", "showHeaderArtwork", "showInstanceArtwork", "showPanelArtwork"):
        if isinstance(raw.get(k), bool):
            d[k] = raw[k]
    d["backgroundOpacity"] = _num(raw.get("backgroundOpacity"), *OPACITY_RANGE, DEFAULT_APPEARANCE["backgroundOpacity"])
    d["blur"] = _num(raw.get("blur"), *BLUR_RANGE, DEFAULT_APPEARANCE["blur"])
    d["headerHeight"] = int(_num(raw.get("headerHeight"), *HEADER_RANGE, DEFAULT_APPEARANCE["headerHeight"]))
    d["position"] = raw.get("position") if raw.get("position") in POSITIONS else "center"
    return d


def parse_collection(raw: dict, folder: str = "") -> Collection | None:
    """One collection from its config (`assets/anime/<id>/collection.json`). None when it is not usable."""
    try:
        cid = slug(raw["id"], "")
        name = str(raw["name"]).strip()
        if not cid or not name:
            return None
        art = raw.get("artwork") if isinstance(raw.get("artwork"), dict) else {}
        chars = []
        for c in art.get("characters") or []:
            if isinstance(c, dict) and c.get("id") and c.get("name"):
                chars.append(Character(slug(c["id"]), str(c["name"]).strip(), str(c.get("image") or "")))
        accent = str(raw.get("accent") or "")
        return Collection(cid, name, int(raw.get("order") or 0), accent if valid_hex(accent) else "#6B7A90", tuple(chars),
                          str(art.get("defaultBackground") or ""), str(art.get("header") or ""), str(art.get("preview") or ""),
                          _appearance(raw.get("appearance")), folder)
    except (KeyError, TypeError, ValueError):
        return None


def load_collections(root: str | Path) -> dict[str, Collection]:
    """Every anime collection, in gallery order. A broken config is skipped; it never stops the others."""
    found: dict[str, Collection] = {}
    for base in asset_roots(root):
        for cfg in sorted(base.glob("*/collection.json")):
            col = parse_collection(_read_json(cfg), str(cfg.parent))
            if col is not None and col.id not in found:
                found[col.id] = col
    return dict(sorted(found.items(), key=lambda kv: (kv[1].order, kv[1].name)))


# ------------------------------------------------------------------------------------------------ the manifest
REQUIRED_FIELDS = ("file", "collection", "kind", "source_url", "licence", "permitted_use")


def manifest_problems(entry: dict) -> list[str]:
    """Why a manifest entry does not allow its picture to be shown (empty = fine)."""
    out = [f"missing {k}" for k in REQUIRED_FIELDS if not str(entry.get(k) or "").strip()]
    if entry.get("approved") is not True:
        out.append("not marked approved")
    if str(entry.get("kind") or "") not in KINDS:
        out.append("unknown kind")
    return out


class Manifest:
    """`assets/anime/manifest.json`: where each bundled picture came from and what it may be used for."""

    def __init__(self, root: str | Path):
        self.entries: dict[str, dict] = {}
        for base in reversed(asset_roots(root)):
            for e in _read_json(base / "manifest.json").get("assets") or []:
                if isinstance(e, dict) and e.get("file"):
                    self.entries[str(e["file"]).replace("\\", "/")] = e

    def approved(self, rel: str) -> bool:
        e = self.entries.get(rel.replace("\\", "/"))
        return e is not None and not manifest_problems(e)


# ------------------------------------------------------------------------------------------------ pictures on disk
@dataclass(frozen=True)
class ArtImage:
    key: str               # "bundled:<path under assets/anime>" or "user:<file name>": what a choice remembers
    path: Path
    kind: str
    collection: str
    character: str         # a character id for "characters", else ""
    label: str
    source: str            # "bundled" or "user"

    @property
    def is_user(self) -> bool:
        return self.source == "user"


def _files(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_TYPES)
    except OSError:
        return []


def _label(stem: str) -> str:
    return re.sub(r"[-_]+", " ", stem).strip().title()


class Library:
    """What can be shown for each collection: the approved bundled pictures plus the user's own."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.collections = load_collections(root)
        self.manifest = Manifest(root)
        self._bases = asset_roots(root)

    def reload(self) -> None:
        self.__init__(self.root)

    # ---- listing
    def images(self, cid: str, kind: str, character: str = "") -> list[ArtImage]:
        out: list[ArtImage] = []
        for base in self._bases:
            for p in _files(base / cid / kind):
                rel = f"{cid}/{kind}/{p.name}"
                e = self.manifest.entries.get(rel)
                if e is None or manifest_problems(e):
                    continue                                     # no recorded right to show it: ignored
                who = slug(e.get("character") or "", "")
                if kind == "characters" and character and who != character:
                    continue
                if not any(o.key == f"bundled:{rel}" for o in out):
                    out.append(ArtImage(f"bundled:{rel}", p, kind, cid, who, str(e.get("label") or _label(p.stem)), "bundled"))
        for p in _files(user_dir(self.root) / cid / kind):
            who = p.stem.split("--", 1)[0] if kind == "characters" and "--" in p.stem else ""
            if kind == "characters" and character and who != character:
                continue
            tail = p.stem.split("--", 1)[-1]
            out.append(ArtImage(f"user:{kind}/{p.name}", p, kind, cid, who, _label(tail) + " (yours)", "user"))
        return out

    def find(self, cid: str, kind: str, key: str, character: str = "") -> ArtImage | None:
        return next((i for i in self.images(cid, kind, character) if i.key == key), None)

    def has_any(self, cid: str) -> bool:
        return any(self.images(cid, k) for k in ("backgrounds", "characters", "banners"))

    # ---- adding and removing the user's own
    def add_user_image(self, cid: str, kind: str, src: str | Path, character: str = "", label: str = "") -> ArtImage:
        """Convert the user's picture to WebP and keep it in data/lite/artwork. Raises ArtError with a plain reason."""
        if cid not in self.collections or kind not in ("backgrounds", "characters", "banners"):
            raise ArtError("That is not a place artwork can be added to.")
        src = Path(src)
        try:
            size = src.stat().st_size
        except OSError:
            raise ArtError("That file cannot be read.") from None
        if size > MAX_FILE_BYTES:
            raise ArtError("That file is over 60 MB. Resize it first.")
        try:
            with Image.open(src) as probe:
                probe.verify()
            with Image.open(src) as im:
                if im.width * im.height > MAX_PIXELS:
                    raise ArtError("That picture is larger than 60 megapixels. Resize it first.")
                im = ImageOps.exif_transpose(im)
                im.load()
                limit = MAX_SIDE[kind]
                if max(im.size) > limit:
                    im.thumbnail((limit, limit), Image.LANCZOS)
                im = im.convert("RGBA")
        except ArtError:
            raise
        except Exception:  # noqa: BLE001 - Pillow raises many kinds of error for a file that is not a picture
            raise ArtError("That file is not a picture ReRun LITE can open (use WebP, PNG, JPG, BMP or GIF).") from None
        folder = user_dir(self.root) / cid / kind
        folder.mkdir(parents=True, exist_ok=True)
        base = slug(label or src.stem)
        stem = f"{character}--{base}" if kind == "characters" and character else base
        name, n = f"{stem}.webp", 2
        while (folder / name).exists():
            name, n = f"{stem}-{n}.webp", n + 1
        dst = folder / name
        tmp = dst.with_name(dst.name + ".tmp")
        try:
            opaque = im.getchannel("A").getextrema()[0] == 255
            (im.convert("RGB") if opaque else im).save(tmp, format="WEBP", quality=90, method=4)
            os.replace(tmp, dst)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise ArtError(f"Could not save the picture: {e.strerror or e}") from None
        self._record_user(cid, kind, name, character, im.size, src.name)
        found = self.find(cid, kind, f"user:{kind}/{name}", character)
        if found is None:
            raise ArtError("The picture was saved but could not be found again.")
        return found

    def import_folder(self, folder: str | Path) -> tuple[list[ArtImage], list[str]]:
        """Add many of the user's own pictures at once. `folder` holds one sub-folder per anime (named by its id, for
        example `jujutsu-kaisen`); inside, `gojo.png` (or `gojo--alt.png`) is a character, a name starting `background` is
        a background and one starting `banner` is a banner. Pictures already added from the same file name are skipped, so
        importing twice does not make copies. Returns (added, notes about what was skipped and why)."""
        added: list[ArtImage] = []
        notes: list[str] = []
        done = {(a.get("collection"), a.get("kind"), str(a.get("source", "")).split("'")[1] if "'" in str(a.get("source", "")) else "")
                for a in _read_json(user_dir(self.root) / USER_MANIFEST).get("assets") or [] if isinstance(a, dict)}
        root = Path(folder)
        try:
            subs = sorted(d for d in root.iterdir() if d.is_dir())
        except OSError:
            return [], ["That folder cannot be read."]
        for sub in subs:
            col = self.collections.get(slug(sub.name))
            if col is None:
                notes.append(f"{sub.name}: not one of the 16 anime folder names")
                continue
            for f in sorted(sub.iterdir()):
                if not f.is_file() or f.suffix.lower() not in IMPORT_TYPES:
                    continue
                stem = f.stem.lower()
                if stem.startswith("background"):
                    kind, who = "backgrounds", ""
                elif stem.startswith("banner"):
                    kind, who = "banners", ""
                else:
                    kind, who = "characters", slug(stem.split("--")[0], "")
                    if col.character(who) is None:
                        notes.append(f"{sub.name}/{f.name}: no character called '{who}' in {col.name}")
                        continue
                if (col.id, kind, f.name) in done:
                    continue
                try:
                    added.append(self.add_user_image(col.id, kind, f, who, stem.split("--", 1)[-1]))
                except ArtError as e:
                    notes.append(f"{sub.name}/{f.name}: {e}")
        return added, notes

    def _record_user(self, cid: str, kind: str, name: str, character: str, size, original: str) -> None:
        """Keep a note of where each of the user's pictures came from (the same facts the bundled manifest holds)."""
        path = user_dir(self.root) / USER_MANIFEST
        data = _read_json(path)
        data.setdefault("schema", SCHEMA)
        assets = [a for a in data.get("assets") or [] if isinstance(a, dict)]
        assets.append({
            "file": f"{cid}/{kind}/{name}", "collection": cid, "kind": kind, "character": character,
            "width": size[0], "height": size[1], "source_url": "", "source": f"Added by the user from the file '{original}'",
            "licence": "Supplied by the user", "permitted_use": "Personal use on this PC only; never uploaded or bundled",
            "attribution": ""})
        data["assets"] = assets
        try:
            _write_json(path, data)
        except OSError:
            pass                                                 # the note is a courtesy; the picture is already saved

    def remove_user_image(self, art: ArtImage) -> bool:
        """Delete one of the user's own pictures (never a bundled one)."""
        if not art.is_user:
            return False
        try:
            art.path.unlink()
        except OSError:
            return False
        path = user_dir(self.root) / USER_MANIFEST
        data = _read_json(path)
        rel = f"{art.collection}/{art.kind}/{art.path.name}"
        if data.get("assets"):
            data["assets"] = [a for a in data["assets"] if not (isinstance(a, dict) and a.get("file") == rel)]
            try:
                _write_json(path, data)
            except OSError:
                pass
        return True


# ------------------------------------------------------------------------------------------------ what the user chose
@dataclass
class Prefs:
    """`enabled` and `collection` are global; everything else is kept per anime in `per[collection id]` and only when the
    user changed it, so a collection's own defaults still apply to everything left alone."""
    enabled: bool = True
    collection: str = ""
    favourites: list[str] = field(default_factory=list)
    per: dict[str, dict] = field(default_factory=dict)

    PER_KEYS = ("character", "variant", "background", "banner", "opacity", "blur", "position", "showBackground",
                "showCharacterArtwork", "showHeaderArtwork", "showInstanceArtwork", "showPanelArtwork", "headerHeight")

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "collection": self.collection, "favourites": list(self.favourites),
                "per": {k: dict(v) for k, v in self.per.items()}}

    def set(self, cid: str, **changes) -> None:
        d = self.per.setdefault(cid, {})
        for k, v in changes.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        if not d:
            self.per.pop(cid, None)

    def reset_collection(self, cid: str) -> None:
        self.per.pop(cid, None)

    def reset_all(self) -> None:
        """Back to the defaults. Favourites are kept: they are a list the user made, not a setting."""
        self.enabled, self.collection, self.per = True, "", {}

    def toggle_favourite(self, key: str) -> bool:
        if key in self.favourites:
            self.favourites.remove(key)
            return False
        self.favourites.append(key)
        return True


def prefs_from_ui(ui: dict) -> Prefs:
    raw = ui.get("artwork") if isinstance(ui, dict) else None
    p = Prefs()
    if not isinstance(raw, dict):
        return p
    p.enabled = bool(raw.get("enabled", True))
    p.collection = str(raw.get("collection") or "")
    favs = raw.get("favourites")
    p.favourites = [f for f in favs if isinstance(f, str)] if isinstance(favs, list) else []
    for cid, d in (raw.get("per") or {}).items() if isinstance(raw.get("per"), dict) else []:
        if isinstance(d, dict):
            p.per[str(cid)] = {k: v for k, v in d.items() if k in Prefs.PER_KEYS}
    return p


@dataclass(frozen=True)
class Settings:
    """The artwork choices in force: the collection's defaults with the user's changes on top."""
    enabled: bool
    collection: Collection | None
    character_id: str
    variant: str
    background: str            # "default", "none" or an ArtImage key
    banner: str
    opacity: float
    blur: float
    position: str
    show_background: bool
    show_character: bool
    show_header: bool
    show_instance: bool
    show_panel: bool
    header_height: int

    @property
    def anchor(self) -> tuple[float, float]:
        return POSITIONS.get(self.position, POSITIONS["center"])


def effective(prefs: Prefs, collections: dict[str, Collection], cid: str | None = None) -> Settings:
    """The settings for collection `cid` (default: the chosen one)."""
    cid = prefs.collection if cid is None else cid
    col = collections.get(cid)
    base = col.defaults if col else DEFAULT_APPEARANCE
    u = prefs.per.get(cid, {}) if col else {}

    def flag(user_key: str, cfg_key: str) -> bool:
        return u[user_key] if isinstance(u.get(user_key), bool) else bool(base[cfg_key])
    char = str(u.get("character") or "")
    if col and col.character(char) is None:
        char = col.characters[0].id if col.characters else ""
    pos = u.get("position") if u.get("position") in POSITIONS else base["position"]
    return Settings(
        bool(prefs.enabled and col is not None), col, char, str(u.get("variant") or ""), str(u.get("background") or "default"),
        str(u.get("banner") or "default"), _num(u.get("opacity", base["backgroundOpacity"]), *OPACITY_RANGE, base["backgroundOpacity"]),
        _num(u.get("blur", base["blur"]), *BLUR_RANGE, base["blur"]), pos, flag("showBackground", "showBackground"),
        flag("showCharacterArtwork", "showCharacterArtwork"), flag("showHeaderArtwork", "showHeaderArtwork"),
        flag("showInstanceArtwork", "showInstanceArtwork"), flag("showPanelArtwork", "showPanelArtwork"),
        int(_num(u.get("headerHeight", base["headerHeight"]), *HEADER_RANGE, base["headerHeight"])))


class Resolver:
    """Turns `Settings` into the actual files to show. Every method returns None when there is nothing to show."""

    def __init__(self, lib: Library):
        self.lib = lib

    def _pick(self, cid: str, kind: str, choice: str, default_rel: str, character: str = "") -> ArtImage | None:
        if choice == "none":
            return None
        imgs = self.lib.images(cid, kind, character)
        if choice not in ("", "default"):
            hit = next((i for i in imgs if i.key == choice), None)
            if hit is not None:
                return hit                                       # a choice whose file has gone falls back to the default
        if default_rel:
            hit = next((i for i in imgs if i.key == f"bundled:{cid}/{default_rel}"), None)
            if hit is not None:
                return hit
        return imgs[0] if imgs else None

    def background(self, s: Settings) -> ArtImage | None:
        if not (s.enabled and s.show_background and s.collection):
            return None
        return self._pick(s.collection.id, "backgrounds", s.background, s.collection.background)

    def character(self, s: Settings) -> ArtImage | None:
        if not (s.enabled and s.collection and s.character_id):
            return None
        c = s.collection.character(s.character_id)
        return self._pick(s.collection.id, "characters", s.variant, c.image if c else "", s.character_id)

    def header(self, s: Settings) -> ArtImage | None:
        """The banner picture; with none, the character's picture cropped wide."""
        if not (s.enabled and s.show_header and s.collection):
            return None
        banner = self._pick(s.collection.id, "banners", s.banner, s.collection.header)
        if banner is not None:
            return banner
        return self.character(s) if s.show_character else None

    def portrait(self, s: Settings) -> ArtImage | None:
        return self.character(s) if s.show_instance and s.show_character else None

    def panel(self, s: Settings) -> ArtImage | None:
        """Decoration for the statistics panels: the background if there is one, else the character."""
        if not (s.enabled and s.show_panel and s.collection):
            return None
        return self.background(Settings(**{**s.__dict__, "show_background": True})) or self.character(s)


def fav_key(cid: str, kind: str, ident: str) -> str:
    return f"{cid}|{kind}|{ident}"


def search(lib: Library, prefs: Prefs, query: str = "", favourites_only: bool = False) -> list[tuple[Collection, list[str]]]:
    """Collections matching `query` (every word must appear in the anime's name, id, a character's name or id, or the name
    of a picture in it), each with the names of the characters that matched. With `favourites_only`, only collections that
    have a favourite."""
    words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    out = []
    for col in lib.collections.values():
        if favourites_only and not any(f.startswith(col.id + "|") for f in prefs.favourites):
            continue
        hay_col = f"{col.name} {col.id}".lower()
        user_labels = " ".join(i.label.lower() for k in ("backgrounds", "characters", "banners") for i in lib.images(col.id, k)) \
            if words else ""
        hits: list[str] = []
        ok = True
        for w in words:
            in_col = w in hay_col or w in user_labels
            who = [c.name for c in col.characters if w in c.name.lower() or w in c.id]
            if not (in_col or who):
                ok = False
                break
            if not in_col:
                hits += [n for n in who if n not in hits]
        if ok:
            out.append((col, hits))
    return out


# ------------------------------------------------------------------------------------------------ making pictures ready
def load_rgba(path: str | Path, max_side: int = 2560) -> Image.Image:
    """A picture as RGBA, no larger than `max_side`. Raises on anything unreadable (callers catch it)."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.load()
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        return im.convert("RGBA")


def fit_cover(im: Image.Image, w: int, h: int, anchor: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    """`im` scaled to fill w x h and cropped to it (CSS background-size: cover), the crop placed by `anchor`."""
    w, h = max(1, int(w)), max(1, int(h))
    sw, sh = im.size
    s = max(w / sw, h / sh)
    nw, nh = max(w, round(sw * s)), max(h, round(sh * s))
    r = im.resize((nw, nh), Image.LANCZOS if s < 1 else Image.BICUBIC)
    x, y = round((nw - w) * anchor[0]), round((nh - h) * anchor[1])
    return r.crop((x, y, x + w, y + h))


def _rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _font(size: int, bold: bool = False):
    for name in (("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


class ImageCache:
    """Pictures already made ready, kept in memory (so the same artwork is never decoded twice in a row) and, for
    thumbnails, on disk in data/lite/cache/artwork (so the next start does not decode a big file again)."""

    def __init__(self, root: str | Path, limit: int = 64):
        self.root, self.limit = Path(root), limit
        self._mem: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key):
        with self._lock:
            if key in self._mem:
                self._mem.move_to_end(key)
                self.hits += 1
                return self._mem[key]
        return None

    def put(self, key, value) -> None:
        with self._lock:
            self._mem[key] = value
            self._mem.move_to_end(key)
            while len(self._mem) > self.limit:
                self._mem.popitem(last=False)

    def make(self, key, fn):
        """The cached value for `key`, else `fn()` (stored when it is not None). An error inside fn gives None."""
        hit = self.get(key)
        if hit is not None:
            return hit
        self.misses += 1
        try:
            value = fn()
        except Exception:  # noqa: BLE001 - a bad or missing picture must never crash the window
            return None
        if value is not None:
            self.put(key, value)
        return value

    def source(self, path: str | Path, max_side: int = 640) -> Image.Image | None:
        """A picture no larger than `max_side`, from memory, from the disk cache, or from the file."""
        path = Path(path)
        try:
            st = path.stat()
        except OSError:
            return None
        stamp = (str(path), st.st_mtime_ns, st.st_size, max_side)

        def build():
            f = cache_dir(self.root) / (hashlib.sha1(repr(stamp).encode()).hexdigest()[:20] + ".webp")
            if f.is_file():
                try:
                    return load_rgba(f, max_side)
                except Exception:  # noqa: BLE001 - a damaged cache file is rebuilt
                    f.unlink(missing_ok=True)
            im = load_rgba(path, max_side)
            if max(Image.open(path).size) > max_side:            # only a big original is worth keeping a thumbnail of
                try:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    im.save(f, "WEBP", quality=88, method=4)
                except OSError:
                    pass
            return im
        return self.make(("src",) + stamp, build)

    def prune_disk(self, keep: int = 300) -> int:
        """Delete the oldest cached thumbnails beyond `keep`. Returns how many were removed."""
        try:
            files = sorted(cache_dir(self.root).glob("*.webp"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return 0
        n = 0
        for p in files[keep:]:
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n


# ---- drawing
def placeholder(w: int, h: int, accent: str, base: str, text: str = "") -> Image.Image:
    """A plain stand-in drawn in code: a gradient in the anime's accent colour and its initials. Not artwork."""
    w, h = max(2, int(w)), max(2, int(h))
    a, b = _rgb(mix(base, accent, 0.55)), _rgb(mix(base, accent, 0.12))
    row = Image.new("RGB", (w, 1))
    row.putdata([tuple(round(a[i] + (b[i] - a[i]) * x / max(1, w - 1)) for i in range(3)) for x in range(w)])
    im = row.resize((w, h))
    if text:
        d = ImageDraw.Draw(im)
        f = _font(max(10, int(h * 0.62)), True)
        bbox = d.textbbox((0, 0), text, font=f)
        d.text(((w - (bbox[2] - bbox[0])) // 2 - bbox[0], (h - (bbox[3] - bbox[1])) // 2 - bbox[1]), text, font=f,
               fill=_rgb(mix(base, "#FFFFFF", 0.22)))
    return im


@dataclass(frozen=True)
class StripSpec:
    """Everything that decides how a header banner or panel strip looks (so it can be cached on it)."""
    w: int
    h: int
    path: str                  # "" = none (nothing is drawn; callers hide the strip instead)
    stamp: tuple               # the file's (mtime, size), so an edited file is not served from the cache
    anchor: tuple
    base: str                  # the colour of the bar or page it sits on
    accent: str
    strength: float            # 0..1: how strongly the picture shows
    blur: float
    caption: str
    caption_fg: str
    fade: bool = True


def render_strip(spec: StripSpec, cache: ImageCache | None = None) -> Image.Image:
    """A wide, short picture: the artwork fading into `base` from the left, an accent hairline underneath and a small
    caption (anime · character) at the right. Pure drawing; the picture is read through `cache`."""
    w, h = spec.w, spec.h
    base = Image.new("RGB", (w, h), _rgb(spec.base))
    src = None
    if spec.path:
        src = cache.source(spec.path, max(640, min(1920, w))) if cache is not None else load_rgba(spec.path, 1920)
    art = fit_cover(src, w, h, spec.anchor) if src is not None else placeholder(w, h, spec.accent, spec.base)
    if spec.blur > 0:
        art = art.convert("RGBA").filter(ImageFilter.GaussianBlur(spec.blur * max(0.4, w / 1280)))
    art = art.convert("RGBA")
    # the mask: the picture's own transparency, times a fade from the left (the title side) times the strength
    mask = art.getchannel("A")
    ramp = Image.new("L", (w, 1))
    if spec.fade:
        ramp.putdata([round(255 * min(1.0, max(0.0, (x / max(1, w) - 0.18) / 0.62)) ** 1.4) for x in range(w)])
    else:
        ramp.putdata([255] * w)
    ramp = ramp.resize((w, h))
    mask = ImageChops.multiply(ImageChops.multiply(mask, ramp), Image.new("L", (w, h), round(255 * spec.strength)))
    art.putalpha(mask)
    out = Image.alpha_composite(base.convert("RGBA"), art)
    d = ImageDraw.Draw(out)
    d.rectangle((0, h - 2, w, h), fill=_rgb(spec.accent) + (255,))
    if spec.caption:
        f = _font(max(10, min(14, h // 4)), True)
        tw = d.textbbox((0, 0), spec.caption, font=f)
        cw, ch = tw[2] - tw[0], tw[3] - tw[1]
        x1, y1 = w - 10, h - 8
        x0, y0 = x1 - cw - 16, y1 - ch - 10
        if x0 > w * 0.3:
            d.rounded_rectangle((x0, y0, x1, y1), 6, fill=_rgb(spec.base) + (215,))
            d.text((x0 + 8 - tw[0], y0 + 5 - tw[1]), spec.caption, font=f, fill=_rgb(spec.caption_fg))
    return out.convert("RGB")


def render_portrait(path: str | Path, size: int, accent: str, cache: ImageCache | None = None) -> Image.Image | None:
    """A small square portrait (the top of the picture, where faces are) with a thin accent edge. None if unreadable."""
    try:
        src = cache.source(path, max(256, size * 2)) if cache is not None else load_rgba(path, max(256, size * 2))
        if src is None:
            return None
        im = fit_cover(src, size, size, (0.5, 0.12))
        flat = Image.new("RGB", (size, size), _rgb(mix(accent, "#000000", 0.55)))
        flat.paste(im.convert("RGB"), (0, 0), im.getchannel("A"))
        ImageDraw.Draw(flat).rectangle((0, 0, size - 1, size - 1), outline=_rgb(accent), width=1)
        return flat
    except Exception:  # noqa: BLE001 - never let a bad picture reach the window
        return None


@dataclass(frozen=True)
class PreviewSpec:
    """A gallery card: a small picture of the real window with this anime's artwork in each place it can appear."""
    w: int
    h: int
    palette: tuple                  # (bg, card, bar, label, secondary, sep, accent) as hex, from the open look
    accent: str                     # the anime's own accent
    monogram: str
    background: str = ""
    header: str = ""
    portrait: str = ""
    panel: str = ""
    opacity: float = 0.18
    blur: float = 2.0
    anchor: tuple = (0.5, 0.5)
    stamps: tuple = ()


def render_preview(spec: PreviewSpec, cache: ImageCache | None = None) -> Image.Image:
    """The Auto Crest window in miniature, drawn from the same colours and the same artwork as the real one."""
    w, h = spec.w, spec.h
    bg, card, bar, label, secondary, sep, accent = spec.palette
    im = Image.new("RGB", (w, h), _rgb(bg))

    def src(p, side):
        if not p:
            return None
        return cache.source(p, side) if cache is not None else load_rgba(p, side)
    art = src(spec.background, 640)
    if art is not None:                                          # the background, toned the way the real one is
        pic = fit_cover(art, w, h, spec.anchor).convert("RGB")
        if spec.blur > 0:
            pic = pic.filter(ImageFilter.GaussianBlur(spec.blur * w / 1280 * 2))
        im = Image.blend(im, pic, spec.opacity)
    d = ImageDraw.Draw(im, "RGBA")
    bar_h = max(8, h // 9)
    d.rectangle((0, 0, w, bar_h), fill=_rgb(bar))
    d.rectangle((0, bar_h, w, bar_h), fill=_rgb(sep))
    d.rectangle((6, bar_h // 2 - 2, 6 + w // 9, bar_h // 2 + 2), fill=_rgb(label))
    for i in range(3):
        x = w // 3 + i * (w // 11)
        d.rectangle((x, bar_h // 2 - 2, x + w // 15, bar_h // 2 + 2), fill=_rgb(secondary if i else accent))
    y = bar_h + 5
    if spec.header or spec.monogram:
        hh = max(10, h // 6)
        strip = render_strip(StripSpec(w - 12, hh, spec.header, (), spec.anchor, bg, spec.accent, 0.9, 0.0, "", label), cache) \
            if spec.header else placeholder(w - 12, hh, spec.accent, bg, spec.monogram)
        im.paste(strip, (6, y))
        y += hh + 5
    # the instance card (with a portrait when there is one) and the five totals tiles
    cw = int(w * 0.58)
    ch = max(14, h // 5)
    d.rounded_rectangle((6, y, 6 + cw, y + ch), 3, fill=_rgb(card), outline=_rgb(sep))
    tx = 12
    if spec.portrait:
        p = render_portrait(spec.portrait, ch - 6, spec.accent, cache)
        if p is not None:
            im.paste(p, (9, y + 3))
            tx = 9 + p.width + 5
    d.rectangle((tx, y + 5, tx + cw // 3, y + 8), fill=_rgb(label))
    d.rectangle((tx, y + 11, tx + cw // 2, y + 13), fill=_rgb(secondary))
    d.ellipse((6 + cw - 10, y + ch // 2 - 3, 6 + cw - 4, y + ch // 2 + 3), fill=_rgb(accent))
    y += ch + 5
    tw = (cw - 4 * 3) // 5
    for i in range(5):
        x = 6 + i * (tw + 3)
        d.rounded_rectangle((x, y, x + tw, y + max(8, h // 9)), 2, fill=_rgb(card), outline=_rgb(sep))
        d.rectangle((x + 3, y + 3, x + tw - 3, y + 5), fill=_rgb(label))
    y += max(8, h // 9) + 3
    if spec.panel:
        ps = render_strip(StripSpec(cw, max(6, h // 14), spec.panel, (), spec.anchor, bg, spec.accent, 0.4, 0.0, "", label), cache)
        im.paste(ps, (6, y))
    # the live view on the right stays solid and artwork-free
    d.rounded_rectangle((6 + cw + 8, bar_h + 5, w - 6, h - 8), 3, fill=_rgb(card), outline=_rgb(sep))
    d.rectangle((6 + cw + 14, bar_h + 11, w - 12, bar_h + 14), fill=_rgb(secondary))
    return im


__all__ = ["ArtError", "ArtImage", "Character", "Collection", "ImageCache", "Library", "Manifest", "Prefs", "PreviewSpec",
           "Resolver", "Settings", "StripSpec", "effective", "fav_key", "fit_cover", "load_collections", "load_rgba",
           "manifest_problems", "placeholder", "prefs_from_ui", "render_portrait", "render_preview", "render_strip", "search"]
