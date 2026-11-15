"""Publish an update: writes the folder you upload to your update host (rerun/updates.py).

    py tools/publish_update.py                        templates + routines only (stable)
    py tools/publish_update.py --exe dist/Rerun/Rerun.exe --notes "Fixes the arena"
    py tools/publish_update.py --channel beta --out updates_site

Output (default: updates_site/, git-ignored):
    <out>/<channel>/manifest.json, manifest.sig, content/<sha256>..., app/Rerun-<v>.exe

Upload the whole <out> folder so <url>/<channel>/manifest.json is reachable, where <url>
is UPDATE_URL in rerun/updates.py. Re-running keeps the files already there, so an upload
only adds new ones. Without --exe the previous release's app entry is kept, so a
template-only release never takes an app update away.

Signs with the same private key as tools/keygen.py (Documents\\Rerun Keygen\\
signing_key.txt), so only you can publish. The version offered for --exe is
rerun/__init__.py's __version__: bump it before building the exe you publish.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun import __version__, ed25519  # noqa: E402
from rerun.license import PUBLIC_KEY  # noqa: E402
from rerun.updates import (CHANNELS, CONTENT_DIRS, FORMAT, META_PATH, parse_manifest,  # noqa: E402
                           sha256_file, sign_manifest, version_tuple)

CONTENT_GLOBS = {"templates": ("*.png",), "routines": ("*.yaml", "*.yml", "*.md")}


def content_files(root: Path) -> dict[str, Path]:
    out = {}
    for folder in CONTENT_DIRS:
        for pattern in CONTENT_GLOBS[folder]:
            for p in sorted((root / folder).glob(pattern)):
                if p.is_file():
                    out[f"{folder}/{p.name}"] = p
    return out


def load_secret(path: Path | None) -> bytes:
    if path is None:
        from tools.keygen import Keygen
        secret = Keygen().secret()
        where = Keygen().secret_path
    else:
        where = path
        try:
            secret = bytes.fromhex(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            secret = None
    if not secret or len(secret) != 32:
        raise SystemExit(f"No signing key at {where} - make or import one with tools/keygen.py")
    if ed25519.public_key(secret) != PUBLIC_KEY:
        raise SystemExit("That signing key does not match the public key built into Rerun "
                         "(rerun/license.py) - Rerun would refuse this update")
    return secret


def publish(out: Path, channel: str, secret: bytes, exe: Path | None = None, notes: str = "",
            content_version: str = "", src: Path = ROOT, remove: list[str] | None = None) -> dict:
    chan = out / channel
    (chan / "content").mkdir(parents=True, exist_ok=True)
    prev_path = chan / "manifest.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else {}

    files, used = {}, set()
    for rel, p in content_files(src).items():
        sha = sha256_file(p)
        files[rel] = {"sha256": sha, "size": p.stat().st_size}
        used.add(sha)
        dest = chan / "content" / sha
        if not dest.exists():
            shutil.copyfile(p, dest)
    meta_all = json.loads((src / META_PATH).read_text(encoding="utf-8")) \
        if (src / META_PATH).exists() else {}
    names = {Path(r).stem for r in files if r.startswith("templates/")}
    meta = {n: meta_all[n] for n in sorted(names) if n in meta_all}

    # files the previous release had and this one doesn't: removed where still untouched
    gone = set((prev.get("content") or {}).get("files", {})) - set(files)
    gone |= set(remove or [])

    app = prev.get("app")
    if exe is not None:
        exe = Path(exe)
        if not exe.is_file():
            raise SystemExit(f"No such exe: {exe}")
        if app and version_tuple(app["version"]) >= version_tuple(__version__) \
                and app.get("sha256") != sha256_file(exe):
            raise SystemExit(f"Version {__version__} was already published with a different exe "
                             "- bump __version__ in rerun/__init__.py and rebuild")
        name = f"app/Rerun-{__version__}.exe"
        (chan / "app").mkdir(exist_ok=True)
        shutil.copyfile(exe, chan / name)
        app = {"version": __version__, "file": name, "sha256": sha256_file(exe),
               "size": exe.stat().st_size, "notes": notes.strip(),
               "published": time.strftime("%Y-%m-%d")}

    serial = max(int(time.time()), int(prev.get("serial", 0)) + 1)
    manifest = {
        "format": FORMAT, "channel": channel, "serial": serial,
        "published": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app": app,
        "content": {"version": content_version or time.strftime("%Y.%m.%d.%H%M"),
                    "files": files, "meta": meta, "remove": sorted(gone)},
    }
    if app is None:
        del manifest["app"]
    raw = json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")
    sig = sign_manifest(raw, secret)
    parse_manifest(raw, sig)   # the exact check Rerun will make
    (chan / "manifest.json").write_bytes(raw)
    (chan / "manifest.sig").write_text(sig, encoding="ascii")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "updates_site"))
    ap.add_argument("--channel", default="stable", choices=CHANNELS)
    ap.add_argument("--exe", help="a Rerun.exe built from this source (python build.py)")
    ap.add_argument("--notes", default="", help="what's new, shown when Rerun offers the update")
    ap.add_argument("--content-version", default="")
    ap.add_argument("--remove", action="append", default=[],
                    help="extra content path to remove, e.g. templates/old_button.png")
    ap.add_argument("--key", help="signing key file (default: the keygen's)")
    a = ap.parse_args(argv)
    secret = load_secret(Path(a.key) if a.key else None)
    m = publish(Path(a.out), a.channel, secret, Path(a.exe) if a.exe else None, a.notes,
                a.content_version, remove=a.remove)
    c = m["content"]
    print(f"Published {a.channel} serial {m['serial']}: {len(c['files'])} content files "
          f"(version {c['version']}), {len(c['remove'])} removed"
          + (f", app {m['app']['version']}" if m.get("app") else ", no app"))
    print(f"Upload {Path(a.out).resolve()} so {a.channel}/manifest.json is under your UPDATE_URL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
