"""One command to check everything before a release: lint, every test, and a build with its self-test.

    py tools/run_checks.py            # lint + all tests + a trial build (about 5 minutes)
    py tools/run_checks.py --quick    # lint + all tests only
    py tools/run_checks.py --build    # the trial build only

The trial build goes into a temporary folder that is deleted afterwards; nothing of yours is touched and nothing is
published. The tests open real windows for a few minutes: leave the keyboard and mouse alone while they run. They retry when Windows
briefly refuses to hand over one of Tk's own files and wait longer on a busy PC, so a failure here is worth believing; if one
window test fails anyway, run it alone first (py -m pytest tests/<file> -k <name>) before assuming a bug.
Prints a plain PASS or FAIL for each step and a verdict. Exit code 0 only when every step passed.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(label: str, cmd: list[str], ok_text: str | None = None, timeout: int = 1500) -> bool:
    print(f"\n=== {label}", flush=True)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"FAIL  {label}: no answer after {timeout} s")
        return False
    out = (p.stdout or "") + (p.stderr or "")
    good = p.returncode == 0 and (ok_text is None or ok_text in out)
    tail = "\n".join(out.strip().splitlines()[-12:])
    print(tail)
    print(f"{'PASS' if good else 'FAIL'}  {label}  ({time.time() - t0:.0f} s)", flush=True)
    return good


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="lint and tests only (no trial build)")
    ap.add_argument("--build", action="store_true", help="the trial build only")
    args = ap.parse_args(argv)
    py = sys.executable
    results: list[tuple[str, bool]] = []
    if not args.build:
        results.append(("lint (ruff)", run("lint (ruff)", [py, "-m", "ruff", "check", "."])))
        results.append(("tests (pytest)", run("tests (pytest)", [py, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"])))
    if not args.quick:
        out = Path(tempfile.mkdtemp(prefix="rlite_check_"))
        try:
            results.append(("trial build and self-test", run("trial build and self-test", [py, "build_lite.py", "--out", str(out)],
                                                             ok_text="Self-test passed")))
        finally:
            shutil.rmtree(out, ignore_errors=True)
    print("\n" + "-" * 50)
    for name, good in results:
        print(f"{'PASS' if good else 'FAIL'}  {name}")
    ok = all(g for _, g in results)
    print("\nEVERYTHING PASSED" if ok else "\nSOMETHING FAILED - see the step above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
