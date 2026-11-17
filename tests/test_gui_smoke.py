import subprocess, sys
from pathlib import Path


def test_pages_build_against_stand_in_widgets():
    runner = Path(__file__).with_name("_gui_smoke_runner.py")
    r = subprocess.run([sys.executable, str(runner)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "SMOKE OK" in r.stdout, r.stdout[-1500:] + r.stderr[-2500:]
