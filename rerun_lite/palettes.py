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
# ---- the 16 anime themes. Each is made from six colours (page, card, text, muted text, accent, second accent) that were
# checked for 4.5:1 contrast; the rest of the palette is mixed from them. The key is the anime's collection id, so choosing a
# theme can also pick that anime's artwork (rerun_lite/artwork.py). The looping video behind each is drawn by
# tools/make_anime_backgrounds.py.
def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _mix(a, b, t):
    x, y = _rgb(a), _rgb(b)
    return "#%02X%02X%02X" % tuple(round(x[i] + (y[i] - x[i]) * t) for i in range(3))


def _lum(h):
    c = [v / 255 for v in _rgb(h)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _on(h):
    """Black or white text, whichever reads better on `h`."""
    return "#101010" if (_lum(h) + 0.05) / (_lum("#101010") + 0.05) > 1.05 / (_lum(h) + 0.05) else "#FFFFFF"


def _anime(key, label, dark, bg, card, ink, muted, accent, accent2, blurb):
    ok = ("#4FE3B2", "#FF6B81", "#FFC56B") if dark else ("#13A06F", "#D93030", "#C77A0A")
    pal = _p(bg, card, _mix(bg, ink, 0.16), ink, muted, _mix(bg, ink, 0.38), accent, *ok,
             _mix(card, ink, 0.08), _mix(bg, card, 0.6), _mix(bg, card, 0.35), muted,
             _mix(bg, "#000000", 0.45) if dark else _mix(bg, ink, 0.08), card)
    return Look(key, label, dark, pal, (accent2, _on(accent2)), key + ".mp4", blurb)


ANIME = (
    ("jujutsu-kaisen", "Jujutsu Kaisen", True, "#0A0B14", "#12141F", "#F2F4FF", "#9AA3C7", "#6C8CFF", "#E5484D", "Cursed blue and red on ink black"),
    ("solo-leveling", "Solo Leveling", True, "#060A18", "#0C1430", "#E8F1FF", "#8FA6D0", "#3CA0FF", "#8B5CFF", "System blue, shadow violet"),
    ("naruto", "Naruto Akatsuki", True, "#0C0C0E", "#17171B", "#F3EDE4", "#A79F94", "#F2495C", "#D8C7A0", "Black cloak, red clouds, crows"),
    ("bleach", "Bleach", False, "#F4F4F1", "#FFFFFF", "#0A0A0A", "#5C5C58", "#0A0A0A", "#F26B1D", "Black ink on white, Soul Reaper orange"),
    ("evangelion", "Evangelion", True, "#050605", "#0D120D", "#E6FFE9", "#7FB58A", "#FF6A00", "#3DFF8E", "NERV terminal: orange hazard, phosphor green"),
    ("demon-slayer", "Demon Slayer", True, "#0F1411", "#17201B", "#F3EFE4", "#A9B5A8", "#2E9E6B", "#F29AB8", "Tanjiro's checks, water and flame"),
    ("one-piece", "One Piece", False, "#E9D9AE", "#F6ECCB", "#2B1B0E", "#6B5434", "#B8281F", "#1A6AA6", "Treasure-map parchment, sea blue"),
    ("attack-on-titan", "Attack on Titan", True, "#1A1F19", "#252C23", "#EDE8D8", "#A8AB98", "#8FB06A", "#C9B27C", "Survey Corps green and steel"),
    ("chainsaw-man", "Chainsaw Man", True, "#0B0B0B", "#161616", "#F5F1E8", "#A8A29A", "#FF3B1F", "#F5D547", "Blood red, halftone, torn paper"),
    ("frieren", "Frieren", False, "#F3EEF8", "#FFFFFF", "#2C2A3A", "#6B6880", "#6A58B5", "#C9A24B", "Soft lavender, flat petals, rune circles"),
    ("cowboy-bebop", "Cowboy Bebop", True, "#101010", "#1A1A1A", "#F4ECD8", "#B5AB92", "#F26B1F", "#2F63D9", "Blue Note panels, orange and blue"),
    ("tokyo-ghoul", "Tokyo Ghoul", True, "#0E0E10", "#18181B", "#ECECEC", "#9A9AA2", "#F25461", "#FFFFFF", "Black, kagune red, glass"),
    ("hunter-x-hunter", "Hunter x Hunter", False, "#F1EAD0", "#FBF6E4", "#1D2A1F", "#566452", "#1E7A46", "#C99A2E", "Hunter license green and gold"),
    ("initial-d", "Initial D", True, "#14161A", "#1E2127", "#F5F5F0", "#A6A9B0", "#FFD21F", "#E4262B", "Touge asphalt, yellow and red"),
    ("dragon-ball", "Dragon Ball", False, "#FFF1DA", "#FFFFFF", "#1C1B3A", "#5A5878", "#B85800", "#2D7BE5", "Bold outlines, orange gi, sky blue"),
    ("spy-x-family", "Spy x Family", False, "#EAF4EE", "#FFFFFF", "#26302B", "#5E6E65", "#B84A66", "#3E7F6B", "Cold-War dossier, Anya pink"),
)
for _a in ANIME:
    LOOKS[_a[0]] = _anime(*_a)
ANIME_KEYS = tuple(a[0] for a in ANIME)


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
