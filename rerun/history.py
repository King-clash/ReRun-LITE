"""What the scripts found and did - crests, refills, failures, finishes - with a
small picture of each, for the History tab and Discord's /history."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import errlog

MAX_ENTRIES = 2000
THUMB_MAX = (360, 200)  # w, h


class History:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.thumbs = self.folder / "thumbs"
        self.thumbs.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "history.jsonl"
        self._lock = threading.Lock()
        self.entries: list[dict] = []
        self.listeners: list[Callable[[dict], None]] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    self.entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self.entries = self.entries[-MAX_ENTRIES:]
        self._seq = 0

    def add(self, instance: str, script: str, kind: str, detail: str,
            image: np.ndarray | None = None, **extra) -> dict:
        with self._lock:
            self._seq += 1
            stamp = time.time()
            entry = {"t": stamp, "instance": instance, "script": script, "kind": kind,
                     "detail": detail, **{k: v for k, v in extra.items() if v is not None}}
            if image is not None and image.size:
                name = f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(stamp))}_{self._seq}.jpg"
                h, w = image.shape[:2]
                s = min(THUMB_MAX[0] / w, THUMB_MAX[1] / h, 1.0)
                thumb = cv2.resize(image, (max(1, int(w * s)), max(1, int(h * s))),
                                   interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    buf.tofile(str(self.thumbs / name))
                    entry["thumb"] = name
            self.entries.append(entry)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            if len(self.entries) > MAX_ENTRIES + 200:
                self._compact()
        for fn in list(self.listeners):
            try:
                fn(entry)
            except Exception as e:  # noqa: BLE001 - a listener must never break a script
                errlog.note("history listener", e)
        return entry

    def _compact(self) -> None:
        """Drop the oldest entries (and their pictures) past MAX_ENTRIES."""
        old, self.entries = self.entries[:-MAX_ENTRIES], self.entries[-MAX_ENTRIES:]
        for e in old:
            if e.get("thumb"):
                (self.thumbs / e["thumb"]).unlink(missing_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e) + "\n" for e in self.entries), encoding="utf-8")
        tmp.replace(self.path)

    def recent(self, n: int = 200, instance: str | None = None, kind: str | None = None) -> list[dict]:
        with self._lock:
            items = [e for e in reversed(self.entries)
                     if (instance is None or e["instance"] == instance)
                     and (kind is None or e["kind"] == kind)]
        return items[:n]

    def thumb_path(self, entry: dict) -> Path | None:
        t = entry.get("thumb")
        p = self.thumbs / t if t else None
        return p if p and p.exists() else None

    def clear(self) -> None:
        with self._lock:
            for e in self.entries:
                if e.get("thumb"):
                    (self.thumbs / e["thumb"]).unlink(missing_ok=True)
            self.entries = []
            self.path.write_text("", encoding="utf-8")

    def crest_summary(self, instance: str | None = None) -> dict[str, int]:
        """{'kept': n, 'scrapped': n, 'lv4': n, ...} from crest entries."""
        out: dict[str, int] = {}
        for e in self.recent(MAX_ENTRIES, instance, "crest"):
            for key in (e.get("action"), e.get("rarity")):
                if key:
                    out[key] = out.get(key, 0) + 1
        return out
