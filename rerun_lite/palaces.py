"""The daily Crest Palace selector: the palace list, the day rule, and the import from GS Companion.

  palaces.yaml          THE palace list: one palace per line, "Palace name: images/file.png". Image paths appear
                        only here. Nothing else (schedule, settings, code) names an image file.
  images/               the palace pictures, each named after its palace (shrine_of_cursed_claw.png)
  data/lite/palace_schedule.json
                        which palace runs when, by palace NAME only:
                          mode   off | weekday | cycle
                          week   {"Monday": "Shrine of Perdition", ...}            (weekday mode)
                          cycle  {"start": name, "anchor": "YYYY-MM-DD", "only": [names]}   (cycle mode)

"Today" is the GAME day: it starts at the 6 AM UTC-6 reset (rerun.checklist.GAME_TZ / RESET_HOUR, the same clock
Crest and the checklist already use), never at the computer's midnight.

Nothing here writes over an existing picture or an existing palace line: the import skips what is already there
and says so.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
import yaml

from rerun.checklist import GAME_TZ, RESET_HOUR

LIST_FILE = "palaces.yaml"
IMAGE_DIR = "images"
SCHEDULE_FILE = "data/lite/palace_schedule.json"
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MODES = {"off": "Off (Crest uses its own palace settings)", "weekday": "Weekday table", "cycle": "Cycle the list"}
LIST_HEADER = ("# ReRun LITE palace list: one palace per line, 'Palace name: image file'.\n"
               "# This is the only place image paths are written. Edit by hand or import from GS Companion.\n")


@dataclass(frozen=True)
class Palace:
    name: str
    image: str            # exactly as written in the list, relative to the app folder


@dataclass
class Schedule:
    mode: str = "off"
    week: dict = field(default_factory=dict)
    cycle_start: str = ""
    cycle_anchor: str = ""
    cycle_only: list = field(default_factory=list)


@dataclass
class Choice:
    """What to run today. `problem` is non-empty when nothing may run (say why instead of running something else)."""
    mode: str
    day: str
    game_date: date
    palace: Palace | None = None
    path: Path | None = None
    problem: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem and self.palace is not None and self.path is not None


# ---------------------------------------------------------------- the game day
def game_date(now: datetime | None = None) -> date:
    """The game's calendar day: it turns over at RESET_HOUR in GAME_TZ (6 AM UTC-6)."""
    now = (now or datetime.now(GAME_TZ)).astimezone(GAME_TZ)
    return (now - timedelta(hours=RESET_HOUR)).date()


# ---------------------------------------------------------------- the list
def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def read_list(root: str | Path) -> list[Palace]:
    """The palaces in file order. A missing file is an empty list; an unreadable one is an error."""
    path = Path(root) / LIST_FILE
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{LIST_FILE} is not valid: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{LIST_FILE} must be lines of 'Palace name: images/file.png'.")
    return [Palace(str(k), str(v)) for k, v in data.items() if v]


def line_for(palace: Palace) -> str:
    return f"{palace.name}: {palace.image}\n"


def image_path(root: str | Path, palace: Palace) -> Path:
    return Path(root) / palace.image


def find(palaces: list[Palace], name: str) -> Palace | None:
    wanted = name.strip().lower()
    return next((p for p in palaces if p.name.lower() == wanted), None)


# ---------------------------------------------------------------- the schedule
def load_schedule(root: str | Path) -> Schedule:
    try:
        raw = json.loads((Path(root) / SCHEDULE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Schedule()
    cyc = raw.get("cycle") or {}
    mode = raw.get("mode") if raw.get("mode") in MODES else "off"
    return Schedule(mode, {d: str(n) for d, n in (raw.get("week") or {}).items() if d in DAYS and n},
                    str(cyc.get("start") or ""), str(cyc.get("anchor") or ""), [str(n) for n in cyc.get("only") or []])


def save_schedule(root: str | Path, s: Schedule) -> None:
    path = Path(root) / SCHEDULE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"mode": s.mode, "week": s.week, "cycle": {"start": s.cycle_start, "anchor": s.cycle_anchor, "only": s.cycle_only}}
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")


def cycle_order(palaces: list[Palace], s: Schedule) -> list[Palace]:
    """The palaces the cycle walks through, in list order (all of them unless the schedule names a subset)."""
    only = {n.lower() for n in s.cycle_only}
    return [p for p in palaces if not only or p.name.lower() in only]


def choose(root: str | Path, now: datetime | None = None) -> Choice:
    """Which palace runs today, and where its picture is. Never falls back to another palace."""
    gd = game_date(now)
    day = DAYS[gd.weekday()]
    s = load_schedule(root)
    out = Choice(s.mode, day, gd)
    if s.mode == "off":
        return out
    try:
        palaces = read_list(root)
    except ValueError as e:
        out.problem = str(e)
        return out
    if not palaces:
        out.problem = f"The palace list ({LIST_FILE}) is empty. Import the palaces or add lines to it."
        return out
    if s.mode == "weekday":
        name = s.week.get(day, "")
        if not name:
            out.problem = f"No palace is chosen for {day} in the weekday table."
            return out
        palace = find(palaces, name)
        if palace is None:
            out.problem = f"{day}'s palace '{name}' is not in {LIST_FILE}."
            return out
    else:
        order = cycle_order(palaces, s)
        if not order:
            out.problem = "The cycle has no palaces (check the cycle list)."
            return out
        start = next((i for i, p in enumerate(order) if p.name.lower() == s.cycle_start.strip().lower()), 0)
        try:
            anchor = date.fromisoformat(s.cycle_anchor)
        except ValueError:
            anchor = gd
        palace = order[(start + (gd - anchor).days) % len(order)]
    out.palace = palace
    path = image_path(root, palace)
    if not path.is_file():
        out.problem = f"{day} is {palace.name}, but its picture is missing: {palace.image}"
        return out
    out.path = path
    return out


def runs_on(s: Schedule, palaces: list[Palace], now: datetime | None = None) -> dict[str, list[str]]:
    """palace name -> the weekday names it is chosen for (weekday mode), or 'every N days' text via cycle."""
    out: dict[str, list[str]] = {p.name: [] for p in palaces}
    if s.mode == "weekday":
        for day in DAYS:
            n = s.week.get(day, "")
            p = find(palaces, n) if n else None
            if p is not None:
                out[p.name].append(day)
    elif s.mode == "cycle":
        order = cycle_order(palaces, s)
        for p in order:
            out[p.name] = [f"every {len(order)} days"] if len(order) > 1 else ["every day"]
    return out


# ---------------------------------------------------------------- import from GS Companion
@dataclass
class ImportReport:
    copied: list = field(default_factory=list)            # (palace, file) newly written
    same: list = field(default_factory=list)              # already there, identical
    kept: list = field(default_factory=list)              # a different file is already there: not touched
    no_source: list = field(default_factory=list)         # palaces with no picture in the source folder
    listed: list = field(default_factory=list)            # palaces newly added to the list
    already_listed: list = field(default_factory=list)
    weekdays: dict = field(default_factory=dict)          # name -> days the site says it is open
    suggested: dict = field(default_factory=dict)         # the weekday table written on a first import


def gscompanion_stages(src: str | Path) -> list[dict]:
    p = Path(src) / "crest_palace.json"
    if not p.is_file():
        raise FileNotFoundError(f"No crest_palace.json in {src}. Choose the GS Companion data folder (data/gscompanion).")
    return json.loads(p.read_text(encoding="utf-8")).get("stages") or []


TIER_ORDER = ("EXTREME", "NOVA", "PRO")      # which palace a day starts with: the first tier that has one that day


def suggested_week(stages: list[dict]) -> dict[str, str]:
    """A starting weekday table from GS Companion's data (day -> palace name). It is only a suggestion: change it
    in Settings > Palace Selector."""
    out: dict[str, str] = {}
    for day in DAYS:
        open_today = [st for st in stages if day in (st.get("days") or [])]
        for tier in TIER_ORDER:
            hit = next((st for st in open_today if str(st.get("difficulty")).upper() == tier), None)
            if hit:
                out[day] = str(hit["name"])
                break
    return out


def import_from_gscompanion(src: str | Path, root: str | Path) -> ImportReport:
    """Copy every Crest Palace banner into images/ (as PNG, named after its palace) and list it in palaces.yaml.
    Existing pictures and existing list lines are never changed."""
    src, root = Path(src), Path(root)
    rep = ImportReport()
    existing = {p.name.lower(): p for p in read_list(root)}
    new_lines: list[str] = []
    (root / IMAGE_DIR).mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for st in gscompanion_stages(src):
        name = str(st.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rep.weekdays[name] = list(st.get("days") or [])
        rel = f"{IMAGE_DIR}/{slug(name)}.png"
        src_img = src / "images" / "stages" / f"banner_{st.get('stage_id')}.webp"
        img = cv2.imread(str(src_img)) if src_img.is_file() else None
        if img is None:
            rep.no_source.append(name)
            continue
        dst = root / rel
        if dst.exists():
            old = cv2.imread(str(dst))
            (rep.same if old is not None and old.shape == img.shape and (old == img).all() else rep.kept).append((name, rel))
        else:
            cv2.imwrite(str(dst), img)
            rep.copied.append((name, rel))
        if name.lower() in existing:
            rep.already_listed.append(name)
        else:
            new_lines.append(line_for(Palace(name, rel)))
            rep.listed.append(name)
    if new_lines:
        path = root / LIST_FILE
        had = path.is_file() and path.read_text(encoding="utf-8").strip()
        with path.open("a", encoding="utf-8") as f:
            if not had:
                f.write(LIST_HEADER)
            elif not path.read_text(encoding="utf-8").endswith("\n"):
                f.write("\n")
            f.writelines(new_lines)
    if not (root / SCHEDULE_FILE).is_file():                  # first import: start from the site's week, selector ON
        listed = {p.name for p in read_list(root)}
        rep.suggested = {d: n for d, n in suggested_week(gscompanion_stages(src)).items() if n in listed}
        save_schedule(root, Schedule("weekday", rep.suggested))
    return rep

