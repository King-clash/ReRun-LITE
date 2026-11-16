import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rerun_lite import hotkeys as h, notifyprefs as n


def test_parse_ok():
    assert h.parse("f12") == ("f12", "<f12>")           # the same string the old code built from "f12"
    assert h.parse("Ctrl + Alt + S") == ("ctrl+alt+s", "<ctrl>+<alt>+s")
    assert h.parse("") == ("", "")
    assert h.parse("shift+ctrl+home")[1] == "<ctrl>+<shift>+<home>"


@pytest.mark.parametrize("bad", ["a", "5", "ctrl", "ctrl+", "foo+s", "ctrl+ctrl+s", "ctrl+banana", "alt+shift"])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        h.parse(bad)


def test_clash_and_mapping():
    assert h.clashes({"a": "f12", "b": "F12"}) and not h.clashes({"a": "f12", "b": "f11", "c": ""})
    m = h.mapping({"stop_all": "f12", "pause_all": "bad!", "compact": ""}, {"stop_all": 1, "pause_all": 2, "compact": 3})
    assert m == {"<f12>": 1}


def test_notify_prefs():
    assert n.load(None) == n.DEFAULTS and n.load({"enabled": "yes"})["enabled"] is False
    p = n.load({"enabled": True})
    assert n.decide(p, "failed", window_visible=False) and not n.decide(p, "failed", window_visible=True)
    assert not n.decide(p, "finished", False)                     # off by default
    assert not n.decide(n.load({}), "failed", False)              # master switch off
    p["only_hidden"] = False
    assert n.decide(p, "failed", True)


def test_throttle():
    t = n.Throttle(60)
    assert t.allow("failed", "A", 0) and not t.allow("failed", "A", 30) and t.allow("failed", "B", 30) and t.allow("failed", "A", 61)
