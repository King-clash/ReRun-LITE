"""Which template pictures ReRun LITE ships: the ones Crest, Login & Mail and Raid Tickets declare
(each script's own list plus the shared pop-up templates) - nothing for the scripts LITE does not have.
Used by build_lite.py (what goes next to RerunLite.exe) and tools/publish_lite_update.py (what a LITE
update holds), so both always agree."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from rerun.scripts import SCRIPTS

from . import LITE_SCRIPTS

META = "_meta.json"


def template_names() -> list[str]:
    """Every template name LITE's scripts can use, in a stable order."""
    seen, out = set(), []
    for sid in LITE_SCRIPTS:
        for t in SCRIPTS[sid].all_templates():
            if t.name not in seen:
                seen.add(t.name)
                out.append(t.name)
    return out


def lite_files(root: str | Path) -> dict[str, Path]:
    """'templates/<name>.png' -> file, for the LITE templates that exist under `root`."""
    folder = Path(root) / "templates"
    out = {}
    for name in sorted(template_names()):
        p = folder / f"{name}.png"
        if p.is_file():
            out[f"templates/{name}.png"] = p
    return out


def lite_meta(root: str | Path) -> dict:
    """The entries of templates/_meta.json (match thresholds and regions) for LITE's templates."""
    try:
        meta = json.loads((Path(root) / "templates" / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    names = {Path(rel).stem for rel in lite_files(root)}
    return {k: v for k, v in meta.items() if k in names}


def copy_to(root: str | Path, dst: str | Path) -> dict[str, Path]:
    """Copy LITE's templates and their _meta.json entries from `root` into `dst`/templates.
    Returns 'templates/<name>.png' -> the copy."""
    dst = Path(dst)
    (dst / "templates").mkdir(parents=True, exist_ok=True)
    out = {}
    for rel, src in lite_files(root).items():
        shutil.copy2(src, dst / rel)
        out[rel] = dst / rel
    meta = lite_meta(root)
    if meta:
        (dst / "templates" / META).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out


__all__ = ["template_names", "lite_files", "lite_meta", "copy_to"]
