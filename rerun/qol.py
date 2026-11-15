"""Small pure helpers behind the quality-of-life settings (times, name lists, window position).

Kept free of Tk / ADB so every rule can be tested on its own."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_HHMM = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")


def parse_hhmm(text: str) -> tuple[int, int] | None:
    """'07:30' -> (7, 30); None when it isn't a 24-hour HH:MM time."""
    m = _HHMM.match(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def next_time_after(now: datetime, hhmm: str) -> datetime | None:
    """The next moment the wall clock shows HH:MM (today if still ahead, else tomorrow)."""
    t = parse_hhmm(hhmm)
    if t is None:
        return None
    cand = now.replace(hour=t[0], minute=t[1], second=0, microsecond=0)
    return cand if cand > now else cand + timedelta(days=1)


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    """Whether `now` is inside the quiet window; the window may cross midnight (23:00-07:00).
    A missing/invalid time or start == end means no quiet hours."""
    a, b = parse_hhmm(start), parse_hhmm(end)
    if a is None or b is None or a == b:
        return False
    cur = (now.hour, now.minute)
    return (a <= cur < b) if a < b else (cur >= a or cur < b)


def split_names(text: str) -> list[str]:
    """'Cursed Claw, Whirlwind; Light' -> ['Cursed Claw', 'Whirlwind', 'Light'] (order kept)."""
    return [p.strip() for p in re.split(r"[,;|\n]", text or "") if p.strip()]


def _day_index(token: str) -> int | None:
    t = token.strip().lower()[:3]
    return DAY_NAMES.index(t) if t in DAY_NAMES else None


def parse_day_table(text: str) -> dict[int, list[str]]:
    """'Mon: Cursed Claw, Whirlwind; Sat,Sun: Heavenly Light' -> {0: [...], 5: [...], 6: [...]}.
    Entries are separated by ';' or new lines, days by ',' or '-' ranges are not supported."""
    table: dict[int, list[str]] = {}
    for entry in re.split(r"[;\n]", text or ""):
        if ":" not in entry:
            continue
        days_part, names_part = entry.split(":", 1)
        days = [_day_index(d) for d in days_part.split("/") if d.strip()] if "/" in days_part else \
               [_day_index(d) for d in re.split(r"[ ]+", days_part.strip()) if d.strip()]
        names = split_names(names_part.replace(";", ","))
        for d in days:
            if d is not None and names:
                table.setdefault(d, []).extend(names)
    return table


def names_for_day(weekday: int, day_table_text: str, default_text: str) -> list[str]:
    """Palace names to try on a weekday: that day's row of the table, else the default list."""
    table = parse_day_table(day_table_text)
    return table.get(weekday) or split_names(default_text)


def table_problems(day_table_text: str) -> list[str]:
    """Entries of a day table that could not be read (shown as a warning instead of ignored)."""
    out = []
    for entry in re.split(r"[;\n]", day_table_text or ""):
        if not entry.strip():
            continue
        if ":" not in entry:
            out.append(f"'{entry.strip()}' has no ':' (write Mon: Name, Name)")
            continue
        days_part = entry.split(":", 1)[0]
        toks = days_part.split("/") if "/" in days_part else days_part.split()
        if not toks or any(_day_index(t) is None for t in toks if t.strip()):
            out.append(f"'{days_part.strip()}' is not a weekday (use Mon Tue Wed Thu Fri Sat Sun)")
    return out


# ---- alerts ---------------------------------------------------------------------------------
PING_KEYS = {"gold": "rare", "red": "problem", "green": "finished", "info": "other"}


def ping_allowed(kind: str, toggles: dict | None) -> bool:
    """Does the user want an @mention for this kind of alert (gold/red/green/info)?"""
    return bool((toggles or {}).get(PING_KEYS.get(kind, "other"), True))


# ---- window position ----------------------------------------------------------------------------
_GEO = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")   # Tk writes negatives as +-10


def clamp_geometry(geo: str, screen_w: int, screen_h: int, min_w: int = 600, min_h: int = 400) -> str:
    """A saved 'WxH+X+Y' that is safe to restore on the current screens: '' when it can't be read
    or would put the window (mostly) off screen - the caller then keeps its default."""
    m = _GEO.match((geo or "").strip())
    if not m:
        return ""
    w, h = int(m.group(1)), int(m.group(2))
    x, y = int(m.group(3)), int(m.group(4))
    if w < min_w or h < min_h or w > screen_w * 2 or h > screen_h * 2:
        return ""
    w, h = min(w, screen_w), min(h, screen_h)
    # at least 200 px of the title bar must stay reachable on the current screen
    if x > screen_w - 200 or y > screen_h - 80 or x + w < 200 or y < -10:
        return ""
    return f"{w}x{h}+{x}+{y}"
