"""Draw ReRun LITE's built-in background videos: assets/<theme>.mp4.

    py tools/make_background.py                 all of them
    py tools/make_background.py neon aurora     only these

Original, looping animations, one per theme (see rerun_lite/palettes.py): Ahri (drifting petals, a moon, rising wisps),
Midnight (twinkling stars and shooting stars), Sakura (a light scene of falling blossom), Ember (rising sparks), Aurora
(slow green and violet lights) and Neon (a scrolling grid and a low sun). Everything is drawn here with numpy and OpenCV,
so the videos are ours to ship; they use no artwork from any game, wallpaper or website. 1280x720, 24 fps, 12 seconds,
and each loops without a jump (every motion repeats exactly once per loop).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

W, H, FPS, SECONDS = 1280, 720, 24, 12
N = FPS * SECONDS
ASSETS = Path(__file__).resolve().parents[1] / "assets"

PINK = np.array([255, 143, 191], np.float32)      # RGB
ROSE = np.array([240, 96, 154], np.float32)
CYAN = np.array([111, 230, 238], np.float32)
MOON = np.array([255, 226, 238], np.float32)


def rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], np.float32)


def vgrad(stops: list[tuple[float, str]]) -> np.ndarray:
    """A vertical gradient through (position 0..1, colour) stops."""
    y = np.linspace(0, 1, H, dtype=np.float32)
    cols = np.zeros((H, 3), np.float32)
    for c in range(3):
        cols[:, c] = np.interp(y, [p for p, _ in stops], [rgb(col)[c] for _, col in stops])
    return np.repeat(cols[:, None, :], W, axis=1)


def glow(canvas: np.ndarray, cx: float, cy: float, r: float, color, strength: float) -> None:
    x0, x1, y0, y1 = int(max(cx - 3 * r, 0)), int(min(cx + 3 * r, W)), int(max(cy - 3 * r, 0)), int(min(cy + 3 * r, H))
    if x1 <= x0 or y1 <= y0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d2 = ((xx - cx) ** 2 + (yy - cy) ** 2) / (r * r)
    canvas[y0:y1, x0:x1] += np.exp(-d2)[..., None] * np.asarray(color, np.float32) * strength


def vignette(strength: float = 0.5, light: bool = False) -> np.ndarray:
    v = np.sqrt(((np.arange(W) - W / 2) / (W / 2)) ** 2 + ((np.arange(H)[:, None] - H / 2) / (H / 2)) ** 2).astype(np.float32)
    k = np.clip(v - 0.45, 0, 1) ** 1.3 * strength
    return (1 - k)[..., None] if not light else (1 - 0.6 * k)[..., None]


def ridge_layer(rng, shades) -> np.ndarray:
    """RGBA float layer of ridges, far to near (shades: [(base, amp, colour, alpha), ...])."""
    layer = np.zeros((H, W, 4), np.float32)
    xs = np.arange(W, dtype=np.float32)
    for base, amp, shade, alpha in shades:
        ph = rng.rand(3) * 6.28
        top = (base * H + amp * (np.sin(xs / 190 + ph[0]) * 0.55 + np.sin(xs / 83 + ph[1]) * 0.3 + np.sin(xs / 41 + ph[2]) * 0.15)).astype(np.int32)
        for x in range(W):
            layer[top[x]:, x, :3] = rgb(shade)
            layer[top[x]:, x, 3] = alpha
    return cv2.GaussianBlur(layer, (0, 0), 1.2)


def alpha_blit(canvas: np.ndarray, patch: np.ndarray, alpha: np.ndarray, x: float, y: float) -> None:
    """Composite `patch` (colour) through `alpha` (0..1) with its centre at x, y."""
    ph, pw = alpha.shape
    x0, y0 = int(x) - pw // 2, int(y) - ph // 2
    sx0, sy0, sx1, sy1 = max(0, -x0), max(0, -y0), min(pw, W - x0), min(ph, H - y0)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    a = alpha[sy0:sy1, sx0:sx1, None]
    dst = canvas[y0 + sy0:y0 + sy1, x0 + sx0:x0 + sx1]
    dst[:] = dst * (1 - a) + patch[sy0:sy1, sx0:sx1] * a


# ------------------------------------------------------------------------------------------------- Ahri
def scene_ahri():
    rng = np.random.RandomState(20260116)
    base = vgrad([(0, "#090718"), (0.55, "#1B1038"), (1, "#2E1646")])
    ridge = ridge_layer(rng, [(0.70, 46, "#1E1840", 0.55), (0.80, 60, "#14102E", 0.75), (0.92, 40, "#0C091E", 0.95)])
    vig = vignette(0.5)
    petals = [dict(x=rng.rand() * W, y=rng.rand() * (H + 60), amp=rng.uniform(20, 70), f=int(rng.choice([1, 2, 3])), ph=rng.rand(),
                   n=int(rng.choice([1, 1, 2])), size=rng.uniform(5, 15), spin=int(rng.choice([-2, -1, 1, 2])),
                   col=PINK * rng.uniform(0.75, 1.0) + 255 * rng.uniform(0, 0.12), depth=rng.uniform(0.4, 1.0)) for _ in range(64)]
    wisps = [dict(x=rng.rand() * W, amp=rng.uniform(40, 120), f=int(rng.choice([1, 2])), ph=rng.rand(), n=int(rng.choice([1, 1, 2])),
                  size=rng.uniform(3, 7), off=rng.rand()) for _ in range(18)]

    def frame(t):
        c = base.copy()
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * t)
        glow(c, W * 0.80, H * 0.24, 240 + 20 * pulse, ROSE, 0.34)
        glow(c, W * 0.16, H * 0.66, 300 - 20 * pulse, CYAN, 0.14)
        glow(c, W * 0.80, H * 0.24, 70, MOON, 0.55)
        cv2.circle(c, (int(W * 0.80), int(H * 0.24)), 62, tuple(float(v) for v in MOON), -1, cv2.LINE_AA)
        spirit = np.zeros_like(c)
        for w in wisps:
            for k in range(26):
                tt = (t - k * 0.0035) % 1.0
                y = H + 30 - ((tt * w["n"] + w["off"]) % 1.0) * (H + 80)
                x = w["x"] + w["amp"] * math.sin(2 * math.pi * (w["f"] * tt + w["ph"]) + y / 90)
                a = (1 - k / 26) ** 2 * (0.35 + 0.65 * math.sin(math.pi * min(max((H + 30 - y) / (H + 80), 0), 1)))
                cv2.circle(spirit, (int(x), int(y)), max(1, int(w["size"] * (1 - k / 40))), tuple(float(v) * a for v in CYAN), -1, cv2.LINE_AA)
        c += cv2.GaussianBlur(spirit, (0, 0), 6) * 1.5 + spirit * 0.55
        for p in sorted(petals, key=lambda q: q["depth"]):
            y = ((p["y"] + p["n"] * (H + 60) * t) % (H + 60)) - 30
            x = p["x"] + p["amp"] * math.sin(2 * math.pi * (p["f"] * t + p["ph"]))
            ang = 360.0 * p["spin"] * t + p["ph"] * 360
            s = p["size"] * p["depth"]
            col = tuple(float(v) * (0.55 + 0.45 * p["depth"]) for v in p["col"])
            g = np.zeros((int(6 * s) + 8, int(6 * s) + 8, 3), np.float32)
            cv2.ellipse(g, (g.shape[1] // 2, g.shape[0] // 2), (int(s * 1.6), int(s * 0.8)), ang, 0, 360, col, -1, cv2.LINE_AA)
            tip = cv2.GaussianBlur(g, (0, 0), s * 0.9) * 0.9 + g
            x0, y0 = int(x) - tip.shape[1] // 2, int(y) - tip.shape[0] // 2
            sx0, sy0, sx1, sy1 = max(0, -x0), max(0, -y0), min(tip.shape[1], W - x0), min(tip.shape[0], H - y0)
            if sx1 > sx0 and sy1 > sy0:
                c[y0 + sy0:y0 + sy1, x0 + sx0:x0 + sx1] += tip[sy0:sy1, sx0:sx1]
        a = ridge[..., 3:4]
        c = c * (1 - a) + ridge[..., :3] * a
        return c * vig
    return frame


# ------------------------------------------------------------------------------------------------- Midnight
def scene_midnight():
    rng = np.random.RandomState(7)
    base = vgrad([(0, "#04060F"), (0.6, "#0B1530"), (1, "#16305E")])
    ridge = ridge_layer(rng, [(0.78, 40, "#0C1A3A", 0.6), (0.88, 50, "#070F26", 0.85), (0.96, 30, "#04091A", 1.0)])
    vig = vignette(0.55)
    stars = [dict(x=rng.rand() * W, y=rng.rand() * H * 0.78, f=int(rng.choice([1, 2, 3])), ph=rng.rand(), r=rng.uniform(0.6, 2.0),
                  b=rng.uniform(0.35, 1.0)) for _ in range(230)]
    shoot = [dict(t0=t0, x0=rng.uniform(0.15, 0.85) * W, y0=rng.uniform(0.05, 0.35) * H, dx=rng.uniform(260, 420) * s, dy=rng.uniform(120, 220))
             for t0, s in ((0.12, 1), (0.47, -1), (0.78, 1))]

    def frame(t):
        c = base.copy()
        glow(c, W * 0.25 + 40 * math.sin(2 * math.pi * t), H * 0.35, 330, (50, 70, 160), 0.18)
        glow(c, W * 0.78 - 30 * math.sin(2 * math.pi * t), H * 0.28, 280, (90, 60, 170), 0.14)
        sky = np.zeros_like(c)
        for s in stars:
            tw = 0.55 + 0.45 * math.sin(2 * math.pi * (s["f"] * t + s["ph"]))
            cv2.circle(sky, (int(s["x"]), int(s["y"])), max(1, int(s["r"])), tuple(float(v) * s["b"] * tw for v in (220, 232, 255)), -1, cv2.LINE_AA)
        c += cv2.GaussianBlur(sky, (0, 0), 1.6) * 1.4 + sky
        for m in shoot:
            u = (t - m["t0"]) / 0.07
            if 0 <= u <= 1:
                head = (m["x0"] + m["dx"] * u, m["y0"] + m["dy"] * u)
                for k in range(22):
                    f = max(0.0, u - k * 0.02)
                    p = (int(m["x0"] + m["dx"] * f), int(m["y0"] + m["dy"] * f))
                    a = (1 - k / 22) ** 1.6 * math.sin(math.pi * min(u, 1))
                    cv2.circle(c, p, max(1, 3 - k // 8), tuple(float(v) * a for v in (255, 250, 235)), -1, cv2.LINE_AA)
                glow(c, head[0], head[1], 14, (200, 220, 255), 0.5 * math.sin(math.pi * u))
        a = ridge[..., 3:4]
        c = c * (1 - a) + ridge[..., :3] * a
        return c * vig
    return frame


# ------------------------------------------------------------------------------------------------- Sakura (light)
def scene_sakura():
    rng = np.random.RandomState(11)
    base = vgrad([(0, "#FFF1F5"), (0.6, "#FBE3EC"), (1, "#F6D3E0")])
    vig = vignette(0.4, light=True)
    bokeh = [dict(x=rng.rand() * W, y=rng.rand() * (H + 200), r=rng.uniform(20, 70), n=int(rng.choice([1, 1])), amp=rng.uniform(10, 40),
                  f=int(rng.choice([1, 2])), ph=rng.rand(), a=rng.uniform(0.10, 0.28)) for _ in range(22)]
    petals = [dict(x=rng.rand() * W, y=rng.rand() * (H + 80), amp=rng.uniform(30, 90), f=int(rng.choice([1, 2, 3])), ph=rng.rand(),
                   n=int(rng.choice([1, 1, 2])), size=rng.uniform(7, 18), spin=int(rng.choice([-2, -1, 1, 2])), depth=rng.uniform(0.5, 1.0),
                   col=np.array([240, 122, 164], np.float32) * rng.uniform(0.85, 1.05)) for _ in range(54)]

    def frame(t):
        c = base.copy()
        glow(c, W * 0.82, H * 0.18, 300, (255, 236, 200), 0.28)
        glow(c, W * 0.10, H * 0.85, 360, (255, 190, 215), 0.18)
        for b in bokeh:
            y = H + 100 - ((b["y"] / (H + 200) + b["n"] * t) % 1.0) * (H + 200)
            x = b["x"] + b["amp"] * math.sin(2 * math.pi * (b["f"] * t + b["ph"]))
            ring = np.zeros((int(b["r"] * 2.6), int(b["r"] * 2.6)), np.float32)
            cv2.circle(ring, (ring.shape[1] // 2, ring.shape[0] // 2), int(b["r"]), 1.0, -1, cv2.LINE_AA)
            ring = cv2.GaussianBlur(ring, (0, 0), b["r"] * 0.25)
            alpha_blit(c, np.full(ring.shape + (3,), (255, 250, 252), np.float32), ring * b["a"], x, y)
        for p in sorted(petals, key=lambda q: q["depth"]):
            y = ((p["y"] + p["n"] * (H + 80) * t) % (H + 80)) - 40
            x = p["x"] + p["amp"] * math.sin(2 * math.pi * (p["f"] * t + p["ph"]))
            ang = 360.0 * p["spin"] * t + p["ph"] * 360
            s = p["size"] * p["depth"]
            size = int(7 * s) + 10
            m = np.zeros((size, size), np.float32)
            cv2.ellipse(m, (size // 2, size // 2), (int(s * 1.6), int(s * 0.85)), ang, 0, 360, 1.0, -1, cv2.LINE_AA)
            shade = cv2.GaussianBlur(m, (0, 0), s * 0.5)
            patch = np.zeros(m.shape + (3,), np.float32)
            patch[:] = p["col"] * (0.75 + 0.25 * p["depth"])
            patch += (m[..., None] * 18)
            alpha_blit(c, np.zeros_like(patch) + (200, 120, 150), shade * 0.18, x + 3, y + 5)          # a soft shadow
            alpha_blit(c, patch, m * (0.55 + 0.4 * p["depth"]), x, y)
        return c * vig + (1 - vig) * 255 * 0.0
    return frame


# ------------------------------------------------------------------------------------------------- Ember
def scene_ember():
    rng = np.random.RandomState(23)
    base = vgrad([(0, "#0B0504"), (0.6, "#1D0B07"), (1, "#3A140A")])
    ridge = ridge_layer(rng, [(0.80, 44, "#1A0A06", 0.8), (0.92, 36, "#0D0503", 1.0)])
    vig = vignette(0.6)
    sparks = [dict(x=rng.rand() * W, off=rng.rand(), n=int(rng.choice([1, 1, 2])), amp=rng.uniform(15, 70), f=int(rng.choice([1, 2, 3])),
                   ph=rng.rand(), r=rng.uniform(1.0, 3.2), life=rng.uniform(0.6, 1.0)) for _ in range(150)]

    def frame(t):
        c = base.copy()
        flick = 0.5 + 0.5 * math.sin(2 * math.pi * 2 * t)
        glow(c, W * 0.5, H * 1.05, 520, (255, 110, 30), 0.34 + 0.06 * flick)
        glow(c, W * 0.18, H * 0.95, 300, (255, 80, 20), 0.20)
        glow(c, W * 0.84, H * 0.98, 320, (255, 130, 40), 0.20)
        lay = np.zeros_like(c)
        for s in sparks:
            for k in range(9):
                tt = (t - k * 0.004) % 1.0
                u = (tt * s["n"] + s["off"]) % 1.0
                y = H + 20 - u * (H + 60) * s["life"] - 10
                x = s["x"] + s["amp"] * math.sin(2 * math.pi * (s["f"] * tt + s["ph"]) + u * 5)
                a = (1 - k / 9) * (1 - u) ** 0.7 * (0.6 + 0.4 * math.sin(2 * math.pi * (3 * tt + s["ph"])))
                col = (255, 160 + 70 * (1 - u), 40 + 90 * (1 - u))
                cv2.circle(lay, (int(x), int(y)), max(1, int(s["r"] * (1 - k / 14))), tuple(float(v) * a for v in col), -1, cv2.LINE_AA)
        c += cv2.GaussianBlur(lay, (0, 0), 5) * 1.6 + lay * 0.9
        a = ridge[..., 3:4]
        c = c * (1 - a) + ridge[..., :3] * a
        return c * vig
    return frame


# ------------------------------------------------------------------------------------------------- Aurora
def scene_aurora():
    rng = np.random.RandomState(31)
    base = vgrad([(0, "#03080A"), (0.65, "#08191A"), (1, "#0D2A28")])
    ridge = ridge_layer(rng, [(0.84, 36, "#06181A", 0.9), (0.94, 30, "#030B0C", 1.0)])
    vig = vignette(0.55)
    stars = [(rng.rand() * W, rng.rand() * H * 0.6, rng.uniform(0.5, 1.5), rng.rand(), int(rng.choice([1, 2]))) for _ in range(120)]
    ribbons = [dict(base=0.30, amp=70, lam=520, k=1, ph=0.0, col=(60, 255, 170), w=34),
               dict(base=0.40, amp=55, lam=380, k=2, ph=0.35, col=(60, 200, 230), w=28),
               dict(base=0.24, amp=90, lam=640, k=-1, ph=0.7, col=(170, 110, 255), w=30)]
    xs = np.arange(0, W + 8, 8, dtype=np.float32)

    def frame(t):
        c = base.copy()
        sky = np.zeros_like(c)
        for x, y, r, ph, f in stars:
            tw = 0.5 + 0.5 * math.sin(2 * math.pi * (f * t + ph))
            cv2.circle(sky, (int(x), int(y)), 1, tuple(float(v) * tw * r * 0.7 for v in (210, 240, 235)), -1, cv2.LINE_AA)
        c += sky
        for rb in ribbons:
            lay = np.zeros((H, W), np.float32)
            ys = rb["base"] * H + rb["amp"] * np.sin(2 * math.pi * (xs / rb["lam"] + rb["k"] * t + rb["ph"])) + 22 * np.sin(2 * math.pi * (xs / 190 + 2 * t))
            pts = np.stack([xs, ys], axis=1).astype(np.int32)
            cv2.polylines(lay, [pts], False, 1.0, rb["w"], cv2.LINE_AA)
            streak = 0.82 + 0.18 * np.sin(np.arange(W, dtype=np.float32)[None, :] / 23.0 + 6.28 * t)      # vertical curtain texture
            lay = cv2.GaussianBlur(lay, (0, 0), 30) * streak
            down = cv2.GaussianBlur(lay, (0, 0), 60)
            c += np.stack([lay, lay, lay], -1) * np.array(rb["col"], np.float32) * 0.9 + down[..., None] * np.array(rb["col"], np.float32) * 0.5
        a = ridge[..., 3:4]
        c = c * (1 - a) + ridge[..., :3] * a
        return c * vig
    return frame


# ------------------------------------------------------------------------------------------------- Neon
def scene_neon():
    rng = np.random.RandomState(41)
    base = vgrad([(0, "#07030F"), (0.58, "#1B0B34"), (0.58, "#0A0414"), (1, "#0A0414")])
    vig = vignette(0.5)
    horizon = int(H * 0.58)
    stars = [(rng.rand() * W, rng.rand() * horizon * 0.9, rng.uniform(0.4, 1.0), rng.rand(), int(rng.choice([1, 2]))) for _ in range(90)]
    vx = W / 2
    cell_rows = 12

    def frame(t):
        c = base.copy()
        for x, y, b, ph, f in stars:
            tw = 0.5 + 0.5 * math.sin(2 * math.pi * (f * t + ph))
            cv2.circle(c, (int(x), int(y)), 1, tuple(float(v) * b * tw for v in (230, 210, 255)), -1, cv2.LINE_AA)
        # the sun, sliced by moving dark bars
        sun = np.zeros((H, W), np.float32)
        cx, cy, r = W // 2, horizon - 10, 150
        cv2.circle(sun, (cx, cy), r, 1.0, -1, cv2.LINE_AA)
        for i in range(7):
            yb = cy + 18 + i * 20 + ((t * 20) % 20) - 20
            th = 2 + i * 2
            cv2.rectangle(sun, (cx - r, int(yb)), (cx + r, int(yb) + th), 0.0, -1)
        sun[horizon:, :] = 0
        sy = np.clip((np.arange(H)[:, None] - (cy - r)) / (2.0 * r), 0, 1)[..., None]
        scol = np.array((255, 215, 90), np.float32) * (1 - sy) + np.array((255, 40, 150), np.float32) * sy
        c += sun[..., None] * scol * 0.95
        glow(c, cx, cy, 260, (255, 60, 160), 0.30)
        # the grid: lines to the vanishing point, and rows that scroll one cell per loop
        gl = np.zeros_like(c)
        for i in range(-16, 17):
            x_bottom = vx + i * 150
            cv2.line(gl, (int(vx + i * 6), horizon), (int(x_bottom), H), (60, 220, 255), 2, cv2.LINE_AA)
        for k in range(1, cell_rows + 2):
            z = k - t
            y = horizon + (H - horizon) * min(1.0, (z / (cell_rows + 0.5)) ** 2.1)
            cv2.line(gl, (0, int(y)), (W, int(y)), (255, 70, 200), 2, cv2.LINE_AA)
        gl[:horizon] = 0
        c += cv2.GaussianBlur(gl, (0, 0), 7) * 1.2 + gl * 0.8
        c[::3] *= 0.94                                                                   # a faint scanline texture
        return c * vig
    return frame


SCENES = {"spirit_blossom": scene_ahri, "midnight": scene_midnight, "sakura": scene_sakura, "ember": scene_ember,
          "aurora": scene_aurora, "neon": scene_neon}


def render(name: str) -> None:
    frame = SCENES[name]()
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / f"{name}.mp4"
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    if not vw.isOpened():
        sys.exit("OpenCV could not open an mp4 writer")
    for i in range(N):
        img = np.clip(frame(i / N), 0, 255).astype(np.uint8)
        vw.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        if i % 72 == 0:
            print(f"  {name}: frame {i}/{N}", flush=True)
    vw.release()
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    want = sys.argv[1:] or list(SCENES)
    for n in want:
        render({"ahri": "spirit_blossom"}.get(n, n))
