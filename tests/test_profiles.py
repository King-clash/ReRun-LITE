import json, sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataclasses import dataclass, field
from rerun_lite import profiles as P


@dataclass
class S:
    key: str; label: str; type: str; default: object; choices: list = field(default_factory=list)

SPEC = [S("loops", "Loops", "int", 0), S("on", "On", "bool", True), S("mode", "Mode", "choice", "a", ["a", "b"]),
        S("palace_name", "Palace", "text", "")]


def store():
    return P.ProfileStore(Path(tempfile.mkdtemp()) / "profiles.json", "1.2.0")


def test_validate_skips_bad_and_unknown():
    c, probs = P.validate({"loops": 5, "on": "yes", "mode": "z", "palace_name": "X", "gone": 1}, SPEC)
    assert c == {"loops": 5, "palace_name": "X"} and len(probs) == 3
    assert P.validate({"loops": True}, SPEC)[0] == {} and P.validate({"loops": 3.0}, SPEC)[0] == {"loops": 3}


def test_save_load_roundtrip_and_duplicates():
    s = store()
    s.save("Farm", {"loops": 3, "mode": "b"}, SPEC)
    assert P.ProfileStore(s.path).profiles["Farm"]["values"] == {"loops": 3, "mode": "b"}
    with pytest.raises(P.ProfileError):
        s.save("Farm", {}, SPEC)
    s.save("Farm", {"loops": 9}, SPEC, overwrite=True)
    assert s.profiles["Farm"]["values"] == {"loops": 9}
    s.rename("Farm", "Night")
    s.delete("Night")
    assert s.names() == [] and json.loads(s.path.read_text())["version"] == 1


def test_newer_or_damaged_file_is_never_overwritten():
    s = store()
    s.path.write_text(json.dumps({"version": 99, "profiles": {"X": {"values": {"loops": 1}}}}))
    t = P.ProfileStore(s.path)
    assert "X" in t.profiles and t.read_only
    with pytest.raises(P.ProfileError):
        t.save("Y", {}, SPEC)
    assert "99" in s.path.read_text()
    s.path.write_text("{not json")
    t = P.ProfileStore(s.path)
    with pytest.raises(P.ProfileError):
        t.save("Y", {}, SPEC)
    assert s.path.read_text() == "{not json"


def test_diff_and_import_export():
    s = store()
    assert P.diff({"loops": 1}, {"loops": 2, "on": True}, SPEC) == [("Loops", 1, 2)]
    s.save("A", {"loops": 4}, SPEC)
    text = s.export_text("A")
    name, probs = s.import_text(text, SPEC)
    assert name == "A (2)" and probs == [] and s.profiles["A"]["values"] == s.profiles["A (2)"]["values"]
    with pytest.raises(P.ProfileError):
        s.import_text("nope", SPEC)
    with pytest.raises(P.ProfileError):
        s.import_text(json.dumps({"version": 5, "values": {}}), SPEC)
    with pytest.raises(P.ProfileError):
        P.clean_name("   ")
