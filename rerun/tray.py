"""System-tray icon: keeps Rerun reachable while its window is hidden.

The menu only queues requests; the window's own event loop carries them out,
because Tk must only be touched from its own thread."""
from __future__ import annotations

from typing import Callable

try:
    import pystray
except ImportError:  # optional dependency
    pystray = None

from .appicon import make_icon


class Tray:
    def __init__(self, request: Callable[[str], None]):
        self.request = request
        self.icon = None

    @property
    def available(self) -> bool:
        return pystray is not None

    def start(self) -> bool:
        if pystray is None:
            return False
        r = self.request
        menu = pystray.Menu(
            pystray.MenuItem("Show Rerun", lambda *_: r("show"), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start all", lambda *_: r("start_all")),
            pystray.MenuItem("Pause / resume all", lambda *_: r("pause_all")),
            pystray.MenuItem("Stop all", lambda *_: r("stop_all")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Rerun", lambda *_: r("quit")),
        )
        try:
            self.icon = pystray.Icon("Rerun", make_icon(64), "Rerun", menu)
            self.icon.run_detached()
        except Exception:  # noqa: BLE001 - no tray on this system: the app still works
            self.icon = None
            return False
        return True

    def notify(self, message: str, title: str = "Rerun") -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception:  # noqa: BLE001 - notifications are a nicety
                pass

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass
            self.icon = None
