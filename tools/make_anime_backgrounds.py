"""Draw the 16 anime themes' looping background videos: assets/<anime-id>.mp4.

    py tools/make_anime_backgrounds.py                  all of them
    py tools/make_anime_backgrounds.py bleach dragon-ball

Original animation drawn here with numpy and OpenCV: no artwork from any show, game or website. The look follows what
animators call hand-drawn VFX, not smooth motion graphics: hard edges, thick outlines, no blur and no easing, and every
motion is animated "on twos" (a new drawing every second frame) or "on threes". Each loop is 8 seconds at 24 fps and is
seamless: every motion repeats a whole number of times per loop. They sit behind the app window, so the shapes are bold
but the values stay close to the theme's page colour; text and numbers on top stay readable.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

W, H = 640, 360                      # drawn small and shown at 2x with hard pixels
OUT_W, OUT_H, FPS, SECONDS = 1280, 720, 24, 8
N = FPS * SECONDS
ASSETS = Path(__file__).resolve().parents[1] / "assets"


def rgb(h: str):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))          # BGR for OpenCV


def mix(a: str, b: str, t: float):
    x, y = rgb(a), rgb(b)
    return tuple(int(x[i] + (y[i] - x[i]) * t) for i in range(3))


def step(t: float, k: int = 2) -> float:
    """Quantise loop time so the picture only changes every k-th frame."""
    return (int(t * N) // k * k) / N


def poly(c, pts, col, outline=None, w=2):
    p = np.array(pts, np.int32)
    cv2.fillPoly(c, [p], col)
    if outline is not None:
        cv2.polylines(c, [p], True, outline, w, cv2.LINE_8)


def diamond(c, x, y, s, col, outline=None):
    poly(c, [(x, y - s * 1.5), (x + s, y), (x, y + s * 1.5), (x - s, y)], col, outline, 1)


def flame(c, x, y, s, col, inner=None, lean=0.0):
    """A cel flame tongue: a teardrop that leans, with an inner tongue."""
    pts = [(x - s * .5, y), (x - s * .6 + lean, y - s * .9), (x - s * .15 + lean * 1.4, y - s * 1.5), (x + lean * 2, y - s * 2.4),
           (x + s * .2 + lean * 1.2, y - s * 1.4), (x + s * .62 + lean * .6, y - s * .8), (x + s * .5, y)]
    poly(c, pts, col, rgb("#000000"), 2)
    if inner is not None:
        poly(c, [(x - s * .25, y), (x - s * .25 + lean * .8, y - s * .6), (x + lean * 1.4, y - s * 1.3), (x + s * .3 + lean * .5, y - s * .6),
                 (x + s * .25, y)], inner)


def bolt(c, x0, y0, x1, y1, rng, col, w=3, edge=None):
    """Lightning: a jagged polyline whose shape holds for a few frames, then jumps (the caller reseeds it)."""
    n = 7
    pts = [(x0, y0)]
    for i in range(1, n):
        t = i / n
        off = rng.uniform(-22, 22)
        pts.append((x0 + (x1 - x0) * t + off, y0 + (y1 - y0) * t + rng.uniform(-6, 6)))
    pts.append((x1, y1))
    p = np.array(pts, np.int32)
    if edge is not None:
        cv2.polylines(c, [p], False, edge, w + 4, cv2.LINE_8)
    cv2.polylines(c, [p], False, col, w, cv2.LINE_8)


def crow(c, x, y, s, col, pose):
    """A flapping silhouette: two wing poses."""
    up = pose % 2 == 0
    wy = -s * 1.1 if up else s * .7
    poly(c, [(x - s * 2, y + wy), (x - s * .9, y - s * .1), (x, y + s * .2), (x + s * .9, y - s * .1), (x + s * 2, y + wy),
             (x + s * .9, y + s * .55), (x, y + s * .9), (x - s * .9, y + s * .55)], col)
    cv2.circle(c, (int(x + s * 1.0), int(y + s * .1)), int(max(2, s * .35)), col, -1)


def hexagon(c, x, y, r, col, w=2, fill=False):
    pts = np.array([(x + r * math.cos(math.pi / 3 * i), y + r * math.sin(math.pi / 3 * i)) for i in range(6)], np.int32)
    cv2.fillPoly(c, [pts], col) if fill else cv2.polylines(c, [pts], True, col, w, cv2.LINE_8)


def star4(c, x, y, s, col):
    poly(c, [(x, y - s * 1.6), (x + s * .3, y - s * .3), (x + s * 1.6, y), (x + s * .3, y + s * .3), (x, y + s * 1.6),
             (x - s * .3, y + s * .3), (x - s * 1.6, y), (x - s * .3, y - s * .3)], col)


def petal(c, x, y, s, col, ang):
    cv2.ellipse(c, (int(x), int(y)), (int(s * 1.6), int(s * .8)), ang, 0, 360, col, -1, cv2.LINE_8)


def puff(c, x, y, s, fill, line):
    """A cartoon smoke puff: overlapping discs with a hard outline."""
    for dx, dy, r in ((0, 0, s), (-s * .8, s * .3, s * .7), (s * .8, s * .25, s * .75), (s * .1, -s * .6, s * .6)):
        cv2.circle(c, (int(x + dx), int(y + dy)), int(r), line, -1)
    for dx, dy, r in ((0, 0, s), (-s * .8, s * .3, s * .7), (s * .8, s * .25, s * .75), (s * .1, -s * .6, s * .6)):
        cv2.circle(c, (int(x + dx), int(y + dy)), max(1, int(r - 2)), fill, -1)


def streaks(c, rng_seed, count, angle, col, t, cycles=1, length=(80, 220), width=(1, 3)):
    rng = np.random.RandomState(rng_seed)
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    span = W + H
    for _ in range(count):
        ph, ln, wd = rng.rand(), rng.uniform(*length), int(rng.uniform(*width))
        ry, rx = rng.uniform(-H * .4, H * 1.2), rng.uniform(-W * .2, W * .6)
        pos = ((ph + t * cycles) % 1.0) * (span + 2 * ln) - ln
        x = rx + ca * pos
        y = ry + sa * pos
        cv2.line(c, (int(x), int(y)), (int(x + ca * ln), int(y + sa * ln)), col, wd, cv2.LINE_8)


def halftone(c, col, step_px, tilt, region, big=5.0):
    x0, y0, x1, y1 = region
    for j, y in enumerate(range(y0, y1, step_px)):
        for i, x in enumerate(range(x0, x1, step_px)):
            px = x + (step_px // 2 if j % 2 else 0)
            k = max(0.0, 1 - math.hypot(px - x0, y - y0) / math.hypot(x1 - x0, y1 - y0) * tilt)
            r = big * k
            if r >= 1:
                cv2.circle(c, (px, y), int(r), col, -1)


def rise(c, seed, count, t, cycles, draw, drift=30):
    rng = np.random.RandomState(seed)
    for _ in range(count):
        x0, ph, sz, c2 = rng.uniform(0, W), rng.rand(), rng.uniform(.6, 1.4), rng.randint(1, 3)
        y = H + 20 - ((ph + t * cycles * c2 / 2) % 1.0) * (H + 40)
        x = x0 + drift * math.sin(2 * math.pi * (ph + t * cycles))
        draw(c, x, y, sz, int((ph + t * cycles) * 8))


def fall(c, seed, count, t, draw, cycles=1, sway=30):
    rng = np.random.RandomState(seed)
    for _ in range(count):
        x0, ph, sz = rng.uniform(0, W), rng.rand(), rng.uniform(.6, 1.4)
        y = ((ph + t * cycles) % 1.0) * (H + 40) - 20
        x = x0 + sway * math.sin(2 * math.pi * (ph * 3 + t * cycles))
        draw(c, x, y, sz, int((ph + t) * 6))


def seigaiha(c, y0, col, line, rows, shift):
    r = 26
    for row in range(rows):
        for x in range(-r * 2, W + r * 2, r * 2):
            cx = x + (r if row % 2 else 0) + shift
            cy = y0 + row * r // 2 * 1
            for k, rr in enumerate((r, int(r * .72), int(r * .44))):
                cv2.circle(c, (cx, cy), rr, line if k % 2 == 0 else col, -1 if k % 2 == 0 else -1)
            cv2.circle(c, (cx, cy), r, line, 1)


def scanlines(c, col, gap=4, alpha=.35):
    o = c.copy()
    o[::gap] = col
    cv2.addWeighted(o, alpha, c, 1 - alpha, 0, c)


def grain(c, seed, amount=10):
    rng = np.random.RandomState(seed)
    c[:] = np.clip(c.astype(np.int16) + rng.randint(-amount, amount + 1, (H, W, 1)), 0, 255).astype(np.uint8)


def base(col_a, col_b=None, angle=0):
    if col_b is None:
        return np.full((H, W, 3), rgb(col_a), np.uint8)
    a, b = np.array(rgb(col_a), np.float32), np.array(rgb(col_b), np.float32)
    t = (np.linspace(0, 1, H)[:, None] * math.cos(math.radians(angle)) + np.linspace(0, 1, W)[None] * math.sin(math.radians(angle)))
    t = np.clip(t, 0, 1)[..., None]
    return (a + (b - a) * t).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------- the 16 scenes
def s_jjk():
    def f(t):
        ts = step(t); c = base("#0A0B14", "#10143A", 120)
        streaks(c, 1, 26, 24, rgb("#2B44C8"), step(t, 3), 2, (120, 300), (2, 6))
        streaks(c, 2, 12, 24, rgb("#B02A3A"), step(t, 3), 3, (100, 260), (2, 5))
        k = int(ts * N) // 8
        rng = np.random.RandomState(100 + k)
        if (k % 3) != 2:                                         # cursed lightning appears and disappears
            bolt(c, rng.uniform(380, 600), -10, rng.uniform(300, 600), H * .7, rng, rgb("#0A0B14"), 3, rgb("#E5484D"))
        for i in range(6):                                       # tumbling shards
            x = (i * 131 + ts * 5 * 120) % (W + 60) - 30
            y = (i * 73 + ts * 3 * 90) % (H + 40) - 20
            poly(c, [(x, y), (x + 14, y + 4), (x + 6, y + 20)], rgb("#243696"), rgb("#6C8CFF"), 1)
        return c
    return f


def s_sl():
    def f(t):
        ts = step(t); c = base("#060A18", "#0C1A44", 160)
        for x in range(0, W, 40):
            cv2.line(c, (x, 0), (x, H), rgb("#0E1D45"), 1)
        for y in range(0, H, 40):
            cv2.line(c, (0, y), (W, y), rgb("#0E1D45"), 1)
        y0 = int(40 + (ts * 2 % 1) * 40) % 40                     # grid scans downward on twos
        cv2.line(c, (0, y0 + 40 * int(ts * 8 % 8)), (W, y0 + 40 * int(ts * 8 % 8)), rgb("#3CA0FF"), 2)
        rise(c, 5, 16, step(t, 3), 1, lambda cc, x, y, s, k: flame(cc, x, y, 16 * s, rgb("#5B2FD1"), rgb("#8B5CFF"), (-3, 0, 3, 0)[k % 4]), 20)
        rise(c, 6, 14, step(t, 2), 2, lambda cc, x, y, s, k: diamond(cc, x, y, 3 * s, rgb("#FF9A3C")))
        return c
    return f


def s_nar():
    def f(t):
        ts = step(t, 3); c = base("#0C0C0E", "#2A0A10", 100)
        for i in range(5):                                        # red clouds drift on threes
            x = (i * 190 + ts * 160) % (W + 160) - 80; y = 60 + (i * 77) % 260
            for dx, dy, r in ((0, 0, 24), (-22, 8, 17), (22, 6, 18), (4, -18, 15)):
                cv2.circle(c, (int(x + dx), int(y + dy)), r, rgb("#B5192B"), -1)
                cv2.circle(c, (int(x + dx), int(y + dy)), r, rgb("#F3EDE4"), 1)
        for i in range(7):                                        # crows fly across on twos
            x = (i * 120 + step(t) * 2 * (W + 100)) % (W + 100) - 50; y = 40 + (i * 53) % 240 + 10 * math.sin(step(t) * 12 + i)
            crow(c, x, y, 9 + i % 3 * 3, rgb("#060606"), int(step(t) * N / 3) + i)
        return c
    return f


def s_ble():
    def f(t):
        ts = step(t); c = base("#F4F4F1")
        streaks(c, 7, 22, 20, rgb("#0A0A0A"), step(t, 3), 1, (160, 380), (2, 8))
        k = int(ts * N) // 6
        rng = np.random.RandomState(40 + k)
        cx, cy, r = rng.uniform(260, 460), rng.uniform(120, 240), rng.uniform(90, 170)   # a black crescent slash that changes shape
        a0 = rng.uniform(-40, 10)
        pts = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in np.linspace(a0, a0 + 130, 12)]
        pts2 = [(cx + (r - 22) * math.cos(math.radians(a)) + 10, cy + (r - 22) * math.sin(math.radians(a)) + 8) for a in np.linspace(a0 + 120, a0 + 10, 10)]
        poly(c, pts + pts2, rgb("#0A0A0A"))
        for i in range(9):
            x = (i * 91 + ts * 120) % W; y = (i * 47) % H
            cv2.circle(c, (int(x), int(y)), 3 + i % 3, rgb("#F26B1D") if i % 4 == 0 else rgb("#0A0A0A"), -1)
        return c
    return f


def s_eva():
    def f(t):
        ts = step(t); c = base("#050605")
        for x in range(-40, W + 40, 40):                           # hazard stripes crawl along the top and bottom
            for yy in (0, H - 18):
                o = (x + int(ts * 8 * 40)) % (W + 80) - 40
                poly(c, [(o, yy), (o + 20, yy), (o + 8, yy + 18), (o - 12, yy + 18)], rgb("#FF6A00"))
        for gx in range(0, W, 32):
            cv2.line(c, (gx, 0), (gx, H), rgb("#0C2112"), 1)
        for gy in range(0, H, 32):
            cv2.line(c, (0, gy), (W, gy), rgb("#0C2112"), 1)
        on = int(ts * N) // 12 % 2 == 0                            # hard on/off blink
        for (x, y, r) in ((140, 130, 34), (500, 220, 50), (330, 90, 22)):
            hexagon(c, x, y, r, rgb("#3DFF8E") if on else rgb("#1A5C36"), 2)
        r = 20 + int((ts * 2 % 1) * 150)
        hexagon(c, 320, 180, r, rgb("#FF6A00"), 3)
        scanlines(c, (0, 0, 0))
        return c
    return f


def s_dem():
    def f(t):
        ts = step(t, 3); c = base("#0F1411", "#10281C", 90)
        for i in range(0, W + 40, 20):                              # low checkered band, moving on threes
            for j in range(3):
                col = rgb("#2E9E6B") if (i // 20 + j) % 2 == 0 else rgb("#0A0F0C")
                x = (i + int(ts * 2 * W)) % (W + 40) - 20
                cv2.rectangle(c, (x, H - 60 + j * 20), (x + 20, H - 40 + j * 20), col, -1)
        for k in range(3):                                         # water-breathing waves: white crest over blue body
            x0 = (k * 240 + ts * W) % (W + 240) - 120; y0 = 190 + k * 36
            pts = [(x0 + a, y0 - 40 * math.sin(math.pi * a / 200) ** 2 * (1 - a / 260)) for a in range(0, 200, 10)]
            poly(c, pts + [(x0 + 190, y0 + 60), (x0, y0 + 60)], rgb("#1B5E8A"), rgb("#F3EFE4"), 2)
        rise(c, 9, 18, step(t, 2), 1, lambda cc, x, y, s, k: diamond(cc, x, y, 2.5 * s, rgb("#F29AB8") if k % 2 else rgb("#FF8A2B")), 24)
        return c
    return f


def s_op():
    def f(t):
        ts = step(t, 3); c = base("#E9D9AE", "#DCC58C", 160)
        for x in range(0, W, 44):                                   # dotted treasure-map route
            cv2.circle(c, (x, 90 + int(28 * math.sin(x / 70))), 3, rgb("#7A5A2E"), -1)
        cv2.line(c, (300, 160), (340, 200), rgb("#B8281F"), 4); cv2.line(c, (340, 160), (300, 200), rgb("#B8281F"), 4)   # X marks the spot
        for k in range(3):
            seigaiha(c, H - 70 + k * 26, rgb("#1A6AA6"), rgb("#EAF4FF"), 2, int(ts * (k + 1) * 52) % 52 - 26)
        fall(c, 11, 8, step(t, 3), lambda cc, x, y, s, k: star4(cc, x, y, 3 * s, rgb("#B8281F")), 1, 12)
        return c
    return f


def s_aot():
    def f(t):
        ts = step(t, 3); c = base("#1A1F19", "#2C3426", 130)
        for x in range(0, W, 120):                                  # the Wall: heavy blocks
            cv2.rectangle(c, (x, H - 90), (x + 118, H), rgb("#242B22"), -1)
            cv2.rectangle(c, (x, H - 90), (x + 118, H), rgb("#0E120D"), 2)
        rise(c, 12, 10, ts, 1, lambda cc, x, y, s, k: puff(cc, x, y, 16 * s, rgb("#D9D6C6"), rgb("#0E120D")), 40)   # ODM steam
        rng = np.random.RandomState(int(ts * N) // 6)
        for i in range(5):
            x, y = rng.uniform(0, W), rng.uniform(0, H)
            poly(c, [(x, y), (x + 9, y + 2), (x + 3, y + 12)], rgb("#8FB06A"), rgb("#0E120D"), 1)
        return c
    return f


def s_csm():
    def f(t):
        ts = step(t); c = base("#0B0B0B", "#1A0807", 140)
        halftone(c, rgb("#FF3B1F"), 10, 1.0, (0, 0, 300, 200), 5.0)
        k = int(ts * N) // 4
        rng = np.random.RandomState(70 + k)
        for _ in range(2):                                          # red slashes: clean crescents that jump
            cx, cy, r, a0 = rng.uniform(300, 600), rng.uniform(140, 300), rng.uniform(100, 200), rng.uniform(-30, 20)
            pts = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in np.linspace(a0, a0 + 110, 10)]
            pts2 = [(cx + (r - 14) * math.cos(math.radians(a)) + 6, cy + (r - 14) * math.sin(math.radians(a)) + 5) for a in np.linspace(a0 + 100, a0 + 8, 8)]
            poly(c, pts + pts2, rgb("#FF3B1F"))
        cx, cy, r = 540, 90, 36                                      # chainsaw ring, spinning on twos
        cv2.circle(c, (cx, cy), r, rgb("#F5F1E8"), 2)
        for i in range(12):
            a = math.radians(i * 30 + int(ts * 8 * 30) * 1)
            cv2.line(c, (int(cx + (r - 2) * math.cos(a)), int(cy + (r - 2) * math.sin(a))), (int(cx + (r + 8) * math.cos(a)), int(cy + (r + 8) * math.sin(a))), rgb("#F5D547"), 3)
        grain(c, int(ts * N) // 12, 5)
        return c
    return f


def s_fri():
    def f(t):
        ts = step(t, 3); c = base("#F3EEF8", "#E0D8F2", 150)
        cx, cy = 480, 170                                            # a rune circle drawn in segments, turning on threes
        a0 = int(ts * N / 3) * 6
        for rr, n in ((120, 18), (92, 12), (64, 8)):
            for i in range(n):
                s = math.radians(a0 * (1 if rr != 92 else -1) + i * 360 / n)
                cv2.line(c, (int(cx + rr * math.cos(s)), int(cy + rr * math.sin(s))), (int(cx + rr * math.cos(s + .12)), int(cy + rr * math.sin(s + .12))), rgb("#6A58B5"), 3)
        for k in range(4):
            a = math.radians(a0 + k * 90); poly(c, [(cx + 46 * math.cos(a), cy + 46 * math.sin(a)), (cx + 64 * math.cos(a + .3), cy + 64 * math.sin(a + .3)), (cx + 64 * math.cos(a - .3), cy + 64 * math.sin(a - .3))], rgb("#C9A24B"))
        fall(c, 13, 22, ts, lambda cc, x, y, s, k: petal(cc, x, y, 6 * s, rgb("#CFC0EE") if k % 2 else rgb("#F2D3E0"), k * 25), 1, 40)
        fall(c, 14, 10, step(t, 2), lambda cc, x, y, s, k: star4(cc, x, y, 3 * s, rgb("#C9A24B")), 2, 10)
        return c
    return f


def s_bop():
    def f(t):
        ts = step(t); c = base("#101010")
        k = int(ts * N) // 8                                         # jazz rhythm: panels re-cut every 8 frames
        rng = np.random.RandomState(80 + k)
        x = 0
        while x < W:
            w = int(rng.choice([60, 90, 140, 200]))
            col = rng.choice(["#1A1A1A", "#F26B1F", "#2F63D9", "#1A1A1A", "#F4ECD8"])
            cv2.rectangle(c, (x, 0), (x + w, H), mix("#101010", col, .6 if col != "#1A1A1A" else 1), -1)
            x += w
        for _ in range(6):                                           # film scratches
            sx = rng.uniform(0, W); cv2.line(c, (int(sx), 0), (int(sx + rng.uniform(-4, 4)), H), rgb("#F4ECD8"), 1)
        return c
    return f


def s_tg():
    def f(t):
        ts = step(t); c = base("#0E0E10", "#1C0A10", 110)
        k = int(ts * N) // 6
        rng = np.random.RandomState(90 + k)
        for _ in range(4):                                           # kagune: tapered red lunges
            x0, y0 = rng.choice([0, W]), rng.uniform(40, H - 40)
            x1 = W / 2 + rng.uniform(-160, 160); y1 = rng.uniform(80, H - 80)
            nx, ny = -(y1 - y0), (x1 - x0); L = math.hypot(nx, ny) or 1; nx, ny = nx / L * 10, ny / L * 10
            poly(c, [(x0 + nx, y0 + ny), (x1, y1), (x0 - nx, y0 - ny)], rgb("#F25461"), rgb("#050506"), 2)
        for i in range(8):                                           # glass shards falling
            x = (i * 83 + 20) % W; y = ((i * 61 + ts * 160) % (H + 40)) - 20
            poly(c, [(x, y), (x + 12, y + 6), (x + 3, y + 22)], rgb("#8C8C96"), rgb("#ECECEC"), 1)
        return c
    return f


def s_hxh():
    def f(t):
        ts = step(t, 3); c = base("#F1EAD0", "#E1D7B0", 140)
        for y in range(40, H, 60):
            cv2.line(c, (0, y), (W, y), rgb("#D6C998"), 1)
        for k in range(3):                                           # Nen rings radiating around a point
            r = ((ts * 2 + k / 3) % 1.0) * 220 + 12
            cv2.circle(c, (460, 190), int(r), rgb("#1E7A46"), 4); cv2.circle(c, (460, 190), int(r) + 7, rgb("#C99A2E"), 2)
        rise(c, 15, 24, step(t, 2), 1, lambda cc, x, y, s, k: cv2.circle(cc, (int(x), int(y)), int(3 * s), rgb("#1E7A46"), -1), 20)
        return c
    return f


def s_ini():
    def f(t):
        ts = step(t); c = base("#14161A", "#1E2127", 170)
        for i in range(7):                                           # speed streaks, horizontal
            y = 20 + i * 48
            streaks(c, 20 + i, 3, 0, rgb("#3A3F4A") if i % 2 else rgb("#C9A417"), step(t, 2), 4, (80, 260), (2, 5))
        for x in range(-60, W + 60, 90):                             # dashed centre line scrolling, skewed
            o = (x - int(ts * 6 * 90)) % (W + 120) - 60
            poly(c, [(o, 262), (o + 52, 262), (o + 40, 274), (o - 12, 274)], rgb("#F5F5F0"))
        rng = np.random.RandomState(int(ts * N) // 4)
        for i in range(4):
            puff(c, 120 + i * 40 + rng.uniform(-6, 6), 300 - i * 14, 14 + i * 5, rgb("#5A5D66"), rgb("#0C0D10"))
        cv2.rectangle(c, (0, H - 22), (W, H), rgb("#E4262B"), -1)
        return c
    return f


def s_db():
    def f(t):
        ts = step(t, 3); c = base("#FFF1DA")
        cx, cy = 440, 210
        a0 = int(ts * N / 3) * 4
        for i in range(0, 360, 15):                                  # rotating burst rays
            if (i // 15) % 2 == 0:
                a, b = math.radians(i + a0), math.radians(i + a0 + 12)
                poly(c, [(cx, cy), (cx + 900 * math.cos(a), cy + 900 * math.sin(a)), (cx + 900 * math.cos(b), cy + 900 * math.sin(b))], rgb("#FFD98A"))
        rng = np.random.RandomState(int(step(t, 2) * N) // 6)
        bolt(c, rng.uniform(380, 520), 0, rng.uniform(380, 520), 200, rng, rgb("#FFFFFF"), 3, rgb("#2D7BE5"))
        for i in range(6):                                           # aura flames, 3-cel cycle
            flame(c, 60 + i * 56, H + 4, 34 + (i % 3) * 8, rgb("#FFA23A"), rgb("#FFE066"), ((int(ts * N / 3) + i) % 3 - 1) * 4)
        return c
    return f


def s_sxf():
    def f(t):
        ts = step(t, 3); c = base("#EAF4EE", "#D8EADF", 150)
        for x in range(0, W, 24):
            cv2.line(c, (x, 0), (x, H), rgb("#D0E2D7"), 1)
        for y in range(0, H, 24):
            cv2.line(c, (0, y), (W, y), rgb("#D0E2D7"), 1)
        cv2.circle(c, (500, 130), 70, rgb("#B84A66"), 3)              # a camera iris that closes and reopens
        for i in range(8):
            a = math.radians(i * 45 + 22)
            r1 = 70 * (1 - abs(math.sin(math.pi * ts * 2)))           # twice per loop
            cv2.line(c, (int(500 + 70 * math.cos(a)), int(130 + 70 * math.sin(a))), (int(500 + r1 * math.cos(a + .6)), int(130 + r1 * math.sin(a + .6))), rgb("#3E7F6B"), 3)
        for i in range(10):
            cx = 60 + i * 62; cy = int(H - 40 - (i * 37) % 120 - (ts * 160) % 40)
            cv2.circle(c, (cx, cy), 8, rgb("#B84A66"), 2)
            cv2.line(c, (cx - 12, cy), (cx + 12, cy), rgb("#B84A66"), 1); cv2.line(c, (cx, cy - 12), (cx, cy + 12), rgb("#B84A66"), 1)
        return c
    return f


SCENES = {"jujutsu-kaisen": s_jjk, "solo-leveling": s_sl, "naruto": s_nar, "bleach": s_ble, "evangelion": s_eva,
          "demon-slayer": s_dem, "one-piece": s_op, "attack-on-titan": s_aot, "chainsaw-man": s_csm, "frieren": s_fri,
          "cowboy-bebop": s_bop, "tokyo-ghoul": s_tg, "hunter-x-hunter": s_hxh, "initial-d": s_ini, "dragon-ball": s_db,
          "spy-x-family": s_sxf}


def render(name: str) -> Path:
    frame = SCENES[name]()
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / f"{name}.mp4"
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (OUT_W, OUT_H))
    if not vw.isOpened():
        sys.exit("OpenCV could not open an mp4 writer")
    held, last = -1, None
    for i in range(N):
        if i // 2 != held:                                           # one drawing per two frames
            held = i // 2
            last = cv2.resize(frame(i / N), (OUT_W, OUT_H), interpolation=cv2.INTER_NEAREST)
        vw.write(last)
    vw.release()
    print(f"wrote {out.name} ({out.stat().st_size / 1e6:.1f} MB)")
    return out


if __name__ == "__main__":
    for n in sys.argv[1:] or list(SCENES):
        render(n)
