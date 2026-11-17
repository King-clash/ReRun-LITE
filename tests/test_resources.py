import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rerun_lite.resources import Sampler


def test_cpu_percent_from_deltas_and_warnings():
    t = [0.0]
    cpu = [0.0]
    s = Sampler((lambda: 2000.0, lambda: cpu[0], lambda: (95.0, 16.0)), clock=lambda: t[0])
    s.cores = 4
    s.sample()
    t[0], cpu[0] = 10.0, 5.0            # 5 CPU-seconds in 10 s on 4 cores = 12.5 %
    r = s.sample()
    assert r["app_cpu_pct"] == 12.5
    assert len(s.warnings()) == 2 and "n/a" not in s.text()


def test_failing_reader_gives_none_not_an_exception():
    def boom(): raise OSError("no")
    s = Sampler((boom, boom, boom), clock=lambda: 1.0)
    r = s.sample()
    assert r["app_mb"] is None and s.warnings() == [] and "n/a" in s.text()


def test_real_readers_run_here():
    r = Sampler().sample()
    assert "app_mb" in r
