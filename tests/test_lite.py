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
from rerun_lite import __version__ as LITE_VERSION  # noqa: E402
from rerun_lite.app import SCHEDULE_NOTE, LiteApp  # noqa: E402
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


def wait_done(m: Manager, inst: str, seconds: float = 240) -> None:
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


def open_lite(instances: list[dict] | None = None, backdrop: bool = False):
    root = lite_root(instances, real_templates=True)
    (root / "data" / "lite").mkdir(parents=True, exist_ok=True)
    look = {"look": "ahri", "mode": "dark"} if backdrop else {"look": "plain", "mode": "dark"}          # a video only for Ahri
    (root / "data" / "lite" / "ui.json").write_text(json.dumps({"appearance": look}), encoding="utf-8")
    m, inst = manager(root)
    app = LiteApp(m)
    app.errors = []
    app.report_callback_exception = lambda *a: app.errors.append(a)
    app.shown = []
    app.toast.show = lambda text, kind="info": app.shown.append(text)
    app.geometry("1140x840+30+30")
    pump(app)
    return root, m, inst, app


def wait_until(app, cond, seconds: float = 30.0) -> bool:
    t0 = time.time()
    while not cond() and time.time() - t0 < seconds:
        app.update()
        time.sleep(0.02)
    return bool(cond())


def close(app, root) -> None:
    app.update()
    app.destroy()
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- what exists in LITE
def test_lite_offers_only_crest():
    root = lite_root()
    shutil.copytree(ROOT / "routines", root / "routines")      # even with custom routines present
    try:
        m, inst = manager(root)
        assert tuple(m.scripts_available()) == LITE_SCRIPTS == ("crest",)
        assert list(m.scripts_available().values()) == ["Crest"]
        for other in ("any_quest", "arena", "chain", "queue", "compendium_counter", "login_mail", "raid_tickets", "custom:example_tap_through"):
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
    from rerun_lite.crest import LiteCrest
    assert SCRIPTS["crest"] is LiteCrest and issubclass(LiteCrest, CrestScript) and SCRIPTS["login_mail"] is LoginMailScript
    own_methods = {k for k, v in vars(LiteCrest).items() if callable(v) and not k.startswith("__")}
    assert own_methods == {"selector_choice", "selector_on", "check_nav_templates", "_stop_for", "_selector_root",
                           "handle_crest_palace_screen", "handle_quest_list", "scrap", "confirm_word", "tap_confirm"}, own_methods          # Crest itself is the original (finding the palace lives in palace_find.py)
    for name in ("script_settings", "save_script_settings", "notify", "stop", "scheduler_tick", "template_checklist", "missing_templates", "totals", "energy"):
        assert getattr(LiteManager, name) is getattr(Manager, name), name
    for name in ("_build_dashboard", "start_sel", "dry_run_sel", "stop_sel", "pause_sel", "start_all", "stop_all",
                 "_refresh_crests", "_auto_preview", "_am_checklist", "_am_task", "am_add_task", "am_run_task",
                 "am_run_next", "_start_checked", "_build_history", "_build_templates", "_build_settings",
                 "_save_settings_form", "_build_discord", "_build_app_settings", "_poll_events",
                 "quit_app", "on_close", "check_updates", "_check_key"):
        assert getattr(LiteApp, name) is getattr(App, name), name
    import inspect
    for name in ("_record_session", "pause", "resume"):       # LITE adds run tracking around the original, nothing else
        assert "super()." + name in inspect.getsource(getattr(LiteManager, name)), name
    root = lite_root()
    try:
        m, _ = manager(root)
        assert type(m.ops.checklist) is Checklist
        own = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "rerun_lite").glob("*.py"))
        assert "class CrestScript" not in own and "BUILTIN_TASKS" not in own and own.count("def handle_") == 2
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
        assert m.start("A", "login_mail") == "Unknown script 'login_mail'"
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
    assert names <= declared and 45 <= len(names) == len(list((ROOT / "templates").glob("*.png")))
    for must in ("equip_crest_screen", "crest_icon_lv4plus", "redeploy_button"):
        assert must in names, must
    assert not [n for n in names if n.startswith(("arena_", "mines_", "gc_", "compendium_"))]
    assert "mail_chest" not in names and "claim_all_button" not in names          # Login & Mail is not in LITE
    root = lite_root(real_templates=True)
    try:
        m, _ = manager(root)
        # Crest needs nothing more than what LITE ships
        assert m.missing_templates("crest") == []
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
def test_window_has_the_two_features_and_only_their_tools():
    root, m, inst, app = open_lite()
    try:
        assert [lb.cget("text") for _, lb in app.nb._tabs] == ["Auto Crest", "History", "Templates", "Settings"]
        assert app.title() == APP_NAME
        assert [k for k, _ in app._set_nav._items] == ["crest", "palaces", "profiles", "discord", "notifications", "appearance", "shortcuts", "app", "sessions", "health", "log"]
        for attr in ("_am_nav", "_farm_nav", "_tab_accounts", "_tab_farming", "unit_tree", "companion"):
            assert not hasattr(app, attr), f"{attr}: a page LITE must not build"
        crest_page = app.nb._pages[app._tab_crest]
        assert TOS_WARNING in texts(crest_page)
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
            assert box["values"] == ["Crest"] and box.get() == "Crest"
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
        app.nb.select(app._tab_settings)
        assert not app._dashboard_in_view()
        assert not app.errors, app.errors
    finally:
        m.instances[inst].status = "idle"
        close(app, root)


def test_settings_pages_are_the_originals_with_lite_names_and_places():
    from rerun.setup_check import Check
    root, m, inst, app = open_lite()
    try:
        app.open_script_settings("crest")
        pump(app)
        assert app.nb.index() == app._tab_settings and app._set_nav.current == "crest"
        assert app.set_script.get() == "Crest" and {"runs", "keep", "start_home", "palace_name"} <= set(app.form_vars)
        assert app.form.winfo_children()[-1].footer.cget("text") == SCHEDULE_NOTE
        assert app._rs_title.cget("text") == "Crest Settings"
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
        assert f"Connect When {APP_NAME} Starts" in words and f"{APP_NAME} {LITE_VERSION}" in words
        assert not [w for w in words if "Rerun" in w], [w for w in words if "Rerun" in w]
        app._set_update_status(f"Up to date (Rerun {LITE_VERSION})")
        assert app.upd_status.cget("text") == f"Up to date ({APP_NAME} {LITE_VERSION})"
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
        app.nb.select(app._tab_templates)
        app._save_ui_state()
        assert (root / "config.yaml").read_text(encoding="utf-8") == before
        ui = json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))
        assert ui["tab"] == app._tab_templates and "x" in ui["geometry"]
        app.nb.select(0)
        app._restore_tab()
        assert app.nb.index() == app._tab_templates
    finally:
        close(app, root)


def test_status_chip_badges_and_title_follow_what_the_emulators_do():
    root, m, inst, app = open_lite()
    try:
        app._refresh_status()
        assert "Needs setup" in app.nb.chip.cget("text")                  # no palace chosen yet
        assert app.nb._badges[app._tab_crest].cget("text") == "!" and app._ready_notice.winfo_manager()
        m.instances[inst].status = "running"
        app._status_sig = None
        app._refresh_status()
        assert f"Crest running on {inst}" in app.nb.chip.cget("text")
        assert app.nb._badges[app._tab_crest].cget("text") == "●" and app.title().endswith(f"Crest running on {inst}")
        m.instances[inst].status = "paused"
        app._status_sig = None
        app._refresh_status()
        assert "Paused" in app.nb.chip.cget("text") and app.nb._badges[app._tab_crest].cget("text") == "II"
        m.instances[inst].status = "idle"
        m.save_script_settings(inst, "crest", {**m.script_settings(inst, "crest"), "palace_name": "Wind"})
        app._status_sig = None
        app._refresh_status()
        assert app.title() == f"{APP_NAME}" or not app.title().endswith("Paused")     # the suffix is taken off again
        assert not any(p.fix == "settings" for p in app._problems)         # a palace name is enough
        assert not app.nb._badges[app._tab_settings].winfo_manager()
        assert not app.errors, app.errors
    finally:
        close(app, root)


def test_readiness_checks_are_local_and_name_the_fix():
    from rerun_lite import readiness
    root, m, inst, app = open_lite()
    try:
        fixes = {p.fix for p in readiness.crest_problems(m, inst)}
        assert "settings" in fixes                                        # nothing says which palace to open
        m.save_script_settings(inst, "crest", {**m.script_settings(inst, "crest"), "start_home": False})
        assert "settings" not in {p.fix for p in readiness.crest_problems(m, inst)}   # not needed without Home start
        sim_templates(m, "crest")
        assert not [p for p in readiness.crest_problems(m, inst) if p.fix == "templates"]
    finally:
        close(app, root)


def test_shortcuts_pin_and_settings_section_are_remembered():
    root, m, inst, app = open_lite()
    try:
        for n in range(1, 5):
            assert app.bind_all(f"<Control-Key-{n}>"), n
        app._go_tab(1)
        assert app.nb.index() == 1
        app._cycle_tab(1)
        assert app.nb.index() == 2
        app._cycle_tab(-1)
        assert app.nb.index() == 1
        assert bool(app.attributes("-topmost")) is False
        app._toggle_pin()
        assert bool(app.attributes("-topmost")) and app.nb.pin.cget("text") == "Pinned" and app._pin_var.get()
        app.nb.select(app._tab_settings)
        app._set_nav.select("palaces")
        app._save_ui_state()
        ui = json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))
        assert ui["pinned"] is True and ui["section"] == "palaces"
        app._set_nav.select("discord")                                    # moved away: the saved entry comes back
        app._restore_tab()
        assert app._set_nav.current == "palaces"
        words = " ".join(texts(app._set_pages["app"]))
        assert "Keep this window on top" in words and "Open the data folder" in words
    finally:
        close(app, root)


def test_video_background_plays_behind_the_window_and_follows_it():
    import time
    from rerun_lite import background
    root, m, inst, app = open_lite(backdrop=True)
    try:
        t0 = time.time()
        while not app.backdrop.active and time.time() - t0 < 5:
            app.update()
            time.sleep(0.02)
        bd = app.backdrop
        assert bd.active and bd.path.name == "spirit_blossom.mp4"                 # the built-in video
        assert str(app.attributes("-transparentcolor")).lower() == ios.C["bg"].lower()                 # the page colour shows the video
        t0 = time.time()
        while bd.player.frame is None and time.time() - t0 < 5:
            app.update()
            time.sleep(0.02)
        assert bd.player.frame is not None and bd.player.frame.shape[2] == 3
        app.geometry("1100x820+120+90")
        for _ in range(20):
            app.update()
            time.sleep(0.02)
        w = bd.win
        assert (w.winfo_width(), w.winfo_height()) == (app.winfo_width(), app.winfo_height())
        assert (w.winfo_rootx(), w.winfo_rooty()) == (app.winfo_rootx(), app.winfo_rooty())
        assert bd.player.size == (app.winfo_width(), app.winfo_height())
        assert "Playing: spirit_blossom.mp4" in app._bg_label.cget("text")
        # a video dropped into background/ is used instead of the built-in one
        (root / "background").mkdir()
        shutil.copy(ROOT / "assets" / "spirit_blossom.mp4", root / "background" / "mine.mp4")
        assert background.find_video(root).name == "mine.mp4"
        # Appearance > Background: Off removes the second window and the colour key (the window is rebuilt: a new backdrop)
        from dataclasses import replace
        app.apply_appearance(replace(app._look, background="off"))
        app.update()
        bd = app.backdrop
        assert not bd.active and bd.win is None and app.attributes("-transparentcolor") == ""
        assert json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))["appearance"]["background"] == "off"
        app.apply_appearance(replace(app._look, background="auto"))
        assert wait_until(app, lambda: app.backdrop.active)
        app._bg_changed(bg_dim="Strong")
        assert app.backdrop.player.dim == background.DIMS["Strong"]
        assert not app.errors, app.errors
    finally:
        app.backdrop.stop()
        close(app, root)


def test_the_video_is_not_used_in_classic_and_a_missing_file_is_harmless():
    from dataclasses import replace

    from rerun_lite import background, theme
    root, m, inst, app = open_lite(backdrop=True)
    try:
        assert wait_until(app, lambda: app.backdrop.active)
        app.backdrop.stop()
        assert background.find_video(root, str(root / "nope.mp4")).name == "spirit_blossom.mp4"       # falls back to the built-in
        theme.ACTIVE = "classic"
        assert app.backdrop.start() is False                                       # ReRun's own look: no video, no colour key
        theme.ACTIVE = "ahri"
        app.apply_appearance(replace(app._look, background="custom", custom_video=str(root / "nope.mp4")))
        app.update()
        assert not app.backdrop.active and not app.errors, app.errors              # a missing file is just "no video found"
        assert "No video found" in app._bg_label.cget("text") if getattr(app, "_bg_label", None) is not None else True
        app.apply_appearance(replace(app._look, background="auto"))
        assert wait_until(app, lambda: app.backdrop.active)                        # and the built-in plays again
    finally:
        app.backdrop.stop()
        close(app, root)


def test_extras_start_stop_button_sound_and_remembered_emulator():
    root, m, inst, app = open_lite()
    try:
        started = []
        m._worker = lambda i: started.append(i.name)
        assert app.nb.action.cget("text") == "Start"
        app._toggle_run()                                                     # Ctrl+Enter / the button: start the selected emulator
        m.instances[inst].thread.join(5)
        assert started == [inst] and app.nb.index() == app._tab_crest
        m.instances[inst].status = "running"
        app._refresh_status()
        assert app.nb.action.cget("text") == "Stop"
        stopped = []
        app.stop_all_clicked = lambda: stopped.append(1)
        app._stop_run()
        assert stopped == [1]
        m.instances[inst].status = "idle"
        app._refresh_status()
        assert app.nb.action.cget("text") == "Start"
        # the emulator you pick is remembered in LITE's own file
        assert json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8")).get("emulator") == inst
        # sound: only when it is on, only for alerts
        import sys
        import types
        beeps = []
        fake = types.SimpleNamespace(MB_ICONASTERISK=64, MessageBeep=lambda k: beeps.append(k))
        sys.modules["winsound"] = fake
        try:
            app._maybe_sound({"type": "notify"})
            assert beeps == []
            app._sound_var.set(True)
            app._set_sound()
            n = len(beeps)
            app._maybe_sound({"type": "status"})
            app._maybe_sound({"type": "notify"})
            assert len(beeps) == n + 1
        finally:
            del sys.modules["winsound"]
        assert json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))["sound_alerts"] is True
        assert not app.errors, app.errors
    finally:
        m.instances[inst].status = "idle"
        close(app, root)


def test_clicking_the_video_does_not_raise_it_over_the_app():
    """The bug: a click where the page background shows the video landed on the video window, which Windows then made
    active and raised over the app, so every widget vanished. The video window must refuse that activation."""
    import ctypes
    import time
    from ctypes import wintypes
    root, m, inst, app = open_lite(backdrop=True)
    try:
        t0 = time.time()
        while not app.backdrop.active and time.time() - t0 < 5:
            app.update()
            time.sleep(0.02)
        bd = app.backdrop
        assert bd.active and bd.hooked >= 2, bd.hooked                        # the video window and the windows inside it
        u = ctypes.windll.user32
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW.restype = ctypes.c_ssize_t
        top = u.GetParent(bd.win.winfo_id()) or bd.win.winfo_id()
        kids = []
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumChildWindows(top, enum(lambda h, _l: (kids.append(h), True)[1]), 0)
        WM_MOUSEACTIVATE, MA_NOACTIVATE = 0x21, 3
        for h in [top, *kids]:                                                # "a mouse button went down on this window"
            assert u.SendMessageW(h, WM_MOUSEACTIVATE, top, 0x02010001) == MA_NOACTIVATE, hex(h)
        EX = -20
        main_top = u.GetParent(app.winfo_id()) or app.winfo_id()
        assert not u.GetWindowLongW(main_top, EX) & 0x08000000                # the app itself can still be activated
        assert u.GetWindowLongW(top, EX) & 0x08000080 == 0x08000080          # no activation, no taskbar button
        # the app window stays directly above the video, also after the video is clicked (events reach Tk)
        bd.win.event_generate("<ButtonPress-1>", x=40, y=40)
        bd.win.event_generate("<ButtonRelease-1>", x=40, y=40)
        for _ in range(10):
            app.update()
        order = []
        h = u.GetTopWindow(None)
        while h:
            if h in (main_top, top):
                order.append("app" if h == main_top else "video")
            h = u.GetWindow(h, 2)
        assert order == ["app", "video"], order
        assert not app.errors, app.errors
    finally:
        app.backdrop.stop()
        close(app, root)


def test_classic_is_the_original_black_and_white_and_plain_is_the_new_default():
    from dataclasses import replace

    from rerun_lite import appearance as ap
    from rerun_lite import theme
    od, ol = dict(theme.CLASSIC_DARK), dict(theme.CLASSIC_LIGHT)
    assert od["bg"] == "#000000" and od["card"] == "#1C1C1E" and ol["bg"] == "#F2F2F7" and ol["card"] == "#FFFFFF"   # ReRun's own
    for mode, orig in (("dark", od), ("light", ol)):
        res = theme.apply(ap.Appearance("classic", mode))
        table = ios.DARK if mode == "dark" else ios.LIGHT
        assert res.ios_mode == mode and all(table[k] == v for k, v in orig.items()), mode      # exactly as the engine has it
        assert not res.tokens.outline and res.tokens.radius == 12                                 # and its flat 12 px cards
    res = theme.apply(ap.Appearance())                                                           # the default: Plain
    assert res.appearance.look == "plain" and res.tokens.outline and res.tokens.radius == 6 and theme.is_custom()
    assert theme.apply_palette("dark") == "dark" and theme.apply_palette("auto") == "auto" and not theme.is_custom()
    assert theme.apply_palette("ahri") == "dark" and theme.is_ahri() and ios.DARK["bg"] == theme.AHRI["bg"]
    assert theme.apply_palette("nonsense") == "dark" and theme.current() is None                  # unknown: the default (Plain)
    root, m, inst, app = open_lite()
    try:
        assert app._look.look == "plain" and ios.C["blue"] == ap.resolve(app._look, True).palette["blue"]
        asked = []
        ios.confirm = lambda *a, **k: asked.append(a[1]) or False
        m.save_config()
        before_config = (root / "config.yaml").read_bytes()
        app.apply_appearance(replace(app._look, look="classic", mode="light"))
        assert app._look.look == "classic" and ios.C["bg"] == ol["bg"]                            # the window is now Classic Light
        assert json.loads((root / "data" / "lite" / "ui.json").read_text(encoding="utf-8"))["appearance"]["look"] == "classic"
        assert (root / "config.yaml").read_bytes() == before_config                               # config.yaml untouched
        assert not app.errors, app.errors
    finally:
        theme.apply(ap.Appearance("ahri"))
        close(app, root)


def test_selftest_builds_the_whole_window():
    import lite_main
    out = Path(tempfile.mkdtemp()) / "r.txt"
    try:
        assert lite_main.selftest(out) == 0, out.read_text(encoding="utf-8")
        assert out.read_text(encoding="utf-8") == "ok Auto Crest | History | Templates | Settings"
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
        (src / "templates" / "equip_crest_screen.png").write_bytes(b"a newer equip screen picture")
        exe = tmp / "RerunLite.exe"
        exe.write_bytes(b"MZ a newer ReRun LITE")
        publish_update.__version__ = "99.0.0"
        man = publish_lite_update.publish(site, "stable", secret, exe=exe, notes="newer", src=src)
        assert man["product"] == "lite" and "templates/arena_x.png" not in man["content"]["files"]
        assert set(man["content"]["files"]) == set(content.lite_files(src))
        res = updates.check(inst, cfg)
        assert not res.error and res.app["version"] == "99.0.0", res.error
        # (no baseline in this folder: every picture counts as yours, so content is left alone)
        assert res.plan is not None and res.plan.install == {} and "templates/equip_crest_screen.png" in res.plan.kept
        got = updates.download_app(inst, cfg, res.app)
        assert got.name == "RerunLite.update.exe" and got.read_bytes() == exe.read_bytes()
        assert not (inst / "Rerun.update.exe").exists() and not (inst / "content_state.json").exists()
        # 4. with a build's baseline the changed picture IS updated, and the state goes to LITE's own file
        base = {rel: updates.sha256_file(p) for rel, p in content.lite_files(inst).items()}
        (inst / "lite_content_baseline.json").write_text(json.dumps({"files": base}), encoding="utf-8")
        res = updates.check(inst, cfg)
        assert list(res.plan.install) == ["templates/equip_crest_screen.png"], res.plan.install
        updates.stage_content(inst, cfg, res.plan)
        assert "1 file(s) updated" in updates.commit_staged(inst)
        assert (inst / "templates" / "equip_crest_screen.png").read_bytes() == b"a newer equip screen picture"
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
