"""The appearance model and the design tokens: one place that decides every colour and size in the window.

An `Appearance` is five small choices the user makes in Settings > Appearance:

    look        Plain (the default), Classic (ReRun's own black/white), or a themed look (Ahri, Midnight, ...)
    mode        System / Light / Dark   (Plain and Classic only; a themed look has its own)
    accent      one colour, from the presets or a colour picker ("" = the look's own)
    contrast    Standard / High
    density     Comfortable / Compact
    background  Auto (the look's own video) / Off / one of the built-in videos / your own file

`resolve()` turns that into a palette (the widget kit's colour table plus a few roles of our own: hover, select, ring,
on_accent) and a `Tokens` (corner radius, outlines, spacing scale). Nothing else in the program holds a colour.

How Plain is built (after Radix's 12-step roles and Linear's "base, accent, contrast" generator): tinted neutrals on a
fixed lightness ramp (app background, panel, control, hover, hairline, text) in OKLCH, with the accent hue mixed in at very
low chroma so the surfaces feel related to it without looking coloured. The accent itself is used only where it means
something: the primary action, selection, focus, toggles and links. It is nudged in lightness until it has enough
contrast on the surface it sits on, and the text on top of it is white or near-black, whichever reads better.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from . import palettes
from .colors import contrast, fit_lightness, from_oklch, mix, readable_on, to_oklch, valid_hex

ACCENTS = {                      # name -> colour. Chosen to sit evenly in lightness, not to be loud.
    "Azure": "#3E7BFA", "Violet": "#7C5CFC", "Rose": "#E2447F", "Amber": "#E59A10",
    "Green": "#2FA866", "Teal": "#14A89B", "Coral": "#EE6A4C", "Slate": "#6B7A90",
}
MODES = {"system": "System", "light": "Light", "dark": "Dark"}
CONTRASTS = {"standard": "Standard", "high": "High"}
DENSITIES = {"comfortable": "Comfortable", "compact": "Compact"}
DENSITY_SCALE = {"comfortable": 1.0, "compact": 0.88}
LOOKS = {"plain": "Plain", "classic": "Classic", **{k: v.label for k, v in palettes.LOOKS.items()}}
DEFAULT_LOOK = "plain"
BACKGROUNDS = {"auto": "Look's own", "off": "Off", **{k: v.label for k, v in palettes.LOOKS.items()}, "custom": "Your own video"}
# the two ReRun palettes that "Classic" keeps exactly as the engine has them (filled in by theme.py at import time)
CLASSIC: dict[str, dict] = {"dark": {}, "light": {}}


@dataclass(frozen=True)
class Appearance:
    look: str = DEFAULT_LOOK
    mode: str = "system"
    accent: str = ""
    contrast: str = "standard"
    density: str = "comfortable"
    background: str = "auto"
    custom_video: str = ""

    def clean(self) -> Appearance:
        """The same choices with anything unknown replaced by its default."""
        return Appearance(
            self.look if self.look in LOOKS else DEFAULT_LOOK, self.mode if self.mode in MODES else "system",
            self.accent if valid_hex(self.accent or "") else "", self.contrast if self.contrast in CONTRASTS else "standard",
            self.density if self.density in DENSITIES else "comfortable",
            self.background if self.background in BACKGROUNDS else "auto", str(self.custom_video or ""))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Tokens:
    radius: int            # corner radius of cards and fields, in px at 100%
    outline: bool          # a 1 px hairline round cards
    nav_pad: int           # vertical padding of a navigation tab
    edge: str = "sep"      # the hairline: "sep" (quiet), "strong" (firmer) or "accent" (tinted with the accent)


TOKENS = {"plain": Tokens(6, True, 7), "classic": Tokens(12, False, 12)}
THEMED_TOKENS = Tokens(10, True, 10)
# each themed look has its own shape, not just its own colours
LOOK_TOKENS = {"ahri": Tokens(12, True, 10), "midnight": Tokens(4, True, 8), "sakura": Tokens(14, True, 10),
               "ember": Tokens(6, True, 9, "strong"), "aurora": Tokens(10, True, 10), "neon": Tokens(2, True, 8, "accent")}
# the spacing ramp (px at 100%), after Fluent 2's 4 px base: use these, not loose numbers
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}


@dataclass(frozen=True)
class Resolved:
    appearance: Appearance
    palette: dict
    dark: bool
    tokens: Tokens
    ios_mode: str          # what to hand ios.init: "dark" or "light"
    video: str             # the built-in video file for this look/background ("" = none)

    @property
    def accent(self) -> str:
        return self.palette["blue"]


# ------------------------------------------------------------------------------------------------ palettes
def plain_palette(dark: bool, accent: str, high_contrast: bool = False) -> dict:
    """Tinted neutrals on a fixed OKLCH lightness ramp plus the accent."""
    hue = to_oklch(accent)[2]
    k = 1.0 if high_contrast else 0.0

    def n(light: float, chroma: float = 0.010) -> str:
        return from_oklch(light, chroma, hue)
    if dark:
        p = {"bg": n(0.165), "card": n(0.205), "field": n(0.225), "fill": n(0.250), "hover": n(0.290), "sep": n(0.300 + 0.04 * k),
             "bar": n(0.145), "viewer": n(0.125), "menu": n(0.235), "alert": n(0.235), "tertiary": n(0.46 + 0.04 * k, 0.012),
             "secondary": n(0.72 + 0.05 * k, 0.012), "label": n(0.95 + 0.04 * k, 0.006), "tab_off": n(0.64 + 0.06 * k, 0.012)}
        green, red, orange = from_oklch(0.78, 0.16, 152), from_oklch(0.72, 0.17, 22), from_oklch(0.82, 0.14, 78)
    else:
        p = {"bg": n(0.968, 0.006), "card": "#FFFFFF", "field": n(0.955, 0.006), "fill": n(0.935, 0.008), "hover": n(0.91, 0.010),
             "sep": n(0.885 - 0.07 * k, 0.008), "bar": "#FFFFFF", "viewer": n(0.93, 0.008), "menu": "#FFFFFF", "alert": "#FFFFFF",
             "tertiary": n(0.74 - 0.12 * k, 0.010), "secondary": n(0.46 - 0.10 * k, 0.012), "label": n(0.22 - 0.12 * k, 0.010),
             "tab_off": n(0.50 - 0.08 * k, 0.012)}
        green, red, orange = from_oklch(0.56, 0.15, 152), from_oklch(0.56, 0.20, 26), from_oklch(0.62, 0.15, 68)
    p.update({"green": green, "red": red, "orange": orange, "gray": p["secondary"], "blue": accent})
    return p


def apply_accent(palette: dict, accent: str, tidy: bool = True) -> dict:
    """The palette with `accent` as its accent colour, plus the roles built from it: hover, select, ring, on_accent.
    An accent that already reads on the panel colour is kept exactly; one that does not is nudged in lightness."""
    p = dict(palette)
    card = p["card"]
    dark = to_oklch(p["bg"])[0] < 0.5
    lo, hi = (0.56, 0.88) if dark else (0.28, 0.64)
    solid = accent if contrast(accent, card) >= 3.2 else fit_lightness(accent, card, 3.2, lo, hi)
    # The accent is used as text (links) and as a button fill with text on it: both should reach 4.5:1 when a lightness
    # exists that allows it. In a dark look that means a lighter accent with dark text; in a light one, a deeper accent.
    if tidy and (contrast(solid, card) < 4.5 or contrast(readable_on(solid), solid) < 4.5):
        L, C, h = to_oklch(solid)
        step = 0.01 if dark else -0.01
        while lo <= L <= hi:
            cand = from_oklch(L, C, h)
            if contrast(cand, card) >= 4.5 and contrast(readable_on(cand), cand) >= 4.5:
                solid = cand
                break
            L += step
    p["blue"] = solid
    p["on_accent"] = readable_on(solid)
    p["accent_hover"] = mix(solid, "#FFFFFF" if dark else "#000000", 0.12)
    for m in (0.20 if dark else 0.12, 0.15, 0.11, 0.08, 0.05):         # the selected row: as much tint as still lets the accent text read
        p["select"] = mix(card, solid, m)
        if not tidy or contrast(solid, p["select"]) >= 4.5:
            break
    # Grey text and status colours keep to readable contrast whatever a look chose.
    for key, need in ((("secondary", 4.5), ("tertiary", 3.0), ("green", 4.0), ("red", 4.0), ("orange", 4.0)) if tidy else ()):
        if contrast(p[key], card) < need or contrast(p[key], p["bg"]) < need:
            worse = min((card, p["bg"]), key=lambda c_: contrast(p[key], c_))
            p[key] = fit_lightness(p[key], worse, need)
    if tidy:
        p["gray"] = p["secondary"]
    p["ring"] = solid
    p.setdefault("hover", mix(p["fill"], p["label"], 0.06))
    return p


def resolve(a: Appearance, system_dark: bool = True) -> Resolved:
    """Every colour and size for these choices."""
    a = a.clean()
    look = palettes.LOOKS.get(a.look)
    if look is not None:                                         # a themed look: its own colours and its own mode
        dark, base, tokens, default_video = look.dark, dict(look.palette), LOOK_TOKENS.get(look.key, THEMED_TOKENS), look.video
        accent = a.accent or base["blue"]
    else:
        dark = system_dark if a.mode == "system" else a.mode == "dark"
        tokens, default_video = TOKENS[a.look], ""
        accent = a.accent or (ACCENTS["Azure"] if a.look == "plain" else CLASSIC[("dark" if dark else "light")]["blue"])
        base = (plain_palette(dark, accent, a.contrast == "high") if a.look == "plain"
                else dict(CLASSIC["dark" if dark else "light"]))
    palette = apply_accent(base, accent, tidy=not (a.look == "classic" and not a.accent))   # Classic stays exactly ReRun's
    video = {"auto": default_video, "off": "", "custom": ""}.get(a.background)
    if video is None:                                            # the video of one of the themed looks, by name
        video = palettes.LOOKS[a.background].video
    return Resolved(a, palette, dark, tokens, "dark" if dark else "light", video)


def system_dark() -> bool:
    """Whether Windows is set to dark app mode (Light when it cannot tell)."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def splash_colors(a: Appearance) -> dict:
    """The few colours the start-up window needs (it appears before the widget kit exists)."""
    r = resolve(a, system_dark())
    p = r.palette
    look = palettes.LOOKS.get(r.appearance.look)
    tag = look.mark if look else (p["blue"], p["on_accent"])
    return {"bg": p["bg"], "edge": p["sep"], "track": p["fill"], "fill": p["blue"], "text": p["label"],
            "muted": p["secondary"], "tag": tag[0], "tag_text": tag[1]}


# ------------------------------------------------------------------------------------------------ saved in ui.json
LEGACY_THEMES = {                # the single "theme" choice of 1.0.x -> the new model
    "ahri": Appearance("ahri"), "midnight": Appearance("midnight"), "sakura": Appearance("sakura"),
    "ember": Appearance("ember"), "aurora": Appearance("aurora"), "neon": Appearance("neon"),
    "dark": Appearance("classic", "dark"), "light": Appearance("classic", "light"), "auto": Appearance("classic", "system"),
}


def from_ui(ui: dict) -> Appearance:
    """The saved choices (data/lite/ui.json). Older files that only have "theme" are carried over."""
    raw = ui.get("appearance")
    if isinstance(raw, dict):
        known = {f: raw[f] for f in Appearance.__dataclass_fields__ if f in raw}
        return Appearance(**known).clean()
    legacy = LEGACY_THEMES.get(str(ui.get("theme") or ""))
    if legacy is not None:                                       # 1.0.x kept one "theme" plus a few video settings
        own = next((ui[k] for k in ("bg_path_ahri", "bg_path") if ui.get(k)), "")
        background = "off" if ui.get("bg_on") is False else ("custom" if own else "auto")
        return replace(legacy, background=background, custom_video=str(own)).clean()
    return Appearance().clean()
