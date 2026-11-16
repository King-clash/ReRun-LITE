"""Colour maths for the appearance system: OKLCH (a perceptually even colour space), contrast ratios, hex helpers.

Why OKLCH: a red and a yellow with the same lightness *look* equally light in it, so a palette built from one accent
colour comes out evenly balanced whatever accent the user picks (Linear's theme generator makes the same argument for
LCH). Nothing here needs more than the standard library.
"""
from __future__ import annotations

import math


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(v * 255))) for v in (r, g, b)))


def valid_hex(h: str) -> bool:
    try:
        hex_to_rgb(h)
        return len(h.strip().lstrip("#")) in (3, 6)
    except (ValueError, IndexError):
        return False


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def to_oklch(h: str) -> tuple[float, float, float]:
    """(lightness 0..1, chroma ~0..0.4, hue degrees) of a hex colour."""
    r, g, b = (_lin(v) for v in hex_to_rgb(h))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _oklch_to_rgb(L: float, C: float, hue: float) -> tuple[float, float, float]:
    a, b = C * math.cos(math.radians(hue)), C * math.sin(math.radians(hue))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def from_oklch(L: float, C: float, hue: float) -> str:
    """A hex colour; if the asked chroma is outside what a screen can show it is reduced until it fits."""
    L = max(0.0, min(1.0, L))
    c = max(0.0, C)
    for _ in range(40):
        r, g, b = _oklch_to_rgb(L, c, hue)
        if all(-0.0005 <= v <= 1.0005 for v in (r, g, b)):
            break
        c *= 0.92
    return rgb_to_hex(_gam(r), _gam(g), _gam(b))


def luminance(h: str) -> float:
    r, g, b = (_lin(v) for v in hex_to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio, 1 (none) to 21 (black on white)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, t: float) -> str:
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(*(x + (y - x) * t for x, y in zip(ra, rb)))


def readable_on(bg: str, light: str = "#FFFFFF", dark: str = "#0B0B0F", prefer_light: float = 3.6) -> str:
    """The text colour for a solid button of colour `bg`: white when that is readable enough for bold button text
    (the usual look), otherwise whichever of the two reads better."""
    if contrast(light, bg) >= prefer_light:
        return light
    return light if contrast(light, bg) >= contrast(dark, bg) else dark


def fit_lightness(color: str, bg: str, minimum: float, lo: float = 0.0, hi: float = 1.0) -> str:
    """Move `color`'s lightness (keeping hue and chroma) until it has at least `minimum` contrast against `bg`."""
    L, C, h = to_oklch(color)
    dark_bg = luminance(bg) < 0.4
    step = 0.01 if dark_bg else -0.01
    L = max(lo, min(hi, L))
    for _ in range(100):
        out = from_oklch(L, C, h)
        if contrast(out, bg) >= minimum or not (lo <= L + step <= hi):
            return out
        L += step
    return from_oklch(L, C, h)
