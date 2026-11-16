"""Starting ReRun LITE again (after a theme change, and by the one-file exe's own test).

A one-file exe unpacks itself into a temporary folder and sets environment variables that point a child process at that
same folder. A child started the plain way would then try to load its libraries from the folder its parent deletes on
exit, and die with "No module named 'cv2...'". PYINSTALLER_RESET_ENVIRONMENT=1 makes the new process unpack its own copy
(rerun/updates.py does the same when it swaps in an update).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

NEW_PROCESS_GROUP = 0x00000200


def command(args=()) -> list[str]:
    """The command line that starts this program again."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(sys.argv[0]).resolve()), *args]


def relaunch(root: str | Path, args=()) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env.pop("_MEIPASS2", None)
    flags = NEW_PROCESS_GROUP if os.name == "nt" else 0           # closing this window must not end the new one
    return subprocess.Popen(command(args), cwd=str(root), env=env, close_fds=True, creationflags=flags,   # noqa: S603
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
