"""Finds on-screen elements by matching captured template images."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# Checked on the live game: true matches of imported templates score 0.85-0.97,
# while the best wrong element on a busy Home screen scored 0.67.
DEFAULT_THRESHOLD = 0.80
MATCH_SCALE = 0.5  # match at half resolution: ~4x faster, still accurate for UI


class MissingTemplate(KeyError):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        return (f"Template '{self.name}' has not been captured yet. "
                "Open the Templates tab and capture it.")


@dataclass
class Match:
    name: str
    x: int  # top-left, in screen pixels
    y: int
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


class TemplateStore:
    """Loads template PNGs from a folder. Each template remembers the screen
    resolution it was captured at, so matching still works if you resize."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._meta_path = self.folder / "_meta.json"
        self._cache: dict[str, np.ndarray] = {}
        self._gen: dict[str, int] = {}  # bumped whenever a template changes
        self._lock = threading.Lock()
        self.meta: dict[str, dict] = self._load_meta()

    def _load_meta(self) -> dict:
        if self._meta_path.exists():
            try:
                return json.loads(self._meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_meta(self) -> None:
        self._meta_path.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    def path(self, name: str) -> Path:
        return self.folder / f"{name}.png"

    def has(self, name: str) -> bool:
        return self.path(name).exists()

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.png"))

    def get(self, name: str) -> np.ndarray:
        with self._lock:
            if name not in self._cache:
                p = self.path(name)
                if not p.exists():
                    raise MissingTemplate(name)
                img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    raise MissingTemplate(name)
                self._cache[name] = img
            return self._cache[name]

    def resolution(self, name: str) -> tuple[int, int] | None:
        m = self.meta.get(name)
        return (m["screen_w"], m["screen_h"]) if m else None

    def save(self, name: str, screen: np.ndarray, x: int, y: int, w: int, h: int,
             threshold: float | None = None) -> None:
        crop = screen[y:y + h, x:x + w]
        if crop.size == 0:
            raise ValueError("Empty selection")
        ok, buf = cv2.imencode(".png", crop)
        if not ok:
            raise ValueError("Could not encode template")
        buf.tofile(str(self.path(name)))
        with self._lock:
            self._cache.pop(name, None)
            self._gen[name] = self._gen.get(name, 0) + 1
            self.meta[name] = {
                "screen_w": int(screen.shape[1]), "screen_h": int(screen.shape[0]),
                "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            }
            if threshold is not None:
                self.meta[name]["threshold"] = float(threshold)
            self._save_meta()

    def import_file(self, name: str, src: str | Path, screen_w: int, screen_h: int,
                    source: str = "import") -> None:
        """Copy an existing template image, recording the frame size it came from."""
        img = cv2.imdecode(np.fromfile(str(src), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Not an image: {src}")
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise ValueError(f"Could not encode {src}")
        buf.tofile(str(self.path(name)))
        with self._lock:
            self._cache.pop(name, None)
            self._gen[name] = self._gen.get(name, 0) + 1
            self.meta[name] = {"screen_w": int(screen_w), "screen_h": int(screen_h),
                               "w": int(img.shape[1]), "h": int(img.shape[0]), "source": source}
            self._save_meta()

    def delete(self, name: str) -> None:
        with self._lock:
            self._cache.pop(name, None)
            self._gen[name] = self._gen.get(name, 0) + 1
            self.meta.pop(name, None)
            self._save_meta()
        if self.path(name).exists():
            self.path(name).unlink()

    def reload(self) -> None:
        """Forget every cached image and re-read _meta.json (after a template update)."""
        with self._lock:
            old = set(self.meta)
            self.meta = self._load_meta()
            names = set(self._cache) | set(self._gen) | old | set(self.meta)
            self._cache.clear()
            for name in names:
                self._gen[name] = self._gen.get(name, 0) + 1

    def generation(self, name: str) -> int:
        return self._gen.get(name, 0)

    def is_from_restart(self, name: str) -> bool:
        return self.meta.get(name, {}).get("source") == "restart"

    def threshold(self, name: str, default: float = DEFAULT_THRESHOLD) -> float:
        return float(self.meta.get(name, {}).get("threshold", default))


class _Prepared:
    """A template plus its derived images, built once and reused every frame."""
    __slots__ = ("full", "coarse", "scale", "bright")

    def __init__(self, tmpl: np.ndarray):
        th, tw = tmpl.shape[:2]
        self.full = tmpl
        self.scale = MATCH_SCALE if min(th, tw) * MATCH_SCALE >= 12 else 1.0
        small = (cv2.resize(tmpl, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
                 if self.scale != 1.0 else tmpl)
        self.coarse = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        self.bright = float(cv2.cvtColor(tmpl, cv2.COLOR_BGR2HSV)[..., 2].mean())


# Two passes: a greyscale search (a third of the work of colour) finds where the
# template best fits, then a full-resolution colour match in a few pixels around
# that spot gives the exact position and score. Checked against the old
# colour-everywhere search on every real-screen fixture: identical results.
REFINE_MARGIN = 3
CANDIDATES = 6  # grey peaks re-scored in colour
CANDIDATE_FLOOR = 0.5  # weaker grey peaks are not worth re-scoring


class Vision:
    def __init__(self, store: TemplateStore):
        self.store = store
        self._prepared: dict[str, tuple[int, _Prepared]] = {}
        self._local = threading.local()  # per-thread cache of the current frame's scaled copies

    def _prep(self, name: str) -> _Prepared:
        tmpl = self.store.get(name)  # raises MissingTemplate; cached by the store
        gen = self.store.generation(name)
        hit = self._prepared.get(name)
        if hit is None or hit[0] != gen:  # re-captured since -> rebuild
            hit = (gen, _Prepared(tmpl))
            self._prepared[name] = hit
        return hit[1]

    def _frame(self, screen: np.ndarray, res: tuple[int, int]) -> dict:
        """Scaled copies of `screen`, made once per frame (and per capture size)."""
        loc = self._local
        if getattr(loc, "screen", None) is not screen:
            loc.screen, loc.views = screen, {}
        views = loc.views.get(res)
        if views is None:
            sh, sw = screen.shape[:2]
            work = screen if (sw, sh) == res else cv2.resize(screen, res, interpolation=cv2.INTER_AREA)
            views = loc.views[res] = {"work": work}
        return views

    @staticmethod
    def _view(views: dict, key: str, make):
        v = views.get(key)
        if v is None:
            v = views[key] = make()
        return v

    def find(self, screen: np.ndarray, name: str, threshold: float | None = None,
             region: tuple[int, int, int, int] | None = None) -> Match | None:
        """Best match for template `name` on `screen`, or None if below threshold."""
        thr = threshold if threshold is not None else self.store.threshold(name)
        m = self.score(screen, name, region)
        if m and m.score >= thr:
            self._note_hit(name, m.score)
            return m
        return None

    # ------------------------------------------------------------ health
    HEALTH_KEEP = 30      # recent match scores kept per template
    HEALTH_MIN_HITS = 5
    HEALTH_MARGIN = 0.05  # median this close to the threshold = about to fail

    def _note_hit(self, name: str, score: float) -> None:
        h = self.__dict__.setdefault("_health", {})
        d = h.get(name)
        if d is None:
            from collections import deque
            d = h[name] = deque(maxlen=self.HEALTH_KEEP)
        d.append(score)

    def health(self) -> dict[str, dict]:
        """{template: {'median', 'threshold', 'hits', 'weak'}} for templates seen
        lately. 'weak' = real matches now score barely above the threshold - the
        usual sign of a game update; re-capture or re-import it before it fails."""
        out = {}
        for name, d in list(self.__dict__.get("_health", {}).items()):
            scores = sorted(d)
            if not scores:
                continue
            med = scores[len(scores) // 2]
            thr = self.store.threshold(name)
            out[name] = {"median": round(med, 3), "threshold": thr, "hits": len(scores),
                         "weak": len(scores) >= self.HEALTH_MIN_HITS and med < thr + self.HEALTH_MARGIN}
        return out

    def reset_health(self, name: str | None = None) -> None:
        h = self.__dict__.get("_health", {})
        if name:
            h.pop(name, None)
        else:
            h.clear()

    def score(self, screen: np.ndarray, name: str,
              region: tuple[int, int, int, int] | None = None) -> Match | None:
        p = self._prep(name)
        tmpl = p.full
        sh, sw = screen.shape[:2]
        res = self.store.resolution(name) or (sw, sh)
        # Scale the screen to the resolution the template was captured at.
        fx = sw / res[0]
        fy = sh / res[1]
        views = self._frame(screen, res)
        work = views["work"]
        th, tw = tmpl.shape[:2]
        s = p.scale
        ox = oy = 0
        if region:
            rx, ry, rw, rh = region
            work = work[ry:ry + rh, rx:rx + rw]
            ox, oy = rx, ry
            if work.shape[0] < th or work.shape[1] < tw:
                return None
            small = work if s == 1.0 else cv2.resize(work, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            coarse = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        else:
            if work.shape[0] < th or work.shape[1] < tw:
                return None
            coarse = self._view(views, ("gray", s), lambda: cv2.cvtColor(
                work if s == 1.0 else cv2.resize(work, None, fx=s, fy=s, interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2GRAY))
        if coarse.shape[0] < p.coarse.shape[0] or coarse.shape[1] < p.coarse.shape[1]:
            return None
        cmap = cv2.matchTemplate(coarse, p.coarse, cv2.TM_CCOEFF_NORMED)
        # Grey can't tell colours apart (e.g. a blue checkbox from a grey one),
        # so the few best grey spots are each scored in colour and the best wins.
        best, lx, ly = -2.0, 0, 0
        ch, cw = p.coarse.shape[:2]
        m = int(REFINE_MARGIN / s)
        for _ in range(CANDIDATES):
            _, cbest, _, loc = cv2.minMaxLoc(cmap)
            if not np.isfinite(cbest) or cbest < CANDIDATE_FLOOR and best > -2.0:
                break
            cx, cy = int(loc[0] / s), int(loc[1] / s)
            x0, y0 = max(0, cx - m), max(0, cy - m)
            x1 = min(work.shape[1], cx + tw + m)
            y1 = min(work.shape[0], cy + th + m)
            _, fb, _, fl = cv2.minMaxLoc(cv2.matchTemplate(work[y0:y1, x0:x1], tmpl, cv2.TM_CCOEFF_NORMED))
            if np.isfinite(fb) and fb > best:
                best, lx, ly = fb, x0 + fl[0], y0 + fl[1]
            # Blank this peak's neighbourhood so the next loop finds a different spot.
            cmap[max(0, loc[1] - ch // 2):loc[1] + ch // 2 + 1,
                 max(0, loc[0] - cw // 2):loc[0] + cw // 2 + 1] = -1.0
        if best <= -2.0:
            return None
        x = lx + ox
        y = ly + oy
        return Match(name, int(x * fx), int(y * fy), int(tw * fx), int(th * fy), float(best))

    def brightness(self, screen: np.ndarray, m: Match) -> float:
        """Mean brightness (HSV value) of the screen under a match."""
        crop = screen[m.y:m.y + m.h, m.x:m.x + m.w]
        return float(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 2].mean()) if crop.size else 0.0

    def template_brightness(self, name: str) -> float:
        return self._prep(name).bright

    def closest_by_brightness(self, screen: np.ndarray, m: Match, names: list[str]) -> str:
        """Matching ignores brightness, so an enabled and a greyed-out button can
        both score ~1.0. Pick whichever template's brightness is closest."""
        b = self.brightness(screen, m)
        return min(names, key=lambda n: abs(self.template_brightness(n) - b))

    def find_all(self, screen: np.ndarray, name: str, threshold: float | None = None,
                 max_hits: int = 12) -> list[Match]:
        """Every place `name` appears (e.g. one 'Use' button per potion row), top to bottom."""
        tmpl = self._prep(name).full
        sh, sw = screen.shape[:2]
        res = self.store.resolution(name) or (sw, sh)
        fx, fy = sw / res[0], sh / res[1]
        work = self._frame(screen, res)["work"]
        th, tw = tmpl.shape[:2]
        if work.shape[0] < th or work.shape[1] < tw:
            return []
        thr = threshold if threshold is not None else self.store.threshold(name)
        r = cv2.matchTemplate(work, tmpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(r >= thr)
        hits: list[Match] = []
        for i in np.argsort(-r[ys, xs]):
            x, y = int(xs[i]), int(ys[i])
            if all(abs(x - h.x / fx) >= tw // 2 or abs(y - h.y / fy) >= th // 2 for h in hits):
                hits.append(Match(name, int(x * fx), int(y * fy), int(tw * fx), int(th * fy),
                                  float(r[y, x])))
                if len(hits) >= max_hits:
                    break
        return sorted(hits, key=lambda h: (h.y, h.x))

    def find_any(self, screen: np.ndarray, names: list[str],
                 threshold: float | None = None, skip_missing: bool = False) -> Match | None:
        """First template in `names` that is visible (in list order)."""
        for n in names:
            try:
                m = self.find(screen, n, threshold)
            except MissingTemplate:
                if skip_missing:
                    continue
                raise
            if m:
                return m
        return None
