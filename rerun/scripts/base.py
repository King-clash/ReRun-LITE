"""Shared machinery for farming scripts.

Every script is a state machine: each tick it takes a screenshot, works out
which screen the game is on (first matching template wins, in STATES order),
and calls `handle_<state>`. Because it reacts to what is on screen instead of
following a fixed sequence, it recovers from popups, lag and crashes on its own.

Built for BlueStacks set to 1280x720. Grand Summoners runs in portrait, so the
frames the scripts see are 720 wide x 1280 tall.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from .. import errlog
from ..adb import AdbError
from ..engine import Context, StopRoutine
from ..vision import Match, MissingTemplate

BASE_W, BASE_H = 720, 1280  # portrait game frame
GAME_TZ = timezone(timedelta(hours=-6))  # Grand Summoners' reset clock (UTC-6)
DAILY_RESET_HOUR = 6


class Finished(StopRoutine):
    """The script stopped on purpose - possibly because something needs you
    (a rare crest left on screen, an Omega boss...). A chain stops here."""


class Done(Finished):
    """The script simply completed: runs done, out of energy, mailbox empty.
    Nothing needs you, so a chain may carry on with its next step."""


class WindowElapsed(StopRoutine):
    """A time-boxed script (e.g. Crest inside Queue) used up its window."""


@dataclass
class Setting:
    key: str
    label: str
    type: str  # int | bool | choice | text
    default: Any
    choices: list[str] = field(default_factory=list)
    help: str = ""


@dataclass
class T:
    """A template the script needs, with capture instructions for the user."""
    name: str
    description: str
    optional: bool = False


# Popups recognised by their words when no template matched (the screen stayed
# "unknown"). (phrases, action, buttons to tap - first found wins)
TEXT_POPUPS: list[tuple[tuple[str, ...], str, tuple[str, ...]]] = [
    (("unexpected error",), "tap", ("OK",)),
    (("communication error", "connection error", "network error", "failed to connect",
      "could not connect", "connection timed out", "timed out"), "tap", ("Retry", "OK")),
    (("date has changed", "returning to title"), "tap", ("OK",)),
    (("potion to restore your energy",), "tap", ("OK",)),  # "Used L Potion to restore your energy."
    (("under maintenance", "maintenance"), "maintenance", ()),
    (("new version", "please update", "update the app", "download the latest"), "stop", ()),
]
TEXT_CHECK_AFTER_S = 8    # unknown this long before reading the screen
TEXT_CHECK_EVERY_S = 20   # and at most this often (reading takes ~0.5-1 s)


def _norm(s: str) -> str:
    return " ".join("".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").split())


def game_now() -> datetime:
    return datetime.now(GAME_TZ)


def game_weekday() -> int:
    """Weekday (0 = Monday) of the GAME day, which starts at the 6 AM UTC-6 reset, not at midnight."""
    return (game_now() - timedelta(hours=DAILY_RESET_HOUR)).weekday()


def next_reset_after(ref: datetime, hour: int = DAILY_RESET_HOUR) -> datetime:
    cut = ref.replace(hour=hour, minute=0, second=0, microsecond=0)
    return cut if cut > ref else cut + timedelta(days=1)


# Popups any script may meet. Order matters only within this list.
COMMON_TEMPLATES = [
    T("unexpected_error", "OK button of the 'An unexpected error has occurred' popup.", optional=True),
    T("unexpected_error_text", "The error message text of that popup (needed so a plain OK "
                               "elsewhere isn't mistaken for it).", optional=True),
    T("data_download_prompt", "Title/text of the 'download additional data' popup.", optional=True),
    T("xpop_up", "The small X that closes surprise pop-ups / banners.", optional=True),
    T("summon_later_button", "'Later' button on the free-summon prompt after login.", optional=True),
    T("summon_close_button", "Close button on the summon prompt.", optional=True),
    T("total_sign_in_bonus", "Title of the Total Sign-in Bonus screen (tap anywhere to continue).", optional=True),
    T("data_download_ok", "OK on the 'Download additional data' popup.", optional=True),
    T("info_close_button", "Close button of the Information/news dialog shown after login.", optional=True),
    T("game_start_screen", "A button only shown on the Game Start (title) screen, e.g. 'Transfer Device' "
                           "at the bottom. Needed for 24/7 mode.", optional=True),
    T("potion_used_ok", "Blue OK of the 'Used L Potion to restore your energy.' popup.", optional=True),
    T("potion_used_text", "'your energy.' line of that popup (so a lone blue OK elsewhere doesn't count).",
      optional=True),
]


DEBUG_KEEP = 60     # newest screenshots kept in debug/ (each is about 1 MB); older ones are deleted


def prune_debug_folder(folder, keep: int = DEBUG_KEEP) -> int:
    """Delete the oldest .png files in `folder` beyond the newest `keep`. Returns how many went.
    The names start with a timestamp, so sorting by name is sorting by age."""
    try:
        files = sorted(f for f in folder.iterdir() if f.suffix.lower() == ".png")
    except OSError as e:
        errlog.note("base.prune_debug", e)
        return 0
    removed = 0
    for f in files[:max(0, len(files) - keep)]:
        try:
            f.unlink()
            removed += 1
        except OSError as e:
            errlog.note("base.prune_debug", e)
    return removed


class BaseScript:
    ID = "base"
    NAME = "Base"
    BETA = False  # built from ReStart's flow but not yet run on a real game
    DESCRIPTION = ""
    INSTRUCTIONS = ""
    SETTINGS: list[Setting] = []
    TEMPLATES: list[T] = []
    # (state, [templates]) checked in order; first visible wins.
    STATES: list[tuple[str, list[str]]] = []
    # Simple states that only need "tap this template": state -> (template, log, settle)
    TAPS: dict[str, tuple[str, str, float]] = {}
    UNKNOWN_SNAPSHOT_S = 5 * 60  # save one frame when the screen is unrecognised this long
    # (state, templates[, context templates that must ALSO be visible])
    # A bare orange "OK" is on dozens of screens, so popups whose button is a
    # plain OK only count when that popup's own title/text is on screen too.
    COMMON_STATES: list[tuple] = [
        # Seen live: after a potion the game shows this over whatever was on screen.
        ("potion_used", ["potion_used_ok"], ["potion_used_text"]),
        ("unexpected_error", ["unexpected_error"], ["unexpected_error_text"]),
        ("data_download_ok", ["data_download_ok"], ["data_download_prompt"]),
        ("summon_later_button", ["summon_later_button"]),
        ("summon_close_button", ["summon_close_button"]),
        ("total_sign_in_bonus", ["total_sign_in_bonus"]),
        ("xpop_up", ["xpop_up"]),
        ("info_close_button", ["info_close_button"]),
        ("game_start_screen", ["game_start_screen"]),
    ]
    # States whose button must be lit: when a popup dims the screen, the button
    # underneath still matches (matching ignores brightness), and tapping it does
    # nothing. A dimmed match is skipped so the popup gets handled instead.
    LIT_STATES: set[str] = set()
    DIM_RATIO = 0.6
    LIT_RATIO: dict[str, float] = {}  # stricter per-state ratios
    TICK = 0.8
    NO_PROGRESS_RESTART_S = 20 * 60  # restart the game if nothing advances this long
    MAX_REPEAT = 25  # same state handled this many times in a row = stuck
    WAITING_STATES = {"unknown", "drop_info", "equip_crest_screen", "mail_close_button"}

    @property
    def last_progress(self) -> float:
        return self._last_progress

    @last_progress.setter
    def last_progress(self, value: float) -> None:
        self._last_progress = value
        self.ctx.params["last_progress"] = value        # read by the window's stuck watch (rerun_lite/stuck.py)

    def __init__(self, ctx: Context, settings: dict | None = None):
        self.ctx = ctx
        self.cfg = {s.key: s.default for s in self.SETTINGS}
        self.cfg.update(self.migrate_settings(dict(settings or {})))
        self.state = "unknown"
        self.prev_state = "unknown"
        self.last_progress = time.monotonic()
        self.next_reset = next_reset_after(game_now())
        self.screen_img: np.ndarray | None = None
        self.session_runs = 0
        self.repeat = 0
        self._unknown_since: float | None = None
        self._unknown_saved = False
        self.deadline: float | None = None  # monotonic time; set by Queue for time windows

    @classmethod
    def display_name(cls) -> str:
        return f"{cls.NAME} (Beta)" if cls.BETA else cls.NAME

    # ------------------------------------------------------------ plumbing
    @classmethod
    def all_templates(cls) -> list[T]:
        seen, out = set(), []
        for t in cls.TEMPLATES + COMMON_TEMPLATES:
            if t.name not in seen:
                seen.add(t.name)
                out.append(t)
        return out

    def log(self, msg: str) -> None:
        self.ctx.log(self.ctx.instance, f"[{self.NAME}] {msg}")

    def notify(self, msg: str, screenshot: bool = True, ping: bool = True) -> None:
        self.ctx.notify(self.ctx.instance, msg,
                        image=self.screen_img if screenshot else None, ping=ping)

    def count(self, key: str, n: int = 1) -> None:
        self.ctx.stats.incr(self.ctx.instance, f"{self.ID}.{key}", n)

    def progress(self) -> None:
        """Call whenever the farm meaningfully advances (resets the idle watchdog)."""
        self.last_progress = time.monotonic()

    def record(self, kind: str, detail: str, image: np.ndarray | None = None, **extra) -> None:
        """Add an entry to the History tab (crests, drops, failures...)."""
        h = self.ctx.history
        if h is not None:
            h.add(self.ctx.instance, self.ID, kind, detail,
                  image if image is not None else self.screen_img, **extra)

    # ------------------------------------------------------------ text (OCR)
    @property
    def ocr(self):
        """Tesseract reader, or None when it isn't available on this PC."""
        if not hasattr(self, "_ocr"):
            from ..ocr import OcrUnavailable, get_ocr
            try:
                self._ocr = get_ocr(self.ctx.params.get("tesseract_path"))
            except OcrUnavailable as e:
                self.log(str(e))
                self._ocr = None
        return self._ocr

    def read_text(self, x: int, y: int, w: int, h: int, screen: np.ndarray | None = None,
                  min_conf: float = 75.0, **kw) -> str | None:
        """Text in a box of the 720x1280 frame; None if unreadable or not confident."""
        if self.ocr is None:
            return None
        img = screen if screen is not None else (self.screen_img if self.screen_img is not None
                                                 else self.grab())
        r = self.ocr.read_region(img, x, y, w, h, **kw)
        return r.text if r and r.confidence >= min_conf else None

    def read_number(self, x: int, y: int, w: int, h: int,
                    screen: np.ndarray | None = None) -> int | None:
        if self.ocr is None:
            return None
        img = screen if screen is not None else (self.screen_img if self.screen_img is not None
                                                 else self.grab())
        return self.ocr.read_number(img[max(0, y):y + h, max(0, x):x + w])

    def closest_screens(self, screen: np.ndarray, n: int = 3) -> str:
        """'exploring_button 0.62, home_nav_button 0.41': which known screens this frame resembles
        most (best template scores, even below the match threshold). Makes a 'stuck' or
        'unrecognised' report actionable: a score just under the threshold means re-capture
        that template; low scores everywhere mean a screen Rerun has never seen."""
        try:
            names = list(dict.fromkeys(t for e in self.COMMON_STATES + self.STATES for t in e[1]))
            scores = []
            for name in names:
                try:
                    m = self.ctx.vision.score(screen, name)
                except MissingTemplate:
                    continue
                if m is not None:
                    scores.append((m.score, name))
            return ", ".join(f"{name} {sc:.2f}" for sc, name in sorted(scores, reverse=True)[:n])
        except Exception as e:  # noqa: BLE001 - diagnostics must never break a script
            errlog.note("base.closest_screens", e)
            return ""

    def describe_screen(self, screen: np.ndarray) -> str:
        """The words on screen, for stuck/unknown reports ('' without OCR)."""
        try:
            return self.ocr.screen_text(screen) if self.ocr is not None else ""
        except Exception as e:  # noqa: BLE001 - diagnostics must never break a script
            errlog.note("base.screen_text", e)
            return ""

    def save_frame(self, tag: str, screen: np.ndarray | None = None) -> str | None:
        """Save a frame to debug/ (e.g. when stuck) so it can be inspected or captured."""
        img = screen if screen is not None else self.screen_img
        if img is None:
            return None
        import cv2
        from pathlib import Path
        folder = Path(self.ctx.data_dir or ".") / "debug"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{time.strftime('%Y%m%d_%H%M%S')}_{self.ID}_{tag}.png"
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(str(path))
            prune_debug_folder(folder)
            return str(path)
        return None

    def checkpoint(self) -> None:
        if self.ctx.stop_event.is_set():
            raise StopRoutine("stopped by user")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise WindowElapsed("time window elapsed")
        paused = False
        while self.ctx.pause_event.is_set():
            paused = True
            if self.ctx.stop_event.is_set():
                raise StopRoutine("stopped by user")
            time.sleep(0.2)
            self.last_progress = time.monotonic()  # pausing is not "stuck"
        if paused:
            self.log("Resumed")
            self.on_resume()

    def on_resume(self) -> None:
        """Called once when a pause ends (the game may have been touched meanwhile)."""

    @classmethod
    def migrate_settings(cls, saved: dict) -> dict:
        """Upgrade settings saved by an older Rerun (read-time only; config.yaml is
        rewritten in the new form the next time the user saves Settings)."""
        return saved

    def sleep(self, seconds: float, jitter: float = 0.0) -> None:
        end = time.monotonic() + seconds + (random.uniform(0, jitter) if jitter else 0)
        while time.monotonic() < end:
            self.checkpoint()
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def grab(self) -> np.ndarray:
        self.checkpoint()
        self.screen_img = self.ctx.device.screencap()
        self.ctx.last_screen = self.screen_img  # the live view shows this; no extra capture
        self._maybe_update_energy(self.screen_img)
        return self.screen_img

    ENERGY_EVERY_S = 60

    def _maybe_update_energy(self, frame: np.ndarray) -> None:
        """About once a minute, read the energy bar in the background (the script
        never waits on it) for the dashboard: ctx.params['energy'] = (cur, max, time)."""
        now = time.monotonic()
        if now - getattr(self, "_energy_at", -1e9) < self.ENERGY_EVERY_S or \
                getattr(self, "_energy_busy", False) or self.ocr is None:
            return
        self._energy_at, self._energy_busy = now, True
        img = frame.copy()

        def work():
            from ..ocr import read_energy
            try:
                e = read_energy(self.ocr, img)
                if e:
                    self.ctx.params["energy"] = (e[0], e[1], time.time())
            except Exception as e:  # noqa: BLE001 - informational only
                errlog.note("base.energy_read", e)
            finally:
                self._energy_busy = False
        import threading
        threading.Thread(target=work, daemon=True).start()

    def find(self, name: str, screen: np.ndarray | None = None,
             threshold: float | None = None, region=None) -> Match | None:
        img = screen if screen is not None else self.grab()
        try:
            return self.ctx.vision.find(img, name, threshold, region)
        except MissingTemplate:
            return None

    def has_template(self, name: str) -> bool:
        return self.ctx.vision.store.has(name)

    def require_template(self, name: str) -> None:
        if not self.has_template(name):
            raise MissingTemplate(name)

    def tap(self, x: int, y: int, settle: float = 0.6) -> None:
        self.ctx.device.tap(x, y)
        self.sleep(settle, jitter=0.3)

    def tap_base(self, x: int, y: int, settle: float = 0.6) -> None:
        """Tap a point given in 720x1280 (portrait frame) coordinates."""
        img = self.screen_img if self.screen_img is not None else self.grab()
        h, w = img.shape[:2]
        self.tap(int(x * w / BASE_W), int(y * h / BASE_H), settle)

    def tap_match(self, m: Match, settle: float = 0.6) -> None:
        self.tap(*m.center, settle=settle)

    def tap_template(self, name: str, screen: np.ndarray | None = None,
                     settle: float = 0.6) -> bool:
        m = self.find(name, screen)
        if m:
            self.tap_match(m, settle)
            return True
        return False

    def wait_for(self, names: list[str], timeout: float) -> Match | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            img = self.grab()
            for n in names:
                m = self.find(n, img)
                if m:
                    return m
            self.sleep(0.5)
        return None

    # ------------------------------------------------------------ state machine
    def detect_state(self, screen: np.ndarray) -> str:
        for entry in self.COMMON_STATES + self.STATES:
            state, names = entry[0], entry[1]
            context = entry[2] if len(entry) > 2 else []
            if context and not all(self.find(c, screen) for c in context):
                continue  # a missing context template also means "never"
            for n in names:
                m = self.find(n, screen)
                if m and not (state in self.LIT_STATES and self.dimmed(screen, m, state)):
                    return state
        return "unknown"

    def dimmed(self, screen: np.ndarray, m: Match, state: str | None = None) -> bool:
        v = self.ctx.vision
        ratio = self.LIT_RATIO.get(state, self.DIM_RATIO)
        return v.brightness(screen, m) < ratio * v.template_brightness(m.name)

    def run(self) -> None:
        self.check_setup()
        self.log("Script started")
        self.on_start()
        while True:
            self.checkpoint()
            try:
                screen = self.grab()
            except AdbError as e:
                self.log(f"Screenshot failed ({e}) - retrying")
                self.sleep(3)
                self.recover_crash()
                continue
            if self.housekeeping(screen):
                continue
            state = self.detect_state(screen)
            if state != self.state:
                self.log(f"State: {state}")
                self.repeat = 0
            elif state not in self.WAITING_STATES:
                self.repeat += 1
                if self.repeat >= self.MAX_REPEAT:
                    saved = self.save_frame(f"stuck_{state}", screen)
                    words = self.describe_screen(screen)
                    close = self.closest_screens(screen)
                    self.notify(f"{self.NAME} is stuck: it handled '{state}' {self.repeat} times in a "
                                "row and the screen didn't change. Stopped - please check the emulator."
                                + (f" Screen says: \"{words[:200]}\"." if words else "")
                                + (f" Closest known screens: {close}." if close else "")
                                + (f" Frame saved to {saved}." if saved else ""))
                    raise StopRoutine(f"stuck on {state}")
            self._watch_unknown(state, screen)
            if state == "unknown" and self._text_safety_net(screen):
                self.sleep(self.TICK)
                continue
            self.prev_state, self.state = self.state, state
            self.ctx.params["script_state"] = state       # for the window's run phase (rerun_lite/phases.py)
            handler = getattr(self, f"handle_{state}", None)
            if handler is None:
                handler = self._tap_handler if state in self.TAPS else self.handle_unknown
            handler(screen)
            self.sleep(self.TICK, jitter=0.2)

    def _text_safety_net(self, screen: np.ndarray) -> bool:
        """When nothing matched for a while, read the screen: known popups (errors,
        'Retry', maintenance...) are handled by their words, no template needed.
        True if it acted."""
        now = time.monotonic()
        if self._unknown_since is None or now - self._unknown_since < TEXT_CHECK_AFTER_S:
            return False
        if now - getattr(self, "_last_text_check", 0.0) < TEXT_CHECK_EVERY_S or self.ocr is None:
            return False
        self._last_text_check = now
        try:
            words = self.ocr.screen_words(screen)
        except Exception as e:  # noqa: BLE001 - the safety net must never break a script
            errlog.note("base.text_safety_net", e)
            return False
        text = _norm(" ".join(w.text for w in words))
        for phrases, action, buttons in TEXT_POPUPS:
            hit = next((p for p in phrases if p in text), None)
            if not hit:
                continue
            said = " ".join(w.text for w in words)[:160]
            self.count("text_popups")
            if action == "tap":
                for label in buttons:
                    cands = [w for w in words if _norm(w.text) == label.lower()]
                    if cands:
                        btn = max(cands, key=lambda w: w.y)  # buttons sit below the message
                        self.log(f"Read a '{hit}' popup (\"{said}\") - tapping {label}")
                        self.record("popup", f"'{hit}' popup - tapped {label}", screen)
                        self.tap(*btn.center, settle=2.0)
                        self.progress()
                        return True
                self.log(f"Read a '{hit}' popup but no {'/'.join(buttons)} button: \"{said}\"")
                return False
            if action == "maintenance" and self.cfg.get("mode_247"):
                self.record("popup", "Game maintenance - waiting 10 minutes", screen)
                self.notify(f"{self.NAME}: the game is under maintenance. Waiting 10 minutes, "
                            "then relaunching (24/7 mode).", ping=False)
                end = time.monotonic() + 600
                while time.monotonic() < end:
                    self.sleep(min(30, end - time.monotonic()))
                    self.progress()
                self.restart_game(scheduled=True)   # expected: the game was down for maintenance
                return True
            self.record("popup", f"'{hit}' screen - stopped", screen)
            self.notify(f"{self.NAME}: the game says \"{said}\". Stopped - this needs you.")
            raise StopRoutine(f"game shows '{hit}'")
        return False

    def _tap_handler(self, screen: np.ndarray) -> None:
        tpl, msg, settle = self.TAPS[self.state]
        if self.tap_template(tpl, screen, settle=settle) and msg:
            self.log(msg)

    def _watch_unknown(self, state: str, screen: np.ndarray) -> None:
        """A screen nothing recognises for minutes is worth one saved frame: it is
        usually a popup that needs its own template (capture it from debug/)."""
        if state != "unknown":
            self._unknown_since, self._unknown_saved = None, False
            return
        now = time.monotonic()
        if self._unknown_since is None:
            self._unknown_since = now
        elif not self._unknown_saved and now - self._unknown_since > self.UNKNOWN_SNAPSHOT_S:
            self._unknown_saved = True
            saved = self.save_frame("unrecognised", screen)
            words = self.describe_screen(screen)
            close = self.closest_screens(screen)
            self.log(f"Screen unrecognised for {self.UNKNOWN_SNAPSHOT_S // 60} min - saved {saved}. "
                     + (f"Screen says: \"{words[:200]}\". " if words else "")
                     + (f"Closest known screens: {close}. " if close else "")
                     + "If it's a popup, capture its button in the Templates tab.")

    def check_setup(self) -> None:
        missing = [t.name for t in self.TEMPLATES if not t.optional and not self.has_template(t.name)]
        if missing:
            raise MissingTemplate(missing[0] if len(missing) == 1 else
                                  f"{missing[0]} (+{len(missing) - 1} more: {', '.join(missing[1:6])})")
        img = self.grab()
        h, w = img.shape[:2]
        if (w, h) != (BASE_W, BASE_H):
            if abs(w / h - BASE_W / BASE_H) > 0.02:
                raise StopRoutine(f"Game frame is {w}x{h}. Set BlueStacks Display to 1280x720 "
                                  "(the game then runs at 720x1280 portrait).")
            self.log(f"Game frame is {w}x{h}; BlueStacks at 1280x720 (720x1280 portrait) "
                     "is recommended for reliable detection.")

    def on_start(self) -> None:
        pass

    # ------------------------------------------------------------ resilience
    def housekeeping(self, screen: np.ndarray) -> bool:
        """Crash, daily reset and no-progress checks. True if it acted."""
        if self.cfg.get("mode_247", False):
            if not self._game_running():
                self.recover_crash()
                return True
            if game_now() >= self.next_reset:
                self.log("Daily reset (6 AM UTC-6) - logging back in")
                self.next_reset = next_reset_after(game_now())
                self.restart_game(scheduled=True)   # the daily relogin is expected, not a failure
                return True
        if time.monotonic() - self.last_progress > self.NO_PROGRESS_RESTART_S:
            mins = self.NO_PROGRESS_RESTART_S // 60
            self.log(f"Nothing has advanced in {mins} minutes - restarting the game")
            self.ctx.stats.incr(self.ctx.instance, "game_restarts")
            if not self.cfg.get("mode_247", False):
                self.notify(f"{self.NAME} made no progress for {mins} minutes - stopped.")
                raise StopRoutine("no progress")
            self.notify(f"{self.NAME} made no progress for {mins} minutes - restarted the game.",
                        ping=False)
            self.restart_game()
            return True
        return False

    def _game_running(self) -> bool:
        try:
            return self.ctx.device.is_game_foreground()
        except AdbError:
            return False

    def note_restart(self, scheduled: bool = False) -> None:
        """Count a game restart against 'Max game restarts per day' and stop instead of restarting
        again once the cap is passed (a crash loop must not run all night). Expected restarts - the
        daily relogin, maintenance, switching farms - are free. The count is kept per game day."""
        cap = int(self.cfg.get("max_restarts_per_day") or 0)
        if scheduled or cap <= 0:
            return
        day = (game_now() - timedelta(hours=DAILY_RESET_HOUR)).strftime("%Y-%m-%d")
        key = f"restarts.{day}"
        done = self.ctx.stats.get(self.ctx.instance).get(key, 0)
        if done >= cap:
            self.notify(f"{self.NAME}: the game has already been restarted {done} time(s) today (your "
                        f"limit is {cap}) - something keeps going wrong. Stopped instead of restarting again.")
            raise Finished(f"restart limit reached ({cap} per game day)")
        self.ctx.stats.incr(self.ctx.instance, key)

    def restart_game(self, scheduled: bool = False) -> None:
        self.note_restart(scheduled)
        self.ctx.params["recovering"] = "logging back in" if scheduled else "restarting the game"
        try:
            dev = self.ctx.device
            dev.stop_game()
            self.sleep(3)
            dev.launch_game()
            self.progress()
            self.on_relaunch()
        finally:
            self.ctx.params.pop("recovering", None)

    def recover_crash(self) -> None:
        if not self.cfg.get("mode_247", False):
            if not self._game_running():
                self.notify(f"{self.NAME}: the game closed or crashed - stopped (turn on 24/7 mode to auto-recover).")
                raise StopRoutine("game not running")
            return
        self.note_restart()
        self.log("Game is not running - relaunching")
        self.ctx.stats.incr(self.ctx.instance, "game_restarts")
        self.ctx.params["recovering"] = "relaunching the game"
        try:
            self.ctx.device.launch_game()
            self.sleep(10)
            self.progress()
            self.on_relaunch()
        finally:
            self.ctx.params.pop("recovering", None)

    def on_relaunch(self) -> None:
        """After a relaunch the game is on its title screen; the script's
        handle_game_start_screen takes it from there."""

    # ------------------------------------------------------------ common handlers
    def handle_unknown(self, screen: np.ndarray) -> None:
        pass

    def handle_potion_used(self, screen):
        self.log("'Used potion' popup - OK")
        self.tap_template("potion_used_ok", screen, settle=1.5)
        self.progress()

    def handle_unexpected_error(self, screen):
        self.log("Unexpected error popup - dismissing")
        self.tap_template("unexpected_error", screen)

    def handle_data_download_ok(self, screen):
        self.log("Data download prompt - accepting")
        self.tap_template("data_download_ok", screen, settle=2)

    def handle_summon_later_button(self, screen):
        self.tap_template("summon_later_button", screen)

    def handle_summon_close_button(self, screen):
        self.tap_template("summon_close_button", screen)

    def handle_total_sign_in_bonus(self, screen):
        self.tap_base(360, 1000, settle=1.0)

    def handle_xpop_up(self, screen):
        self.log("Pop-up - closing")
        self.tap_template("xpop_up", screen)

    def handle_info_close_button(self, screen):
        self.tap_template("info_close_button", screen)

    def handle_game_start_screen(self, screen):
        self.log("Game Start screen - tapping to log in")
        self.tap_base(360, 640, settle=3)
        self.progress()
