"""Find things on a screen by the words written on them (palace names, quest titles).

Used as the fallback when no hand-captured picture matches, because palaces rotate and every
quest looks different. Works on the words Tesseract reads from a whole screen (ocr.Word), so the
logic here is plain Python and testable without an OCR engine.

Banner text is stylised and partly misread ("Shrine of Cursed Claw" comes out as "Shrine of Cursed"
and "Whirlwind" as "Whirl."), so matching is by the distinctive words with prefix/fuzzy tolerance
rather than by the whole phrase."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Words too common to identify a palace or quest on their own.
COMMON = {"of", "the", "a", "an", "and", "to", "in", "shrine", "temple", "tower", "palace"}
MIN_SCORE = 0.78
BAND_PX = 140          # words this close together vertically belong to the same banner
SCREEN_CENTER_X = 360


@dataclass
class NameHit:
    x: int
    y: int
    score: float
    matched: list[str]


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def distinctive(wanted: str) -> list[str]:
    toks = tokens(wanted)
    keep = [t for t in toks if t not in COMMON and len(t) >= 2]
    return keep or toks  # a name made only of common words: use all of it


def word_score(token: str, word: str) -> float:
    """How well one read word matches a wanted token (1.0 = same)."""
    w = "".join(tokens(word))
    if not w or not token:
        return 0.0
    if w == token:
        return 1.0
    if len(w) >= 4 and (token.startswith(w) or w.startswith(token)):
        return 0.85                      # "Whirl." for "whirlwind", cut-off banner words
    return SequenceMatcher(None, token, w).ratio()


def find_name(words, wanted: str, y_range: tuple[int, int] = (0, 1280),
              min_score: float = MIN_SCORE) -> NameHit | None:
    """Best place on screen whose words match `wanted`; None if nothing matches well enough.
    Returns the tap point (screen centre x, matched words' centre y)."""
    want = distinctive(wanted)
    if not want:
        return None
    hits = []   # (y, token, score, text)
    for w in words:
        cy = w.y + w.h // 2
        if not (y_range[0] <= cy <= y_range[1]) or w.h > 140:
            continue
        for t in want:
            s = word_score(t, w.text)
            if s >= min_score:
                hits.append((cy, t, s, w.text))
    if not hits:
        return None
    groups = []   # (total, matched tokens, y) for each banner-sized band that has hits
    for cy0, *_ in hits:
        group = [h for h in hits if abs(h[0] - cy0) <= BAND_PX]
        per_token = {}
        for _, t, s, _ in group:
            per_token[t] = max(per_token.get(t, 0.0), s)
        total = sum(per_token.values()) / len(want)      # share of the name found here
        ys = [h[0] for h in group]
        groups.append((total, sorted(per_token), sum(ys) // len(ys)))
    groups.sort(key=lambda g: -g[0])
    total, matched, y = groups[0]
    # Another band matches just as well (e.g. two palaces share a word): never guess.
    if any(abs(g[2] - y) > BAND_PX and g[0] >= total - 0.05 for g in groups[1:]):
        return None
    return NameHit(SCREEN_CENTER_X, y, round(total, 3), matched)


def quest_rows(words, y_min: int = 560) -> list[dict]:
    """Quest cards on a quest list: each card has a 'Rank Needed' label; its title sits just
    above it. Returns [{'y': tap y, 'title': text}] top to bottom."""
    anchors = sorted((w for w in words if "".join(tokens(w.text)) == "rank" and w.y > y_min),
                     key=lambda w: w.y)
    rows = []
    for a in anchors:
        title_words = [w for w in words if a.y - 85 <= w.y <= a.y - 35 and w.h < 40
                       and w.x < a.x]
        title = " ".join(w.text for w in sorted(title_words, key=lambda w: w.x))
        rows.append({"y": a.y - 55, "title": title})
    return rows


def sample_text(words, y0: int, y1: int, limit: int = 160) -> str:
    """The clearly read words between two heights, for 'here is what I can see' messages."""
    seen = [w.text for w in sorted(words, key=lambda w: (w.y // 40, w.x))
            if y0 <= w.y <= y1 and w.conf >= 85 and len(w.text) >= 3 and w.h < 140]
    return " ".join(seen)[:limit]


# ---- capture helper: where to draw the template box (720x1280 frame) --------------------------------
PALACE_TILE_BOX = (95, 530, 110)             # x, w, h; y is 50 px above the name text
QUEST_ROW_BOX = (36, 340, 34)               # x, w, h; y comes from the 'Rank Needed' anchor
HOME_BUTTON_BOX = (4, 1156, 112, 118)       # the bottom bar's Home button never moves
NON_TILE = ("crest_palace_icon", "crest_palace_icon2", "crest_palace_header")


def suggest_palace_tile(words, prefs: list[str] | None = None):
    """(x, y, w, h) around one palace banner's name (not its red 'time left' badge, which changes).
    The first of `prefs` that is on screen, else the topmost banner. None when no banner text is read."""
    cy = None
    for name in prefs or []:
        hit = find_name(words, name, (300, 1000))
        if hit:
            cy = hit.y
            break
    if cy is None:
        tall = sorted((w for w in words if 300 <= w.y <= 1000 and w.conf >= 80 and 30 <= w.h <= 140),
                      key=lambda w: w.y)
        if not tall:
            return None
        cy = tall[0].y + tall[0].h // 2
    return (PALACE_TILE_BOX[0], max(0, cy - 50), PALACE_TILE_BOX[1], PALACE_TILE_BOX[2])


def suggest_quest_row(words):
    """(x, y, w, h) around the first quest card's title row on a quest list; None if there is none."""
    rows = quest_rows(words)
    if not rows:
        return None
    return (QUEST_ROW_BOX[0], rows[0]["y"] - 15, QUEST_ROW_BOX[1], QUEST_ROW_BOX[2])


def suggest_crop(name: str, words, prefs: list[str] | None = None):
    """((x, y, w, h), explanation) for the template called `name`, or None when there is no rule for
    it. Coordinates are in the 720x1280 frame; the caller scales them to the screenshot."""
    if name == "home_nav_button":
        return HOME_BUTTON_BOX, "the bottom bar's Home button"
    if name.startswith("crest_palace_") and name not in NON_TILE:
        rect = suggest_palace_tile(words, prefs)
        if rect:
            return rect, "a palace banner (name only, without the changing 'time left' badge)"
    if name.startswith("quest_list_entry"):
        rect = suggest_quest_row(words)
        if rect:
            return rect, "the first quest's title row"
    return None
