"""Reading the Units list grid and a unit's page (real 720x1280 captures, 2026-11-14).

Units list (header 'Units', template compendium_grid_header): a fixed 5-column
grid. Cards carry no readable text - portrait, element icon, star badge, 'Lv'
badge without a number - so names come from each unit's page.

Unit page (template compendium_detail_marker = 'Achievements'): element icon +
name on one line (white text over artwork), race on the right, and
'Quest cleared: N' at the bottom. The page shows no level.
Calibrated on tests/fixtures/units_grid_*.png and unit_profile_ira.png.
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from .ocr import BORDER

# --------------------------------------------------------------------------- grid
GRID_COLS = [64, 199, 335, 470, 605]   # x of each card's 'Lv' badge
ROW_PITCH = 121.8                       # px between card rows
GRID_TOP, GRID_BOTTOM = 330, 1070       # badge rows outside this are cut off by the frame
CARD_MIN_SCORE = 0.72                   # cards 0.79+, empty cells <= 0.27 on the fixtures
TAP_OFFSET = (30, -40)                  # badge -> card body


def _cell_score(gray: np.ndarray, tmpl_gray: list[np.ndarray], x: int, y: int) -> float:
    best = 0.0
    for t in tmpl_gray:
        th, tw = t.shape[:2]
        x0, y0 = x - tw // 2 - 8, y - th // 2 - 8
        win = gray[max(0, y0):y0 + th + 16, max(0, x0):x0 + tw + 16]
        if win.shape[0] >= th and win.shape[1] >= tw:
            best = max(best, float(cv2.minMaxLoc(cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED))[1]))
    return best


def grid_cards(screen: np.ndarray, vision) -> list[tuple[int, int]]:
    """Tap points of every card on the visible grid, top-left to bottom-right.
    Rows are anchored on confident 'Lv' badge matches, then every column of
    each row is checked on its own (template matching alone missed ~25%)."""
    names = [n for n in ("compendium_card_lv", "compendium_card_lv_rainbow") if vision.store.has(n)]
    anchors = sorted(m.center[1] for n in names for m in vision.find_all(screen, n)
                     if GRID_TOP <= m.center[1] <= GRID_BOTTOM)
    if not anchors:
        return []
    base = anchors[0]
    ys = set()
    k = -int((base - GRID_TOP) // ROW_PITCH)
    while True:
        y = round(base + k * ROW_PITCH)
        if y > GRID_BOTTOM:
            break
        if y >= GRID_TOP:
            ys.add(y)
        k += 1
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    tg = [cv2.cvtColor(vision.store.get(n), cv2.COLOR_BGR2GRAY) for n in names]
    out = []
    for y in sorted(ys):
        for x in GRID_COLS:
            if _cell_score(gray, tg, x, y) >= CARD_MIN_SCORE:
                out.append((x + TAP_OFFSET[0], y + TAP_OFFSET[1]))
    return out


# --------------------------------------------------------------------------- unit page
ICON_BOX = (64, 703, 32, 32)        # element icon, left of the name
CLEARED_BOX = (420, 1100, 280, 46)
# OpenCV hue (0-180) of the element icon, all seen on real captures (2026-11-14 scan):
# fire 8-9, light 16-21, earth 63, water 103-105, dark 131-133.
ELEMENTS = [("Fire", 0, 14, True), ("Light", 15, 32, True), ("Earth", 33, 85, True),
            ("Water", 86, 125, True), ("Dark", 126, 165, True), ("Fire", 166, 180, True)]
# A real icon is vivid and shaded: >=638 px with S>140, median S >= 207, brightness spread ~53.
# Plain parchment (a page with no icon, seen on a nameless unicorn) is flat: median S 180,
# spread 13. A page still fading in has a faint icon (251 px).
ICON_MIN_PX, ICON_MIN_SAT, ICON_MIN_V_SPREAD = 550, 195, 25
_CLEARED = re.compile(r"cleared\s*[:;.]?\s*([\d,]+)", re.I)


def white_text(img: np.ndarray, smax: int, vmin: int, scale: float = 3.0) -> np.ndarray:
    """Keep only near-white, unsaturated strokes: the game's white text over artwork."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 0, vmin), (180, smax, 255))
    m = cv2.resize(m, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(255 - m, BORDER, BORDER, BORDER, BORDER, cv2.BORDER_CONSTANT, value=255)


LINE_BOX = (100, 700, 515, 42)     # name ... race, one line (x 100-615)
RACE_MIN_X = 515                    # race word starts right of here (Human: 536-540)
RACE_GAP = 18                       # px gap between the name's end and the race word
SCALE = 3.0


def outlined_text(img: np.ndarray, vmin: int, smax: int, dark_v: int, reach: int) -> np.ndarray:
    """White strokes that touch the game's black text outline. Bright artwork (flames,
    sparkles) has no outline, so it drops out - seen live on Clyde's fiery page."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, vmin), (180, smax, 255))
    dark = cv2.inRange(hsv, (0, 0, 0), (180, 255, dark_v))
    m = cv2.bitwise_and(white, cv2.dilate(dark, np.ones((reach, reach), np.uint8)))
    for _ in range(3):  # grow back to the full stroke, staying inside the white
        m = cv2.bitwise_and(cv2.dilate(m, np.ones((3, 3), np.uint8)), white)
    m = cv2.resize(m, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(255 - m, BORDER, BORDER, BORDER, BORDER, cv2.BORDER_CONSTANT, value=255)


# (kind, args) - seven independent readings of the name line
_LINE_MASKS = [("white", (40, 170)), ("white", (40, 200)), ("white", (55, 170)),
               ("outline", (190, 50, 70, 5)), ("outline", (200, 45, 60, 5)),
               ("outline", (180, 60, 80, 7)), ("outline", (170, 55, 70, 5))]


def _clean(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9' ,.&:()!?-]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.:-'")
    return text


def _tidy(text: str) -> str:
    """Stray marks OCR puts between letters: 'the:Crimson' / 'Sword,God' -> spaces."""
    text = re.sub(r"(?<=[A-Za-z])[:;](?=[A-Za-z])", " ", text)
    text = re.sub(r",(?=[A-Za-z])", " ", text)   # a real comma is followed by a space
    return re.sub(r"\s+", " ", text).strip()


def _spelling_score(text: str) -> tuple:
    words = text.split()
    whole = sum(1 for w in words if len(w.strip(",.!?'")) >= 2 or w.lower() in ("a", "i"))
    fragments = len(words) - whole
    odd = len(re.findall(r"[^A-Za-z0-9 ,'&()-]", text))
    caps = sum(w[:1].isupper() for w in words)
    mid_caps = len(re.findall(r"[a-z][A-Z]", text))   # 'GaMagoori', 'SWord' are OCR noise
    return (-fragments, -odd, -mid_caps, caps, -len(words))


def _vote_key(text: str) -> str:
    """Compare readings ignoring case, punctuation and the I/l/1 confusion."""
    k = re.sub(r"[^a-z0-9]", "", text.lower())
    return k.translate(str.maketrans({"l": "i", "1": "i", "0": "o"}))


def read_line(ocr, screen: np.ndarray) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """All readings of the name line, split into (names, races) by word position."""
    x, y, w, h = LINE_BOX
    line = screen[y:y + h, x:x + w]
    names, races = [], []
    for kind, args in _LINE_MASKS:
        prep = white_text(line, *args) if kind == "white" else outlined_text(line, *args)
        words = [wd for wd in ocr._words(prep, 7, None) if re.search(r"[A-Za-z]", wd.text)]
        if not words:
            continue
        lefts = [x + (wd.x - BORDER) / SCALE for wd in words]
        rights = [x + (wd.x - BORDER + wd.w) / SCALE for wd in words]
        race_i = None
        if len(words) >= 2 and (lefts[-1] >= RACE_MIN_X or lefts[-1] - rights[-2] >= RACE_GAP):
            race_i = len(words) - 1
        name_words = words[:race_i] if race_i is not None else words
        if name_words:
            names.append((_clean(" ".join(wd.text for wd in name_words)),
                          sum(wd.conf for wd in name_words) / len(name_words)))
        if race_i is not None:
            races.append((_clean(words[race_i].text), words[race_i].conf))
    return [n for n in names if n[0]], [r for r in races if r[0]]


def _pick(reads: list[tuple[str, float]]) -> tuple[str, float, int]:
    """Most-agreed reading (by vote key); its best-confidence spelling."""
    if not reads:
        return "", 0.0, 0
    groups: dict[str, list[tuple[str, float]]] = {}
    for t, c in reads:
        groups.setdefault(_vote_key(t), []).append((t, c))
    best = max(groups.values(), key=lambda g: (len(g), max(c for _, c in g)))
    # The readings agree on the letters; pick the cleanest spelling of them:
    # whole words (not 'Clyd e ... Swo rd'), capitals ('Ira' not 'lra'), no stray marks.
    text = max((_tidy(t) for t, _ in best), key=_spelling_score)
    conf = max(c for _, c in best)
    votes = len(best)
    if votes < 2:
        conf = min(conf, 55.0)  # no two readings agree: keep it, but as uncertain
    return text, round(conf, 1), votes


def read_name(ocr, screen: np.ndarray) -> tuple[str, float, int]:
    """(name, confidence, number of agreeing readings out of 7)."""
    names, _ = read_line(ocr, screen)
    return _pick(names)


def read_element(screen: np.ndarray) -> tuple[str | None, float]:
    x, y, w, h = ICON_BOX
    hsv = cv2.cvtColor(screen[y:y + h, x:x + w], cv2.COLOR_BGR2HSV).reshape(-1, 3)
    px = hsv[(hsv[:, 1] > 140) & (hsv[:, 2] > 80)]
    if (len(px) < ICON_MIN_PX or float(np.median(px[:, 1])) < ICON_MIN_SAT
            or float(np.std(px[:, 2])) < ICON_MIN_V_SPREAD):
        return None, 0.0  # no icon (or not drawn yet)
    hue = float(np.median(px[:, 0]))
    for name, lo, hi, seen in ELEMENTS:
        if lo <= hue <= hi:
            return name, (90.0 if seen else 50.0)  # unseen colours stay 'uncertain'
    return None, 0.0


def read_profile(ocr, screen: np.ndarray) -> dict:
    """One observation for UnitRoster.apply_scan."""
    names, races = read_line(ocr, screen)
    name, name_conf, votes = _pick(names)
    element, el_conf = read_element(screen)
    race_text, race_conf, race_votes = _pick(races)
    race = type("R", (), {"confidence": race_conf if race_votes >= 2 else min(race_conf, 55.0)})
    cl = ocr.read_region(screen, *CLEARED_BOX)
    m = _CLEARED.search(cl.text or "")
    clears = int(m.group(1).replace(",", "")) if m else None
    fields = {
        "element": {"value": element, "confidence": el_conf},
        "race": {"value": race_text or None, "confidence": race.confidence},
        "quest_clears": {"value": clears, "confidence": cl.confidence if m else 0},
    }
    return {"name": name, "name_conf": name_conf, "name_votes": votes, "fields": fields}
