"""Rerun's key system: Rerun only opens with a valid key.

A key is 21 bytes of facts signed with Ed25519 (rerun/ed25519.py):
  version (1) | issued (u32, unix time) | expires (u32, 0 = lifetime)
  | PC lock (8 bytes, all zero = any PC) | key id (4 random bytes)
followed by the 64-byte signature, written in base32 as RERUN-XXXXXXXX-... (any case;
spaces and dashes are ignored when it is typed or pasted).

Only the key generator (tools/keygen.py) holds the private signing key, on your own PC
(Documents\\Rerun Keygen\\signing_key.txt, never in git or in Rerun.exe). Rerun holds
just the public key below, so it can check keys but nobody can make new ones from it.

The accepted key is kept in <Rerun folder>/license.json with the latest time Rerun saw,
so turning the PC clock back to before that does not revive an expired key. Keys are
checked offline: a key cannot be withdrawn early - give out short time frames when unsure.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from . import ed25519

# The public half of your signing key (made by tools/keygen.py --init, 2026-11-14).
PUBLIC_KEY = bytes.fromhex("c247cac8365e7e4939331fa2cbe2e470abade07b01d4972cb8ea3ea4ad6ffaa9")

VERSION = 1
PREFIX = "RERUN"
PAYLOAD = struct.Struct("<BII8s4s")   # 21 bytes
SIG_LEN = 64
CLOCK_SLACK_S = 3600                 # the PC clock may go back this much (time zone fixes etc.)
ANY_PC = bytes(8)


class KeyError_(ValueError):
    """A key that is not accepted; str() is the reason in plain words."""


@dataclass
class License:
    key: str
    issued: float
    expires: float          # 0 = lifetime
    pc: bytes               # ANY_PC = works on any PC
    key_id: str

    @property
    def lifetime(self) -> bool:
        return self.expires == 0

    def remaining(self, now: float | None = None) -> float:
        """Seconds left (inf for a lifetime key)."""
        if self.lifetime:
            return float("inf")
        return self.expires - (time.time() if now is None else now)

    def describe(self, now: float | None = None) -> str:
        if self.lifetime:
            return "Lifetime key"
        left = self.remaining(now)
        when = time.strftime("%d %b %Y %H:%M", time.localtime(self.expires))
        if left <= 0:
            return f"Expired {when}"
        return f"Valid until {when} ({fmt_left(left)} left)"


def fmt_left(s: float) -> str:
    if s >= 2 * 86400:
        return f"{int(s // 86400)} days"
    if s >= 2 * 3600:
        return f"{int(s // 3600)} hours"
    return f"{max(1, int(s // 60))} minutes"


# ---------------------------------------------------------------- this PC
def machine_id() -> bytes:
    """8 bytes identifying this Windows install (from its MachineGuid; hashed, so the
    ID shown to you reveals nothing else). Elsewhere: the host name."""
    raw = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                            0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
            raw = str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except (OSError, ImportError):
        raw = os.environ.get("COMPUTERNAME", "")
        if not raw and hasattr(os, "uname"):
            raw = os.uname().nodename
    return hashlib.sha256(("rerun-pc:" + raw).encode()).digest()[:8]


def format_pc(pc: bytes) -> str:
    h = pc.hex().upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def parse_pc(text: str) -> bytes:
    h = "".join(c for c in (text or "") if c.isalnum())
    if len(h) != 16:
        raise ValueError("A PC ID has 16 letters/digits, e.g. 1A2B-3C4D-5E6F-7A8B")
    return bytes.fromhex(h)


# ---------------------------------------------------------------- keys
def _b32(b: bytes) -> str:
    return base64.b32encode(b).decode().rstrip("=")


def _unb32(s: str) -> bytes:
    s = s + "=" * (-len(s) % 8)
    return base64.b32decode(s)


def make_key(secret: bytes, expires: float, pc: bytes = ANY_PC, issued: float | None = None,
             key_id: bytes | None = None) -> str:
    """Sign a new key (key generator only). expires: unix time, 0 = lifetime."""
    issued = int(time.time() if issued is None else issued)
    payload = PAYLOAD.pack(VERSION, issued, int(expires), pc, key_id or os.urandom(4))
    raw = _b32(payload + ed25519.sign(secret, payload))
    return PREFIX + "-" + "-".join(raw[i:i + 8] for i in range(0, len(raw), 8))


def parse_key(text: str, public: bytes | None = None) -> License:
    """Check a key's signature and read it (expiry and PC are checked by `check`)."""
    s = "".join(c for c in (text or "").upper() if c.isalnum())
    if s.startswith(PREFIX):
        s = s[len(PREFIX):]
    try:
        raw = _unb32(s)
    except (ValueError, base64.binascii.Error):
        raise KeyError_("That doesn't look like a Rerun key - copy the whole key, it starts with RERUN-")
    if len(raw) != PAYLOAD.size + SIG_LEN:
        raise KeyError_("That key is incomplete - copy the whole key, it starts with RERUN-")
    payload, sig = raw[:PAYLOAD.size], raw[PAYLOAD.size:]
    if not ed25519.verify(public or PUBLIC_KEY, payload, sig):
        raise KeyError_("This key is not valid (it was changed or not made for Rerun)")
    ver, issued, expires, pc, kid = PAYLOAD.unpack(payload)
    if ver != VERSION:
        raise KeyError_("This key is for a different version of Rerun")
    return License(key=format_key(text), issued=issued, expires=expires, pc=pc, key_id=kid.hex())


def format_key(text: str) -> str:
    s = "".join(c for c in (text or "").upper() if c.isalnum())
    if s.startswith(PREFIX):
        s = s[len(PREFIX):]
    return PREFIX + "-" + "-".join(s[i:i + 8] for i in range(0, len(s), 8))


def check(text: str, now: float | None = None, last_seen: float = 0.0,
          public: bytes | None = None, pc: bytes | None = None) -> License:
    """A key accepted for this PC right now, or KeyError_ with the reason."""
    lic = parse_key(text, public)
    now = time.time() if now is None else now
    if lic.pc != ANY_PC and lic.pc != (pc if pc is not None else machine_id()):
        raise KeyError_("This key is locked to another PC")
    if last_seen and now < last_seen - CLOCK_SLACK_S:
        raise KeyError_("Your PC's clock is behind the last time Rerun ran - set the correct "
                        "date and time, then try again")
    if lic.issued > now + 86400:
        raise KeyError_("This key starts in the future - check your PC's date and time")
    if not lic.lifetime and now >= lic.expires:
        raise KeyError_(f"This key expired on {time.strftime('%d %b %Y %H:%M', time.localtime(lic.expires))}")
    return lic


# ---------------------------------------------------------------- the saved key
class KeyStore:
    """<Rerun folder>/license.json: {"key", "last_seen"}."""

    def __init__(self, root: str | Path):
        self.path = Path(root) / "license.json"

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    @property
    def last_seen(self) -> float:
        try:
            return float(self._load().get("last_seen", 0))
        except (TypeError, ValueError):
            return 0.0

    def saved_key(self) -> str:
        return str(self._load().get("key", ""))

    def save(self, key: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        data = {"key": key, "last_seen": max(now, self.last_seen)}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def touch(self, now: float | None = None) -> None:
        """Remember the latest time Rerun ran (clock-rollback check)."""
        d = self._load()
        if d.get("key"):
            self.save(d["key"], now)

    def current(self, now: float | None = None, public: bytes | None = None,
                pc: bytes | None = None) -> License:
        """The saved key if it is still valid here and now (else KeyError_)."""
        key = self.saved_key()
        if not key:
            raise KeyError_("Enter your Rerun key to sign in")
        return check(key, now, self.last_seen, public, pc)

    def sign_out(self) -> None:
        d = self._load()
        d.pop("key", None)
        self.path.write_text(json.dumps(d, indent=1), encoding="utf-8")


__all__ = ["License", "KeyError_", "KeyStore", "check", "parse_key", "make_key", "machine_id",
           "format_pc", "parse_pc", "format_key", "PUBLIC_KEY", "ANY_PC", "fmt_left"]
