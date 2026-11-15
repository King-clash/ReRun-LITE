"""Reads on-screen text with Tesseract OCR - the engine ReStart itself uses.

No download is needed when ReStart is installed: it ships Tesseract 5 with
English data in %LOCALAPPDATA%\\ReStart\\bin, and Rerun uses that copy (or a
normal Tesseract install, or one set as 'tesseract_path' in config.yaml).

Game text is light on dark, outlined and over busy art, so every crop is
cleaned up first (enlarged, greyscale, made dark-on-light) and, like ReStart,
several clean-up variants are tried; the reading Tesseract is most confident
about wins.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Rerun's own folder: next to Rerun.exe, or the project folder when run from source
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parents[1]
CANDIDATES = [
    APP_DIR / "tesseract" / "tesseract.exe",   # bundled by `python build.py --release`
    Path(os.environ.get("LOCALAPPDATA", "")) / "ReStart" / "bin" / "tesseract.exe",
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    conf: float
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


BORDER = 12  # white margin added around every crop before reading


@dataclass
class Reading:
    text: str
    confidence: float  # 0-100, mean of the words Tesseract kept
    variant: str       # which clean-up produced it

    def __bool__(self) -> bool:
        return bool(self.text)


def find_tesseract(configured: str | None = None) -> tuple[Path, Path]:
    """(tesseract.exe, tessdata folder)."""
    cands = []
    if configured and configured != "auto":
        cands.append(Path(configured))
    cands += CANDIDATES
    which = shutil.which("tesseract")
    if which:
        cands.append(Path(which))
    for exe in cands:
        if exe.is_file():
            data = exe.parent / "tessdata"
            if (data / "eng.traineddata").is_file():
                return exe, data
    raise OcrUnavailable(
        "Text reading needs Tesseract OCR. Rerun uses its own copy (the tesseract folder "
        "next to Rerun.exe - copy it along if you moved Rerun.exe), else the one that comes with ReStart "
        "(%LOCALAPPDATA%\\ReStart\\bin) - run ReStart once so it unpacks - or install "
        "Tesseract and set 'tesseract_path' in config.yaml.")


# ------------------------------------------------------------------ clean-up
def _prepare(img: np.ndarray, variant: str, scale: float) -> np.ndarray:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if variant == "gray":
        out = gray
    elif variant == "otsu":
        _, out = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif variant == "bright":  # keep only near-white strokes (white game text)
        _, out = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
    else:
        raise ValueError(variant)
    # Tesseract reads dark text on a light page best.
    if np.mean(out) < 128:
        out = 255 - out
    return cv2.copyMakeBorder(out, BORDER, BORDER, BORDER, BORDER, cv2.BORDER_CONSTANT, value=255)


VARIANTS = ("otsu", "bright", "gray")


class Ocr:
    def __init__(self, configured: str | None = None):
        self.exe, self.tessdata = find_tesseract(configured)
        self._env = {**os.environ, "TESSDATA_PREFIX": str(self.tessdata)}

    def _run(self, img: np.ndarray, psm: int, whitelist: str | None) -> list[tuple[str, float]]:
        return [(w.text, w.conf) for w in self._words(img, psm, whitelist)]

    def _words(self, img: np.ndarray, psm: int, whitelist: str | None) -> list["Word"]:
        ok, png = cv2.imencode(".png", img)
        if not ok:
            return []
        cmd = [str(self.exe), "stdin", "stdout", "--psm", str(psm), "-l", "eng"]
        if whitelist:
            cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
        # Word-by-word output with confidences. (Set directly: ReStart's trimmed
        # tessdata has no 'configs/tsv' file for the usual `tsv` shortcut.)
        cmd += ["-c", "tessedit_create_tsv=1"]
        try:
            p = subprocess.run(cmd, input=png.tobytes(), capture_output=True, timeout=15,
                               env=self._env, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            return []
        words = []
        for line in p.stdout.decode("utf-8", errors="ignore").splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) == 12 and cols[11].strip():
                try:
                    conf = float(cols[10])
                    x, y, w, h = (int(c) for c in cols[6:10])
                except ValueError:
                    continue
                if conf >= 0:
                    words.append(Word(cols[11].strip(), conf, x, y, w, h))
        return words

    def screen_words(self, screen: np.ndarray, min_conf: float = 60.0) -> list["Word"]:
        """Words on a full screen with their positions in screen pixels."""
        s = 1.5
        found = self._words(_prepare(screen, "bright", s), 11, None)
        out = []
        for w in found:
            if w.conf < min_conf or len(w.text) < 2:
                continue
            out.append(Word(w.text, w.conf, int((w.x - BORDER) / s), int((w.y - BORDER) / s),
                            int(w.w / s), int(w.h / s)))
        return out

    def read(self, img: np.ndarray, line: bool = True, whitelist: str | None = None,
             scale: float = 3.0, variants=VARIANTS) -> Reading:
        """Text in `img` (a crop). line=True for one line, else a block."""
        if img is None or img.size == 0:
            return Reading("", 0.0, "")
        best = Reading("", 0.0, "")
        for v in variants:
            words = self._run(_prepare(img, v, scale), 7 if line else 6, whitelist)
            if not words:
                continue
            text = " ".join(w for w, _ in words)
            conf = sum(c for _, c in words) / len(words)
            if conf > best.confidence:
                best = Reading(text, conf, v)
            if conf >= 90:
                break  # clearly read - skip the slower variants
        return best

    def read_number(self, img: np.ndarray, **kw) -> int | None:
        r = self.read(img, whitelist="0123456789", **kw)
        digits = re.sub(r"\D", "", r.text)
        return int(digits) if digits else None

    def read_region(self, screen: np.ndarray, x: int, y: int, w: int, h: int, **kw) -> Reading:
        return self.read(screen[max(0, y):y + h, max(0, x):x + w], **kw)

    def screen_text(self, screen: np.ndarray, min_conf: float = 70.0) -> str:
        """Readable words anywhere on a full screen (for logs when a screen is
        unrecognised: the words usually say what the popup is)."""
        return " ".join(w.text for w in self.screen_words(screen, min_conf))

    def find_text(self, img: np.ndarray, needle: str) -> bool:
        """Whether `needle` appears (case/spacing-insensitive) in a block of text."""
        norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
        return norm(needle) in norm(self.read(img, line=False).text)


# The energy figure ("204/517", top bar) is in a stylised font: any single
# OCR setting misreads some values (a thin '1' dropped: 214 -> 24). Misreads
# differ between settings while the true value repeats, so several settings
# vote and a value counts only when at least two agree and it leads.
# Checked on 10 real screens: 10/10 right (best single setting: 9/10).
ENERGY_VOTERS = [  # (x, width, scale, clean-up) - y band 145..183
    (598, 120, 2.0, "otsu"), (598, 120, 3.0, "bright"), (598, 120, 2.0, "bright"),
    (590, 128, 3.0, "gray"), (598, 120, 3.0, "otsu"), (590, 128, 4.0, "otsu"),
]
_FRACTION = re.compile(r"(\d{1,4})/(\d{2,4})")


def read_energy(ocr: "Ocr", screen: np.ndarray) -> tuple[int, int] | None:
    """(current, maximum) energy from the top bar, or None if not sure."""
    from collections import Counter
    votes: Counter = Counter()
    for i, (x, w, scale, v) in enumerate(ENERGY_VOTERS):
        r = ocr.read(screen[145:183, x:x + w], whitelist="0123456789/", variants=(v,), scale=scale)
        m = _FRACTION.fullmatch(r.text.replace(" ", ""))
        if m:
            cur, mx = int(m.group(1)), int(m.group(2))
            if 20 <= mx <= 3000 and cur <= mx * 3:
                votes[(cur, mx)] += 1
        top = votes.most_common(2)
        if top and top[0][1] >= 2 and len(votes) == 1:
            return top[0][0]  # two agree, nothing against: done early
    top = votes.most_common(2)
    if top and top[0][1] >= 2 and (len(top) == 1 or top[0][1] > top[1][1]):
        return top[0][0]
    return None


def read_energy_cost(ocr: "Ocr", screen: np.ndarray) -> int | None:
    """'Energy Cost  N' on the party screen (None if not there/unreadable)."""
    n = ocr.read_number(screen[868:910, 500:610])
    return n if n is not None and 0 < n <= 200 else None


_shared: dict[str, Ocr] = {}


def get_ocr(configured: str | None = None) -> Ocr:
    """One shared reader (finding Tesseract is done once)."""
    key = configured or "auto"
    if key not in _shared:
        _shared[key] = Ocr(configured)
    return _shared[key]


# Top bar numbers (every normal screen shows it): gold, gems and Rank (= player level). The font is stylised, so,
# like energy, several settings vote and a value counts only when at least HEADER_MIN_VOTES agree and it leads.
# Checked on the 26 real screens in tests/fixtures that show the bar; a dimmed bar (a popup is open) is not read.
HEADER_REGIONS = {"gold": (462, 66, 140, 40), "gems": (640, 66, 75, 40), "player_level": (4, 146, 70, 34)}
HEADER_SETTINGS = [(v, s) for v in ("otsu", "bright", "gray") for s in (2.0, 3.0)]
HEADER_MIN_VOTES = 3


def header_visible(screen: np.ndarray) -> bool:
    """True when the top bar is shown at full brightness (not covered by a popup or the battle screen)."""
    if screen is None or screen.shape[0] < 120:
        return False
    gray = cv2.cvtColor(screen[60:110, 440:710], cv2.COLOR_BGR2GRAY)
    return bool(np.percentile(gray, 99) >= 215)


def read_header(ocr: "Ocr", screen: np.ndarray) -> dict[str, tuple[int, float]]:
    """{'gold'|'gems'|'player_level': (value, confidence)} for the numbers that were read with agreement.
    Missing keys mean 'not sure'; nothing is ever guessed."""
    from collections import Counter
    out: dict[str, tuple[int, float]] = {}
    if not header_visible(screen):
        return out
    for key, (x, y, w, h) in HEADER_REGIONS.items():
        votes: Counter = Counter()
        for variant, scale in HEADER_SETTINGS:
            n = ocr.read_number(screen[y:y + h, x:x + w], variants=(variant,), scale=scale)
            if n is not None:
                votes[n] += 1
        top = votes.most_common(2)
        if top and top[0][1] >= HEADER_MIN_VOTES and (len(top) == 1 or top[0][1] > top[1][1]):
            out[key] = (top[0][0], float(min(95, 70 + 5 * top[0][1])))
    return out
