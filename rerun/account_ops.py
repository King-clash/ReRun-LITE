"""Glue between the Account Manager data and the rest of Rerun (Manager, scripts, Discord).

Every farming session is tied to exactly one account here, before it starts:
  * one account bound to the emulator            -> that account;
  * several accounts share the emulator          -> refused unless the caller confirms which account is
                                                    logged in (Rerun cannot see which account is on screen);
  * no account bound to it                       -> the active account if it is unbound, else unattributed.
"""
from __future__ import annotations

import time
from datetime import datetime

from . import errlog, safety
from .accounts import SCAN_SUPPORT, AccountError, AccountStore
from .checklist import GAME_TZ, Checklist, fmt_until, period_start
from .crest_stats import RARITIES
from .goals import Goals
from .units import UnitRoster
from .vault import Vault


class AccountOps:
    def __init__(self, m):
        self.m = m
        self.store = AccountStore(m.root)
        self.checklist = Checklist(self.store)
        self.vault = Vault(self.store, m.crests)
        self.goals = Goals(self.store, self.vault, self.roster_for, m.crests)
        self.legacy_units: UnitRoster = m.units
        self._rosters: dict[str, UnitRoster] = {}
        self.ensure_default()
        self.use_account(self.store.active_id, announce=False)
        self.store.listeners.append(lambda *a: m.emit({"type": "account", "kind": a[0], "account": a[1],
                                                       "detail": a[2]}))

    # ------------------------------------------------------------------ setup
    def ensure_default(self) -> None:
        """First run: one account called 'Main' that owns the existing unit roster, so nothing is lost
        or copied. It is linked to the emulator when there is exactly one."""
        if self.store.ids():
            return
        insts = list(self.m.instances)
        self.store.create("Main", instance=insts[0] if len(insts) == 1 else "", legacy_units=True,
                          notes="Created automatically from your existing Rerun data.")

    def roster_for(self, aid: str) -> UnitRoster | None:
        d = self.store.units_dir(aid)
        if d is None:
            return self.legacy_units
        if aid not in self._rosters:
            r = UnitRoster(d)
            leg = self.legacy_units
            r.reference, r.reference_facts = leg.reference, leg.reference_facts
            self._rosters[aid] = r
        return self._rosters[aid]

    def use_account(self, aid: str, announce: bool = True) -> None:
        """Make `aid` the account the Units tab and the Compendium show and write to."""
        from .compendium import Compendium
        if aid:
            self.store.set_active(aid)
        roster = self.roster_for(aid) if aid else self.legacy_units
        if roster is not self.m.units or not hasattr(self.m, "compendium"):
            self.m.units = roster
            self.m.compendium = Compendium(roster, self.m.history)
            roster.rename_listeners = [self.m.compendium.rename]
        if announce:
            self.m.log("app", f"Active account: {self.store.get(aid)['name']}")

    def name(self, aid: str | None) -> str:
        try:
            return self.store.get(aid)["name"] if aid else ""
        except AccountError:
            return ""

    # ------------------------------------------------------------------ who is this run for
    def resolve(self, instance: str, confirm_account: str | None = None) -> tuple[str | None, str | None]:
        """(account id or None, error). The error is a sentence for the user."""
        bound = self.store.accounts_for_instance(instance)
        if len(bound) == 1:
            return bound[0]["id"], None
        if len(bound) > 1:
            if confirm_account and any(a["id"] == confirm_account for a in bound):
                return confirm_account, None
            names = ", ".join(a["name"] for a in bound)
            return None, (f"{len(bound)} accounts share '{instance}' ({names}). Rerun cannot see which one is "
                          "logged in - pick the account in the Macro Farming tab and confirm it is the one "
                          "currently open in the emulator.")
        act = self.store.active()
        if act and not act["instance"]:
            return act["id"], None
        return None, None            # unattributed: runs as before, recorded in no account

    def account_of_running(self, instance: str) -> str | None:
        inst = self.m.instances.get(instance)
        return getattr(inst, "account", "") or None

    def before_start(self, instance: str, script: str, confirm_account: str | None, dry_run: bool):
        """(account id | None, error | None, dry_run) - run by Manager.start before a thread is created."""
        aid, err = self.resolve(instance, confirm_account)
        if err:
            return None, err, False
        if aid:
            why = safety.check_start(self.store, aid, script)
            if why:
                return None, why, False
            dry_run = dry_run or bool(self.store.get(aid)["safety"]["dry_run"])
        return aid, None, dry_run

    # ------------------------------------------------------------------ sessions
    def session_started(self, inst, aid: str | None, dry_run: bool) -> None:
        inst.account, inst.session_id = aid or "", ""
        if not aid:
            return
        try:
            inst.session_id = self.store.begin_session(aid, inst.name, inst.script, dry_run)
            lim = int(self.store.get(aid)["safety"]["session_minutes_limit"])
            if lim and not dry_run:
                self.m.arm_limit(inst, lim)
        except Exception as e:  # noqa: BLE001 - bookkeeping must never stop a farm
            errlog.note("ops.session_start", e)

    def session_ended(self, inst, delta: dict, reason: str) -> None:
        aid, sid = getattr(inst, "account", ""), getattr(inst, "session_id", "")
        if not aid or not sid:
            return
        try:
            results = {}
            for label, pick in (("runs", lambda k: k.endswith(".runs")),
                                ("crests", lambda k: ".crest_" in k),
                                ("potions", lambda k: "potion" in k.rsplit(".", 1)[-1]),
                                ("restarts", lambda k: k.endswith("game_restarts"))):
                n = sum(v for k, v in delta.items() if pick(k))
                if n > 0:
                    results[label] = n
            dry = bool(getattr(inst, "dry_run", False))
            if dry:
                results["planned actions"] = len(getattr(inst, "last_plan", None) or [])
            ok = reason.startswith("finished") or reason.startswith("stopped: stopped")
            status = "completed" if (reason.startswith("finished") or (dry and "dry run complete" in reason))                 else ("stopped" if ok else "error")
            err = "" if status != "error" else reason
            self.store.end_session(aid, sid, status, results, err)
            ctx = inst.ctx
            e = ctx.params.get("energy") if ctx is not None else None
            if e and not getattr(inst, "dry_run", False):
                self.store.record_scan(aid, {"energy": (e[0], 90.0), "energy_max": (e[1], 90.0)},
                                       source="energy bar (read while farming)")
            tid = getattr(inst, "task", "")
            if tid:
                if getattr(inst, "dry_run", False):
                    self.checklist.cancel_run(aid, tid)             # a dry run completes nothing
                else:
                    self.checklist.end_run(aid, tid, ok=reason.startswith("finished"))
            if status == "error" and not dry and self.store.get(aid)["notify"]["failures"]:
                self.m.notify(inst.name, f"{self.name(aid)}: {inst.script} ended with a problem: {reason}", ping=True)
        except Exception as ex:  # noqa: BLE001
            errlog.note("ops.session_end", ex)

    def run_task(self, aid: str, tid: str) -> str:
        """Start the script behind a checklist task. Refuses anything done already, unautomatable, or unsafe;
        returns a sentence for the user."""
        try:
            tdef = next((d for d in self.checklist.definitions(aid) if d["id"] == tid), None)
            if tdef is None:
                return "Unknown task."
            avail = self.m.scripts_available()
            if not tdef.get("script") or tdef["script"] not in avail:
                return f"'{tdef['name']}' is a manual task - Rerun has no tested routine for it."
            inst = self.store.get(aid)["instance"]
            if not inst or inst not in self.m.instances:
                return "Link this account to an emulator first (Account Manager > Information)."
            if len(self.store.accounts_for_instance(inst)) > 1 and self.store.active_id != aid:
                return "Several accounts share this emulator - make this account active and confirm it is open in the game."
            self.checklist.begin_run(aid, tid)
        except AccountError as e:
            return str(e)
        msg = self.m.start(inst, tdef["script"], confirm_account=aid, task=tid)
        if not msg.startswith(("Started", "Dry run")):
            self.checklist.cancel_run(aid, tid)
        return msg

    # ------------------------------------------------------------------ scanning
    def scan_screen(self, aid: str) -> dict:
        """Read the top bar (energy, gold, gems, Rank) from the emulator linked to this account and store each
        value with its provenance. Needs a normal screen with the bar at full brightness."""
        a = self.store.get(aid)
        inst = a["instance"]
        unsupported = [k for k, v in SCAN_SUPPORT.items() if v[0] == "unsupported"]
        if not inst or inst not in self.m.instances:
            raise AccountError("Link this account to an emulator first (Account Manager > Account Information).")
        if len(self.store.accounts_for_instance(inst)) > 1 and self.store.active_id != aid:
            raise AccountError("Several accounts share this emulator. Make this account the active one, "
                               "and make sure it is the account open in the game, before scanning.")
        try:
            from .ocr import get_ocr, read_energy, read_header
            shot = self.m.screenshot(inst)
            ocr = get_ocr(self.m.config.get("tesseract_path", "auto"))
            r = read_energy(ocr, shot)
            head = read_header(ocr, shot)
        except Exception as e:  # noqa: BLE001 - no device / no OCR: report, change nothing
            self.store.log_activity(aid, "scan", f"Energy scan failed: {e}")
            raise AccountError(f"Could not scan: {e}") from e
        readings = {"energy": (r[0], 90.0), "energy_max": (r[1], 90.0)} if r else {}
        readings.update(head)
        return self.store.record_scan(aid, readings, "top bar (scan)",
                                      expected=["energy", "energy_max", "gold", "gems", "player_level"],
                                      unsupported=unsupported)

    # ------------------------------------------------------------------ dashboard numbers
    def energy_refill(self, aid: str, now: float | None = None) -> str:
        now = now or time.time()
        e, mx = self.store.field(aid, "energy"), self.store.field(aid, "energy_max")
        regen = int(self.store.get(aid)["prefs"]["energy_regen_minutes"])
        if not e or not mx:
            return "unknown (no energy recorded)"
        if e["value"] >= mx["value"]:
            return "full"
        if not regen:
            return "unknown (set minutes per energy point in Safety & settings)"
        left = (mx["value"] - e["value"]) * regen * 60 - (now - e["t"])
        return "full by now (estimate)" if left <= 0 else f"full in about {fmt_until(left)} (estimate)"

    def stale_scan(self, aid: str, now: float | None = None) -> bool:
        ok = self.store.get(aid)["last_scan_ok"]
        hrs = int(self.store.get(aid)["prefs"]["stale_scan_hours"])
        return not ok or (now or time.time()) - ok > hrs * 3600

    def series(self, aid: str, kind: str, now: float | None = None, n: int = 7) -> list[tuple[str, float]]:
        """Chart data from recorded history only. Periods with no data are 0 or missing, never invented."""
        now = now or time.time()
        out: list[tuple[str, float]] = []
        wd = int(self.store.get(aid)["prefs"]["week_reset_weekday"])
        if kind == "crests_per_day":
            recs = self.vault.ledger_records(aid)
            for i in range(n - 1, -1, -1):
                s = period_start(now - i * 86400, "daily")
                c = sum(1 for r in recs if s <= float(r["t"]) < s + 86400)
                out.append((datetime.fromtimestamp(s, GAME_TZ).strftime("%a %d"), c))
        elif kind == "sessions_per_day":
            ss = [s for s in self.store.sessions(aid) if not s.get("dry_run")]
            for i in range(n - 1, -1, -1):
                s0 = period_start(now - i * 86400, "daily")
                c = sum(1 for s in ss if s0 <= s["start"] < s0 + 86400)
                out.append((datetime.fromtimestamp(s0, GAME_TZ).strftime("%a %d"), c))
        elif kind == "energy_used_per_day":
            hist = self.store.resource_history(aid, "energy")
            for i in range(n - 1, -1, -1):
                s0 = period_start(now - i * 86400, "daily")
                pts = [(t, v) for t, v in hist if s0 <= t < s0 + 86400]
                used = sum(max(0, a[1] - b[1]) for a, b in zip(pts, pts[1:]))
                out.append((datetime.fromtimestamp(s0, GAME_TZ).strftime("%a %d"), used))
        elif kind == "gems_by_week":
            hist = self.store.resource_history(aid, "gems")
            for i in range(n - 1, -1, -1):
                s0 = period_start(now - i * 7 * 86400, "weekly", wd)
                pts = [v for t, v in hist if s0 <= t < s0 + 7 * 86400]
                if pts:
                    out.append((datetime.fromtimestamp(s0, GAME_TZ).strftime("%d %b"), pts[-1]))
        return out

    # ------------------------------------------------------------------ reports + alerts
    def daily_report(self, aid: str, now: float | None = None) -> str:
        now = now or time.time()
        a = self.store.get(aid)
        cl = self.checklist.summary(aid, now)
        d0 = period_start(now, "daily")
        sess = [s for s in self.store.sessions(aid) if s["start"] >= d0 and not s.get("dry_run")]
        res: dict[str, int] = {}
        for s in sess:
            for k, v in (s.get("results") or {}).items():
                res[k] = res.get(k, 0) + v
        crest = [r for r in self.vault.ledger_records(aid) if float(r["t"]) >= d0]
        lines = [f"**{a['name']}**" + (f" ({a['label']})" if a["label"] else "") + " - game day report"]
        lines.append(f"Daily tasks: {cl['daily']['done']}/{cl['daily']['total']} done"
                     + (f" - remaining: {', '.join(cl['daily']['remaining'])}" if cl["daily"]["remaining"] else ""))
        if cl["daily"]["unverified"]:
            lines.append(f"  ({cl['daily']['unverified']} finished by a script but not confirmed by you)")
        lines.append(f"Weekly tasks: {cl['weekly']['done']}/{cl['weekly']['total']} done "
                     f"(resets in {fmt_until(cl['weekly']['resets_in'])})")
        e, mx = self.store.field(aid, "energy"), self.store.field(aid, "energy_max")
        if e and mx:
            lines.append(f"Energy: {e['value']}/{mx['value']} ({e['status']}) - refill {self.energy_refill(aid, now)}")
        lines.append(f"Farming: {len(sess)} session(s)" + (", " + ", ".join(f"{v} {k}" for k, v in res.items()) if res else ""))
        if crest:
            by = {r["rarity"]: 0 for r in crest}
            for r in crest:
                by[r["rarity"]] += 1
            lines.append("Crests: " + ", ".join(f"{n} {k}" for k, n in sorted(by.items(), key=lambda kv: RARITIES.index(kv[0]))))
        bad = [s for s in sess if s["status"] == "error"]
        if bad:
            lines.append("Problems: " + "; ".join(f"{s['script']}: {s['error'][:80]}" for s in bad))
        gp = [p for p in self.goals.refresh(aid) if p["goal"]["status"] == "active"]
        if gp:
            lines.append("Goals: " + "; ".join(f"{p['goal']['title']} {p['current'] if p['current'] is not None else '?'}/{p['target']}" for p in gp[:4]))
        if self.stale_scan(aid, now):
            lines.append("Note: last successful scan is older than your limit - values may be out of date.")
        return "\n".join(lines)

    def _once(self, aid: str, key: str, now: float) -> bool:
        """True the first time `key` fires in this game day (alerts are never repeated)."""
        a = self.store.get(aid)
        day = str(period_start(now, "daily"))
        if a["alerts_sent"].get(key) == day:
            return False
        a["alerts_sent"][key] = day
        self.store._save(a)
        return True

    def check_alerts(self, now: float | None = None) -> list[str]:
        """Called from the scheduler tick. Returns the alerts it sent (for tests)."""
        now = now or time.time()
        sent = []
        for a in self.store.all():
            n, aid = a["notify"], a["id"]
            if not n["enabled"]:
                continue
            inst = a["instance"] or "app"
            e, below = self.store.field(aid, "energy"), int(n["low_energy_below"])
            if n["low_energy"] and below and e and e["value"] < below and self._once(aid, "low_energy", now):
                sent.append(self._alert(a, inst, f"Low energy: {e['value']} (alert level {below})."))
            if n["event_warnings"]:
                for ev in self.store.events():
                    left = ev["end"] - now
                    if ev["start"] <= now < ev["end"] and left <= int(n["event_warn_hours"]) * 3600 \
                            and ev["id"] not in a["event_done"] and self._once(aid, "event:" + ev["id"], now):
                        sent.append(self._alert(a, inst, f"Event '{ev['title']}' ends in {fmt_until(left)} and is not marked done."))
        return sent

    def _alert(self, a: dict, inst: str, text: str) -> str:
        msg = f"{a['name']}: {text}"
        self.m.notify(inst, msg, ping=bool(a["notify"]["ping"]))
        self.store.log_activity(a["id"], "alert", text)
        return msg

    def send_daily_reports(self, now: float | None = None) -> list[str]:
        sent = []
        for a in self.store.all():
            if a["notify"]["enabled"] and a["notify"]["daily_report"] and self.m.discord:
                self.m.discord.send(self.daily_report(a["id"], now), None, False)
                sent.append(a["id"])
        return sent
