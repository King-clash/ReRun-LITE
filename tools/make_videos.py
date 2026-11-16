"""Make the how-to videos for setting ReRun LITE up by hand.

    py tools/make_videos.py              all videos  -> docs/videos/*.mp4 and *.webm
    py tools/make_videos.py emulator     only the one whose key contains "emulator"

Every video is recorded from the REAL ReRun LITE window running in a throw-away folder (no settings, accounts or
keys of yours), with a fake emulator that always shows the same two game pictures. Nothing is sent to a real
emulator, Discord or the network. The window sits on screen but behind your other windows while it records (Windows does not draw an
off-screen window fully); only the app's own window is captured (tools/video_kit.py). The game pictures are blurred at the top so no player name or
account number is shown.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import tkinter as tk
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from rerun import ios  # noqa: E402
from rerun_lite import content  # noqa: E402
from rerun_lite.app import LiteApp  # noqa: E402
from rerun_lite.manager import LiteManager  # noqa: E402
from video_kit import Film  # noqa: E402

OUT = ROOT / "docs" / "videos"
ASSETS = ROOT / "tools" / "video_assets"


# ---------------------------------------------------------------- the sandbox
def game_picture(name: str):
    img = cv2.imread(str(ASSETS / name))
    img[0:200] = cv2.GaussianBlur(img[0:200], (0, 0), 14)       # no player name, rank or ids
    return img


class Sandbox:
    def __init__(self, instances: list[dict], picture: str = "home.png"):
        self.root = Path(tempfile.mkdtemp(prefix="rerunlite_video_"))
        content.copy_to(ROOT, self.root)
        (self.root / "config.yaml").write_text(yaml.safe_dump({"instances": instances}), encoding="utf-8")
        self.frame = [game_picture(picture)]
        (self.root / "data" / "lite").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "lite" / "ui.json").write_text('{"bg_on": false}', encoding="utf-8")   # the recorder needs a solid window
        m = LiteManager(self.root)
        m.config["game_package"] = "fake.grandsummoners"
        m.config["live_view_fps"] = 0
        m.config["setup_seen"] = True
        m.config["discord"]["enabled"] = False
        if not instances:
            m.set_instances([])
        frame = self.frame
        LiteManager.screenshot = lambda self_, name: frame[0].copy()           # the fake emulator
        import rerun.gui_dashboard as gd
        gd.discover_bluestacks_instances = lambda: [
            {"name": "Instance 1", "serial": "127.0.0.1:5555", "adb_enabled": True}]
        self.m = m
        self.app = LiteApp(m)
        self.app.geometry("1140x840+40+40")        # Windows only paints it fully while it is on screen; it is kept behind other windows
        self.app.lower()
        self.app.minsize(1060, 800)
        try:
            self.app.tray.stop()
        except Exception:  # noqa: BLE001
            pass
        for _ in range(30):
            self.app.update()

    def close(self):
        try:
            self.app.destroy()
        except tk.TclError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------- finding things on screen
def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


def button(app, text: str, within=None):
    for w in walk(within or app):
        if isinstance(w, ios.Button) and getattr(w, "_text", None) == text and w.winfo_ismapped():
            return w
    raise LookupError(f"no button {text!r}")


def label(app, text: str, within=None, startswith: bool = True):
    for w in walk(within or app):
        if isinstance(w, tk.Label) and w.winfo_ismapped():
            t = str(w.cget("text")).strip()
            if t == text or (startswith and t.startswith(text)):
                return w
    raise LookupError(f"no label {text!r}")


def task_button(app, task: str, text: str):
    """The `text` button on the checklist row of `task`: climb from the task's name until a button is found."""
    w = label(app, task)
    while w is not None:
        for c in walk(w):
            if isinstance(c, ios.Button) and getattr(c, "_text", None) == text and c.winfo_ismapped():
                return c
        w = w.master
    raise LookupError(f"no {text!r} on {task!r}")


def row_control(app, title: str, cls):
    """The first `cls` widget on the settings row whose title starts with `title`."""
    lb = label(app, title)
    row = lb.master.master
    for w in walk(row):
        if isinstance(w, cls):
            return w
    raise LookupError(f"no {cls.__name__} on row {title!r}")


def tab(app, i: int):
    return app.nb._tabs[i][1]


def popover_open(app) -> tk.Toplevel | None:
    for tl in app.winfo_children():
        if isinstance(tl, tk.Toplevel) and tl.winfo_ismapped() and tl.winfo_width() < app.winfo_width() - 40:
            return tl
    return None


def dialog_open(app) -> tk.Toplevel | None:
    return popover_open(app)


def pick(film: Film, select: ios.Select, value: str):
    """Open a pop-up menu with the pointer and choose `value`."""
    yield from film.click(select, 0.8, 0.5, wait=0.4)
    yield from film.wait_for(lambda: popover_open(film.app) is not None, what="menu")
    yield from film.hold(0.3)
    top = popover_open(film.app)
    item = next(w for w in walk(top) if isinstance(w, tk.Label) and str(w.cget("text")).strip() == value)
    yield from film.click(item, 0.4, 0.5, seconds=0.5, wait=0.4)
    yield from film.wait_for(lambda: popover_open(film.app) is None, what="menu to close")


def confirm_dialog(film: Film, button_text: str):
    """Press a button of the open alert/prompt (its 'buttons' are labels)."""
    yield from film.wait_for(lambda: dialog_open(film.app) is not None, what="dialog")
    yield from film.hold(0.5)
    top = dialog_open(film.app)
    b = next(w for w in walk(top) if isinstance(w, tk.Label) and str(w.cget("text")) == button_text)
    yield from film.click(b, seconds=0.6, wait=0.5)
    yield from film.wait_for(lambda: not top.winfo_exists(), what="dialog to close")


def type_in_dialog(film: Film, text: str):
    yield from film.wait_for(lambda: dialog_open(film.app) is not None, what="dialog")
    yield from film.hold(0.6)
    top = dialog_open(film.app)
    entry = next(w for w in walk(top) if isinstance(w, tk.Entry))
    yield from film.move_to(entry, 0.5, 0.5, 0.5)
    yield from film.type_into(entry, text)
    yield from film.hold(0.5)


# ---------------------------------------------------------------- the videos
def intro(f: Film, goal: str, bullets: list[str]):
    yield from f.slide(f.title, [goal] + bullets, 4.5)


def v_emulator(sb: Sandbox):
    app = sb.app

    def scenario(f: Film):
        yield from intro(f, "ReRun LITE controls the game through your BlueStacks emulator. You tell it where the emulator is once.",
                         ["Takes about a minute.", "You need BlueStacks 5 with the game installed."])
        yield from f.slide("First, in BlueStacks", [
            "Open BlueStacks Settings > Advanced and turn on Android Debug Bridge (ADB).",
            "In Settings > Display, set the resolution to 1280 x 720 (the game then runs 720 x 1280, portrait).",
            "Leave BlueStacks open with the game running."], 7.5, kicker="Do this in BlueStacks, not in ReRun LITE")
        yield from f.say(0, "Auto Crest is where emulators are listed. It is empty until you add one.")
        yield from f.click(tab(app, 0), seconds=0.4, wait=0.4)
        yield from f.highlight(button(app, "Detect BlueStacks"), 2)
        yield from f.hold(1.5)
        yield from f.say(1, "Detect BlueStacks reads your BlueStacks settings and adds every instance it finds.")
        yield from f.click(button(app, "Detect BlueStacks"))
        yield from f.highlight(None)
        yield from confirm_dialog(f, "OK")
        yield from f.hold(1.0)
        yield from f.say(2, "No luck? Add one by hand. Press Add, give it any name you like...")
        yield from f.highlight(button(app, "Add"), 2)
        yield from f.click(button(app, "Add"))
        yield from f.highlight(None)
        yield from type_in_dialog(f, "Alt account")
        yield from confirm_dialog(f, "OK")
        yield from f.say(2, "...then its ADB address. BlueStacks shows the port in Settings > Advanced. It looks like 127.0.0.1:5565.")
        yield from type_in_dialog(f, "127.0.0.1:5565")
        yield from confirm_dialog(f, "OK")
        yield from f.hold(1.0)
        yield from f.say(3, "Click an emulator to select it. Press Screenshot (top right of Live View) to check the connection: you should see the game.")
        row = label(app, "Instance 1")
        yield from f.click(row, seconds=0.6, wait=0.6)
        yield from f.highlight(button(app, "Screenshot"), 3)
        yield from f.click(button(app, "Screenshot"))
        yield from f.hold(2.5)
        yield from f.highlight(None)
        yield from f.say(4, "Next: tell Crest which palace to farm (see the next video). The orange strip at the top says what is still missing.")
        yield from f.hold(3.5)
        yield from f.slide("You are set", ["Your emulators are listed on the Auto Crest tab.",
                                           "Next video: pick the palace Crest should farm."], 3.5)
    return scenario


def v_palace(sb: Sandbox):
    app = sb.app
    tree = app.tpl_tree

    def scenario(f: Film):
        yield from intro(f, "Crest needs to know which Crest Palace to open. The most reliable way is a small picture of its tile, saved once.",
                         ["Takes about a minute.", "Have the game open on the Crest Palace list (Exploring > Crest Palace)."])
        yield from f.say(0, "Open the Templates tab. It holds the small pictures ReRun LITE looks for on screen.")
        yield from f.click(tab(app, 2), seconds=0.5, wait=0.8)
        yield from f.say(1, "Make sure 'Checklist for' says Crest, then pick crest_palace_target in the list.")
        yield from f.highlight(app.tpl_script, 6)
        yield from f.hold(1.5)
        yield from f.highlight(None)
        tree.see("crest_palace_target")
        yield
        bx, by, bw, bh = tree.bbox("crest_palace_target")
        yield from f.move(tree.winfo_rootx() - app.winfo_rootx() + bx + 90, tree.winfo_rooty() - app.winfo_rooty() + by + bh / 2, 0.8)
        f.ripple = 14
        tree.selection_set("crest_palace_target")
        yield from f.hold(1.2)
        yield from f.say(2, "Put the game on the Crest Palace list, then press Screenshot. The picture appears on the right.")
        yield from f.click(button(app, "Screenshot"))
        yield from f.wait_for(lambda: app.tpl_img is not None, what="screenshot")
        yield from f.hold(1.5)
        yield from f.say(3, "Drag a box tightly around the palace tile you farm (its banner). Not too much empty space around it.")
        cv = app.tpl_canvas
        s = app.tpl_scale
        x0, y0, x1, y1 = (int(v * s) for v in (44, 338, 682, 488))

        class Ev:
            def __init__(self, x, y):
                self.x, self.y = x, y
        ox, oy = cv.winfo_rootx() - app.winfo_rootx(), cv.winfo_rooty() - app.winfo_rooty()
        yield from f.move(ox + x0, oy + y0, 0.8)
        f.ripple = 14
        app._drag_start(Ev(x0, y0))
        steps = 14
        for i in range(1, steps + 1):
            t = i / steps
            f.cx, f.cy = ox + x0 + (x1 - x0) * t, oy + y0 + (y1 - y0) * t
            app._drag_move(Ev(int(x0 + (x1 - x0) * t), int(y0 + (y1 - y0) * t)))
            yield
        yield from f.hold(1.5)
        yield from f.say(4, "Press Save Selection. The list now shows crest_palace_target as captured.")
        yield from f.click(button(app, "Save Selection"))
        yield from f.hold(2.0)
        yield from f.say(5, "Press Test: it checks the picture against the screenshot. A match close to 1.00 means it will be found.")
        yield from f.click(button(app, "Test"))
        yield from f.hold(3.0)
        yield from f.say(5, "Palaces rotate. If the picture stops matching, repeat this, or type the palace's name instead (next video).")
        yield from f.hold(3.5)
        yield from f.slide("Palace picture saved", ["Crest can now find your palace from the Home screen.",
                                                    "Next video: set the other Crest options."], 3.5)
    return scenario


def v_crest(sb: Sandbox):
    app = sb.app

    def scenario(f: Film):
        yield from intro(f, "Crest's options decide when it stops, which crests it keeps and which palace it opens by name.",
                         ["Changes apply the next time Crest starts.", "Each emulator has its own settings."])
        yield from f.say(0, "Open Settings. 'Auto Crest' is the first entry on the left.")
        yield from f.click(tab(app, 3), seconds=0.5, wait=0.8)
        yield from f.highlight(label(app, "Auto Crest", within=app._set_nav), 2)
        yield from f.hold(1.5)
        yield from f.highlight(None)
        yield from f.say(1, "'Number of runs' stops Crest after that many runs. 0 means no limit. Press + to raise it.")
        step = row_control(app, "Number of runs", ios.Stepper)
        for _ in range(3):
            yield from f.click(step._cv, 0.8, 0.5, seconds=0.5 if _ == 0 else 0.15, wait=0.25)
        yield from f.hold(1.2)
        yield from f.say(2, "'Crests to keep' is what makes Crest stop and message you. Everything below it is scrapped.")
        keep = row_control(app, "Crests to keep", ios.Select)
        yield from f.scroll_into_view(keep)
        yield from pick(f, keep, "Lv4 and better")
        yield from f.hold(1.2)
        yield from f.say(3, "If no palace picture matches, type part of the palace's name. Several names are tried in order, separated by commas.")
        pal = row_control(app, "Palaces to farm", ios.Field)
        yield from f.scroll_into_view(pal)
        yield from f.move_to(pal.entry, 0.5, 0.5, 0.6)
        yield from f.type_into(pal.entry, "Cursed Claw, Whirlwind")
        yield from f.hold(1.2)
        yield from f.say(4, "Press Save Settings at the bottom of the page.")
        save = button(app, "Save Settings")
        yield from f.scroll_into_view(save)
        yield from f.click(save)
        yield from f.hold(2.2)
        yield from f.say(4, "Palace Selector, the next entry, can pick the palace for you by day of the week.")
        yield from f.highlight(label(app, "Palace Selector", within=app._set_nav), 2)
        yield from f.hold(3.0)
        yield from f.highlight(None)
        yield from f.slide("Crest is configured", ["Press Start (or Dry Run to rehearse without tapping) on the Auto Crest tab.",
                                                   "Dry Run walks through the steps and logs what it would do."], 4.0)
    return scenario


def v_discord(sb: Sandbox):
    app = sb.app

    def scenario(f: Film):
        yield from intro(f, "A Discord bot can message you when Crest keeps a crest or something goes wrong, and answer commands like /status.",
                         ["Optional. Takes about five minutes.", "You need a Discord server where you can add a bot."])
        yield from f.slide("First, on Discord's website", [
            "Open the Discord Developer Portal (discord.com/developers), create an application, add a Bot, and copy its token. Keep it secret.",
            "Invite the bot to your server (OAuth2 > URL Generator, scope 'bot').",
            "In Discord, turn on Developer Mode (User Settings > Advanced). Right-click your alert channel > Copy Channel ID. Right-click yourself > Copy User ID."],
            11.0, kicker="Do this on Discord, not in ReRun LITE")
        yield from f.say(0, "Open Settings, then Discord in the list on the left.")
        yield from f.click(tab(app, 3), seconds=0.5, wait=0.6)
        yield from f.click(label(app, "Discord", within=app._set_nav), seconds=0.6, wait=0.8)
        yield from f.say(1, "Paste the bot token. It shows as dots. (This video types a placeholder, never a real token.)")
        tok = row_control(app, "Bot Token", ios.Field)
        yield from f.move_to(tok.entry, 0.5, 0.5, 0.6)
        yield from f.type_into(tok.entry, "paste-your-bot-token", per_char=0.05)
        yield from f.hold(0.8)
        yield from f.say(2, "Paste the Alert Channel ID: where alerts and screenshots are posted.")
        ch = row_control(app, "Alert Channel ID", ios.Field)
        yield from f.move_to(ch.entry, 0.5, 0.5, 0.6)
        yield from f.type_into(ch.entry, "123456789012345678", per_char=0.04)
        yield from f.hold(0.6)
        yield from f.say(3, "Optional: your own User ID, so the bot mentions you on rare crests and failures. 'Allowed User IDs' lists who may control ReRun LITE from Discord.")
        me = row_control(app, "User ID to Ping", ios.Field)
        yield from f.move_to(me.entry, 0.5, 0.5, 0.6)
        yield from f.type_into(me.entry, "234567890123456789", per_char=0.04)
        yield from f.hold(1.0)
        yield from f.say(4, "Press Save & Connect. The dot at the top turns green when the bot is online. Send Test Message posts a test line in your channel.")
        sc = button(app, "Save & Connect")
        yield from f.highlight(sc, 4)
        yield from f.move_to(sc, 0.5, 0.5, 0.8)
        yield from f.hold(1.5)
        yield from f.highlight(button(app, "Send Test Message"), 4)
        yield from f.move_to(button(app, "Send Test Message"), 0.5, 0.5, 0.8)
        yield from f.hold(3.0)
        yield from f.highlight(None)
        yield from f.slide("Alerts are ready", ["This video did not press Save & Connect, so nothing was sent anywhere.",
                                                "Turn on 'Connect When ReRun LITE Starts' to bring the bot online every time."], 4.5)
    return scenario


VIDEOS = {
    "1-emulator": ("Add your emulator", ["Turn on ADB in BlueStacks", "Detect BlueStacks", "...or add one by hand", "Check the connection", "What's next"], v_emulator,
                   dict(instances=[])),
    "2-palace-picture": ("Save your palace picture", ["Open Templates", "Pick crest_palace_target", "Take a screenshot", "Drag a box", "Save Selection", "Test it"], v_palace,
                         dict(instances=[{"name": "Instance 1", "serial": "127.0.0.1:5555", "script": "crest"}], picture="crest_palace_list.png")),
    "3-crest-settings": ("Set up Crest", ["Open Crest settings", "Number of runs", "Crests to keep", "Palace names", "Save"], v_crest,
                         dict(instances=[{"name": "Instance 1", "serial": "127.0.0.1:5555", "script": "crest"}])),
    "4-discord": ("Set up Discord alerts", ["Open Discord settings", "Bot token", "Channel ID", "Your user ID", "Save & Connect"], v_discord,
                  dict(instances=[{"name": "Instance 1", "serial": "127.0.0.1:5555", "script": "crest"}])),
}


def make(key: str) -> None:
    title, steps, build, kw = VIDEOS[key]
    sb = Sandbox(**kw)
    try:
        film = Film(sb.app, title, steps, OUT / f"rerun-lite-{key}", number=f"video {key.split('-')[0]} of {len(VIDEOS)}")
        n = film.run(build(sb))
        print(f"{key}: {n} frames, {n / 15:.0f}s -> {OUT / ('rerun-lite-' + key)}.mp4 / .webm")
    finally:
        sb.close()


if __name__ == "__main__":
    want = sys.argv[1:]
    for k in VIDEOS:
        if not want or any(w in k for w in want):
            make(k)
