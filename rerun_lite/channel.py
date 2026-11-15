"""ReRun LITE's own update channel (uses rerun/updates.py unchanged, pointed somewhere else).

The full ReRun's updater downloads the full Rerun.exe and swaps it in. If LITE read the same address it
would replace RerunLite.exe with the full app, so LITE must never do that. `apply()` runs once, first thing,
inside the LITE process only, and redirects the updater:

  address        <update url>/lite/<channel>/...   (never the full app's <update url>/<channel>/...)
  state files    data/lite/content_state.json, data/lite/update_staging/, lite_content_baseline.json
  new / old exe  RerunLite.update.exe, RerunLite.old.exe

so a LITE and a full ReRun in one folder cannot touch each other's update state. Two more guards:

  * a manifest that is not marked `"product": "lite"` (tools/publish_lite_update.py writes that) is
    refused, whatever address it came from;
  * when the full ReRun's Rerun.exe is in the same folder, LITE leaves templates/ alone (the full app
    updates them) and only updates its own exe.

These are run-time redirections of module settings; rerun/updates.py on disk is not edited.
"""
from __future__ import annotations

from pathlib import Path

from rerun import updates

PRODUCT = "lite"
LITE_PATH = "lite"
DATA_DIR = "data/lite"                       # LITE's own small files (data/ is already git-ignored)
NOT_LITE = "That update address serves the full ReRun, not ReRun LITE - ignored"
NOT_PUBLISHED = "No ReRun LITE updates have been published yet."

_original: dict = {}


def shares_folder(root: str | Path) -> bool:
    """True when the full ReRun's exe lives in this folder too."""
    return (Path(root) / "Rerun.exe").is_file()


def data_dir(root: str | Path) -> Path:
    d = Path(root) / DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def applied() -> bool:
    return bool(_original)


def apply(root: str | Path) -> None:
    """Point rerun.updates at LITE's channel and files. Safe to call twice."""
    if _original:
        return
    root = Path(root)
    data_dir(root)
    for name in ("STATE_FILE", "BASELINE_FILE", "STAGING_DIR", "APP_NEW", "APP_OLD", "settings", "check"):
        _original[name] = getattr(updates, name)
    main_settings, main_check = updates.settings, updates.check

    def settings(config: dict) -> dict:
        s = main_settings(config)
        if s["url"]:
            s["url"] = f"{s['url']}/{LITE_PATH}"          # built-in or config.yaml: LITE's part of the host
        if shares_folder(root):
            s["content"] = False                           # the full ReRun here owns templates/
        return s

    def check(root_: str | Path, config: dict) -> updates.CheckResult:
        res = main_check(root_, config)
        if not res.error and (res.manifest or {}).get("product") != PRODUCT:
            return updates.CheckResult(error=NOT_LITE)
        return res

    updates.STATE_FILE = f"{DATA_DIR}/content_state.json"
    updates.BASELINE_FILE = "lite_content_baseline.json"    # written next to the exe by build_lite.py
    updates.STAGING_DIR = f"{DATA_DIR}/update_staging"
    updates.APP_NEW = "RerunLite.update.exe"
    updates.APP_OLD = "RerunLite.old.exe"
    updates.settings = settings
    updates.check = check


def restore() -> None:
    """Undo apply() (tests)."""
    for name, value in _original.items():
        setattr(updates, name, value)
    _original.clear()


def not_published(error: str) -> bool:
    """The update host answered 'no such file' for LITE's manifest: nothing was published for LITE yet."""
    return "answered 404" in (error or "") and f"/{LITE_PATH}/" in error


__all__ = ["PRODUCT", "LITE_PATH", "DATA_DIR", "NOT_LITE", "NOT_PUBLISHED", "apply", "applied", "restore",
           "shares_folder", "data_dir", "not_published"]
