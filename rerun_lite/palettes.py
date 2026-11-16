"""ReRun LITE's themes, as plain data (nothing imported, so the start-up window can use it before anything heavy loads).

"Dark" and "Light" are ReRun's own black and white themes and are not in here: rerun_lite/theme.py keeps them exactly as
the engine has them. Every theme below is a LITE theme of its own: a palette, the colours of the "LITE" tag, and the
looping video that plays behind the window (assets/<video>; tools/make_background.py draws them).

Palette keys are the ones the widget kit uses: bg, card, sep, label, secondary, tertiary, blue (the accent), green, red,
orange, gray, fill, field, bar, tab_off, viewer, alert, menu.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Look:
    key: str
    label: str
    dark: bool
    palette: dict
    mark: tuple[str, str]          # the "LITE" tag: background, text
    video: str                     # assets/<video>
    blurb: str = ""


def _p(bg, card, sep, label, secondary, tertiary, accent, green, red, orange, fill, field, bar, tab_off, viewer, menu):
    return {"bg": bg, "card": card, "sep": sep, "label": label, "secondary": secondary, "tertiary": tertiary,
            "blue": accent, "green": green, "red": red, "orange": orange, "gray": secondary, "fill": fill,
            "field": field, "bar": bar, "tab_off": tab_off, "viewer": viewer, "alert": menu, "menu": menu}


LOOKS: dict[str, Look] = {l.key: l for l in (
    Look("ahri", "Ahri", True,
         _p("#0B0919", "#17122B", "#2C2449", "#F7F1FB", "#A89DC6", "#51477A", "#F0609A", "#4FE3B2", "#FF6B81", "#FFC56B",
            "#241C3F", "#1E1737", "#0F0B21", "#8E82B0", "#07050F", "#1E1737"),
         ("#8FE9F0", "#052229"), "spirit_blossom.mp4", "Indigo night, blossom pink, spirit cyan"),
    Look("midnight", "Midnight", True,
         _p("#070B16", "#0F1830", "#1D2B4D", "#EAF2FF", "#8FA3C7", "#3D5380", "#2F7DE1", "#4FE3B2", "#FF6B81", "#FFC56B",
            "#16223F", "#121B35", "#0A1224", "#7D90B5", "#050810", "#121B35"),
         ("#7FD1FF", "#04223A"), "midnight.mp4", "Deep navy, drifting stars, shooting stars"),
    Look("sakura", "Sakura", False,
         _p("#FBF3F6", "#FFFFFF", "#EBD7DE", "#2B1B24", "#8A6F7B", "#D3BAC4", "#D6407F", "#13A06F", "#D93030", "#C77A0A",
            "#F6E4EB", "#F8EAEF", "#FFFFFF", "#9A8089", "#F1E2E8", "#FFFFFF"),
         ("#F4A6C0", "#4A1030"), "sakura.mp4", "A light theme: soft cream, falling blossom"),
    Look("ember", "Ember", True,
         _p("#120A08", "#211310", "#3A221B", "#FFF2E8", "#C9A08C", "#6B4A3D", "#E8590C", "#6FE08A", "#FF5A5A", "#FFC15A",
            "#2E1A14", "#27160F", "#160C09", "#A77F6C", "#0B0605", "#27160F"),
         ("#FFB066", "#3A1604"), "ember.mp4", "Charcoal and warm orange, rising embers"),
    Look("aurora", "Aurora", True,
         _p("#06100F", "#0E1E1D", "#1B3836", "#E9FFFA", "#8CC2BA", "#3C6B66", "#0E9F86", "#7BE38B", "#FF6B81", "#FFC56B",
            "#14302E", "#102624", "#08150F", "#78B0A8", "#040B0A", "#102624"),
         ("#7DF0D4", "#03241D"), "aurora.mp4", "Dark teal sky with slow green and violet lights"),
    Look("neon", "Neon", True,
         _p("#0A0612", "#150C26", "#2D1A4F", "#F3EAFF", "#A98FD6", "#4E3A7A", "#D6249F", "#3DF5B0", "#FF4D6D", "#FFC857",
            "#20123B", "#1A0F31", "#0D0819", "#8D75BD", "#06030C", "#1A0F31"),
         ("#27E1F5", "#032A30"), "neon.mp4", "Black, magenta and cyan, a scrolling grid"),
)}
DEFAULT = "ahri"
CLASSIC = {"dark": "Dark", "light": "Light", "auto": "Automatic"}


def labels() -> dict[str, str]:
    """key -> name, in the order the Theme setting lists them: the LITE themes, then ReRun's own."""
    return {**{k: v.label for k, v in LOOKS.items()}, **CLASSIC}


def splash_colors(key: str) -> dict:
    """The few colours the start-up window needs (it appears before the widget kit exists)."""
    look = LOOKS.get(key) or LOOKS[DEFAULT]
    p = look.palette
    return {"bg": p["bg"], "edge": p["sep"], "track": p["fill"], "fill": p["blue"], "text": p["label"],
            "muted": p["secondary"], "tag": look.mark[0], "tag_text": look.mark[1]}
