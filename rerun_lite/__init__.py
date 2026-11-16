"""ReRun LITE - a separate, smaller app for Auto Crest.

LITE is its own project (version 1.1.2, its own releases and update address). It is a thin shell around the Crest
code and window kit of the `rerun` package that is copied into this repository:

  * Auto Crest  = rerun/scripts/crest.py (CrestScript) on the original Dashboard page, plus the daily Crest
                  Palace selector (rerun_lite/crest.py, palaces.py);
  * History, Templates, Discord alerts, Log and the app settings are the original pages.

`rerun_lite.manager.LiteManager` is the original Manager with the script list cut down to Crest, and
`rerun_lite.app.LiteApp` is the original window class building only the pages Crest needs.

Start it with:  py lite_main.py        Build it with:  py build_lite.py
"""
from __future__ import annotations


__version__ = "1.1.2"          # LITE has its own version number; it does not follow ReRun's
APP_NAME = "ReRun LITE"
EXE_NAME = "RerunLite"          # RerunLite.exe - never Rerun.exe, so the two can sit side by side

# The one script an emulator runs in LITE: Start, Start All, schedules and autostart all mean this.
MAIN_SCRIPT = "crest"
# Everything LITE can start.
LITE_SCRIPTS = ("crest",)

__all__ = ["APP_NAME", "EXE_NAME", "MAIN_SCRIPT", "LITE_SCRIPTS", "__version__"]
