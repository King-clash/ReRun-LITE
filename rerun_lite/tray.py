"""ReRun LITE's tray icon: rerun/tray.py's, with LITE's name and icon (so it is not mistaken for the
full ReRun's when both are open)."""
from __future__ import annotations

from rerun import tray as _tray

from . import APP_NAME
from .icon import make_lite_icon


class LiteTray(_tray.Tray):

    def start(self) -> bool:
        pystray = _tray.pystray
        if pystray is None:
            return False
        r = self.request
        menu = pystray.Menu(
            pystray.MenuItem(f"Show {APP_NAME}", lambda *_: r("show"), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Crest on all", lambda *_: r("start_all")),
            pystray.MenuItem("Pause / resume all", lambda *_: r("pause_all")),
            pystray.MenuItem("Stop all", lambda *_: r("stop_all")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Quit {APP_NAME}", lambda *_: r("quit")),
        )
        try:
            self.icon = pystray.Icon("RerunLite", make_lite_icon(64), APP_NAME, menu)
            self.icon.run_detached()
        except Exception:  # noqa: BLE001 - no tray on this system: the app still works
            self.icon = None
            return False
        return True

    def notify(self, message: str, title: str = APP_NAME) -> None:
        super().notify(message.replace("Rerun is", f"{APP_NAME} is"), title)
