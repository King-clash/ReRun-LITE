"""tools/template_health.py: it reads real screenshots and the template pictures, reports what is found, fails an
--expect that is missing, and never writes into the template folder.   Run:  py tests/test_template_health.py"""
from __future__ import annotations

import hashlib
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import template_health  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def run(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = template_health.main(list(args))
    return code, buf.getvalue()


def folder_digest() -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / "templates").iterdir()):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def test_finds_the_palace_header_on_the_real_screen():
    code, out = run("--quiet", str(FIX / "crest_palace_list.png"), "--expect", "crest_palace_header")
    assert code == 0, out
    assert "EXPECTED crest_palace_header: found" in out


def test_expect_fails_when_the_screen_does_not_show_it():
    code, out = run("--quiet", str(FIX / "home.png"), "--expect", "crest_palace_header")
    assert code == 1 and "below" in out, out


def test_expect_fails_for_a_template_that_does_not_exist():
    code, out = run("--quiet", str(FIX / "home.png"), "--expect", "no_such_template")
    assert code == 1 and "no template named" in out, out


def test_unreadable_screenshot_is_skipped_not_fatal():
    code, out = run("--quiet", str(ROOT / "nope.png"), str(FIX / "home.png"))
    assert code == 0 and "skip: cannot read" in out, out


def test_nothing_to_check_is_an_error():
    code, out = run("--quiet", str(ROOT / "nope.png"))
    assert code == 1 and "No screenshots" in out


def test_it_never_changes_the_template_folder():
    before = folder_digest()
    run("--quiet", str(FIX / "home.png"), str(FIX / "crest_palace_list.png"))
    assert folder_digest() == before


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", t.__name__, repr(e))
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
