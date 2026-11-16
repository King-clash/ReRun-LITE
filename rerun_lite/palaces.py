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

The time zone ("timezone" in the schedule file) only changes how that clock is SHOWN: which of your local days and
times each palace's slot starts and ends. Which palace runs is always decided by the game day, so choosing a zone can
never make Crest open the wrong palace. "computer" (the default) follows this PC's own zone, daylight saving included;
"UTC+10:00" style choices are fixed offsets.

Nothing here writes over an existing picture or an existing palace line: the import skips what is already there
and says so.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
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
    timezone: str = "computer"      # "computer" or "UTC+HH:MM": how slot times are shown (never which palace runs)


@dataclass
class Choice:
    """What to run today. `problem` is non-empty when nothing may run (say why instead of running something else)."""
    mode: str
    day: str
    game_date: date
    palace: Palace | None = None
    path: Path | None = None
    problem: str = ""
    starts: datetime | None = None      # this game day's slot, on the game clock (UTC-6)
    ends: datetime | None = None

    @property
    def ok(self) -> bool:
        return not self.problem and self.palace is not None and self.path is not None


# ---------------------------------------------------------------- the game day
def game_date(now: datetime | None = None) -> date:
    """The game's calendar day: it turns over at RESET_HOUR in GAME_TZ (6 AM UTC-6)."""
    now = (now or datetime.now(GAME_TZ)).astimezone(GAME_TZ)
    return (now - timedelta(hours=RESET_HOUR)).date()


def slot_times(gd: date) -> tuple[datetime, datetime]:
    """When game day `gd` starts and ends, on the game clock (UTC-6): reset to the next reset."""
    start = datetime(gd.year, gd.month, gd.day, RESET_HOUR, tzinfo=GAME_TZ)
    return start, start + timedelta(days=1)


# ---------------------------------------------------------------- time zones (display only)
TZ_COMPUTER = "computer"
_TZ_SPEC = re.compile(r"^UTC([+-])(\d{1,2}):([0-5]\d)$")
# standard-time hints for the picker; a fixed offset never shifts for daylight saving
_TZ_HINTS = {
    "UTC-10:00": "Hawaii", "UTC-09:00": "Alaska", "UTC-08:00": "US Pacific", "UTC-07:00": "US Mountain",
    "UTC-06:00": "US Central - the game clock", "UTC-05:00": "US Eastern", "UTC-04:00": "Atlantic, Puerto Rico",
    "UTC-03:00": "Brasilia, Buenos Aires", "UTC+00:00": "London, UTC", "UTC+01:00": "Paris, Berlin",
    "UTC+02:00": "Athens, Cairo, Johannesburg", "UTC+03:00": "Moscow, Riyadh", "UTC+05:30": "India",
    "UTC+07:00": "Bangkok, Jakarta", "UTC+08:00": "Manila, Singapore, Perth", "UTC+09:00": "Tokyo, Seoul",
    "UTC+09:30": "Darwin, Adelaide", "UTC+10:00": "Guam, Brisbane", "UTC+11:00": "Sydney (summer), Noumea",
    "UTC+12:00": "Auckland (winter), Fiji",
}
_TZ_OFFSETS = [(-12, 0)] + [(h, 0) for h in range(-11, 15)] + [(-9, 30), (-3, 30), (3, 30), (4, 30), (5, 30),
                                                               (5, 45), (6, 30), (8, 45), (9, 30), (10, 30), (12, 45)]


def _spec(sign: int, h: int, m: int) -> str:
    return f"UTC{'-' if sign < 0 else '+'}{h:02d}:{m:02d}"


def parse_tz(spec: str) -> tzinfo | None:
    """The zone for a saved choice: None = this computer's own zone (which also follows daylight saving),
    otherwise a fixed offset. Anything unreadable or out of range (-12:00 to +14:00) means this computer."""
    m = _TZ_SPEC.match((spec or "").strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    h, mi = int(m.group(2)), int(m.group(3))
    total = sign * (h * 60 + mi)
    if not -12 * 60 <= total <= 14 * 60:
        return None
    return timezone(timedelta(minutes=total))


def normalize_tz(spec: str) -> str:
    """A saved choice as the picker knows it: 'computer' or a clean 'UTC+HH:MM'."""
    z = parse_tz(spec)
    if z is None:
        return TZ_COMPUTER
    minutes = int(z.utcoffset(None).total_seconds() // 60)
    return _spec(-1 if minutes < 0 else 1, abs(minutes) // 60, abs(minutes) % 60)


def in_zone(dt: datetime, spec: str) -> datetime:
    """`dt` (any aware time) written in the chosen zone."""
    z = parse_tz(spec)
    return dt.astimezone(z) if z is not None else dt.astimezone()


def zone_name(spec: str, now: datetime | None = None) -> str:
    """Short name for a choice: 'UTC+10:00', or this computer's current offset for the computer zone."""
    if parse_tz(spec) is None:
        off = (now or datetime.now(timezone.utc)).astimezone().utcoffset() or timedelta(0)
        minutes = int(off.total_seconds() // 60)
        return _spec(-1 if minutes < 0 else 1, abs(minutes) // 60, abs(minutes) % 60)
    return normalize_tz(spec)


def tz_choices(now: datetime | None = None) -> list[tuple[str, str]]:
    """[(saved value, label shown)] for the picker: this computer first, then every offset in order."""
    out = [(TZ_COMPUTER, f"This computer ({zone_name(TZ_COMPUTER, now)}, follows daylight saving)")]
    seen = set()
    for h, m in sorted(_TZ_OFFSETS, key=lambda hm: hm[0] * 60 + (hm[1] if hm[0] >= 0 else -hm[1])):
        spec = _spec(-1 if h < 0 else 1, abs(h), m)
        if spec in seen:
            continue
        seen.add(spec)
        hint = _TZ_HINTS.get(spec)
        out.append((spec, f"{spec}" + (f"   {hint}" if hint else "")))
    return out


def fmt_when(dt: datetime, spec: str) -> str:
    """'Mon 22:00' for an instant in the chosen zone (24-hour clock)."""
    return in_zone(dt, spec).strftime("%a %H:%M")


def fmt_slot(start: datetime, end: datetime, spec: str) -> str:
    """'Mon 22:00 to Tue 22:00 (UTC+10:00)': the whole slot in the chosen zone."""
    return f"{fmt_when(start, spec)} to {fmt_when(end, spec)} ({zone_name(spec, start)})"


def fmt_left(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60:02d}m" if h else f"{rem // 60}m"


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
                    str(cyc.get("start") or ""), str(cyc.get("anchor") or ""), [str(n) for n in cyc.get("only") or []],
                    normalize_tz(str(raw.get("timezone") or TZ_COMPUTER)))


def save_schedule(root: str | Path, s: Schedule) -> None:
    path = Path(root) / SCHEDULE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"mode": s.mode, "timezone": normalize_tz(s.timezone), "week": s.week,
            "cycle": {"start": s.cycle_start, "anchor": s.cycle_anchor, "only": s.cycle_only}}
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")


def cycle_order(palaces: list[Palace], s: Schedule) -> list[Palace]:
    """The palaces the cycle walks through, in list order (all of them unless the schedule names a subset)."""
    only = {n.lower() for n in s.cycle_only}
    return [p for p in palaces if not only or p.name.lower() in only]


def palace_for(gd: date, s: Schedule, palaces: list[Palace]) -> tuple[Palace | None, str]:
    """The palace for game day `gd` under schedule `s`, or (None, why not). Never falls back to another palace."""
    day = DAYS[gd.weekday()]
    if not palaces:
        return None, f"The palace list ({LIST_FILE}) is empty. Import the palaces or add lines to it."
    if s.mode == "weekday":
        name = s.week.get(day, "")
        if not name:
            return None, f"No palace is chosen for {day} in the weekday table."
        palace = find(palaces, name)
        if palace is None:
            return None, f"{day}'s palace '{name}' is not in {LIST_FILE}."
        return palace, ""
    order = cycle_order(palaces, s)
    if not order:
        return None, "The cycle has no palaces (check the cycle list)."
    start = next((i for i, p in enumerate(order) if p.name.lower() == s.cycle_start.strip().lower()), 0)
    try:
        anchor = date.fromisoformat(s.cycle_anchor)
    except ValueError:
        anchor = gd
    return order[(start + (gd - anchor).days) % len(order)], ""


def choose(root: str | Path, now: datetime | None = None) -> Choice:
    """Which palace runs today, and where its picture is. Never falls back to another palace."""
    gd = game_date(now)
    day = DAYS[gd.weekday()]
    s = load_schedule(root)
    out = Choice(s.mode, day, gd)
    out.starts, out.ends = slot_times(gd)
    if s.mode == "off":
        return out
    try:
        palaces = read_list(root)
    except ValueError as e:
        out.problem = str(e)
        return out
    palace, why = palace_for(gd, s, palaces)
    if palace is None:
        out.problem = why
        return out
    out.palace = palace
    path = image_path(root, palace)
    if not path.is_file():
        out.problem = f"{day} is {palace.name}, but its picture is missing: {palace.image}"
        return out
    out.path = path
    return out


# ---------------------------------------------------------------- slots: which palace, when, in your time zone
@dataclass(frozen=True)
class Slot:
    game_date: date
    day: str                  # the game weekday this slot belongs to
    palace: Palace | None
    start: datetime           # when the slot begins / ends, in the chosen zone
    end: datetime
    problem: str = ""

    @property
    def local_day(self) -> str:
        """The weekday it STARTS on in the chosen zone (can differ from `day`: a UTC+10 player's game Monday
        starts on their Monday evening, a UTC+14 player's on their Tuesday)."""
        return self.start.strftime("%A")


def slot_on(root: str | Path, gd: date, spec: str | None = None, palaces: list[Palace] | None = None,
            s: Schedule | None = None) -> Slot:
    """The slot of game day `gd`, written in the zone `spec` (default: the one saved in the schedule)."""
    s = s or load_schedule(root)
    spec = s.timezone if spec is None else spec
    if palaces is None:
        try:
            palaces = read_list(root)
        except ValueError:
            palaces = []
    start, end = slot_times(gd)
    day = DAYS[gd.weekday()]
    palace, why = (None, "The selector is off.") if s.mode == "off" else palace_for(gd, s, palaces)
    if palace is not None and not image_path(root, palace).is_file():
        why = f"picture missing: {palace.image}"
    return Slot(gd, day, palace, in_zone(start, spec), in_zone(end, spec), why)


def slots(root: str | Path, days: int = 7, now: datetime | None = None, spec: str | None = None) -> list[Slot]:
    """The next `days` game days from today, each with its palace and its start and end in the chosen zone."""
    s = load_schedule(root)
    try:
        palaces = read_list(root)
    except ValueError:
        palaces = []
    gd = game_date(now)
    return [slot_on(root, gd + timedelta(days=i), spec, palaces, s) for i in range(max(0, days))]


def next_slot_for_day(root: str | Path, day: str, now: datetime | None = None, spec: str | None = None) -> Slot:
    """The next (or current) slot of game weekday `day`, e.g. for the weekday table's row labels."""
    gd = game_date(now)
    gd += timedelta(days=(DAYS.index(day) - gd.weekday()) % 7)
    return slot_on(root, gd, spec)


def until_switch(now: datetime | None = None) -> float:
    """Seconds until the game day (and so the palace) changes."""
    now = now or datetime.now(GAME_TZ)
    return (slot_times(game_date(now))[1] - now).total_seconds()


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

