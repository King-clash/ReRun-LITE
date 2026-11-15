"""ReRun LITE (rerun_lite/, lite_main.py): only Auto Crest and Dailies exist in it, both run the ORIGINAL code
(the same classes and functions the full app runs, driven here against the simulated game), and the full
app is not changed by it - neither its files' behaviour nor a config.yaml the two might share."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import ios, updates  # noqa: E402
from rerun.checklist import Checklist  # noqa: E402
from rerun.gui import App  # noqa: E402
from rerun.manager import Manager  # noqa: E402
from rerun.safety import TOS_WARNING  # noqa: E402
from rerun.scripts import SCRIPTS, CrestScript, LoginMailScript  # noqa: E402
from rerun_lite import APP_NAME, LITE_SCRIPTS, MAIN_SCRIPT, channel, content  # noqa: E402
from rerun_lite.app import NOT_LINKED, SCHEDULE_NOTE, LiteApp, bring_accounts  # noqa: E402
from rerun_lite.manager import LiteManager  # noqa: E402
from tests.test_scripts import Screen, Sim, background, crest_equip_screen, fast, patch  # noqa: E402

ALL_SCRIPTS = 16      # what the full app has; LITE must never change that


# ---------------------------------------------------------------- helpers
def lite_root(instances: list[dict] | None = None, real_templates: bool = False) -> Path:
    root = Path(tempfile.mkdtemp(prefix="rerunlite_t_"))
    if instances is not None:
        (root / "config.yaml").write_text(yaml.safe_dump({"instances": instances}), encoding="utf-8")
    if real_templates:
        content.copy_to(ROOT, root)             # exactly what build_lite.py ships
    return root


def manager(root: Path) -> tuple[LiteManager, str]:
    m = LiteManager(root)
    m.config["game_package"] = "fake.grandsummoners"
    m.config["live_view_fps"] = 0
    m.config["setup_seen"] = True
    return m, next(iter(m.instances))


def sim_templates(m: Manager, *script_ids: str) -> None:
    """A synthetic picture for every template those scripts use, captured into the manager's own store
    exactly as tests/test_scripts.make_ctx does for a bare script."""
    for sid in script_ids:
        for t in SCRIPTS[sid].all_templates():
            if not m.store.has(t.name):
                canvas, p = background(), patch(t.name)
                canvas[100:100 + p.shape[0], 100:100 + p.shape[1]] = p
                m.store.save(t.name, canvas, 100, 100, p.shape[1], p.shape[0])


def wait_done(m: Manager, inst: str, seconds: float = 60) -> None:
    """Until the worker thread has completely finished (status, session record, LITE's own clean-up)."""
    t0 = time.time()
    while time.time() - t0 < seconds:
        i = m.instances[inst]
        if i.status in ("idle", "error") and i.thread is not None and not i.thread.is_alive():
            return
        time.sleep(0.02)
    raise AssertionError(f"{inst} is still {m.instances[inst].status} after {seconds}s")


def texts(w) -> list[str]:
    out = []
    for c in w.winfo_children():
        try:
            t = str(c.cget("text")).strip()
            if t:
                out.append(t)
        except tk.TclError:
            pass
        out += texts(c)
    return out


def pump(app, n: int = 6) -> None:
    for _ in range(n):
        app.update()
        time.sleep(0.02)


def open_lite(instances: list[dict] | None = None):
    root = lite_root(instances, real_templates=True)
    m, inst = manager(root)
    app = LiteApp(m)
    app.errors = []
    app.report_callback_exception = lambda *a: app.errors.append(a)
    app.shown = []
    app.toast.show = lambda text, kind="info": app.shown.append(text)
    app.geometry("1140x840+30+30")
    pump(app)
    return root, m, inst, app


def close(app, root) -> None:
    app.update()
    app.destroy()
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- what exists in LITE
def test_lite_offers_only_crest_and_the_two_dailies_scripts():
    root = lite_root()
    shutil.copytree(ROOT / "routines", root / "routines")      # even with custom routines present
    try:
        m, inst = manager(root)
        assert tuple(m.scripts_available()) == LITE_SCRIPTS == ("crest", "login_mail", "raid_tickets")
        assert list(m.scripts_available().values()) == ["Crest", "Login & Mail", "Raid Tickets (Beta)"]
        for other in ("any_quest", "arena", "chain", "queue", "compendium_counter", "custom:example_tap_through"):
            assert m.start(inst, other) == f"Unknown script '{other}'", other
        assert m.instances[inst].status == "idle" and m.instances[inst].script == MAIN_SCRIPT
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_full_app_is_unchanged_by_lite_being_loaded():
    root = lite_root()
    shutil.copytree(ROOT / "routines", root / "routines")
    try:
        assert len(SCRIPTS) == ALL_SCRIPTS and list(SCRIPTS)[:3] == ["any_quest", "crest", "login_mail"]
        full = Manager(root).scripts_available()
        assert len(full) == ALL_SCRIPTS + 1 and "custom:example_tap_through" in full and "arena" in full
        # importing LITE does not redirect the full app's updater; only LITE's own start-up does
        assert not channel.applied()
        assert updates.APP_NEW == "Rerun.update.exe" and updates.STATE_FILE == "content_state.json"
        assert updates.settings({})["url"] == updates.UPDATE_URL
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_lite_runs_the_original_code_not_a_copy():
    """Every piece of Auto Crest and Dailies is the full app's own object."""
    assert SCRIPTS["crest"] is CrestScript and SCRIPTS["login_mail"] is LoginMailScript
    for name in ("_record_session", "script_settings", "save_script_settings", "notify", "stop", "pause",
                 "resume", "scheduler_tick", "template_checklist", "missing_templates", "totals", "energy"):
        assert getattr(LiteManager, name) is getattr(Manager, name), name
    for name in ("_build_dashboard", "start_sel", "dry_run_sel", "stop_sel", "pause_sel", "start_all", "stop_all",
                 "_refresh_crests", "_auto_preview", "_am_checklist", "_am_task", "am_add_task", "am_run_task",
                 "am_run_next", "_start_checked", "_build_history", "_build_templates", "_build_settings",
                 "_save_settings_form", "_build_discord", "_build_log", "_build_app_settings", "_poll_events",
                 "quit_app", "on_close", "check_updates", "_check_key"):
        assert getattr(LiteApp, name) is getattr(App, name), name
    root = lite_root()
    try:
        m, _ = manager(root)
        assert type(m.ops.checklist) is Checklist
        own = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "rerun_lite").glob("*.py"))
        assert "class CrestScript" not in own and "BUILTIN_TASKS" not in own and "def handle_" not in own
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_emulator_is_a_crest_emulator_and_config_yaml_keeps_its_own_script():
    root = lite_root([{"name": "A", "serial": "127.0.0.1:5555", "script": "any_quest"},
                      {"name": "B", "serial": "127.0.0.1:5565", "script": "arena"}])
    try:
        m, _ = manager(root)
        assert [i.script for i in m.instances.values()] == ["crest", "crest"]
        m._worker = lambda inst: None                      # no emulator here: only what would be started
        assert m.start_all() == ["Started Crest on A for Main", "Started Crest on B for Main"]
        for i in m.instances.values():
            assert i.script == "crest" and i.status == "starting"
            i.status = "idle"
        m.config["schedules"] = {"A": {"enabled": True, "time": "06:05"}}
        from datetime import datetime
        assert m.scheduler_tick(datetime(2026, 11, 16, 6, 5))[0] == "start A" and m.instances["A"].script == "crest"
        m.instances["A"].status = "idle"
        assert m.start("A", "login_mail").startswith("Started Login & Mail on A")
        m.instances["A"].status = "idle"
        m.set_instances(m.config["instances"] + [{"name": "C", "serial": "127.0.0.1:5575", "script": "crest"}])
        m.save_config()
        saved = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))["instances"]
        assert [(i["name"], i["script"]) for i in saved] == [("A", "any_quest"), ("B", "arena"), ("C", "crest")], saved
        assert [i.script for i in Manager(root).instances.values()] == ["any_quest", "arena", "crest"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_lite_ships_only_the_templates_its_scripts_use():
    files = content.lite_files(ROOT)
    names = {Path(rel).stem for rel in files}
    declared = set(content.template_names())
    assert names <= declared and 55 <= len(names) == len(list((ROOT / "templates").glob("*.png")))
    for must in ("equip_crest_screen", "crest_icon_lv4plus", "redeploy_button", "mail_chest", "claim_all_button"):
        assert must in names, must
    assert not [n for n in names if n.startswith(("arena_", "mines_", "gc_", "compendium_"))]
    root = lite_root(real_templates=True)
    try:
        m, _ = manager(root)
        # the two tested scripts need nothing more than what LITE ships (Raid Tickets is Beta in the full app too)
        assert m.missing_templates("crest") == [] and m.missing_templates("login_mail") == []
        meta = json.loads((root / "templates" / "_meta.json").read_text(encoding="utf-8"))
        assert meta and set(meta) <= names
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- Auto Crest, through LITE
def crest_run(icon: str, keep: str = "4+ and Burst only"):
    """tests/test_scripts.run_crest, but started the way LITE starts it: LiteManager.start with no script."""
    fast()
    root = lite_root()
    m, inst = manager(root)
    sim_templates(m, "crest")
    m.save_script_settings(inst, "crest", {"keep": keep, "runs": 0, "start_home": False})
    dev = Sim({"equip": crest_equip_screen(icon), "autoloop": Screen([("looping_button", 450, 960)])},
              "equip", {("equip", "redeploy_button"): "autoloop"})
    orig = Sim.tap

    def tap(self, x, y):
        orig(self, x, y)
        if self.tapped[-1] == "looping_button":
            m.stop(inst)
    dev.tap = tap.__get__(dev)
    m.instances[inst].device = dev
    msg = m.start(inst)
    assert msg == f"Started Crest on {inst} for Main", msg
    wait_done(m, inst)
    return root, m, inst, dev


def test_auto_crest_scraps_a_low_crest_and_redeploys_as_in_the_full_app():
    root, m, inst, dev = crest_run("crest_icon_lv3")
    try:
        assert dev.tapped[:3] == ["crest_checkbox", "crest_checkbox", "redeploy_button"], dev.tapped
        st = m.stats.get(inst)
        assert st["crest.crest_lv3"] == 1 and st["crest.scrapped"] == 1, st
        i = m.instances[inst]
        assert i.status == "idle" and i.detail == "stopped by user" and i.script == "crest"
        assert any(e.get("action") == "scrapped" for e in m.history.recent(50, inst))
        assert [r["rarity"] for r in m.crests.records] == ["lv3"], m.crests.records
        ses = m.ops.store.sessions(m.ops.store.active_id)
        assert len(ses) == 1 and ses[0]["script"] == "crest" and ses[0]["status"] == "stopped" and not ses[0]["dry_run"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_auto_crest_keeps_a_4plus_untouched_stops_and_tells_you():
    root, m, inst, dev = crest_run("crest_icon_lv4plus")
    try:
        assert dev.tapped == [], dev.tapped
        assert m.instances[inst].status == "idle" and m.instances[inst].detail == "4+ crest"
        assert any("NOTIFY" in line and "4+ crest found" in line for line in m.log_lines), m.log_lines[-8:]
        assert any(e.get("action") == "kept" for e in m.history.recent(50, inst))
        assert [r["rarity"] for r in m.crests.records] == ["4+"]
        assert m.ops.store.sessions(m.ops.store.active_id)[0]["status"] == "completed"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_auto_crest_keep_setting_and_unknown_crest_behave_as_in_the_full_app():
    root, m, inst, dev = crest_run("crest_icon_lv4", keep="Lv4 and better")
    try:
        assert dev.tapped == [] and m.instances[inst].detail == "lv4 crest"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    root, m, inst, dev = crest_run("some_unknown_icon")
    try:
        assert dev.tapped == [] and m.instances[inst].detail == "unknown crest"      # safe default: stop
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_crest_dry_run_from_lite_taps_nothing_and_is_recorded_as_one():
    import cv2
    from rerun.adb import FakeDevice
    root = lite_root(real_templates=True)
    try:
        m, inst = manager(root)
        dev = FakeDevice([cv2.imread(str(ROOT / "tests" / "fixtures" / "home.png"))])
        m.instances[inst].device = dev
        assert m.start(inst, dry_run=True) == f"Dry run of Crest on {inst} for Main (nothing will be tapped)"
        wait_done(m, inst)
        assert dev.taps == [], dev.taps
        ses = m.ops.store.sessions(m.ops.store.active_id)
        assert len(ses) == 1 and ses[0]["dry_run"] and ses[0]["script"] == "crest", ses
        assert any("DRY RUN RESULT" in line for line in m.log_lines)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- Dailies, through LITE
class LoginSim(Sim):
    def tap(self, x, y):
        if self.current in ("title", "bonus"):
            self.tapped.append(self.current)
            self.go("bonus" if self.current == "title" else "home")
            return
        super().tap(x, y)


def login_sim() -> LoginSim:
    """The game of tests/test_scripts.test_login_mail_claims_until_empty."""
    screens = {
        "title": Screen([], extra=[("game_start_screen", 290, 1040)]),
        "bonus": Screen([], extra=[("total_sign_in_bonus", 280, 160)]),
        "home": Screen([("mail_chest", 550, 192)]),
        "mail_full": Screen([("claim_all_button", 450, 992), ("mail_close_button", 575, 64)]),
        "claimed": Screen([("claim_ok_button", 300, 800)]),
        "mail_empty": Screen([("claim_all_button_dim", 450, 992), ("mail_close_button", 575, 64)]),
    }
    return LoginSim(screens, "title", {("home", "mail_chest"): "mail_full",
                                       ("mail_full", "claim_all_button"): "claimed",
                                       ("claimed", "claim_ok_button"): "mail_empty",
                                       ("mail_empty", "mail_close_button"): "home"})


def test_dailies_run_does_login_and_mail_then_waits_for_your_confirmation():
    fast()
    root = lite_root()
    try:
        m, inst = manager(root)
        sim_templates(m, "login_mail")
        m.save_script_settings(inst, "login_mail", {"mode_247": False, "claim_limit": 30})
        aid, cl = m.ops.store.active_id, m.ops.checklist
        assert m.ops.store.get(aid)["instance"] == inst, "the first account is linked to the only emulator"
        dev = login_sim()
        m.instances[inst].device = dev
        assert [r["id"] for r in cl.due_automatable(aid, m.scripts_available())] == ["login_reward", "raid_tickets"]
        msg = m.ops.run_task(aid, "login_reward")
        assert msg == f"Started Login & Mail on {inst} for Main", msg
        wait_done(m, inst)
        assert dev.tapped == ["title", "bonus", "mail_chest", "claim_all_button", "claim_ok_button",
                              "mail_close_button"], dev.tapped
        rows = {r["id"]: r for r in cl.rows(aid)}
        assert rows["login_reward"]["state"] == "unverified", rows["login_reward"]
        assert m.instances[inst].script == "crest", "after a Dailies task the emulator is a Crest emulator again"
        assert "already done" in m.ops.run_task(aid, "login_reward")          # no duplicate run
        cl.confirm(aid, "login_reward")
        assert {r["id"]: r for r in cl.rows(aid)}["login_reward"]["state"] == "completed"
        ses = m.ops.store.sessions(aid)
        assert [(s["script"], s["status"]) for s in ses] == [("login_mail", "completed")], ses
        assert "manual task" in m.ops.run_task(aid, "daily_missions")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_dailies_checklist_is_the_original_checklist():
    """Game-clock resets, manual done/undo, your own tasks and priorities work on LITE's manager."""
    from datetime import datetime
    from rerun.checklist import GAME_TZ
    root = lite_root()
    try:
        m, _ = manager(root)
        aid, cl = m.ops.store.active_id, m.ops.checklist
        assert [d["id"] for d in cl.definitions(aid)] == ["login_reward", "daily_missions", "weekly_shop", "free_summon",
                                                          "weekly_missions", "raid_tickets"]
        day = datetime(2026, 11, 16, 12, 0, tzinfo=GAME_TZ).timestamp()
        cl.mark_done(aid, "daily_missions", now=day)
        state = lambda t, tid: {r["id"]: r for r in cl.rows(aid, t)}[tid]["state"]       # noqa: E731
        assert state(day, "daily_missions") == "completed"
        assert state(datetime(2026, 11, 17, 5, 59, tzinfo=GAME_TZ).timestamp(), "daily_missions") == "completed"
        assert state(datetime(2026, 11, 17, 6, 1, tzinfo=GAME_TZ).timestamp(), "daily_missions") == "available"
        cl.undo(aid, "daily_missions")
        assert state(day, "daily_missions") == "available"
        tid = cl.add_task(aid, "Guild check-in", "weekly", 1)
        assert cl.definitions(aid)[0]["id"] == tid and cl.summary(aid)["weekly"]["total"] == 3
        cl.remove_task(aid, "free_summon")
        assert "free_summon" not in [d["id"] for d in cl.definitions(aid)]
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- the window
def test_window_has_the_two_features_and_only_their_tools():
    root, m, inst, app = open_lite()
    try:
        assert [lb.cget("text") for _, lb in app.nb._tabs] == ["Auto Crest", "Dailies", "History", "Templates", "Settings"]
        assert app.title() == APP_NAME
        assert [k for k, _ in app._set_nav._items] == ["scripts", "discord", "log", "app"]
        for attr in ("_am_nav", "_farm_nav", "_tab_accounts", "_tab_farming", "unit_tree", "companion"):
            assert not hasattr(app, attr), f"{attr}: a page LITE must not build"
        crest_page, dailies_page = app.nb._pages[app._tab_crest], app.nb._pages[app._tab_dailies]
        for page in (crest_page, dailies_page):                  # the warning is on both feature pages
            assert TOS_WARNING in texts(page)
        shown = texts(crest_page)
        assert "Auto Crest" in shown and "Dashboard" not in shown
        for word in ("INSTANCES", "TOTALS", "CRESTS", "LIVE VIEW", "INSTRUCTIONS", "4+ crests", "Crest Burst"):
            assert word in shown, word
        group = app.script_box.master
        while not isinstance(group, ios.Group):
            group = group.master
        assert group.winfo_manager() == "" and app.comp_line.winfo_manager() == "", "no script chooser, no Compendium line"
        assert "CREST FARMING" in app.instr.get("1.0", "end")
        for box in (app.set_script, app.tpl_script):
            assert box["values"] == ["Crest", "Login & Mail", "Raid Tickets (Beta)"] and box.get() == "Crest"
        assert not app.errors, app.errors
    finally:
        close(app, root)


def test_auto_crest_buttons_start_crest_through_the_original_checks():
    root, m, inst, app = open_lite()
    try:
        started = []
        m._worker = lambda i: started.append((i.name, i.script, i.dry_run))
        app.start_sel()
        pump(app)
        assert app.shown[-1] == f"Started Crest on {inst} for Main", app.shown
        m.instances[inst].thread.join(5)
        m.instances[inst].status = "idle"
        app.dry_run_sel()
        m.instances[inst].thread.join(5)
        m.instances[inst].status = "idle"
        app.start_all()
        m.instances[inst].thread.join(5)
        assert started == [(inst, "crest", False), (inst, "crest", True), (inst, "crest", False)], started
        assert app._dashboard_in_view()
        app.nb.select(app._tab_dailies)
        assert not app._dashboard_in_view()
        assert not app.errors, app.errors
    finally:
        m.instances[inst].status = "idle"
        close(app, root)


def test_dailies_tab_draws_the_checklist_and_its_buttons_work():
    root, m, inst, app = open_lite()
    asked = []
    real_confirm = ios.confirm
    ios.confirm = lambda *a, **k: asked.append(a[1]) or False
    try:
        aid, cl = m.ops.store.active_id, m.ops.checklist
        app.nb.select(app._tab_dailies)
        pump(app)
        shown = texts(app._am_inner)
        for word in ("Daily & weekly checklist", "Login reward + mail   (priority 1)", "Automated by Login & Mail",
                     "Automated by Raid Tickets (Beta)", "Weekly shop items   (priority 2)", "Available"):
            assert word in shown, (word, shown[:12])
        assert app._dl_inst.get() == inst and app._dl_week.get() == "Monday"
        assert app._dl_account.winfo_manager() == "", "one account: no account picker"
        app._am_task(aid, "mark_done", "daily_missions")
        pump(app)
        assert {r["id"]: r for r in cl.rows(aid)}["daily_missions"]["state"] == "completed"
        assert "Completed" in texts(app._am_inner)
        # Run on the Beta task asks first (and "no" starts nothing); Run on the tested one starts Login & Mail
        app.am_run_task(aid, "raid_tickets")
        assert asked and "has not been run on a real game" in asked[0] and m.instances[inst].status == "idle"
        started = []
        m._worker = lambda i: started.append((i.script, i.task, i.account))
        app.am_run_next(aid)
        m.instances[inst].thread.join(5)
        assert started == [("login_mail", "login_reward", aid)], started
        assert app.shown[-1] == f"Started Login & Mail on {inst} for Main"
        m.instances[inst].status = "idle"
        cl.cancel_run(aid, "login_reward")
        # the two selectors LITE adds: weekly reset day and the emulator the account plays on
        app._dl_week.set("Thursday")
        app._dl_set_week()
        assert m.ops.store.get(aid)["prefs"]["week_reset_weekday"] == 3
        app._dl_inst.set(NOT_LINKED)
        app._dl_link()
        assert m.ops.store.get(aid)["instance"] == ""
        app.am_run_task(aid, "login_reward")
        assert "Runs on" in app.shown[-1] and "Account Manager" not in app.shown[-1], app.shown[-1]
        app._dl_inst.set(inst)
        app._dl_link()
        assert m.ops.store.get(aid)["instance"] == inst
        # a second account brings the picker back; switching redraws the other account's checklist
        other = m.ops.store.create("Alt")
        pump(app, 10)
        assert app._dl_account.winfo_manager() == "pack" and app._am_picker["values"] == ["Main", "Alt"]
        app._am_picker.set("Alt")
        app._am_pick()
        pump(app)
        assert m.ops.store.active_id == other and app._dl_inst.get() == NOT_LINKED
        assert "Completed" not in texts(app._am_inner)
        assert not app.errors, app.errors
    finally:
        ios.confirm = real_confirm
        m.instances[inst].status = "idle"
        close(app, root)


def test_checklist_redraws_when_the_game_day_turns_over():
    root, m, inst, app = open_lite()
    try:
        aid = m.ops.store.active_id
        m.ops.checklist.mark_done(aid, "daily_missions", now=time.time() - 3 * 86400)   # done three game days ago
        pump(app, 10)
        assert app._dl_signature() == app._dl_sig
        rec = m.ops.store.get(aid)["tasks"]["daily_missions"]
        rec["last_done"] = time.time()                       # as if it was done just now, without any event
        assert app._dl_signature() != app._dl_sig
        app._ticks = 19
        app._tick()
        assert app._dl_signature() == app._dl_sig and "Completed" in texts(app._am_inner)
        assert not app.errors, app.errors
    finally:
        close(app, root)


def test_settings_pages_are_the_originals_with_lite_names_and_places():
    from rerun.setup_check import Check
    root, m, inst, app = open_lite()
    try:
        app.open_script_settings("login_mail")
        pump(app)
        assert app.nb.index() == app._tab_settings and app._set_nav.current == "scripts"
        assert app.set_script.get() == "Login & Mail" and set(app.form_vars) == {"mode_247", "claim_limit"}
        assert app.form.winfo_children()[-1].footer.cget("text") == SCHEDULE_NOTE
        app.open_script_settings("crest")
        assert app.set_script.get() == "Crest" and {"runs", "keep", "start_home", "palace_name"} <= set(app.form_vars)
        app.form_vars["keep"].set("Lv4 and better")
        app._save_settings_form()
        assert m.script_settings(inst, "crest")["keep"] == "Lv4 and better"
        # the original opens Discord with nb.select(self._tab_discord): in LITE that is a Settings section
        app.nb.select(0)
        app.nb.select(app._tab_discord)
        assert app.nb.index() == app._tab_settings and app._set_nav.current == "discord"
        words = texts(app._set_pages["discord"]) + texts(app._set_pages["app"])
        assert f"Connect When {APP_NAME} Starts" in words and f"{APP_NAME} {updates.__version__}" in words
        assert not [w for w in words if "Rerun" in w], [w for w in words if "Rerun" in w]
        app._set_update_status("Up to date (Rerun 1.2.1)")
        assert app.upd_status.cget("text") == f"Up to date ({APP_NAME} 1.2.1)"
        # setup check: LITE's own two tested scripts, not Any Quest
        app._setup_body = tk.Frame(app)
        checks = [Check("Templates", True, "All templates for Any Quest, Crest and Login & Mail are captured.")]
        app._show_setup_results(checks)
        assert checks[0].ok and checks[0].detail == "All templates for Crest and Login & Mail are captured."
        app.flash("Automation is switched off for 'Main' (Account Manager > Safety).")
        assert "full ReRun" in app.shown[-1]
        assert not app.errors, app.errors
    finally:
        close(app, root)


def test_lite_keeps_its_window_memory_out_of_config_yaml():
    root, m, inst, app = open_lite([{"name": "A", "serial": "127.0.0.1:5555", "script": "any_quest"}])
    try:
        m.save_config()
        before = (root / "config.yaml").read_text(encoding="utf-8")
        app.nb.select(app._tab_dailies)
        app._save_ui_state()
        assert (root / "config.yaml").read_text(encoding="utf-8") == before
        ui = json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))
        assert ui["tab"] == app._tab_dailies and "x" in ui["geometry"]
        app.nb.select(0)
        app._restore_tab()
        assert app.nb.index() == app._tab_dailies
    finally:
        close(app, root)


def test_selftest_builds_the_whole_window():
    import lite_main
    out = Path(tempfile.mkdtemp()) / "r.txt"
    try:
        assert lite_main.selftest(out) == 0, out.read_text(encoding="utf-8")
        assert out.read_text(encoding="utf-8") == "ok Auto Crest | Dailies | History | Templates | Settings"
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def test_discord_bot_is_the_original_without_the_roster_commands():
    import asyncio
    try:
        import discord  # noqa: F401
    except ImportError:
        return
    from rerun.discord_bot import DiscordBot
    from rerun_lite.bot import LiteBot
    root = lite_root()
    try:
        m, inst = manager(root)
        m.config["discord"]["token"] = "not-a-real-token"

        async def names(cls):
            client = cls(m)._build_client()
            return sorted(c.name for c in client._connection._command_tree.get_commands())
        full, lite = asyncio.run(names(DiscordBot)), asyncio.run(names(LiteBot))
        assert set(full) - set(lite) == {"units", "compendium"}, (full, lite)
        for cmd in ("start", "stop", "pause", "resume", "status", "screenshot", "crests", "history", "summary", "scripts"):
            assert cmd in lite, cmd
        assert LiteBot.alert is DiscordBot.alert and LiteBot.on_button is DiscordBot.on_button
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- updates and data
def test_lite_updates_use_their_own_channel_and_never_the_full_apps():
    import functools
    import http.server
    import threading
    from rerun import ed25519
    from tools import publish_lite_update, publish_update
    secret = bytes(range(32))
    tmp = Path(tempfile.mkdtemp(prefix="rerunlite_upd_"))
    src, site, inst = tmp / "src", tmp / "site", tmp / "inst"
    content.copy_to(ROOT, src)
    (src / "templates" / "arena_x.png").write_bytes(b"not a LITE picture")     # the full app's content has more
    content.copy_to(ROOT, inst)
    site.mkdir()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    cfg = {"updates": {"url": f"http://127.0.0.1:{httpd.server_port}", "channel": "stable", "content_in_source": True}}
    real_key, real_version = updates.PUBLIC_KEY, publish_update.__version__
    updates.PUBLIC_KEY = ed25519.public_key(secret)
    try:
        channel.apply(inst)
        assert channel.applied() and updates.APP_NEW == "RerunLite.update.exe"
        assert updates.settings(cfg)["url"].endswith("/lite") and updates.settings({})["url"] == updates.UPDATE_URL + "/lite"
        # 1. only the full app has published: LITE finds nothing for itself and says so (not an error)
        publish_update.publish(site, "stable", secret, src=src)
        res = updates.check(inst, cfg)
        assert channel.not_published(res.error) and res.app is None, res.error
        # 2. the full app's manifest served at LITE's address is refused (it is not marked for LITE)
        publish_update.publish(site / "lite", "stable", secret, src=src)
        assert updates.check(inst, cfg).error == channel.NOT_LITE
        shutil.rmtree(site / "lite")
        # 3. a LITE release: LITE's templates only, LITE's exe, found and downloaded under LITE's own names
        (src / "templates" / "mail_chest.png").write_bytes(b"a newer mail chest picture")
        exe = tmp / "RerunLite.exe"
        exe.write_bytes(b"MZ a newer ReRun LITE")
        publish_update.__version__ = "99.0.0"
        man = publish_lite_update.publish(site, "stable", secret, exe=exe, notes="newer", src=src)
        assert man["product"] == "lite" and "templates/arena_x.png" not in man["content"]["files"]
        assert set(man["content"]["files"]) == set(content.lite_files(src))
        res = updates.check(inst, cfg)
        assert not res.error and res.app["version"] == "99.0.0", res.error
        # (no baseline in this folder: every picture counts as yours, so content is left alone)
        assert res.plan is not None and res.plan.install == {} and "templates/mail_chest.png" in res.plan.kept
        got = updates.download_app(inst, cfg, res.app)
        assert got.name == "RerunLite.update.exe" and got.read_bytes() == exe.read_bytes()
        assert not (inst / "Rerun.update.exe").exists() and not (inst / "content_state.json").exists()
        # 4. with a build's baseline the changed picture IS updated, and the state goes to LITE's own file
        base = {rel: updates.sha256_file(p) for rel, p in content.lite_files(inst).items()}
        (inst / "lite_content_baseline.json").write_text(json.dumps({"files": base}), encoding="utf-8")
        res = updates.check(inst, cfg)
        assert list(res.plan.install) == ["templates/mail_chest.png"], res.plan.install
        updates.stage_content(inst, cfg, res.plan)
        assert "1 file(s) updated" in updates.commit_staged(inst)
        assert (inst / "templates" / "mail_chest.png").read_bytes() == b"a newer mail chest picture"
        assert (inst / "data" / "lite" / "content_state.json").exists() and not (inst / "content_state.json").exists()
        assert not (inst / ".update_staging").exists()
        # 5. sharing a folder with the full ReRun: LITE leaves templates/ to it
        (inst / "Rerun.exe").write_bytes(b"MZ")
        assert updates.settings(cfg)["content"] is False and updates.check(inst, cfg).plan is None
    finally:
        channel.restore()
        updates.PUBLIC_KEY, publish_update.__version__ = real_key, real_version
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)
    assert not channel.applied() and updates.APP_NEW == "Rerun.update.exe" and updates.settings({})["url"] == updates.UPDATE_URL


def test_update_result_with_nothing_published_is_shown_as_a_fact():
    root, m, inst, app = open_lite()
    alerts = []
    real_alert = ios.alert
    ios.alert = lambda r, msg, title="Rerun": alerts.append(msg)
    try:
        res = updates.CheckResult(error="Update host answered 404 for https://example.invalid/ReRun/lite/stable/manifest.json")
        app._upd_busy = True
        app._on_update_result({"result": res, "staged": "", "quiet": False})
        assert app.upd_status.cget("text") == channel.NOT_PUBLISHED and app.shown[-1] == channel.NOT_PUBLISHED
        assert not alerts and app._upd_busy is False
        app._on_update_result({"result": updates.CheckResult(error="Could not reach the update host: timed out"),
                               "staged": "", "quiet": False})
        assert alerts == ["Could not reach the update host: timed out"]       # a real failure still is one
        assert not app.errors, app.errors
    finally:
        ios.alert = real_alert
        close(app, root)


def test_first_run_import_also_brings_the_checklist_over():
    old, new = lite_root(), lite_root()
    try:
        m, _ = manager(old)                                   # a ReRun folder with an account and a task of its own
        aid = m.ops.store.active_id
        m.ops.checklist.add_task(aid, "Guild check-in")
        assert bring_accounts(new) == 0                       # nothing was imported: nothing to bring
        (new / "migrated_from.json").write_text(json.dumps({"from": str(old)}), encoding="utf-8")
        assert bring_accounts(new) > 0
        m2, _ = manager(new)
        assert any(d["name"] == "Guild check-in" for d in m2.ops.checklist.definitions(m2.ops.store.active_id))
        assert bring_accounts(new) == 0                       # never over accounts this copy already has
    finally:
        shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(new, ignore_errors=True)


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, repr(e))
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
