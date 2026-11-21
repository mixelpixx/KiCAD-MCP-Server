"""#521: a delete_schematic_wire miss says why, and pin locations read like the file.

The delete matches one stored wire segment within 0.5 mm at both ends. The misses users
hit are a run KiCad split into several segments (at a junction or a T) and a point that is
not where the wire is stored. The reply now lists the segments at each point with their
stored coordinates, so the next call can use them.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from commands.schematic_handlers import SchematicHandlersMixin
from commands.wire_manager import WireManager

HEADER = '(kicad_sch (version 20250114) (generator "eeschema")\n  (lib_symbols)\n'
FOOTER = '  (sheet_instances (path "/" (page "1")))\n)\n'


def _wire(x1: float, y1: float, x2: float, y2: float, n: int) -> str:
    return (
        f"  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n"
        f"    (stroke (width 0) (type default))\n"
        f'    (uuid "00000000-0000-0000-0000-00000000000{n}"))\n'
    )


def _schematic(tmp_path: Path, wires: List[str]) -> Path:
    path = tmp_path / "wires.kicad_sch"
    path.write_bytes((HEADER + "".join(wires) + FOOTER).encode("utf-8"))
    return path


def _delete(path: Path, start: List[float], end: List[float]) -> Dict[str, Any]:
    return SchematicHandlersMixin._handle_delete_schematic_wire(
        SchematicHandlersMixin(),
        {
            "schematicPath": str(path),
            "start": {"x": start[0], "y": start[1]},
            "end": {"x": end[0], "y": end[1]},
        },
    )


def test_a_split_run_is_not_deleted_and_the_reply_lists_both_segments(tmp_path):
    path = _schematic(tmp_path, [_wire(0, 0, 10.16, 0, 1), _wire(10.16, 0, 20.32, 0, 2)])
    before = path.read_bytes()

    result = _delete(path, [0, 0], [20.32, 0])

    assert result["success"] is False
    assert path.read_bytes() == before
    assert result["wiresAtStart"] == [
        {"start": {"x": 0.0, "y": 0.0}, "end": {"x": 10.16, "y": 0.0}, "at": "start"}
    ]
    assert result["wiresAtEnd"] == [
        {"start": {"x": 10.16, "y": 0.0}, "end": {"x": 20.32, "y": 0.0}, "at": "end"}
    ]
    message = result["message"]
    assert "one wire segment" in message and "0.5 mm" in message
    assert "(0, 0) -> (10.16, 0)" in message
    assert "(10.16, 0) -> (20.32, 0)" in message


def test_each_segment_of_the_listed_run_then_deletes(tmp_path):
    path = _schematic(tmp_path, [_wire(0, 0, 10.16, 0, 1), _wire(10.16, 0, 20.32, 0, 2)])
    miss = _delete(path, [0, 0], [20.32, 0])

    for wire in miss["wiresAtStart"] + miss["wiresAtEnd"]:
        s, e = wire["start"], wire["end"]
        assert _delete(path, [s["x"], s["y"]], [e["x"], e["y"]])["success"] is True

    assert b"(wire" not in path.read_bytes()


def test_a_wire_passing_through_a_point_is_reported_as_middle(tmp_path):
    path = _schematic(tmp_path, [_wire(0, 0, 20.32, 0, 1)])

    result = _delete(path, [10.16, 0], [10.16, 10.16])

    assert result["success"] is False
    assert result["wiresAtStart"] == [
        {"start": {"x": 0.0, "y": 0.0}, "end": {"x": 20.32, "y": 0.0}, "at": "middle"}
    ]
    assert result["wiresAtEnd"] == []
    assert "(passes through)" in result["message"]
    assert "No wire touches end (10.16, 10.16)." in result["message"]


def test_float_noise_from_a_pin_location_still_deletes(tmp_path):
    # The report's case: the wire is stored at 439.42, the caller passes the float readout.
    path = _schematic(tmp_path, [_wire(439.42, 100.33, 449.58, 100.33, 1)])

    result = _delete(path, [439.41999999999996, 100.33], [449.58, 100.33])

    assert result == {"success": True}
    assert b"(wire" not in path.read_bytes()


def test_wires_touching_uses_the_same_per_axis_tolerance_as_delete(tmp_path):
    path = _schematic(tmp_path, [_wire(0, 0, 10, 0, 1)])

    # 0.4 mm off on both axes: inside delete's per-axis test, outside a 0.5 mm circle.
    near = WireManager.wires_touching(path, [0.4, 0.4])
    assert [w["at"] for w in near] == ["start"]
    assert WireManager.wires_touching(path, [0.6, 3]) == []


def test_pin_locations_are_rounded_to_the_schematic_resolution(monkeypatch, tmp_path):
    import commands.pin_locator as pin_locator

    class FakeLocator:
        def get_all_symbol_pins(self, *_args: Any) -> Dict[str, List[float]]:
            return {"1": [439.41999999999996, 100.33000000000001]}

    monkeypatch.setattr(pin_locator, "PinLocator", FakeLocator)

    result = SchematicHandlersMixin._handle_get_schematic_pin_locations(
        SimpleNamespace(), {"schematicPath": str(tmp_path / "x.kicad_sch"), "reference": "J1"}
    )

    assert result["success"] is True
    assert result["pins"]["1"] == {"x": 439.42, "y": 100.33}
