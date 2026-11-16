"""Makes a small background video look better on a big window.

A 480x270 GIF stretched over a 1140x840 window (or a maximised one) looks soft, and GIFs carry 256-colour dithering that
turns into visible speckle when enlarged. `ensure()` builds a 1080p copy once and keeps it in data/lite/cache/:

  1. smooth the dithering at the original size (a non-local-means denoise: it keeps edges, removes speckle),
  2. enlarge with Lanczos resampling,
  3. a light unsharp mask to put the edges back.

It takes about 20 seconds for a short GIF (all CPU cores are used) and only happens once per video; until it is done
the original plays.

This makes the video look cleaner and sharper. It cannot add detail that was never in the picture, so a tiny source will
still look like a tiny source; a bigger one is always better. The original file is never changed, and the window still
scales the video to any size (maximised or not) afterwards.
"""
from __future__ import annotations

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

TARGET_HEIGHT = 1080
ENOUGH_WIDTH = 1280            # a video at least this wide is left as it is
VERSION = 3                    # bump when the recipe changes: old caches are then rebuilt


def needs_upscale(width: int) -> bool:
    return 0 < width < ENOUGH_WIDTH


def source_size(path: Path) -> tuple[int, int, float, int]:
    cap = cv2.VideoCapture(str(path))
    try:
        return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                float(cap.get(cv2.CAP_PROP_FPS)) or 24.0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    finally:
        cap.release()


def cache_path(src: Path, cache_dir: Path) -> Path:
    st = src.stat()
    tag = hashlib.sha1(f"{src.resolve()}|{st.st_size}|{int(st.st_mtime)}|{VERSION}".encode()).hexdigest()[:12]
    return Path(cache_dir) / f"{src.stem[:40]}-{TARGET_HEIGHT}p-{tag}.mp4"


def enhance(frame):
    """One frame: denoise, enlarge, sharpen."""
    h, w = frame.shape[:2]
    clean = cv2.fastNlMeansDenoisingColored(frame, None, 8, 8, 5, 11)
    scale = TARGET_HEIGHT / h
    big = cv2.resize(clean, (int(round(w * scale)) // 2 * 2, TARGET_HEIGHT), interpolation=cv2.INTER_LANCZOS4)
    soft = cv2.GaussianBlur(big, (0, 0), 1.4)
    return cv2.addWeighted(big, 1.5, soft, -0.5, 0)


def build(src: Path, dst: Path, progress=None, cancel: threading.Event | None = None) -> bool:
    """Write the enlarged copy of `src` to `dst`. `progress(percent)` is called as it goes. False when cancelled/failed."""
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return False
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = max(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(".part.mp4")
    workers = max(2, os.cpu_count() or 2)
    writer = None
    n = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            done = False
            while not done:
                if cancel is not None and cancel.is_set():
                    return False
                batch = []
                while len(batch) < workers * 2:                 # a few frames at a time, all cores busy
                    ok, frame = cap.read()
                    if not ok:
                        done = True
                        break
                    batch.append(frame)
                for out in pool.map(enhance, batch):            # in order
                    if writer is None:
                        writer = cv2.VideoWriter(str(part), cv2.VideoWriter_fourcc(*"mp4v"), fps, (out.shape[1], out.shape[0]))
                        if not writer.isOpened():
                            return False
                    writer.write(out)
                    n += 1
                if progress is not None and batch:
                    progress(min(99, int(100 * n / total)))
    finally:
        cap.release()
        if writer is not None:
            writer.release()
    if n == 0:
        part.unlink(missing_ok=True)
        return False
    part.replace(dst)                                            # only a finished file is ever used
    if progress is not None:
        progress(100)
    return True


def ready(src: Path, cache_dir: Path) -> Path | None:
    """The enlarged copy if it already exists."""
    c = cache_path(src, cache_dir)
    return c if c.is_file() and c.stat().st_size > 1000 else None
