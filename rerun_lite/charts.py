"""Two small charts drawn on a plain tk.Canvas (no matplotlib, no new dependency): bars and a line.

The geometry is worked out by pure functions (so it is tested without a window); the Canvas classes only draw it.
Colours come from the app's palette so the charts follow light/dark and the chosen accent."""
from __future__ import annotations

import math


def nice_max(v: float) -> float:
    """A round top value for the axis: 7 -> 8, 43 -> 50, 0 -> 1."""
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def bar_geometry(values: list[float], w: int, h: int, pad=(34, 10, 10, 22)) -> dict:
    """Rectangles (x0, y0, x1, y1) for each value inside the plot area; pad = left, top, right, bottom."""
    l, t, r, b = pad
    pw, ph = max(1, w - l - r), max(1, h - t - b)
    top = nice_max(max(values) if values else 0)
    n = max(1, len(values))
    slot = pw / n
    gap = min(6.0, slot * 0.25)
    bars = []
    for i, v in enumerate(values):
        x0 = l + i * slot + gap / 2
        x1 = l + (i + 1) * slot - gap / 2
        y1 = t + ph
        y0 = y1 - (ph * v / top if top else 0)
        bars.append((x0, y0, max(x0 + 1, x1), y1))
    return {"top": top, "bars": bars, "plot": (l, t, l + pw, t + ph)}


def line_geometry(values: list[float], w: int, h: int, pad=(40, 10, 10, 22)) -> dict:
    """Points (x, y) for a line of values; the axis starts at 0 so a flat line really is flat."""
    l, t, r, b = pad
    pw, ph = max(1, w - l - r), max(1, h - t - b)
    top = nice_max(max(values) if values else 0)
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = l + (pw * i / (n - 1) if n > 1 else pw / 2)
        pts.append((x, t + ph - ph * v / top))
    return {"top": top, "points": pts, "plot": (l, t, l + pw, t + ph)}


def _colors():
    from rerun.ios import C  # noqa: PLC0415 - tkinter is only needed when a chart is really drawn
    return C


class _Chart:
    def __init__(self, parent, height: int, empty: str):
        import tkinter as tk  # noqa: PLC0415
        from rerun.ios import bg_of, F  # noqa: PLC0415
        self._tk, self._F = tk, F
        self.canvas = tk.Canvas(parent, height=height, highlightthickness=0, bd=0, bg=bg_of(parent))
        self.values: list[float] = []
        self.labels: list[str] = []
        self.empty = empty
        self.fmt = lambda v: f"{v:g}"
        self.canvas.bind("<Configure>", lambda e: self.draw())

    def pack(self, **kw):
        self.canvas.pack(**kw)

    def set(self, values, labels=None):
        self.values = list(values)
        self.labels = list(labels or [])
        self.draw()

    def _axes(self, top, plot, ticks=4):
        c, C, F = self.canvas, _colors(), self._F
        l, t, r, b = plot
        for i in range(ticks + 1):
            y = b - (b - t) * i / ticks
            c.create_line(l, y, r, y, fill=C["sep"])
            c.create_text(l - 5, y, text=self.fmt(top * i / ticks), anchor="e", fill=C["secondary"], font=F["caption"])

    def _x_labels(self, xs, plot):
        c, C, F = self.canvas, _colors(), self._F
        if not self.labels:
            return
        step = max(1, len(self.labels) // 7)
        for i in range(0, len(self.labels), step):
            c.create_text(xs[i], plot[3] + 12, text=self.labels[i], fill=C["secondary"], font=F["caption"])

    def _empty(self):
        C, F = _colors(), self._F
        self.canvas.create_text(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2, text=self.empty,
                                fill=C["secondary"], font=F["footnote"])


class BarChart(_Chart):
    def draw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60 or h < 60:
            return
        if not self.values or not any(self.values):
            return self._empty()
        g = bar_geometry(self.values, w, h)
        self._axes(g["top"], g["plot"])
        C = _colors()
        for (x0, y0, x1, y1), v in zip(g["bars"], self.values):
            if v:
                c.create_rectangle(x0, y0, x1, y1, fill=C["blue"], outline="")
        self._x_labels([(b[0] + b[2]) / 2 for b in g["bars"]], g["plot"])


class LineChart(_Chart):
    def draw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60 or h < 60:
            return
        if len(self.values) < 2:
            return self._empty()
        g = line_geometry(self.values, w, h)
        self._axes(g["top"], g["plot"])
        C = _colors()
        flat = [v for p in g["points"] for v in p]
        c.create_line(*flat, fill=C["blue"], width=2, smooth=False)
        if len(g["points"]) <= 40:
            for x, y in g["points"]:
                c.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=C["blue"], outline="")
