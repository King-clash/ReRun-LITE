"""ReRun LITE - a separate, smaller app with exactly two features: Auto Crest and Dailies.

LITE is not a copy of ReRun and does not change it. It is a thin shell around the SAME code the full
app runs (the `rerun` package):

  * Auto Crest  = rerun/scripts/crest.py (CrestScript), on the original Dashboard page;
  * Dailies     = rerun/checklist.py (the daily & weekly checklist), with the scripts it can start:
                  Login & Mail (rerun/scripts/login_mail.py) and Raid Tickets (rerun/scripts/raids.py, Beta).

Nothing in this package re-implements either feature: `rerun_lite.manager.LiteManager` is the original
Manager with the list of scripts cut down to those three, and `rerun_lite.app.LiteApp` is the original
window class building only the pages those two features need. No file of the original app is edited.

Start it with:  py lite_main.py        Build it with:  py build_lite.py
"""
from __future__ import annotations

from rerun import __version__  # noqa: F401 - LITE x.y.z is built from ReRun x.y.z (same Crest, same checklist)

APP_NAME = "ReRun LITE"
EXE_NAME = "RerunLite"          # RerunLite.exe - never Rerun.exe, so the two can sit side by side

# The one script an emulator runs in LITE: Start, Start All, schedules and autostart all mean this.
MAIN_SCRIPT = "crest"
# Everything LITE can start. The last two belong to Dailies: they are the scripts behind the checklist's
# "Login reward + mail" and "Raid tickets" tasks, started from the Dailies tab only.
LITE_SCRIPTS = ("crest", "login_mail", "raid_tickets")
DAILIES_SCRIPTS = ("login_mail", "raid_tickets")

__all__ = ["APP_NAME", "EXE_NAME", "MAIN_SCRIPT", "LITE_SCRIPTS", "DAILIES_SCRIPTS", "__version__"]
