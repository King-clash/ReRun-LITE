"""Finding today's Crest Palace on the screen, and the small checks around it.

Everything here only widens HOW a palace is found or says what was seen; none of it runs a palace that is not on the schedule.

  find_tile / find_tile_exact   where a palace picture is on the screen, at any size (a fast two-pass search and the exact one
                                it is compared with in the tests)
  scan_palace_screen            which palaces are on a Crest Palace screenshot, and which whole banners match none of them
  unknown_banners               just the second list (for the warning)
  times_playable                'Times playable xN' on a limited palace's quest list
  PalaceFindMixin               the methods LiteCrest uses: look for the picture, then the name read from the screen, then a fresh
                                look, then scroll the list; keep a picture when it stops; warn about new banners; stop at x0 plays

LiteCrest (crest.py) decides WHICH palaces to look for and taps; this file does the looking.
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from rerun import textnav
from rerun.scripts.base import Finished

from . import palaces

MATCH_MIN = 0.62          # normalised match score needed to accept a tile (a wrong palace scores about 0.35)
SCALES = np.concatenate([np.arange(0.6, 1.0, 0.04), np.arange(1.0, 1.62, 0.02)])


def _match_at(g: np.ndarray, t0: np.ndarray, sc: float) -> tuple[float, int, int] | None:
    """Match the picture `t0` resized by `sc` on the grey screen `g`: (score, centre x, centre y), or None if it does not fit."""
    t = cv2.resize(t0, None, fx=float(sc), fy=float(sc), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
    if t.shape[0] >= g.shape[0] or t.shape[1] >= g.shape[1] or min(t.shape) < 12:
        return None
    _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED))
    return float(mx), loc[0] + t.shape[1] // 2, loc[1] + t.shape[0] // 2


def find_tile_exact(screen: np.ndarray, picture: np.ndarray) -> tuple[float, int, int, float]:
    """Best match of `picture` on `screen` at every size in SCALES: (score, centre x, centre y, scale). Slow and exact;
    find_tile gives the same answer faster and this is what its tests compare it with."""
    g = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    t0 = cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY)
    best = (0.0, 0, 0, 1.0)
    for sc in SCALES:
        m = _match_at(g, t0, sc)
        if m and m[0] > best[0]:
            best = (m[0], m[1], m[2], float(sc))
    return best


COARSE_KEEP = 3            # sizes worth a full-size look after the half-size pass (and their neighbours)


def find_tile(screen: np.ndarray, picture: np.ndarray) -> tuple[float, int, int, float]:
    """Best match of `picture` on `screen` over a range of sizes: (score, centre x, centre y, scale).

    Two passes: every size is tried on a half-size copy (about a quarter of the work), then only the best few sizes and
    their neighbours are tried at full size. The answer matches find_tile_exact on every real screen checked."""
    g = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    t0 = cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY)
    g2 = cv2.resize(g, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    t2 = cv2.resize(t0, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    coarse = []
    for i, sc in enumerate(SCALES):
        m = _match_at(g2, t2, sc)
        if m:
            coarse.append((m[0], i))
    if not coarse:
        return (0.0, 0, 0, 1.0)
    want = set()
    for _score, i in sorted(coarse, reverse=True)[:COARSE_KEEP]:
        want.update(j for j in (i - 1, i, i + 1) if 0 <= j < len(SCALES))
    best = (0.0, 0, 0, 1.0)
    for j in sorted(want):
        m = _match_at(g, t0, SCALES[j])
        if m and m[0] > best[0]:
            best = (m[0], m[1], m[2], float(SCALES[j]))
    return best


def times_playable(ocr, screen: np.ndarray) -> int | None:
    """N from 'Times playable xN' at the top of the quest list of a palace that can only be run a few times a day (the
    Temple of Heavenly Light shows x3 and 'Resets at 4:00 AM PST'). None when the line is not there or the count is not read
    clearly: only a clearly read number is ever acted on."""
    words = ocr.screen_words(screen, min_conf=30)
    anchor = next((w for w in words if w.y < 300 and textnav.word_score("playable", w.text) >= 0.8), None)
    if anchor is None:
        return None
    x = anchor.x + anchor.w + 2
    crop = screen[max(0, anchor.y - 8):anchor.y + anchor.h + 8, x:x + 60]
    r = ocr.read(crop, whitelist="x0123456789")
    m = re.fullmatch(r"x?(\d)", re.sub(r"\s+", "", r.text.lower()))
    return int(m.group(1)) if m and r.confidence >= 70 else None


BANNER_PITCH = 181.5       # banners are stacked this many pixels apart on the 720-wide Crest Palace screen
BANNER_TOP, BANNER_BOTTOM = 320, 1060     # the part of the screen where a whole banner can be seen (header above, Back below)
BANNER_TEXTURE = 300.0     # how detailed a banner's artwork is; the empty background is far below this


def scan_palace_screen(screen: np.ndarray, pictures: list[tuple[str, np.ndarray]]) -> tuple[list[tuple[str, float, int]], list[int]]:
    """What a Crest Palace screenshot shows, against the palace pictures: ([(name, match score, height)] for each palace
    found, [height] for each whole banner that matches none of them).

    The banners are stacked at an even spacing, so once one known palace is found the other places a banner can sit
    are known too; a place with artwork in it but no known palace is a banner that is not in the list (a new or
    limited-time palace). Nothing is read from text. It needs one known palace on the screen to anchor on and only looks at
    banners that are fully on screen, so it can miss one."""
    found: list[tuple[str, float, int]] = []
    for name, pic in pictures:
        score, _x, y, _sc = find_tile(screen, pic)
        if score >= MATCH_MIN:
            found.append((name, score, y))
    if not found:
        return [], []
    anchor = max(found, key=lambda f: f[1])[2]
    known = [f[2] for f in found]
    pitch = BANNER_PITCH * screen.shape[1] / 720.0
    grey = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    unknown = []
    for k in range(-8, 9):
        yc = int(round(anchor + k * pitch))
        if yc - 70 < BANNER_TOP or yc + 70 > BANNER_BOTTOM or any(abs(yc - y) < pitch / 2 for y in known):
            continue
        band = grey[yc - 60:yc + 60, 60:660].astype(np.float64)
        if cv2.Laplacian(band, cv2.CV_64F).var() > BANNER_TEXTURE:
            unknown.append(yc)
    return sorted(found, key=lambda f: f[2]), unknown


def unknown_banners(screen: np.ndarray, pictures: list[tuple[str, np.ndarray]]) -> list[int]:
    """Screen heights of whole banners on the Crest Palace screen that match none of the palace pictures (see
    scan_palace_screen). Only a warning's input: nothing opens or changes because of it."""
    return scan_palace_screen(screen, pictures)[1]


class PalaceFindMixin:
    # ---- Safeguards while opening the palace. Each only widens HOW today's palace is found; none of them runs a palace
    # that is not on the schedule. Order: the picture, then the palace's name read from the screen, then a fresh look
    # (the screen may have been mid-animation), then scrolling the list (the fifth palace sits below the fold), and
    # during the hours when the game's schedule screen and the game day disagree, the schedule's day as a second choice.
    CLOCK_NOW = None          # tests: a function returning the time to use for the second choice
    LOOK_AGAIN = 2            # fresh looks at the same screen before scrolling
    SCROLL_TRIES = 3          # how far down the list to look
    TILE_TAP_LIMIT = 4        # taps on a palace tile that never led out of the Crest Palace screen

    def _keep_frame(self, tag: str, screen) -> str:
        """Save the screen to the debug folder (pruned like the others) and return ' A picture ... saved to X.' for a
        message; '' when it cannot be saved. Never raises."""
        try:
            path = self.save_frame(tag, screen)
        except Exception:  # noqa: BLE001
            return ""
        return f" A picture of the screen was saved to {path}." if path else ""

    def _check_plays_left(self, screen) -> None:
        """A palace with a daily limit says 'Times playable xN'. At x0 stop with a clear message instead of starting a run the
        game will refuse; otherwise just log how many are left. Anything not read clearly is ignored."""
        ocr = getattr(self, "ocr", None)
        if ocr is None:
            return
        try:
            left = times_playable(ocr, screen)
        except Exception:  # noqa: BLE001 - a reading problem must never stop a run
            return
        if left is None:
            return
        if left <= 0:
            self.notify("Crest: this palace has no plays left today ('Times playable x0'; it resets at 4:00 AM PST). "
                        "Stopped - nothing was started.")
            raise Finished("no plays left today")
        if self.__dict__.get("_plays_logged") != left:
            self.__dict__["_plays_logged"] = left
            self.log(f"Plays left today in this palace: {left} (it resets at 4:00 AM PST)")

    def _device(self):
        return getattr(getattr(self, "ctx", None), "device", None)

    def _look_for(self, screen, palace, path):
        """(x, y, how) of `palace` on `screen`, or None. `how` says whether the picture or the name found it."""
        best = 0.0
        picture = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR) if path else None
        if picture is not None:
            score, x, y, scale = find_tile(screen, picture)
            best = score
            if score >= MATCH_MIN:
                return x, y, f"picture {palace.image}, match {score:.2f} at {scale:.2f}x", score
        ocr = getattr(self, "ocr", None)
        if ocr is not None:
            words = ocr.screen_words(screen, min_conf=40)
            hit = textnav.find_name(words, palace.name, (300, 1000)) if words else None
            if hit is not None and hit.score >= 0.85:           # (nearly) every distinctive word of the name was read
                return hit.x, hit.y, f"name read from the screen ({', '.join(hit.matched)})", best
        return None

    def _warn_unknown_palaces(self, screen) -> None:
        """Say once, in the Log, when the Crest Palace screen shows a banner that matches none of the pictures in palaces.yaml
        (a new or limited-time palace). Informational only: it never stops, taps or changes anything, and any problem is ignored."""
        try:
            root = self._selector_root()
            pictures = []
            for p in palaces.read_list(root):
                path = palaces.image_path(root, p)
                img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR) if path.is_file() else None
                if img is not None:                                  # a palace whose picture is missing is simply skipped
                    pictures.append((p.name, img))
            seen = self.__dict__.setdefault("_unknown_seen", set())
            for y in unknown_banners(screen, pictures):
                if y // 150 not in seen:
                    seen.add(y // 150)
                    self.log(f"Palace selector: the Crest Palace screen shows a palace banner (at height {y}) that matches none of the "
                             "pictures in palaces.yaml. If it is a new palace, add a line and a picture for it so the selector can use it.")
        except Exception:  # noqa: BLE001 - a warning must never break a run
            return

    def _scroll_list(self, down: bool):
        """Swipe the Crest Palace list one page and return the new screen, or None when there is no device."""
        dev = self._device()
        if dev is None:
            return None
        a, b = (1000, 380) if down else (380, 1000)
        dev.swipe(360, a, 360, b, 700)
        self.sleep(1.2)
        return self.grab()

    def _scan_pages(self, screen, cand, warn: bool):
        """Look for one candidate: the picture, the name, a fresh look, then down the list a page at a time.
        Returns (found, pages scrolled). When found, the list is LEFT scrolled where the palace is, because the tap
        that follows must land on the screen the position came from."""
        scrolled, frame = 0, screen
        while True:
            for look in range(self.LOOK_AGAIN + 1):
                if look == 0 and warn:
                    self._warn_unknown_palaces(frame)
                found = self._look_for(frame, cand.palace, cand.path)
                if found:
                    how = found[2] + (f", after scrolling {scrolled} page(s)" if scrolled else "")
                    return (found[0], found[1], how, cand), scrolled
                if look < self.LOOK_AGAIN and self._device() is not None:
                    self.sleep(1.0)
                    frame = self.grab()
            if scrolled >= self.SCROLL_TRIES:
                return None, scrolled
            nxt = self._scroll_list(down=True)
            if nxt is None:
                return None, scrolled
            if frame.shape == nxt.shape and float(np.abs(frame.astype(np.int16) - nxt).mean()) < 2.0:
                return None, scrolled                              # the list did not move: that was the end of it
            scrolled += 1
            frame = nxt

    def _find_on_list(self, screen, candidates):
        """Today's palace first, all the way down the list; only when it is nowhere on the list, the next candidate (the
        schedule screen's day, in the hours the two clocks disagree). Returns (x, y, how, choice) or None. When it gives up
        the list is scrolled back to the top so the next try starts from a known place."""
        for i, cand in enumerate(candidates):
            found, scrolled = self._scan_pages(screen, cand, warn=(i == 0))
            if found:
                return found
            if self._device() is not None:
                for _ in range(scrolled):
                    self._scroll_list(down=False)
                if i + 1 < len(candidates):
                    screen = self.grab()
        return None
