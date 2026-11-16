"""Publish a ReRun LITE update: writes LITE's part of the folder you upload to your update host.

    py tools/publish_lite_update.py                                  LITE's templates only (stable)
    py tools/publish_lite_update.py --exe release/RerunLite/RerunLite.exe --notes "Crest fix"
    py tools/publish_lite_update.py --channel beta --out updates_site

Output (default: updates_site/lite/, next to the full app's updates_site/<channel>/):
    <out>/lite/<channel>/manifest.json, manifest.sig, content/<sha256>..., app/Rerun-<v>.exe

ReRun LITE reads <update url>/lite/<channel>/ and nothing else (rerun_lite/channel.py), so this never
changes what the full ReRun is offered, and the full ReRun's publish (tools/publish_update.py, unchanged)
never changes what LITE is offered. The manifest is marked "product": "lite"; LITE refuses one that is not.
It holds only the templates LITE's scripts use (rerun_lite/content.py).

Same signing key and the same publish function as the full app. The version offered for --exe is
rerun_lite/__init__.py's __version__ (LITE has its own version number, 1.0.0 to start): build RerunLite.exe from the same
source you publish.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rerun.updates import CHANNELS, parse_manifest, sign_manifest  # noqa: E402
from rerun_lite import content  # noqa: E402
from rerun_lite.channel import LITE_PATH, PRODUCT  # noqa: E402
from rerun_lite import __version__ as LITE_VERSION  # noqa: E402
from tools import publish_update  # noqa: E402

publish_update.__version__ = LITE_VERSION      # the app version a LITE update offers is LITE's own


def publish(out: Path, channel: str, secret: bytes, exe: Path | None = None, notes: str = "",
            content_version: str = "", src: Path = ROOT) -> dict:
    """tools/publish_update.publish() for LITE: LITE's templates from `src`, into <out>/lite/<channel>/."""
    site = Path(out) / LITE_PATH
    with tempfile.TemporaryDirectory(prefix="rerunlite_pub_") as tmp:
        content.copy_to(src, tmp)
        m = publish_update.publish(site, channel, secret, exe, notes, content_version, src=Path(tmp))
    m["product"] = PRODUCT
    raw = json.dumps(m, indent=1, sort_keys=True).encode("utf-8")
    sig = sign_manifest(raw, secret)
    parse_manifest(raw, sig)   # the exact check ReRun LITE will make
    chan = site / channel
    (chan / "manifest.json").write_bytes(raw)
    (chan / "manifest.sig").write_text(sig, encoding="ascii")
    return m


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "updates_site"))
    ap.add_argument("--channel", default="stable", choices=CHANNELS)
    ap.add_argument("--exe", help="a RerunLite.exe built from this source (py build_lite.py)")
    ap.add_argument("--notes", default="", help="what's new, shown when ReRun LITE offers the update")
    ap.add_argument("--content-version", default="")
    ap.add_argument("--key", help="signing key file (default: the keygen's)")
    a = ap.parse_args(argv)
    secret = publish_update.load_secret(Path(a.key) if a.key else None)
    m = publish(Path(a.out), a.channel, secret, Path(a.exe) if a.exe else None, a.notes, a.content_version)
    c = m["content"]
    print(f"Published ReRun LITE {a.channel} serial {m['serial']}: {len(c['files'])} content files "
          f"(version {c['version']}), {len(c['remove'])} removed"
          + (f", app {m['app']['version']}" if m.get("app") else ", no app"))
    print(f"Upload {Path(a.out).resolve()} so {LITE_PATH}/{a.channel}/manifest.json is under your UPDATE_URL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
