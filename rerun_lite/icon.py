"""ReRun LITE's icon: ReRun's own icon with a "LITE" strip, so the two apps can be told apart in the
taskbar and the tray. Drawn at run time from rerun/appicon.py's picture - no new image file."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from rerun.appicon import make_icon

_FONTS = ("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf", "arial.ttf")


def _font(height: int):
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, height)
        except OSError:
            continue
    return None


def make_lite_icon(size: int = 256) -> Image.Image:
    ss = 4 if size < 128 else 2                      # draw big, then shrink: smooth edges
    S = size * ss
    im = make_icon(S).copy()
    g = ImageDraw.Draw(im)
    top = int(S * 0.64)
    g.rounded_rectangle((int(S * 0.08), top, int(S * 0.92), int(S * 0.93)), radius=int(S * 0.11),
                        fill=(255, 255, 255, 245))
    font = _font(int(S * 0.215))
    if font is not None:
        box = g.textbbox((0, 0), "LITE", font=font)
        w, h = box[2] - box[0], box[3] - box[1]
        g.text(((S - w) / 2 - box[0], top + (int(S * 0.29) - h) / 2 - box[1]), "LITE", font=font,
               fill=(10, 96, 214, 255))
    return im.resize((size, size), Image.LANCZOS)


def write_lite_ico(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    make_lite_icon(256).save(path, sizes=[(s, s) for s in sizes])
    return path
