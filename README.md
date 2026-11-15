# ReRun LITE

ReRun LITE is a small app for Grand Summoners on BlueStacks. It does two things:

1. **Auto Crest** - farms a Crest Palace on Auto-Loop, scraps the crests you do not want and stops (and
   tells you on Discord) when a wanted one drops.
2. **Dailies** - the daily and weekly checklist, including the tasks it can do for you (Login reward +
   mail, and Raid tickets, which is Beta).

This is its own project. It is not a fork of ReRun, it has its own history, its own releases and its own
update address, and nothing here changes or depends on the ReRun repository. (The code that does the
farming was copied from ReRun 1.2.1 when this repository was created; see "Where the code comes from".)

**Please read first:** Grand Summoners may not allow macros, bots or automation. Using ReRun LITE can
lead to account limits, suspension or a permanent ban. The warning is on both feature tabs all the time.

## What is in it

| Tab | What it is |
|---|---|
| **Auto Crest** | Your emulators, Start / Dry Run / Pause / Stop, totals, crest counts (4+, Burst, Lv4, rate), instructions, Live View. An emulator always runs Crest, so there is no script chooser. |
| **Dailies** | The daily and weekly checklist. It resets on the game clock (6 AM UTC-6). Mark Done / Undo / Confirm, your own tasks, Run and Run Next Due. Above it: which emulator the account plays on, and the weekly reset day. |
| **History** | Crests kept and scrapped (with pictures), refills, sessions and problems. |
| **Templates** | Capture, test and import the pictures the scripts look for (for example your palace tile). |
| **Settings** | Crest, Login & Mail and Raid Tickets settings and the daily schedule; Discord alerts; the Log; app settings (theme, tray, start options, setup check, updates). |

Also included: the key sign-in, F12 (stop everything) and F11 (pause/resume), the tray icon, 24/7 mode,
Dry Run, Discord alerts with screenshots and the status board, the daily summary.

## What is not in it

No other scripts (quests, arena, raids, mines and so on), no custom routines, no Account Manager, no Units
or Compendium, no GS Companion, and no `/units` or `/compendium` Discord commands. None of these can be
started or opened from LITE.

## Start it

You need Windows, Python 3.12 and BlueStacks. Install the libraries once with
`py -m pip install -r requirements.txt`.

- **From the source folder:** double-click `Run Rerun LITE.bat`, or run `py lite_main.py`.
- **As an exe:** `py build_lite.py` builds `dist/RerunLite/RerunLite.exe`. `py build_lite.py --release`
  builds a clean `release/RerunLite-<version>.zip` to share (blank config, its own Tesseract, nothing of
  yours; it is checked before it is zipped).

LITE asks for a sign-in key. The first time, **Settings > App > Setup check** shows what is missing. Crest
starts from the Home screen, so it needs either a picture of your palace tile (Templates tab:
`crest_palace_target`, or one per weekday) or the palace's name in **Crest Settings > Palaces to farm**.

If you also use the full ReRun, LITE can copy your settings, stats, crest log, History, key and checklist
from its folder the first time it starts (the ReRun folder is not changed). LITE keeps its own small files
in `data/lite/`.

## Updates

LITE checks its own update address, `https://king-clash.github.io/ReRun-LITE/lite/`, for a signed
manifest. Until a LITE update has been published there, **Settings > App > Check Now** says "No ReRun LITE
updates have been published yet." A copy run from source only reports a new version; the built exe also
installs it. `py tools/publish_lite_update.py --exe release/RerunLite/RerunLite.exe` writes the update
site files (`updates_site/lite/`) for the `gh-pages` branch.

## Where the code comes from

The `rerun/` folder is a copy of the ReRun engine (version 1.2.1) that Crest and the checklist run on.
`rerun_lite/` is what makes it LITE:

- `manager.py` - `LiteManager`: the engine's `Manager` with the script list cut to Crest, Login & Mail and
  Raid Tickets.
- `app.py` - `LiteApp`: the window, built from five of the original pages.
- `channel.py` - the update channel; `content.py` - the templates LITE ships; `bot.py`, `tray.py`,
  `icon.py` - the Discord bot, tray icon and icon.
- `lite_main.py` (entry point), `build_lite.py` and `build.py` (build), `tools/` (build log, update site),
  `tests/test_lite.py` (22 tests: `py tests/test_lite.py`).

The copy of `rerun/` is not kept in step with ReRun automatically. A fix made there has to be brought over
by hand.

## What has and has not been checked

- **Checked automatically:** `tests/test_lite.py` drives Auto Crest and the Dailies' Login & Mail task
  against a simulated game (scrap and redeploy, keep and stop, unknown crest, dry run, checklist states,
  no duplicate runs), builds the window, and tests the update channel against a local server. 22 of 22 pass.
- **Not checked on the real game:** LITE as a whole has not been run against a live BlueStacks window.
  Crest and Login & Mail are the same scripts that were verified live in ReRun; the Dailies checklist
  starting them, Raid Tickets, and Dry Run on a real emulator have not been (they are Beta in ReRun too).
- **Not done:** no LITE update or release has been published yet. The exe is not code-signed, so Microsoft
  Defender may complain.
- **Sign-in and update signing use ReRun's key system.** The sign-in keys and the update signature come
  from the same key pair ReRun uses, so a key that works in ReRun works here.
- The exe still contains the engine's other code, but LITE has no way to start or show it. The download is
  about as large as ReRun's, because the big parts (image matching, the text reader) are what Crest needs.
