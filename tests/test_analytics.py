import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rerun_lite import analytics as a, charts


def S(start, runs=3, active=600, cycles=(100, 200), **kw):
    return {"start": start, "instance": "A", "runs": runs, "active_s": active, "cycles": list(cycles),
            "ended": "completed", "reason": "finished", **kw}


def test_range_and_totals():
    now = 1_800_000_000
    rows = [S(now - 86400 * 10), S(now - 3600, runs=5, cycles=(50,)), S(now - 100, instance="B")]
    assert len(a.in_range(rows, 7, now)) == 2 and len(a.in_range(rows, 0, now)) == 3
    assert len(a.in_range(rows, 0, now, instance="B")) == 1
    t = a.totals(a.in_range(rows, 7, now))
    assert t["runs"] == 8 and t["sessions"] == 2 and t["fastest_s"] == 50 and t["slowest_s"] == 200


def test_empty_totals_are_none_not_zero_guesses():
    t = a.totals([])
    assert t["avg_cycle_s"] is None and t["runs_per_hour"] is None


def test_per_day_fills_zero_days():
    now = time.time()
    per = a.per_day([S(now)], 7, now)
    assert len(per) == 7 and per[-1][1] == 3 and sum(n for _, n in per) == 3


def test_csv_has_header_and_rows():
    out = a.to_csv([S(1_800_000_000)])
    assert out.splitlines()[0].startswith("start,instance") and len(out.splitlines()) == 2


def test_chart_geometry():
    assert charts.nice_max(7) == 10 and charts.nice_max(43) == 50 and charts.nice_max(0) == 1
    g = charts.bar_geometry([1, 2, 4], 300, 150)
    assert len(g["bars"]) == 3 and g["bars"][2][1] < g["bars"][0][1]
    g = charts.line_geometry([5, 5, 5], 300, 150)
    assert len({round(y, 3) for _, y in g["points"]}) == 1
    assert charts.line_geometry([1], 300, 150)["points"]
