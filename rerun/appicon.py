"""Rerun's app icon (glossy blue rounded square with a glowing loop arrow), used for the
window, the tray and the .exe. It is loaded from assets/rerun_icon.png; if that file is
missing, a plain version is drawn in code instead."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ICON_PNG = Path(__file__).resolve().parent / "assets" / "rerun_icon.png"


def make_icon(size: int = 256) -> Image.Image:
    if ICON_PNG.exists():
        with Image.open(ICON_PNG) as im:
            return im.convert("RGBA").resize((size, size), Image.LANCZOS)
    return _drawn_icon(size)


def _drawn_icon(size: int) -> Image.Image:
    ss = 4
    S = size * ss
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(im)
    g.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.225), fill=(10, 132, 255, 255))
    # Loop arrow: a 300-degree ring plus an arrow head at its end.
    c, r, w = S / 2, S * 0.27, int(S * 0.085)
    g.arc((c - r, c - r, c + r, c + r), start=-60, end=240, fill="white", width=w)
    a = math.radians(-60)
    ex, ey = c + r * math.cos(a), c + r * math.sin(a)
    h = S * 0.13
    g.polygon([(ex + h * 0.85, ey - h * 0.15), (ex - h * 0.55, ey - h * 0.55), (ex - h * 0.1, ey + h * 0.75)],
              fill="white")
    return im.resize((size, size), Image.LANCZOS)


def write_ico(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    make_icon(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                     (128, 128), (256, 256)])
    return path
