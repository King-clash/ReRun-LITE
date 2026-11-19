"""Make opening a Tk window in the tests survive a one-off failure to read Tk's own files.

On this PC, opening a window now and then fails with "Can't find a usable tk.tcl ... couldn't read file ...ttk/entry.tcl: no
such file or directory" although the file is there (found by running the window tests while the PC was busy). It is Windows
momentarily refusing to hand over a file (a scan or lock), not a bug in ReRun LITE, and it showed up as a different window test
failing each time. This retries the window start a few times, only for that error, so a green run means the code is fine.
It changes nothing outside the tests.
"""
from __future__ import annotations

import time
import tkinter

_RETRY_WORDS = ("usable tk.tcl", "no such file or directory", "init.tcl", "auto.tcl")
_installed = False


def install(tries: int = 6, wait: float = 1.0) -> None:
    global _installed
    if _installed:
        return
    _installed = True
    original = tkinter.Tk.__init__

    def init_with_retry(self, *a, **kw):
        for attempt in range(tries):
            try:
                original(self, *a, **kw)
                return
            except tkinter.TclError as e:
                text = str(e).lower()
                if attempt == tries - 1 or not any(w in text for w in _RETRY_WORDS):
                    raise
                time.sleep(wait)

    tkinter.Tk.__init__ = init_with_retry
