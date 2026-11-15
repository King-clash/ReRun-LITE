"""Updates: new templates and routines without a new .exe, and new versions of Rerun.exe.

Everything comes from one signed file on your update host:

    <url>/<channel>/manifest.json       what the latest release holds
    <url>/<channel>/manifest.sig        its Ed25519 signature (the key that signs Rerun keys)
    <url>/<channel>/content/<sha256>    each template / routine file, named by its hash
    <url>/<channel>/app/Rerun-<v>.exe   the newest Rerun.exe

tools/publish_update.py writes that folder; upload it to any static host (GitHub Pages,
Cloudflare R2, Netlify, ...). Rerun trusts a manifest only when its signature checks out
against license.PUBLIC_KEY, and every downloaded file only when its hash matches the
manifest, so the host itself does not need to be trusted. A manifest older than the last
one Rerun accepted (its `serial`) is refused, so an old release cannot be replayed.

Content (templates/, routines/) - your own work is never overwritten:
  * a file is replaced only when it is still exactly what Rerun shipped or installed
    (content_baseline.json from the build, content_state.json after an update);
  * a template you re-captured, or a routine you edited, is kept and reported;
  * templates/_meta.json is merged per template; a threshold you tuned is kept unless the
    update sets its own threshold for that template.
Files are downloaded into .update_staging/ first and only moved into place once all of
them are verified, while no script is running (or on the next start).

App: the new exe is downloaded next to Rerun.exe as Rerun.update.exe, checked, and a small
helper swaps it in after Rerun quits, keeps the old one as Rerun.old.exe and starts the new
one. Your data stays put because the folder does not change.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__, ed25519
from .license import PUBLIC_KEY

# Base URL of the update host (no trailing slash): GitHub Pages of King-clash/ReRun-LITE (the `gh-pages` branch).
# Empty = updates are off. config.yaml `updates.url` overrides it (handy for testing).
UPDATE_URL = "https://king-clash.github.io/ReRun-LITE"

CHANNELS = ("stable", "beta")
FORMAT = 1
SIG_DOMAIN = b"RERUN-UPDATE-MANIFEST-v1\0"   # keeps these signatures apart from key signatures
CONTENT_DIRS = ("templates", "routines")
META_PATH = "templates/_meta.json"
STATE_FILE = "content_state.json"
BASELINE_FILE = "content_baseline.json"
STAGING_DIR = ".update_staging"
STAGED_FILE = "staged.json"
APP_NEW = "Rerun.update.exe"
APP_OLD = "Rerun.old.exe"
MAX_MANIFEST = 2_000_000
MAX_FILE = 300_000_000
TIMEOUT_S = 20


class UpdateError(Exception):
    pass


# ---------------------------------------------------------------- small helpers
def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def is_newer(remote: str, local: str | None = None) -> bool:
    return version_tuple(remote) > version_tuple(local or __version__)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def settings(config: dict) -> dict:
    u = dict(config.get("updates") or {})
    url = str(u.get("url") or UPDATE_URL).strip().rstrip("/")
    channel = str(u.get("channel") or "stable").lower()
    return {"url": url, "channel": channel if channel in CHANNELS else "stable",
            "check": bool(u.get("check", True)),
            # content updates edit templates/ and routines/: on in the .exe, off when running
            # from source (a git checkout) unless you turn it on
            "content": bool(u.get("content_in_source", False)) or frozen()}


def channel_url(config: dict) -> str:
    s = settings(config)
    return f"{s['url']}/{s['channel']}" if s["url"] else ""


def _safe_rel(rel: str) -> str:
    """A manifest path must stay inside templates/ or routines/ (no .., no drive)."""
    p = rel.replace("\\", "/")
    parts = p.split("/")
    if (len(parts) < 2 or parts[0] not in CONTENT_DIRS or any(x in ("", ".", "..") for x in parts)
            or ":" in p or p == META_PATH):
        raise UpdateError(f"Unsafe path in update: {rel!r}")
    return p


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- download
def fetch(url: str, max_bytes: int = MAX_MANIFEST, dest: Path | None = None,
          progress: Callable[[int, int], None] | None = None) -> bytes:
    """GET url (https, or http on localhost for testing). Into memory, or into dest."""
    if not (url.startswith("https://") or url.startswith(("http://127.0.0.1", "http://localhost"))):
        raise UpdateError(f"Updates must use https: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"Rerun/{__version__}",
                                               "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - scheme checked above
            total = int(r.headers.get("Content-Length") or 0)
            if total > max_bytes:
                raise UpdateError(f"Download too large ({total} bytes): {url}")
            got, chunks = 0, []
            out = open(dest, "wb") if dest is not None else None
            try:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > max_bytes:
                        raise UpdateError(f"Download too large: {url}")
                    if out is not None:
                        out.write(chunk)
                    else:
                        chunks.append(chunk)
                    if progress is not None:
                        progress(got, total)
            finally:
                if out is not None:
                    out.close()
            return b"".join(chunks)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"Update host answered {e.code} for {url}") from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"Could not reach the update host: {getattr(e, 'reason', e)}") from e


# ---------------------------------------------------------------- manifest
def sign_manifest(raw: bytes, secret: bytes) -> str:
    return base64.b64encode(ed25519.sign(secret, SIG_DOMAIN + raw)).decode("ascii")


def parse_manifest(raw: bytes, sig_text: bytes | str, public: bytes | None = None) -> dict:
    public = public or PUBLIC_KEY
    try:
        sig = base64.b64decode(sig_text.strip() if isinstance(sig_text, (bytes, str)) else b"",
                               validate=True)
    except ValueError as e:
        raise UpdateError("The update's signature is unreadable") from e
    if len(sig) != 64 or not ed25519.verify(public, SIG_DOMAIN + raw, sig):
        raise UpdateError("The update's signature does not match - ignored")
    try:
        m = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise UpdateError("The update manifest is unreadable") from e
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        raise UpdateError("This update needs a newer Rerun - download it from the website")
    if not isinstance(m.get("serial"), int):
        raise UpdateError("The update manifest has no serial")
    content = m.get("content") or {}
    for rel, info in (content.get("files") or {}).items():
        _safe_rel(rel)
        if not isinstance(info, dict) or len(str(info.get("sha256", ""))) != 64:
            raise UpdateError(f"Bad file entry in update: {rel}")
    for rel in content.get("remove") or []:
        _safe_rel(rel)
    app = m.get("app")
    if app is not None and (len(str(app.get("sha256", ""))) != 64 or not app.get("file")
                            or not app.get("version")):
        raise UpdateError("Bad app entry in update")
    return m


def load_state(root: Path) -> dict:
    s = _read_json(Path(root) / STATE_FILE, {})
    s.setdefault("serial", 0)
    s.setdefault("files", {})
    return s


def get_manifest(root: Path, config: dict) -> dict:
    base = channel_url(config)
    if not base:
        raise UpdateError("No update address is set")
    raw = fetch(f"{base}/manifest.json")
    sig = fetch(f"{base}/manifest.sig", max_bytes=4096)
    m = parse_manifest(raw, sig)
    seen = int(load_state(root).get("serial", 0))
    if m["serial"] < seen:
        raise UpdateError("The update host is serving an older release than one already "
                          "installed - ignored")
    return m


# ---------------------------------------------------------------- content plan
@dataclass
class ContentPlan:
    install: dict[str, str] = field(default_factory=dict)   # rel -> sha256 to download
    remove: list[str] = field(default_factory=list)          # ours, dropped by the release
    kept: list[str] = field(default_factory=list)            # yours (edited) - left alone
    meta: dict[str, dict] = field(default_factory=dict)      # template -> new _meta entry
    ours: dict[str, str] = field(default_factory=dict)       # rel -> sha256 once applied
    version: str = ""
    serial: int = 0

    @property
    def empty(self) -> bool:
        return not (self.install or self.remove or self.meta)

    def describe(self) -> str:
        bits = []
        if self.install:
            bits.append(f"{len(self.install)} file(s) to update")
        if self.remove:
            bits.append(f"{len(self.remove)} to remove")
        if self.meta and not self.install:
            bits.append(f"{len(self.meta)} template setting(s)")
        if self.kept:
            bits.append(f"{len(self.kept)} of yours kept")
        return ", ".join(bits) or "up to date"


def _known(root: Path, state: dict) -> dict[str, str]:
    """Hashes of files Rerun itself put there: the build's baseline, then later updates."""
    known = dict(_read_json(Path(root) / BASELINE_FILE, {}).get("files", {}))
    known.update(state.get("files", {}))
    return known


def _template_name(rel: str) -> str | None:
    parts = rel.split("/")
    if parts[0] == "templates" and len(parts) == 2 and rel.endswith(".png"):
        return parts[1][:-4]
    return None


def plan_content(root: str | Path, manifest: dict) -> ContentPlan:
    root = Path(root)
    content = manifest.get("content") or {}
    state = load_state(root)
    known = _known(root, state)
    plan = ContentPlan(version=str(content.get("version", "")), serial=int(manifest["serial"]))
    local_meta = _read_json(root / META_PATH, {})
    pub_meta = content.get("meta") or {}
    for rel, info in sorted((content.get("files") or {}).items()):
        rel = _safe_rel(rel)
        want = str(info["sha256"]).lower()
        p = root / rel
        have = sha256_file(p) if p.is_file() else None
        if have is not None and have != want and known.get(rel) != have:
            plan.kept.append(rel)          # you changed it (or made it): yours wins
            continue
        if have != want:
            plan.install[rel] = want
        plan.ours[rel] = want
        name = _template_name(rel)
        if name and name in pub_meta:
            new = dict(pub_meta[name])
            old = local_meta.get(name) or {}
            if "threshold" in old and "threshold" not in new:
                new["threshold"] = old["threshold"]
            if new != old:
                plan.meta[name] = new
    for rel in content.get("remove") or []:
        rel = _safe_rel(rel)
        p = root / rel
        if p.is_file() and known.get(rel) == sha256_file(p):
            plan.remove.append(rel)
    return plan


# ---------------------------------------------------------------- stage + commit
def stage_content(root: str | Path, config: dict, plan: ContentPlan,
                  progress: Callable[[int, int], None] | None = None) -> Path:
    """Download every file of the plan into .update_staging/ and check its hash.
    Nothing in templates/ or routines/ changes yet."""
    root = Path(root)
    stage = root / STAGING_DIR
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "files").mkdir(parents=True)
    base = channel_url(config)
    for i, (rel, sha) in enumerate(sorted(plan.install.items()), 1):
        dest = stage / "files" / sha
        if not dest.exists():
            fetch(f"{base}/content/{sha}", max_bytes=MAX_FILE, dest=dest)
            if sha256_file(dest) != sha:
                shutil.rmtree(stage, ignore_errors=True)
                raise UpdateError(f"{rel} did not download correctly - try again later")
        if progress is not None:
            progress(i, len(plan.install))
    _write_json(stage / STAGED_FILE, {
        "install": plan.install, "remove": plan.remove, "meta": plan.meta, "ours": plan.ours,
        "kept": plan.kept, "version": plan.version, "serial": plan.serial, "time": time.time()})
    return stage


def has_staged(root: str | Path) -> bool:
    return (Path(root) / STAGING_DIR / STAGED_FILE).is_file()


def commit_staged(root: str | Path) -> str:
    """Move staged files into templates/ and routines/ (call while no script runs).
    Returns a one-line summary, or "" when nothing was staged."""
    root = Path(root)
    stage = root / STAGING_DIR
    s = _read_json(stage / STAGED_FILE, None)
    if not s:
        return ""
    state = load_state(root)
    known = _known(root, state)
    done, kept = 0, list(s.get("kept", []))
    for rel, sha in sorted(s["install"].items()):
        rel = _safe_rel(rel)
        src, dest = stage / "files" / sha, root / rel
        if not src.is_file() or sha256_file(src) != sha:
            raise UpdateError(f"Staged file for {rel} is missing or damaged")
        if dest.is_file():
            have = sha256_file(dest)
            if have != sha and known.get(rel) != have:   # you edited it since the download
                kept.append(rel)
                s["ours"].pop(rel, None)
                s["meta"].pop(_template_name(rel) or "", None)
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".updtmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
        done += 1
    removed = 0
    for rel in s.get("remove", []):
        p = root / _safe_rel(rel)
        if p.is_file() and known.get(rel) == sha256_file(p):
            p.unlink()
            removed += 1
            state["files"].pop(rel, None)
    if s.get("meta"):
        meta_path = root / META_PATH
        meta = _read_json(meta_path, {})
        for name, entry in s["meta"].items():
            if name:
                meta[name] = entry
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(meta_path, meta)
    state["files"].update(s.get("ours", {}))
    state["serial"] = max(int(state.get("serial", 0)), int(s.get("serial", 0)))
    state["content_version"] = s.get("version", "")
    state["updated"] = time.time()
    _write_json(root / STATE_FILE, state)
    shutil.rmtree(stage, ignore_errors=True)
    bits = [f"{done} file(s) updated"]
    if removed:
        bits.append(f"{removed} removed")
    if kept:
        bits.append(f"{len(kept)} of yours kept ({', '.join(sorted(set(kept))[:3])}"
                    f"{'…' if len(set(kept)) > 3 else ''})")
    ver = f" to {s['version']}" if s.get("version") else ""
    return f"Templates and routines updated{ver}: " + ", ".join(bits)


def note_serial(root: str | Path, serial: int) -> None:
    """Remember the newest release seen even when it changed nothing here."""
    root = Path(root)
    state = load_state(root)
    if serial > int(state.get("serial", 0)):
        state["serial"] = serial
        _write_json(root / STATE_FILE, state)


# ---------------------------------------------------------------- app update
def app_update(manifest: dict) -> dict | None:
    """The manifest's app entry when it is newer than this Rerun, else None."""
    app = manifest.get("app")
    return app if app and is_newer(str(app["version"])) else None


def download_app(root: str | Path, config: dict, app: dict,
                 progress: Callable[[int, int], None] | None = None) -> Path:
    root = Path(root)
    dest = root / APP_NEW
    part = root / (APP_NEW + ".part")
    fetch(f"{channel_url(config)}/{app['file'].lstrip('/')}", max_bytes=MAX_FILE, dest=part,
          progress=progress)
    if sha256_file(part) != str(app["sha256"]).lower():
        part.unlink(missing_ok=True)
        raise UpdateError("The new Rerun did not download correctly - try again later")
    os.replace(part, dest)
    return dest


def helper_script(exe: Path, new: Path, old: Path, pids: list[int], restart: bool = True) -> str:
    """Windows batch file: wait for Rerun to close, swap the exe in (keeping the old one),
    and start it when restart is on. If the swap keeps failing, the old Rerun stays (and
    is the one started)."""
    run = f'start "" "{exe}"' if restart else "rem not restarting"
    # Full paths: another 'find' on PATH (Git's, say) would end the wait at once. A one-second
    # pause is a ping: 'timeout' refuses to run without a console, and this has none.
    sleep = '"%SystemRoot%\\System32\\PING.EXE" -n 2 127.0.0.1 >nul'
    waits = "\n".join(
        f':wait{p}\n"%SystemRoot%\\System32\\tasklist.exe" /FI "PID eq {p}" /NH 2>nul'
        f' | "%SystemRoot%\\System32\\find.exe" " {p} " >nul\n'
        f"if not errorlevel 1 ({sleep} & goto wait{p})" for p in pids)
    return f"""@echo off
chcp 65001 >nul
set tries=0
{waits}
copy /Y "{exe}" "{old}" >nul 2>&1
:swap
move /Y "{new}" "{exe}" >nul 2>&1
if not errorlevel 1 goto run
set /a tries+=1
if %tries% geq 30 goto run
{sleep}
goto swap
:run
{run}
(goto) 2>nul & del "%~f0"
"""


def launch_swap(root: str | Path, restart: bool = True) -> None:
    """Start the helper that replaces Rerun.exe once this process (and the one-file
    bootloader that started it) have exited. The caller then quits Rerun."""
    if not frozen() or os.name != "nt":
        raise UpdateError("Only the Rerun.exe build can update itself")
    root = Path(root)
    exe, new = Path(sys.executable).resolve(), root / APP_NEW
    if not new.is_file():
        raise UpdateError("The downloaded update is missing")
    pids = sorted({os.getpid(), os.getppid()})
    bat = Path(tempfile.gettempdir()) / f"rerun_update_{os.getpid()}.bat"
    bat.write_text(helper_script(exe, new, root / APP_OLD, pids, restart), encoding="utf-8")
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # the new exe unpacks itself afresh
    # a hidden console (not DETACHED_PROCESS: without any console the tasklist | find
    # pipe never returns); a new process group so closing Rerun does not end it
    flags = 0x00000200 | 0x08000000  # NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True, env=env,
                     cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def cleanup_after_update(root: str | Path) -> None:
    """Leftovers of an earlier update (kept: Rerun.old.exe, as a way back)."""
    root = Path(root)
    for name in (APP_NEW + ".part",):
        try:
            (root / name).unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------- one check
@dataclass
class CheckResult:
    manifest: dict | None = None
    app: dict | None = None            # newer Rerun.exe on offer
    plan: ContentPlan | None = None    # templates/routines changes (None = content off)
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return self.error
        bits = []
        if self.app:
            bits.append(f"Rerun {self.app['version']} is available")
        if self.plan is not None and not self.plan.empty:
            bits.append(f"templates: {self.plan.describe()}")
        return "; ".join(bits) or f"Up to date (Rerun {__version__})"


def check(root: str | Path, config: dict) -> CheckResult:
    """Fetch and verify the manifest, then work out what would change. Never raises."""
    try:
        m = get_manifest(Path(root), config)
        plan = plan_content(root, m) if settings(config)["content"] else None
        if plan is not None and plan.empty:
            note_serial(root, m["serial"])
        return CheckResult(manifest=m, app=app_update(m), plan=plan)
    except UpdateError as e:
        return CheckResult(error=str(e))
    except Exception as e:  # noqa: BLE001 - an update check must never break Rerun
        return CheckResult(error=f"Update check failed: {e}")
