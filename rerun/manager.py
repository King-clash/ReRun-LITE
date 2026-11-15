"""Owns config, instances and their worker threads. GUI and Discord both drive this."""
from __future__ import annotations

import copy
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import yaml

from .adb import AdbError, Device, find_adb
from .engine import Context, RoutineError, Runner, StopRoutine, load_routines, templates_used
from . import errlog, qol, runlog
from .configcheck import check_config
from .events import Event
from .crest_stats import CrestLedger
from .history import History
from .compendium import Compendium
from .units import UnitRoster
from .account_ops import AccountOps
from .safety import DryRunDevice, plan_summary
from .scripts import SCRIPTS
from .scripts.base import Finished
from .stats import Stats, fmt_duration
from .vision import MissingTemplate, TemplateStore, Vision

CUSTOM_PREFIX = "custom:"

DEFAULT_CONFIG: dict[str, Any] = {
    "adb_path": "auto",
    "game_package": "auto",
    "instances": [
        {"name": "Instance 1", "serial": "127.0.0.1:5555", "script": "crest"},
    ],
    # script_settings[instance][script_id] = {setting: value}
    "script_settings": {},
    "discord": {
        "enabled": False,
        "token": "",
        "channel_id": 0,
        "ping_user_id": 0,
        "allowed_user_ids": [],
        "status_board": True,   # one pinned live-status message per instance
        # no @mentions between these times (alerts are still posted, silently)
        "quiet": {"enabled": False, "start": "23:00", "end": "07:00"},
        # which kinds of alert may @mention you: rare crests/Bursts (gold), stops and problems (red),
        # finished runs (green), everything else
        "ping": {"rare": True, "problem": True, "finished": True, "other": True},
    },
    "hotkeys": {"stop_all": "f12", "pause_all": "f11"},
    "appearance": "auto",       # auto | light | dark
    "close_to_tray": True,      # the window's X hides Rerun to the tray instead of quitting
    "tesseract_path": "auto",   # OCR engine; auto = the copy ReStart ships, else a normal install
    # schedules[instance] = {"enabled": bool, "time": "HH:MM"} - start its script daily
    "schedules": {},
    "summary": {"enabled": True, "time": "21:00",   # daily Discord summary and what it lists
                "include": {"runs": True, "crests": True, "refills": True, "problems": True}},
    "setup_seen": False,
    # window and start-up behaviour (Settings > App)
    "ui": {"geometry": "", "tab": 0, "start_minimized": False, "autostart": False,
           "confirm_stop_all": False},
    # rerun.log and the Log tab (Settings > Logging): file_level all | warnings | errors
    "logging": {"file_level": "all", "file_mb": 1, "file_count": 3, "memory_lines": 3000},
    # Live View: frames per second of the emulator's video stream (rerun/live_stream.py);
    # 0 = the old screenshot preview (one frame every few seconds when idle)
    "live_view_fps": 30,
    # rerun/updates.py: url "" = the address built into Rerun; channel stable | beta;
    # check = look for updates at start and every few hours
    "updates": {"url": "", "channel": "stable", "check": True},
}

LOG_KEEP = 3000


def log_level(msg: str) -> str:
    """info | warn | error, for the Log tab's filter and colours."""
    low = msg.lower()
    if low.startswith(("error", "crashed", "unexpected error")) or "traceback" in low:
        return "error"
    if msg.startswith("NOTIFY") or low.startswith(("stopped", "finished")) or any(
            w in low for w in ("stuck", "could not", "couldn't", "failed", "missing", "warning",
                               "out of energy")):
        return "warn"
    return "info"


@dataclass
class Instance:
    name: str
    serial: str
    script: str
    status: str = "idle"  # idle | starting | running | paused | error
    detail: str = ""
    thread: threading.Thread | None = None
    ctx: Context | None = None
    device: Device | None = None
    account: str = ""        # Account Manager id this run belongs to ("" = unattributed)
    session_id: str = ""
    task: str = ""           # checklist task this run was started for
    dry_run: bool = False
    limit_timer: threading.Timer | None = None
    last_plan: list | None = None     # what the last dry run would have done


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Manager:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        errlog.init(self.root)
        runlog.init(self.root)
        self.config_path = self.root / "config.yaml"
        self.store = TemplateStore(self.root / "templates")
        self.vision = Vision(self.store)
        self.stats = Stats(self.root / "stats.json")
        self.history = History(self.root / "history")
        self.listeners: list[Callable[[dict], None]] = []
        self.history.listeners.append(lambda e: self.emit({"type": "history", "entry": e}))
        self.crests = CrestLedger(self.root)
        try:  # repeatable: rebuilds crests from History once, never twice
            added = self.crests.reconstruct(self.history.entries, self.stats.all(), self.history.thumbs)
        except Exception as e:  # noqa: BLE001 - never block startup on statistics
            errlog.note("manager.crest_rebuild", e)
            added = {"error": repr(e)}
        self._crest_rebuild = added
        self.units = UnitRoster(self.root)
        self.compendium = Compendium(self.units, self.history)
        self.discord = None  # set by DiscordBot.start()
        self.log_lines: list[str] = []
        self.log_entries: list[dict] = []  # same lines with instance + level, for filtering
        self._lock = threading.RLock()
        self.config: dict = {}
        self.routines: dict[str, dict] = {}
        self.instances: dict[str, Instance] = {}
        self.reload()
        self._setup_reference_names()
        self.ops = AccountOps(self)      # accounts, checklist, goals, vault (rerun/account_ops.py)

    # ------------------------------------------------------------ GS Companion names
    def _setup_reference_names(self) -> None:
        """GS Companion unit names take priority over names read from the game when one
        unit clearly matches (rerun/gsc_data.py reference_name). Needs the local data in
        <root>/data/gscompanion/; without it scanned names stay as read."""
        self.units.rename_listeners.append(self.compendium.rename)
        self.gsc = None
        self.reference_renames: list[tuple[str, str]] = []
        try:
            from .gsc_data import GSCData
            g = GSCData(self.root)
            if not g.available or not g.units:
                return
            self.gsc = g
            self.units.reference = g.reference_name
            self.units.reference_facts = g.unit_facts
            self.reference_renames = self.units.adopt_reference_names(g.reference_name)
        except Exception as e:  # noqa: BLE001 - never block startup on reference data
            self.log("app", f"GS Companion names not applied: {e}", level="error")
            return
        if self.reference_renames:
            self.log("app", f"Units: {len(self.reference_renames)} name(s) replaced with GS Companion's "
                            "(old spellings kept as aliases; see units/renames.jsonl)")

    # ------------------------------------------------------------ config
    def reload(self) -> list[str]:
        problems = []
        if not self.config_path.exists():
            self.save_config(DEFAULT_CONFIG)
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        for warning in check_config(raw, DEFAULT_CONFIG):
            self.log("app", warning, "warn")
        self.config = deep_merge(DEFAULT_CONFIG, raw)
        self.apply_logging()
        if "instances" in raw:  # lists replace, not merge
            self.config["instances"] = raw["instances"]
        try:
            self.routines = load_routines(self.root / "routines")
        except (RoutineError, yaml.YAMLError) as e:
            problems.append(f"Custom routines: {e}")
        with self._lock:
            names = set()
            for item in self.config["instances"]:
                name = str(item["name"])
                names.add(name)
                inst = self.instances.get(name)
                script = item.get("script", "crest")
                if inst is None:
                    self.instances[name] = Instance(name, str(item["serial"]), script)
                elif inst.status in ("idle", "error"):
                    if inst.serial != item["serial"]:
                        inst.device = None
                    inst.serial = str(item["serial"])
                    inst.script = script
            for gone in set(self.instances) - names:
                if self.instances[gone].status in ("idle", "error"):
                    del self.instances[gone]
        for p in problems:
            self.log("app", p)
        return problems

    def save_config(self, cfg: dict | None = None) -> None:
        cfg = cfg if cfg is not None else self.config
        self.config_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
                                    encoding="utf-8")

    def set_instances(self, items: list[dict]) -> None:
        self.config["instances"] = items
        self.save_config()
        self.reload()

    def set_instance_script(self, name: str, script: str) -> None:
        for item in self.config["instances"]:
            if item["name"] == name:
                item["script"] = script
        if name in self.instances and self.instances[name].status in ("idle", "error"):
            self.instances[name].script = script
        self.save_config()

    def script_settings(self, instance: str, script: str) -> dict:
        cls = SCRIPTS.get(script)
        defaults = {s.key: s.default for s in cls.SETTINGS} if cls else {}
        saved = self.config.get("script_settings", {}).get(instance, {}).get(script, {})
        if cls:
            saved = cls.migrate_settings(dict(saved))
        return {**defaults, **saved}

    def save_script_settings(self, instance: str, script: str, values: dict) -> None:
        self.config.setdefault("script_settings", {}).setdefault(instance, {})[script] = values
        self.save_config()

    def scripts_available(self) -> dict[str, str]:
        """id -> display name, built-in scripts first, then custom routines."""
        out = {k: c.display_name() for k, c in SCRIPTS.items()}
        for k, r in self.routines.items():
            if not k.startswith("_"):
                out[CUSTOM_PREFIX + k] = f"Custom: {r.get('name', k)}"
        return out

    def adb_path(self) -> str:
        return find_adb(self.config.get("adb_path"))

    # ------------------------------------------------------------ events
    def emit(self, event: Event) -> None:
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception as e:  # a broken listener must never kill a worker
                errlog.note("manager.emit listener", e)

    def log(self, instance: str, msg: str, level: str | None = None) -> None:
        line = f"{time.strftime('%H:%M:%S')} [{instance}] {msg}"
        level = level or log_level(msg)
        entry = {"instance": instance, "message": msg, "line": line, "level": level}
        with self._lock:
            self.log_lines.append(line)
            self.log_entries.append(entry)
            keep = self.log_keep()
            if len(self.log_lines) > keep + 500:  # trim in batches, not on every line
                del self.log_lines[:-keep]
                del self.log_entries[:-keep]
        self.emit({"type": "log", **entry})
        runlog.write(instance, msg, level)

    def reset_stats(self, name: str | None = None) -> str:
        self.stats.reset(name)
        self.log(name or "app", "Stats reset")
        return f"Stats reset for {name or 'all instances'}"

    def totals(self, name: str) -> dict[str, int]:
        """Headline numbers for the dashboard: lifetime counters summed across scripts."""
        d = self.stats.get(name)
        out = {"runs": 0, "kept": 0, "scrapped": 0, "potions": 0, "crystals": 0, "failures": 0,
               "seconds": d.get("seconds_run", 0) + self.stats.uptime(name)}
        for k, v in d.items():
            key = k.split(".", 1)[-1]
            if key == "runs":
                out["runs"] += v
            elif key in ("kept", "burst"):
                out["kept"] += v
            elif key == "scrapped":
                out["scrapped"] += v
            elif key == "potions_used":
                out["potions"] += v
            elif key == "crystal_refreshes":
                out["crystals"] += v
            elif key == "failures":
                out["failures"] += v
        return out

    def log_keep(self) -> int:
        """Lines the Log tab keeps in memory (Settings > Logging), clamped to a sane range."""
        try:
            return max(500, min(int((self.config.get("logging") or {}).get("memory_lines", LOG_KEEP)), 20000))
        except (TypeError, ValueError):
            return LOG_KEEP

    def apply_logging(self) -> None:
        lg = self.config.get("logging") or {}
        try:
            runlog.configure(lg.get("file_mb", 1), lg.get("file_count", 3), lg.get("file_level", "all"))
        except (TypeError, ValueError) as e:
            errlog.note("manager.apply_logging", e)
            runlog.configure()

    def _now(self) -> datetime:
        return datetime.now()          # a seam for tests (quiet hours)

    def effective_ping(self, message: str, ping: bool) -> tuple[bool, str]:
        """(should the alert @mention you, why not): applies 'Ping me for' and quiet hours on top of
        whatever the script asked for."""
        if not ping:
            return False, ""
        d = self.config.get("discord") or {}
        try:
            from .discord_bot import alert_kind
            kind = alert_kind(message)
        except Exception as e:  # noqa: BLE001 - classification is a nicety: unknown = 'info'
            errlog.note("manager.alert_kind", e)
            kind = "info"
        if not qol.ping_allowed(kind, d.get("ping")):
            return False, "this kind of alert is switched off in 'Ping me for'"
        q = d.get("quiet") or {}
        if q.get("enabled") and qol.in_quiet_hours(self._now(), str(q.get("start") or ""),
                                                   str(q.get("end") or "")):
            return False, f"quiet hours ({q.get('start')}-{q.get('end')})"
        return True, ""

    def notify(self, instance: str, message: str, image: np.ndarray | None = None,
               ping: bool = False) -> None:
        ops = getattr(self, "ops", None)
        aid = None
        if ops is not None:
            aid = ops.account_of_running(instance) or next(iter(
                [a["id"] for a in ops.store.accounts_for_instance(instance)][:1]), None)
        muted = bool(aid and not ops.store.get(aid)["notify"]["enabled"])   # this account sends no Discord messages
        if aid and len(self.ops.store.ids()) > 1 and not message.startswith(self.ops.name(aid)):
            message = f"[{self.ops.name(aid)}] {message}"      # several accounts: say which one
        if aid and not self.ops.store.get(aid)["notify"]["ping"]:
            ping = False                                         # this account never @mentions
        self.log(instance, f"NOTIFY: {message}")
        ping, skipped = self.effective_ping(message, ping) if ping else (False, "")
        if skipped:
            self.log(instance, f"(no Discord @mention: {skipped})")
        self.emit({"type": "notify", "instance": instance, "message": message})
        if self.discord and not muted:
            png = None
            if image is not None:
                ok, buf = cv2.imencode(".png", image)
                png = buf.tobytes() if ok else None
            if hasattr(self.discord, "alert"):
                self.discord.alert(instance, message, png, ping)   # colour-coded embed + buttons
            else:
                self.discord.send(f"[{instance}] {message}", png, ping)

    def energy(self, name: str, fresh: bool = False) -> tuple[int, int, float] | None:
        """(current, max, when read) for an instance: what its running script last read,
        else a cached reading; fresh=True reads it now from a screenshot (worker thread)."""
        inst = self.instances.get(name)
        if inst is None:
            return None
        cache = self.__dict__.setdefault("_energy", {})
        e = inst.ctx.params.get("energy") if inst.ctx is not None else None
        if e:
            cache[name] = e
            return e
        if fresh:
            try:
                from .ocr import get_ocr, read_energy
                r = read_energy(get_ocr(self.config.get("tesseract_path", "auto")), self.screenshot(name))
            except Exception as e:  # noqa: BLE001 - no device / no OCR: unknown
                errlog.note("manager.energy_read", e)
                r = None
            if r:
                cache[name] = (r[0], r[1], time.time())
        return cache.get(name)

    def _set_status(self, inst: Instance, status: str, detail: str = "") -> None:
        inst.status = status
        inst.detail = detail
        self.emit({"type": "status", "instance": inst.name, "status": status, "detail": detail})

    # ------------------------------------------------------------ devices
    def device(self, name: str) -> Device:
        inst = self.instances[name]
        if inst.device is None:
            inst.device = Device(self.adb_path(), inst.serial)
        return inst.device

    def screenshot(self, name: str) -> np.ndarray:
        dev = self.device(name)
        if not dev.is_connected():
            dev.connect()
        return dev.screencap()

    # ------------------------------------------------------------ control
    locked = False   # set by the app while its key is expired: nothing may start

    def start(self, name: str, script: str | None = None, confirm_account: str | None = None,
              dry_run: bool = False, task: str = "") -> str:
        """Start a script. `confirm_account` is needed when several accounts share this emulator (it says
        which one is logged in); `dry_run` shows what would be tapped and taps nothing."""
        if self.locked:
            return "Rerun's key has expired - enter a new key in Rerun to start scripts"
        with self._lock:
            inst = self.instances.get(name)
            if not inst:
                return f"No instance named '{name}'"
            if inst.status in ("starting", "running", "paused"):
                return f"{name} is already {inst.status}"
            if script:
                if script not in self.scripts_available():
                    return f"Unknown script '{script}'"
                self.set_instance_script(name, script)
            if inst.script not in self.scripts_available():
                return f"Unknown script '{inst.script}'"
            aid, err, dry = self.ops.before_start(name, inst.script, confirm_account, dry_run)
            if err:
                return err
            inst.account, inst.dry_run, inst.task = aid or "", dry, task
            self._set_status(inst, "starting")
            inst.thread = threading.Thread(target=self._worker, args=(inst,),
                                           name=f"worker-{name}", daemon=True)
            inst.thread.start()
            who = f" for {self.ops.name(aid)}" if aid else ""
            return (f"Dry run of {self.scripts_available()[inst.script]} on {name}{who} (nothing will be tapped)"
                    if dry else f"Started {self.scripts_available()[inst.script]} on {name}{who}")

    def arm_limit(self, inst: Instance, minutes: int) -> None:
        """Stop this run after `minutes` (the account's session limit)."""
        def fire(ctx=inst.ctx, n=inst.name):
            if ctx is not None and not ctx.stop_event.is_set():
                self.log(n, f"Session limit of {minutes} minutes reached - stopping")
                ctx.stop_event.set()
                ctx.pause_event.clear()
        inst.limit_timer = threading.Timer(minutes * 60, fire)
        inst.limit_timer.daemon = True
        inst.limit_timer.start()

    def stop(self, name: str) -> str:
        inst = self.instances.get(name)
        if not inst:
            return f"No instance named '{name}'"
        if inst.ctx:
            inst.ctx.stop_event.set()
            inst.ctx.pause_event.clear()
            return f"Stopping {name}"
        return f"{name} is not running"

    def pause(self, name: str) -> str:
        inst = self.instances.get(name)
        if not inst or not inst.ctx or inst.status != "running":
            return f"{name} is not running"
        inst.ctx.pause_event.set()
        self._set_status(inst, "paused")
        return f"Paused {name}"

    def resume(self, name: str) -> str:
        inst = self.instances.get(name)
        if not inst or not inst.ctx or inst.status != "paused":
            return f"{name} is not paused"
        inst.ctx.pause_event.clear()
        self._set_status(inst, "running", inst.script)
        return f"Resumed {name}"

    def toggle_pause_all(self) -> None:
        running = [n for n, i in self.instances.items() if i.status == "running"]
        if running:
            for n in running:
                self.pause(n)
        else:
            for n, i in self.instances.items():
                if i.status == "paused":
                    self.resume(n)

    def start_all(self) -> list[str]:
        return [self.start(n) for n in list(self.instances)]

    def stop_all(self) -> list[str]:
        return [self.stop(n) for n in list(self.instances) if self.instances[n].ctx]

    def _worker(self, inst: Instance) -> None:
        name = inst.name
        started_at, before, reason = None, {}, "finished"
        plan_dev = None
        try:
            dev = self.device(name)
            dev.connect()
            dev.resolve_package(self.config.get("game_package"))
            if inst.dry_run:
                dev = plan_dev = DryRunDevice(dev, log=lambda m, n=name: self.log(n, m))
            ctx = Context(
                instance=name, device=dev, vision=self.vision, stats=self.stats,
                routines=self.routines, base_resolution=(720, 1280),
                log=self.log, notify=self.notify, history=self.history, data_dir=self.root,
                crests=self.crests,
                units=self.ops.roster_for(inst.account) if inst.account else self.units,
            )
            # Queue runs other scripts with this instance's settings for them.
            ctx.params["settings_of"] = lambda sid, n=name: self.script_settings(n, sid)
            ctx.params["tesseract_path"] = self.config.get("tesseract_path", "auto")
            inst.ctx = ctx
            self._set_status(inst, "running", inst.script)
            self.stats.mark_started(name)
            started_at, before = time.time(), dict(self.stats.get(name))
            self.ops.session_started(inst, inst.account, inst.dry_run)
            if inst.script.startswith(CUSTOM_PREFIX):
                Runner(ctx, inst.script[len(CUSTOM_PREFIX):]).run()
            else:
                cls = SCRIPTS[inst.script]
                cls(ctx, self.script_settings(name, inst.script)).run()
            self._set_status(inst, "idle", "finished")
        except Finished as e:
            self.log(name, f"Finished: {e}")
            reason = f"finished: {e}"
            self._set_status(inst, "idle", str(e))
        except StopRoutine as e:
            self.log(name, f"Stopped ({e})")
            reason = f"stopped: {e}"
            if str(e) not in ("stopped by user", "stopped") and not str(e).startswith("dry run complete"):
                self.notify(name, f"Stopped: {e}", ping=True)
            self._set_status(inst, "idle", str(e))
        except MissingTemplate as e:
            self.log(name, str(e))
            reason = f"missing template: {e}"
            self.notify(name, str(e), ping=True)
            self._set_status(inst, "error", str(e))
        except (AdbError, RoutineError) as e:
            self.log(name, f"Error: {e}")
            reason = f"error: {e}"
            self.notify(name, f"Error: {e}", ping=True)
            self._set_status(inst, "error", str(e))
        except Exception as e:  # noqa: BLE001 - report anything unexpected
            self.log(name, "Unexpected error:\n" + traceback.format_exc())
            reason = f"crashed: {e!r}"
            self.notify(name, f"Crashed: {e!r}", ping=True)
            self._set_status(inst, "error", repr(e))
        finally:
            self.stats.mark_stopped(name)
            if inst.limit_timer is not None:
                inst.limit_timer.cancel()
                inst.limit_timer = None
            if plan_dev is not None:
                self.log(name, "DRY RUN RESULT: " + plan_summary(plan_dev.plan))
                inst.last_plan = list(plan_dev.plan)
            if started_at is not None:
                self._record_session(inst, started_at, before, reason)
            inst.ctx = None

    def _record_session(self, inst: Instance, started_at: float, before: dict, reason: str) -> None:
        """One History + Log line per run of a script: how long, why it ended, what it achieved.
        Answers 'why did it stop' the next morning. Never raises."""
        try:
            name = inst.name
            after = self.stats.get(name)
            delta = {k: after.get(k, 0) - before.get(k, 0) for k in after
                     if after.get(k, 0) != before.get(k, 0)}
            mins = max(0, int((time.time() - started_at) / 60))
            parts = []
            for label, pick in (("run(s)", lambda k: k.endswith(".runs")),
                                ("crest(s)", lambda k: ".crest_" in k),
                                ("potion(s)", lambda k: "potion" in k.rsplit(".", 1)[-1]),
                                ("game restart(s)", lambda k: k.endswith("game_restarts"))):
                n = sum(v for k, v in delta.items() if pick(k))
                if n > 0:
                    parts.append(f"{n} {label}")
            cls = SCRIPTS.get(inst.script)
            title = cls.NAME if cls else inst.script
            detail = f"Session ended after {mins} min ({title}): {reason}"                      + (" | " + ", ".join(parts) if parts else "")
            self.history.add(name, inst.script, "session", detail)
            self.log(name, detail)
            self.ops.session_ended(inst, delta, reason)
        except Exception as e:  # noqa: BLE001 - a summary must never break shutdown
            errlog.note("manager.session_summary", e)

    # ------------------------------------------------------------ schedule + summary
    def start_scheduler(self) -> None:
        """Background clock: starts scheduled instances and sends the daily summary."""
        if getattr(self, "_sched", None):
            return
        self._fired: dict[str, str] = {}
        self._sched = threading.Thread(target=self._scheduler_loop, name="scheduler", daemon=True)
        self._sched.start()

    def _scheduler_loop(self) -> None:
        while True:
            try:
                self.scheduler_tick()
            except Exception as e:  # noqa: BLE001 - the clock must keep running
                self.log("app", f"Scheduler error: {e}", level="error")
            time.sleep(20)

    def scheduler_tick(self, now: "datetime | None" = None) -> list[str]:
        """Do whatever is due at this minute. Returns what it did (for tests)."""
        now = now or datetime.now()
        hhmm, today = now.strftime("%H:%M"), now.strftime("%Y-%m-%d")
        fired = self.__dict__.setdefault("_fired", {})
        did = []
        for name, sch in (self.config.get("schedules") or {}).items():
            if not sch.get("enabled") or sch.get("time") != hhmm or name not in self.instances:
                continue
            key = f"start:{name}"
            if fired.get(key) == today:
                continue
            fired[key] = today
            inst = self.instances[name]
            if inst.status in ("idle", "error"):
                msg = self.start(name)
                self.log(name, f"Scheduled start at {hhmm}: {msg}")
                did.append(f"start {name}")
            else:
                self.log(name, f"Scheduled start at {hhmm} skipped - already {inst.status}")
        s = self.config.get("summary") or {}
        if s.get("enabled") and s.get("time") == hhmm and fired.get("summary") != today:
            fired["summary"] = today
            if self.discord:
                self.discord.send(self.daily_summary(), None, False)
                self.log("app", "Daily summary sent to Discord")
                did.append("summary")
                if self.ops.send_daily_reports():
                    did.append("account reports")
        try:
            if self.ops.check_alerts():
                did.append("account alerts")
        except Exception as e:  # noqa: BLE001 - alerts are a nicety; the clock must keep running
            errlog.note("manager.account_alerts", e)
        return did

    def daily_summary(self, update_baseline: bool = True) -> str:
        """Text of the last 24 hours: runs, crests, refills, problems per instance."""
        state_path = self.root / "summary_state.json"
        try:
            import json
            base = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        except ValueError:
            base = {}
        since = time.time() - 24 * 3600
        lines = [f"**Rerun daily summary** ({datetime.now().strftime('%a %d %b')})"]
        totals_now = {}
        for name in self.instances:
            t = self.totals(name)
            totals_now[name] = t
            b = base.get("totals", {}).get(name, {})
            runs = t["runs"] - b.get("runs", 0) if b else t["runs"]
            seconds = t["seconds"] - b.get("seconds", 0) if b else t["seconds"]
            recent = [e for e in self.history.recent(2000, name) if e["t"] >= since]
            kept = sum(1 for e in recent if e.get("action") == "kept")
            scrapped = sum(1 for e in recent if e.get("action") == "scrapped")
            refills = sum(1 for e in recent if e["kind"] == "energy" and "Used" in e["detail"])
            problems = [e["detail"] for e in recent if e["kind"] in ("failure", "popup")
                        or e.get("action") == "stopped"]
            inc = (self.config.get("summary") or {}).get("include") or {}
            lines.append(f"\n**{name}**" + (f" - {max(0, runs)} run(s), {fmt_duration(max(0, seconds))} farming"
                                           if inc.get("runs", True) else ""))
            if (kept or scrapped) and inc.get("crests", True):
                lines.append(f"Crests: {kept} kept, {scrapped} scrapped")
            if refills and inc.get("refills", True):
                lines.append(f"Energy refills: {refills}")
            if problems and inc.get("problems", True):
                lines.append(f"Problems ({len(problems)}): " + "; ".join(problems[:3]))
        if update_baseline:
            import json
            state_path.write_text(json.dumps({"time": time.time(), "totals": totals_now}),
                                  encoding="utf-8")
        return "\n".join(lines)

    # ------------------------------------------------------------ setup help
    def template_checklist(self, script: str) -> list[tuple[str, str, bool, bool]]:
        """[(name, description, optional, captured)] for the Templates tab."""
        if script in SCRIPTS:
            return [(t.name, t.description, t.optional, self.store.has(t.name))
                    for t in SCRIPTS[script].all_templates()]
        if script.startswith(CUSTOM_PREFIX):
            r = self.routines.get(script[len(CUSTOM_PREFIX):], {})
            names = templates_used([r.get("steps", []), r.get("recovery", []),
                                    r.get("interrupts", [])])
            return [(n, "Used by this custom routine.", False, self.store.has(n))
                    for n in sorted(names)]
        return []

    def missing_templates(self, script: str) -> list[str]:
        return [n for n, _, opt, have in self.template_checklist(script) if not opt and not have]
