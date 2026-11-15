"""Routine engine: runs YAML routines step by step against one device.

A routine is a list of steps. Every wait looks at the live screen, so routines
react to what the game actually shows instead of replaying blind clicks the
way a macro does. See routines/README.md for the full step reference.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from .adb import AdbError, Device
from .stats import Stats
from .vision import Match, MissingTemplate, Vision

POLL = 0.4


class StopRoutine(Exception):
    """Raised to end the routine (user stop, `stop` step, or crest stop)."""


class BreakLoop(Exception):
    pass


class StepFailed(Exception):
    pass


class RoutineError(ValueError):
    """The routine file itself is invalid."""


def load_routines(folder: str | Path) -> dict[str, dict]:
    routines = {}
    for p in sorted(Path(folder).glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or "steps" not in data:
            raise RoutineError(f"{p.name}: a routine needs a 'steps' list")
        data.setdefault("name", p.stem)
        data["_id"] = p.stem
        routines[p.stem] = data
    return routines


def templates_used(steps: Any) -> set[str]:
    """Every template name referenced by a routine (for the setup checklist)."""
    found: set[str] = set()
    keys_single = {"template", "until", "seen"}

    def walk(node: Any, parent_key: str | None = None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("tap", "wait", "wait_gone") and isinstance(v, str):
                    found.add(v)
                elif k in keys_single and isinstance(v, str):
                    found.add(v)
                elif k in ("taps", "seen", "until", "any", "all", "none") and isinstance(v, list):
                    found.update(x for x in v if isinstance(x, str))
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, parent_key)

    walk(steps)
    return {t for t in found if not t.startswith("$")}


@dataclass
class Context:
    instance: str
    device: Device
    vision: Vision
    stats: Stats
    routines: dict[str, dict]
    base_resolution: tuple[int, int]
    log: Callable[[str, str], None]  # (instance, message)
    notify: Callable[..., None]      # (instance, message, image=None, ping=False)
    stop_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    params: dict[str, Any] = field(default_factory=dict)
    last_screen: np.ndarray | None = None  # newest frame (the dashboard's live view reuses it)
    history: Any = None                    # History store for crests/drops (optional)
    data_dir: Any = None                   # where debug frames are saved (defaults to cwd)
    crests: Any = None                     # CrestLedger (append-only crest/run log), optional
    units: Any = None                      # UnitRoster (units/), optional


class Runner:
    def __init__(self, ctx: Context, routine_id: str):
        self.ctx = ctx
        if routine_id not in ctx.routines:
            raise RoutineError(f"Unknown routine '{routine_id}'")
        self.routine = ctx.routines[routine_id]
        self.ctx.params = {**self.routine.get("params", {}), **ctx.params}
        self.interrupts = self.routine.get("interrupts", []) or []
        self._in_interrupt = False
        self._last_interrupt: dict[str, float] = {}

    # ---------------------------------------------------------------- utils
    def log(self, msg: str) -> None:
        self.ctx.log(self.ctx.instance, msg)

    def checkpoint(self) -> None:
        """Honour stop and pause. Called constantly."""
        if self.ctx.stop_event.is_set():
            raise StopRoutine("stopped")
        while self.ctx.pause_event.is_set():
            if self.ctx.stop_event.is_set():
                raise StopRoutine("stopped")
            time.sleep(0.2)

    def sleep(self, seconds: float) -> None:
        end = time.monotonic() + float(seconds)
        while time.monotonic() < end:
            self.checkpoint()
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def param(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            key = value[1:]
            if key not in self.ctx.params:
                raise RoutineError(f"Unknown parameter '{value}'")
            return self.ctx.params[key]
        return value

    def screen(self) -> np.ndarray:
        self.checkpoint()
        img = self.ctx.device.screencap()
        self.ctx.last_screen = img
        return img

    def scale_xy(self, x: float, y: float) -> tuple[int, int]:
        """tap_xy coordinates are written for base_resolution; scale to device."""
        bw, bh = self.ctx.base_resolution
        img = self.ctx.last_screen if self.ctx.last_screen is not None else self.screen()
        h, w = img.shape[:2]
        return int(x * w / bw), int(y * h / bh)

    def _check_interrupts(self, img: np.ndarray) -> bool:
        if self._in_interrupt or not self.interrupts:
            return False
        for intr in self.interrupts:
            name = intr["template"]
            try:
                m = self.ctx.vision.find(img, name, intr.get("threshold"))
            except MissingTemplate:
                continue  # interrupts are always optional
            if not m:
                continue
            cooldown = float(intr.get("cooldown", 3))
            if time.monotonic() - self._last_interrupt.get(name, 0) < cooldown:
                continue
            self._last_interrupt[name] = time.monotonic()
            self.log(f"Interrupt: {name}")
            self._in_interrupt = True
            try:
                self.run_steps(intr.get("steps", []), match=m)
            finally:
                self._in_interrupt = False
            return True
        return False

    def wait_for(self, names: list[str], timeout: float, threshold: float | None = None,
                 skip_missing: bool = False) -> Match | None:
        """Poll the screen until one of `names` appears. Runs interrupts while waiting."""
        end = time.monotonic() + float(timeout)
        while True:
            img = self.screen()
            m = self.ctx.vision.find_any(img, names, threshold, skip_missing=skip_missing)
            if m:
                return m
            if self._check_interrupts(img):
                end += 2  # give the screen a moment after an interrupt
                continue
            if time.monotonic() >= end:
                return None
            self.sleep(POLL)

    # ---------------------------------------------------------------- run
    def run(self) -> None:
        steps = self.routine["steps"]
        recovery = self.routine.get("recovery")
        max_recoveries = int(self.routine.get("max_recoveries", 3))
        failures = 0
        self.log(f"Starting routine: {self.routine.get('name')}")
        while True:
            try:
                self.run_steps(steps)
                self.log("Routine finished")
                return
            except StepFailed as e:
                failures += 1
                self.ctx.stats.incr(self.ctx.instance, "errors")
                self.log(f"Step failed: {e}")
                if not recovery or failures > max_recoveries:
                    self.ctx.notify(self.ctx.instance,
                                    f"Routine stopped after an error: {e}",
                                    image=self.ctx.last_screen, ping=True)
                    raise StopRoutine(str(e)) from e
                self.log(f"Running recovery ({failures}/{max_recoveries})")
                self.run_steps(recovery)

    def run_steps(self, steps: list, match: Match | None = None) -> None:
        for step in steps or []:
            self.checkpoint()
            self.run_step(step, match)

    def run_step(self, step: Any, match: Match | None = None) -> None:
        if isinstance(step, str):
            step = {step: True}
        if not isinstance(step, dict) or not step:
            raise RoutineError(f"Invalid step: {step!r}")
        if "if" in step:
            return self._if(step)
        kind, arg = next(iter(step.items()))
        handler = getattr(self, f"_step_{kind}", None)
        if handler is None:
            raise RoutineError(f"Unknown step type '{kind}'")
        return handler(arg, step, match)

    # ---------------------------------------------------------------- steps
    @staticmethod
    def _opts(arg: Any, key: str = "template") -> dict:
        return dict(arg) if isinstance(arg, dict) else {key: arg}

    def _step_tap(self, arg, step, match):
        o = self._opts(arg)
        name = self.param(o["template"])
        optional = bool(o.get("optional", False))
        timeout = float(o.get("timeout", 10))
        try:
            m = self.wait_for([name], timeout, o.get("threshold"))
        except MissingTemplate:
            if optional:
                self.log(f"Skipped (template not captured): {name}")
                return
            raise
        if not m:
            if optional:
                return
            raise StepFailed(f"'{name}' did not appear within {timeout:.0f}s")
        dx, dy = o.get("offset", [0, 0])
        cx, cy = m.center
        for _ in range(int(o.get("times", 1))):
            self.ctx.device.tap(cx + dx, cy + dy)
            self.sleep(float(o.get("delay", 0.6)))

    def _step_tap_xy(self, arg, step, match):
        x, y = arg
        self.ctx.device.tap(*self.scale_xy(x, y))
        self.sleep(float(step.get("delay", 0.6)))

    def _step_tap_match(self, arg, step, match):
        """Tap whatever triggered the current interrupt / handler."""
        if match:
            self.ctx.device.tap(*match.center)
            self.sleep(0.6)

    def _step_wait(self, arg, step, match):
        o = self._opts(arg)
        name = self.param(o["template"])
        timeout = float(o.get("timeout", 30))
        try:
            m = self.wait_for([name], timeout, o.get("threshold"))
        except MissingTemplate:
            if o.get("optional"):
                return
            raise
        if not m and not o.get("optional"):
            raise StepFailed(f"'{name}' did not appear within {timeout:.0f}s")

    def _step_wait_gone(self, arg, step, match):
        o = self._opts(arg)
        name = self.param(o["template"])
        end = time.monotonic() + float(o.get("timeout", 30))
        while time.monotonic() < end:
            img = self.screen()
            if not self.ctx.vision.find(img, name, o.get("threshold")):
                return
            self._check_interrupts(img)
            self.sleep(POLL)
        if not o.get("optional"):
            raise StepFailed(f"'{name}' did not go away")

    def _step_sleep(self, arg, step, match):
        self.sleep(float(self.param(arg)))

    def _step_back(self, arg, step, match):
        self.ctx.device.back()
        self.sleep(0.8)

    def _step_swipe(self, arg, step, match):
        x1, y1, x2, y2 = arg[:4]
        ms = arg[4] if len(arg) > 4 else 300
        a, b = self.scale_xy(x1, y1)
        c, d = self.scale_xy(x2, y2)
        self.ctx.device.swipe(a, b, c, d, ms)
        self.sleep(0.8)

    def _step_log(self, arg, step, match):
        self.log(str(arg))

    def _step_count(self, arg, step, match):
        self.ctx.stats.incr(self.ctx.instance, str(arg))

    def _step_notify(self, arg, step, match):
        o = self._opts(arg, "message")
        img = self.ctx.last_screen if o.get("screenshot", True) else None
        self.ctx.notify(self.ctx.instance, str(o["message"]), image=img,
                        ping=bool(o.get("ping", False)))

    def _step_stop(self, arg, step, match):
        reason = str(arg) if arg not in (True, None) else "stop step"
        self.log(f"Stopping: {reason}")
        raise StopRoutine(reason)

    def _step_break(self, arg, step, match):
        raise BreakLoop()

    def _step_call(self, arg, step, match):
        name = str(arg)
        if name not in self.ctx.routines:
            raise RoutineError(f"call: unknown routine '{name}'")
        self.run_steps(self.ctx.routines[name]["steps"])

    def _step_loop(self, arg, step, match):
        o = dict(arg)
        times = int(self.param(o.get("times", 0)) or 0)  # 0 = forever
        body = o.get("steps", [])
        i = 0
        while times == 0 or i < times:
            i += 1
            try:
                self.run_steps(body)
            except BreakLoop:
                return

    def _seen(self, cond: Any, threshold=None, timeout: float = 0) -> Match | None:
        names = cond if isinstance(cond, list) else [cond]
        names = [self.param(n) for n in names]
        if timeout > 0:
            return self.wait_for(names, timeout, threshold, skip_missing=True)
        img = self.screen()
        return self.ctx.vision.find_any(img, names, threshold, skip_missing=True)

    def _if(self, step: dict) -> None:
        cond = step["if"]
        cond = cond if isinstance(cond, dict) else {"seen": cond}
        timeout = float(cond.get("timeout", 0))
        if "seen" in cond:
            m = self._seen(cond["seen"], cond.get("threshold"), timeout)
            ok = m is not None
        elif "not_seen" in cond:
            m = None
            ok = self._seen(cond["not_seen"], cond.get("threshold"), timeout) is None
        elif "param" in cond:
            m = None
            ok = bool(self.param("$" + str(cond["param"]).lstrip("$")))
        else:
            raise RoutineError(f"if: needs 'seen', 'not_seen' or 'param': {cond}")
        self.run_steps(step.get("then" if ok else "else", []), match=m)

    def _step_switch(self, arg, step, match):
        """Wait until one of several screens appears, then run its steps."""
        o = dict(arg)
        cases = o["cases"]
        names = [self.param(c["template"]) for c in cases]
        timeout = float(self.param(o.get("timeout", 60)))
        m = self.wait_for(names, timeout, o.get("threshold"), skip_missing=True)
        if not m:
            if "on_timeout" in o:
                return self.run_steps(o["on_timeout"])
            raise StepFailed(f"none of {names} appeared within {timeout:.0f}s")
        for c in cases:
            if self.param(c["template"]) == m.name:
                return self.run_steps(c.get("steps", []), match=m)

    def _step_tap_until(self, arg, step, match):
        """Keep tapping through screens (results, popups) until `until` shows.

        handlers run instead of a tap when their template is visible, e.g. to
        inspect a crest drop before tapping past it.
        """
        o = dict(arg)
        taps = [self.param(t) for t in o.get("taps", [])]
        until = o["until"]
        until = [self.param(u) for u in (until if isinstance(until, list) else [until])]
        handlers = o.get("handlers", []) or []
        fallback = o.get("fallback_xy")
        timeout = float(self.param(o.get("timeout", 120)))
        every = float(o.get("every", 1.0))
        end = time.monotonic() + timeout
        used: set[int] = set()  # handlers marked `once: true` that already ran
        while time.monotonic() < end:
            img = self.screen()
            if self.ctx.vision.find_any(img, until, skip_missing=False):
                return
            handled = False
            for idx, h in enumerate(handlers):
                if idx in used:
                    continue
                hm = self.ctx.vision.find_any(img, [self.param(h["template"])], skip_missing=True)
                if hm:
                    if h.get("once"):
                        used.add(idx)
                    self.run_steps(h.get("steps", []), match=hm)
                    handled = True
                    break
            if not handled and not self._check_interrupts(img):
                tm = self.ctx.vision.find_any(img, taps, skip_missing=True)
                if tm:
                    self.ctx.device.tap(*tm.center)
                elif fallback:
                    self.ctx.device.tap(*self.scale_xy(*fallback))
            self.sleep(every)
        if not o.get("optional"):
            raise StepFailed(f"never reached {until} within {timeout:.0f}s")

    def _step_ensure_game(self, arg, step, match):
        """Relaunch Grand Summoners if it crashed or was closed."""
        o = dict(arg or {})
        dev = self.ctx.device
        try:
            if dev.is_game_foreground():
                return
        except AdbError as e:
            raise StepFailed(str(e)) from e
        self.log("Game is not open - launching it")
        self.ctx.stats.incr(self.ctx.instance, "game_restarts")
        dev.launch_game()
        self.sleep(float(o.get("boot_wait", 15)))
        if "home" in o:
            self._step_tap_until({
                "taps": o.get("taps", []),
                "until": o["home"],
                "timeout": o.get("timeout", 180),
                "fallback_xy": o.get("fallback_xy"),
            }, {}, None)

    def _step_restart_game(self, arg, step, match):
        self.log("Restarting the game")
        self.ctx.device.stop_game()
        self.sleep(2)
        self._step_ensure_game(arg, step, match)
