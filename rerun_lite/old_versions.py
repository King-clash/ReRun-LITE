"""Find older copies of ReRun LITE on this PC and offer to remove them.

New versions are downloaded as a zip and unzipped into a new folder, so old ones pile up (RerunLite-1.1.0, RerunLite-1.1.1,
and their zips). This looks for them, shows what it found with sizes, and moves the ones you pick to the Recycle Bin
(so a mistake can be undone). Nothing is removed without a confirmation, and:

  * only copies OLDER than the one running are listed, and never the running folder or anything inside or around it;
  * a folder is only listed if it holds RerunLite.exe, so it cannot be an ordinary folder that happens to be named alike;
  * a copy that holds your own data (settings, stats, History, key) is marked and left unticked;
  * source folders (anything with a .git next to or above it) are never listed;
  * the clear-out goes through the Recycle Bin, never a permanent delete.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

from rerun import errlog, ios
from rerun.ios import C, F, px
from rerun.migrate import describe, has_user_data

from . import APP_NAME, __version__
from . import EXE_NAME as _EXE_STEM

EXE_NAME = _EXE_STEM + ".exe"

VERSION_RE = re.compile(r"rerun[ _-]?lite[ _-]?v?(\d+(?:\.\d+){1,3})", re.IGNORECASE)
SKIP_DIRS = {"node_modules", ".git", "windows", "appdata", "program files", "program files (x86)", "$recycle.bin", "__pycache__",
             "site-packages", "_internal"}
MAX_DEPTH = 3
MAX_DIRS = 6000
MAX_SECONDS = 10.0


def parse_version(text: str) -> tuple[int, ...] | None:
    """'RerunLite-1.1.1' -> (1, 1, 1); None when the text carries no version."""
    m = VERSION_RE.search(text or "")
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


def version_text(v: tuple[int, ...] | None) -> str:
    return ".".join(str(x) for x in v) if v else "unknown"


def exe_version(path: Path) -> tuple[int, ...] | None:
    """The version stored inside an exe (Windows file properties); None when it cannot be read."""
    if sys.platform != "win32":
        return None
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr, length = ctypes.c_void_p(), ctypes.c_uint()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or length.value < 52:
            return None
        info = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
        ms, ls = info[4], info[5]
        v = (ms >> 16, ms & 0xFFFF, ls >> 16)
        return v if any(v) else None
    except (OSError, AttributeError, ValueError):
        return None


@dataclass
class Old:
    target: Path                 # what would be removed (the folder, or the zip)
    kind: str                    # "folder" or "zip"
    version: tuple[int, ...] | None
    size: int = 0
    has_data: bool = False
    modified: float = 0.0
    note: str = ""

    @property
    def label(self) -> str:
        return self.target.name

    @property
    def where(self) -> str:
        return str(self.target.parent)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return f"{n:.0f} GB"


def tree_size(path: Path, limit: int = 40000) -> int:
    """Bytes in a file or folder (stops counting after `limit` files so a huge folder cannot stall the scan)."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total, seen = 0, 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
            seen += 1
            if seen >= limit:
                return total
    return total


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def in_source_tree(p: Path) -> bool:
    """A development checkout (a .git next to this folder or above it): its dist/ and release/ output is not an install."""
    for anc in [p, *p.parents][:8]:
        if (anc / ".git").exists():
            return True
    return False


def default_roots(current: Path) -> list[Path]:
    home = Path.home()
    roots = [current.parent, current.parent.parent, home / "Downloads", home / "Desktop", home / "Documents"]
    seen, out = set(), []
    for r in roots:
        try:
            r = r.resolve()
        except OSError:
            continue
        if r.is_dir() and r not in seen and r != Path(r.anchor):
            seen.add(r)
            out.append(r)
    return out


def find_old(current: str | Path, current_version: str = __version__, roots: list[Path] | None = None,
             max_seconds: float = MAX_SECONDS) -> list[Old]:
    """Older copies of ReRun LITE (unzipped folders and downloaded zips), newest version first."""
    cur = Path(current).resolve()
    now_v = parse_version("RerunLite-" + current_version) or ()
    found: dict[Path, Old] = {}
    deadline = time.monotonic() + max_seconds
    visited = 0
    for root in (roots if roots is not None else default_roots(cur)):
        stack = [(root, 0)]
        while stack and time.monotonic() < deadline and visited < MAX_DIRS:
            folder, depth = stack.pop()
            visited += 1
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            names = {e.name for e in entries}
            for e in entries:
                p = Path(e.path)
                if e.is_file(follow_symlinks=False) and e.name.lower().endswith(".zip") and parse_version(e.name):
                    v = parse_version(e.name)
                    if v and v < now_v and not in_source_tree(p):
                        found[p] = Old(p, "zip", v, modified=_mtime(p), note="downloaded zip")
            if EXE_NAME in names:
                p = folder.resolve()
                v = parse_version(p.name) or parse_version(p.parent.name) or exe_version(p / EXE_NAME)
                keep = (p != cur and not _inside(p, cur) and not _inside(cur, p) and not in_source_tree(p) and v and v < now_v)
                if keep:
                    target = p
                    par = p.parent
                    try:
                        only_child = len(list(par.iterdir())) == 1
                    except OSError:
                        only_child = False
                    if only_child and parse_version(par.name) and par not in set(roots or []) and not _inside(cur, par):
                        target = par                       # RerunLite-1.1.1/RerunLite/ : take the wrapper folder with it
                    found[target] = Old(target, "folder", v, has_data=has_user_data(p), modified=_mtime(p / EXE_NAME),
                                        note=describe(p) if has_user_data(p) else "")
                continue                                   # do not look inside an install
            if depth < MAX_DEPTH:
                for e in entries:
                    if e.is_dir(follow_symlinks=False) and e.name.lower() not in SKIP_DIRS and not e.name.startswith("."):
                        stack.append((Path(e.path), depth + 1))
    out = list(found.values())
    for o in out:
        o.size = tree_size(o.target)
    return sorted(out, key=lambda o: (o.version or (), o.modified), reverse=True)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def safe_to_remove(o: Old, current: str | Path) -> str:
    """'' when `o` may be removed, otherwise the reason it may not (checked again right before removing)."""
    cur = Path(current).resolve()
    try:
        p = o.target.resolve()
    except OSError:
        return "cannot read it"
    if not p.exists():
        return "already gone"
    if p == cur or _inside(p, cur) or _inside(cur, p):
        return "it is the copy that is running"
    if p == Path(p.anchor) or p == Path.home() or p.parent == p:
        return "not a ReRun LITE copy"
    if in_source_tree(p):
        return "part of a source checkout"
    if o.kind == "zip":
        return "" if p.is_file() and parse_version(p.name) else "not a ReRun LITE zip"
    if not p.is_dir():
        return "not a folder"
    has_exe = (p / EXE_NAME).is_file() or any((c / EXE_NAME).is_file() for c in _children(p))
    return "" if has_exe else "no RerunLite.exe inside, so it may not be a copy of the app"


def _children(p: Path):
    try:
        return [c for c in p.iterdir() if c.is_dir()]
    except OSError:
        return []


# ---------------------------------------------------------------- Recycle Bin
class _FileOp(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p)]


def recycle(paths: list[Path]) -> str:
    """Move files or folders to the Recycle Bin. '' on success, otherwise a sentence saying what went wrong."""
    if not paths:
        return ""
    if sys.platform != "win32":
        return "the Recycle Bin is only available on Windows"
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = _FileOp()
    op.wFunc = FO_DELETE
    op.pFrom = "\0".join(str(p) for p in paths) + "\0\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    try:
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except (OSError, AttributeError) as e:
        return str(e)
    if code or op.fAnyOperationsAborted:
        return f"Windows could not move it (code {code}); it may be open in another program"
    left = [p for p in paths if p.exists()]
    return f"still there: {left[0].name}" if left else ""


def remove(selected: list[Old], current: str | Path, remover=None) -> tuple[list[Old], list[tuple[Old, str]]]:
    """Move each one to the Recycle Bin. Returns (removed, [(not removed, why)])."""
    done, failed = [], []
    for o in selected:
        why = safe_to_remove(o, current)
        if not why:
            why = (remover or recycle)([o.target])
        (failed.append((o, why)) if why else done.append(o))
    return done, failed


# ---------------------------------------------------------------- the window
class OldVersionsDialog(tk.Toplevel):
    def __init__(self, app, found: list[Old], on_dismiss_all=None):
        super().__init__(app)
        self.app, self.found, self.on_dismiss_all = app, found, on_dismiss_all
        self.title(f"Older copies of {APP_NAME}")
        self.configure(bg=C["bg"])
        self.transient(app)
        self.vars = [tk.BooleanVar(value=not o.has_data) for o in found]
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=px(24), pady=px(20))
        tk.Label(wrap, text="Older versions found", bg=C["bg"], fg=C["label"], font=F["large"], anchor="w").pack(fill="x")
        total = sum(o.size for o in found)
        tk.Label(wrap, bg=C["bg"], fg=C["secondary"], font=F["footnote"], justify="left", anchor="w", wraplength=px(560),
                 text=f"You are running version {__version__}. These older copies and downloads take {human_size(total)}. "
                      "Ticked ones go to the Recycle Bin, so you can get them back from there. A copy that holds your own "
                      "data is left unticked: bring that data over first (it is offered when a new folder starts).").pack(
            fill="x", pady=(px(4), px(12)))
        card = ios.Card(wrap, pad=0, radius=ios_radius())
        card.pack(fill="both", expand=True)
        cv = tk.Canvas(card.body, bg=C["card"], highlightthickness=0, bd=0, height=min(px(84) * len(found), px(380)))
        sb = tk.Scrollbar(card.body, orient="vertical", command=cv.yview)
        inner = tk.Frame(cv, bg=C["card"])
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=inner, anchor="nw", width=px(540))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        if len(found) * px(84) > px(380):
            sb.pack(side="right", fill="y")
        self.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        for i, (o, var) in enumerate(zip(found, self.vars)):
            self._row(inner, o, var, divider=bool(i))
        self.summary = tk.Label(wrap, bg=C["bg"], fg=C["secondary"], font=F["footnote"], anchor="w")
        self.summary.pack(fill="x", pady=(px(10), 0))
        bar = tk.Frame(wrap, bg=C["bg"])
        bar.pack(fill="x", pady=(px(12), 0))
        self.go = ios.Button(bar, "", self.remove_selected, kind="filled", color="red")
        self.go.pack(side="right")
        ios.Button(bar, "Not now", self.destroy, kind="gray").pack(side="right", padx=(0, px(8)))
        ios.Button(bar, "Don't ask again", self.never, kind="plain").pack(side="left")
        for v in self.vars:
            v.trace_add("write", lambda *a: self._refresh())
        self._refresh()
        self.update_idletasks()
        w, h = max(self.winfo_reqwidth(), px(620)), self.winfo_reqheight()
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + max(px(40), (app.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(px(560), h)
        self.after(50, lambda: ios.style_window(self) if hasattr(ios, "style_window") else None)
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()

    def _row(self, parent, o: Old, var: tk.BooleanVar, divider: bool):
        if divider:
            tk.Frame(parent, height=1, bg=C["sep"]).pack(fill="x", padx=(px(12), 0))
        r = tk.Frame(parent, bg=C["card"])
        r.pack(fill="x")
        ios.Switch(r, var).pack(side="right", padx=px(12), pady=px(8))
        left = tk.Frame(r, bg=C["card"])
        left.pack(side="left", fill="x", expand=True, padx=(px(12), px(8)), pady=px(9))
        tk.Label(left, text=f"{o.label}", bg=C["card"], fg=C["label"], font=F["body"], anchor="w").pack(fill="x")
        kind = "zip" if o.kind == "zip" else "folder"
        sub = f"version {version_text(o.version)}  ·  {kind}  ·  {human_size(o.size)}  ·  {o.where}"
        tk.Label(left, text=sub, bg=C["card"], fg=C["secondary"], font=F["footnote"], anchor="w", justify="left",
                 wraplength=px(430)).pack(fill="x")
        if o.has_data:
            tk.Label(left, text="Holds your own data (settings, stats, History or key). " + o.note, bg=C["card"], fg=C["orange"],
                     font=F["footnote"], anchor="w", justify="left", wraplength=px(430)).pack(fill="x")

    def chosen(self) -> list[Old]:
        return [o for o, v in zip(self.found, self.vars) if v.get()]

    def _refresh(self):
        picked = self.chosen()
        size = sum(o.size for o in picked)
        self.go.set_text(f"Move {len(picked)} to Recycle Bin" if picked else "Nothing ticked")
        self.go.set_enabled(bool(picked))
        data = sum(1 for o in picked if o.has_data)
        self.summary.configure(
            text=(f"{len(picked)} ticked, {human_size(size)}." if picked else "Tick the ones to remove.")
                 + (f"  {data} of them hold data that exists only there." if data else ""),
            fg=C["orange"] if data else C["secondary"])

    def remove_selected(self):
        picked = self.chosen()
        if not picked:
            return
        data = sum(1 for o in picked if o.has_data)
        msg = (f"Move {len(picked)} older {'copy' if len(picked) == 1 else 'copies'} ({human_size(sum(o.size for o in picked))}) "
               "to the Recycle Bin? You can restore them from there.")
        if data:
            msg += f"\n\n{data} of them hold your own data (settings, stats, History or key) that is kept nowhere else."
        if not ios.confirm(self, msg, title="Remove older versions", ok="Move to Recycle Bin", destructive=True, default_cancel=True):
            return
        done, failed = remove(picked, self.app.m.root)
        self.destroy()
        text = f"Moved {len(done)} to the Recycle Bin ({human_size(sum(o.size for o in done))})" if done else "Nothing was removed"
        if failed:
            text += f"; {len(failed)} could not be moved: {failed[0][0].label} ({failed[0][1]})"
        self.app.flash(text, "warn" if failed else "ok")

    def never(self):
        if self.on_dismiss_all:
            self.on_dismiss_all([o.target for o in self.found])
        self.destroy()


def ios_radius() -> int:
    from . import theme
    return theme.tokens().radius


class OldVersionsMixin:
    """Settings > General > Window & files > 'Older versions', the command palette entry, and a quiet check at start."""

    def _ov_dismissed(self) -> set[str]:
        d = self._ui_state().get("old_versions_dismissed", [])
        return {str(x) for x in d} if isinstance(d, list) else set()

    def _ov_dismiss(self, paths: list[Path]):
        self._bg_save(old_versions_dismissed=sorted(self._ov_dismissed() | {str(p) for p in paths}))

    def _ov_scan(self, done):
        """Look in the background (a disk walk) and call done(found) on the window's thread."""
        def work():
            try:
                found = find_old(self.m.root)
            except Exception as e:  # noqa: BLE001 - a clean-up helper must never break the app
                errlog.note("lite.old_versions", e)
                found = []
            try:
                self.after(0, lambda: done(found))
            except (tk.TclError, RuntimeError):
                pass
        threading.Thread(target=work, daemon=True).start()

    def _ov_auto(self):
        """A short while after start: if there are older copies you have not said 'don't ask' about, ask."""
        if self._busy_any():
            return

        def done(found):
            fresh = [o for o in found if str(o.target) not in self._ov_dismissed()]
            if fresh and not self._busy_any():
                OldVersionsDialog(self, found, on_dismiss_all=self._ov_dismiss)
        self._ov_scan(done)

    def show_old_versions(self):
        """On request: look now and show everything found (or say there is nothing)."""
        self.flash("Looking for older versions…", "info")

        def done(found):
            if not found:
                self.flash(f"No older copies of {APP_NAME} found.", "ok")
            else:
                OldVersionsDialog(self, found, on_dismiss_all=self._ov_dismiss)
        self._ov_scan(done)
