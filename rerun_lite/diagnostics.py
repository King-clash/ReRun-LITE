"""Diagnostic bundle: one zip you can send when asking for help, with secrets taken out first.

What goes in: version and system facts, the status summary, the health checks, the last log lines, the app's error log,
config.yaml with every secret blanked, the window settings (ui.json), and the newest session summaries.
What never goes in: screenshots, captured template pictures, your Discord token or webhook, license keys, the signing
key, account names. Secrets are removed by key NAME (token, key, secret, password, webhook, url...) and again by what the
text LOOKS like (Discord tokens and webhook addresses), so one miss is not enough to leak - and the zip is only
written to the place you choose; nothing is uploaded."""
from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path
from typing import Any

SECRET_KEY = re.compile(r"(token|secret|password|passwd|key|webhook|url|license|auth|cookie|session_id)", re.I)
KEEP_KEYS = {"keyboard", "hotkeys", "key_name"}                  # contain the word "key" but are not secrets
TOKEN_LIKE = re.compile(r"[A-Za-z0-9_\-]{23,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{20,}")   # a Discord bot token
WEBHOOK = re.compile(r"https?://[^\s\"']*(discord(app)?\.com/api/webhooks|hooks\.slack\.com)[^\s\"']*", re.I)
LONG_SECRET = re.compile(r"\b[A-Za-z0-9+/_\-]{40,}={0,2}\b")
USER_PATH = re.compile(r"([A-Za-z]:\\Users\\)[^\\\s\"']+", re.I)
BLANK = "<removed>"


def redact_text(text: str) -> str:
    """Take secrets and the Windows user name out of free text (log lines, error traces)."""
    text = WEBHOOK.sub(BLANK, text)
    text = TOKEN_LIKE.sub(BLANK, text)
    text = LONG_SECRET.sub(BLANK, text)
    return USER_PATH.sub(r"\1<user>", text)


def redact(obj: Any, key: str = "") -> Any:
    """A copy of a config-like structure with secret values blanked (by key name, then by what the value looks like)."""
    if isinstance(obj, dict):
        return {k: redact(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v, key) for v in obj]
    if key and key not in KEEP_KEYS and SECRET_KEY.search(key) and obj not in (None, "", 0, False, True):
        return BLANK
    return redact_text(obj) if isinstance(obj, str) else obj


def tail(path: Path, lines: int = 300, max_bytes: int = 200_000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-lines:])
    except OSError:
        return ""


def clean_session(s: dict) -> dict:
    """A session summary without the account name or the free-text reason details beyond what is needed."""
    drop = {"account"}
    return {k: v for k, v in s.items() if k not in drop}


def build_bundle(parts: dict[str, str]) -> bytes:
    """{file name: text} -> zip bytes. Every part passes through redact_text once more as a last line of defence."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            safe = Path(name).name                      # no folders, no '..'
            z.writestr(safe, redact_text(text))
    return buf.getvalue()


def default_name(app: str = "ReRun-LITE") -> str:
    return f"{app}-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.zip"
