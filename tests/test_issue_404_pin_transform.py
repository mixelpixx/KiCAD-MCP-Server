"""Regression tests for #404: pin geometry in the schematic linting helpers,
and add_schematic_wire admitting when an endpoint snapped to nothing.

The report claimed get_schematic_pin_locations had the y sign wrong. It does
not: KiCad library symbols are drawn y-up and sheets are y-down, so a
rotation-0 instance at (x, y) puts a library pin (px, py) at (x + px, y - py).
That transform (WireDragger.pin_world_xy) is verified against kicad-cli
netlists in tests/test_pin_world_xy_eeschema_truth.py; the demo-file survey
in the issue thread confirms it at every rotation.

Two helpers in schematic_analysis.py did have the bug the report described,
and more. ``_compute_pin_positions_direct`` (behind find_wires_crossing_symbols
and get_elements_in_region) never flipped y and rotated the other way, so it
was wrong at every rotation; ``_transform_local_point`` (symbol body boxes)
rotated the other way and mirrored before rotating, wrong at 90 and 270.
Both now delegate to pin_world_xy.

The expected coordinates below are the netlist-verified placement formulas,
written out by hand rather than derived from the code under test:

    rot 0:   (x + px, y - py)
    rot 90:  (x - py, y - px)
    rot 180: (x - px, y + py)
    rot 270: (x + py, y + px)
    (mirror y) negates the x offset after rotation; (mirror x) the y offset.
"""

import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import sexpdata
from sexpdata import Symbol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_analysis import (  # noqa: E402
    _compute_pin_positions_direct,
    _transform_local_point,
    get_elements_in_region,
)

pytestmark = pytest.mark.unit

TEMPLATE = Path(__file__).resolve().parent.parent / "python" / "templates" / "empty.kicad_sch"

PX, PY = 2.54, 5.08  # asymmetric offsets so every rotation and mirror is distinguishable
SX, SY = 100.0, 50.0


def _expected(rotation: int, mirror_x: bool, mirror_y: bool) -> tuple:
    dx, dy = {0: (PX, -PY), 90: (-PY, -PX), 180: (-PX, PY), 270: (PY, PX)}[rotation]
    if mirror_y:
        dx = -dx
    if mirror_x:
        dy = -dy
    return (SX + dx, SY + dy)


CASES = [
    (rotation, mirror_x, mirror_y)
    for rotation in (0, 90, 180, 270)
    for mirror_x, mirror_y in ((False, False), (True, False), (False, True))
]


@pytest.mark.parametrize("rotation,mirror_x,mirror_y", CASES)
def test_compute_pin_positions_direct_matches_eeschema(rotation, mirror_x, mirror_y):
    sym = {"x": SX, "y": SY, "rotation": rotation, "mirror_x": mirror_x, "mirror_y": mirror_y}
    positions = _compute_pin_positions_direct(sym, {"1": {"x": PX, "y": PY}})
    assert positions["1"] == pytest.approx(_expected(rotation, mirror_x, mirror_y))


@pytest.mark.parametrize("rotation,mirror_x,mirror_y", CASES)
def test_transform_local_point_matches_eeschema(rotation, mirror_x, mirror_y):
    point = _transform_local_point(PX, PY, SX, SY, rotation, mirror_x, mirror_y)
    assert point == pytest.approx(_expected(rotation, mirror_x, mirror_y))


def test_reporters_example_from_issue_404():
    # LM2596 VIN pin at library offset (-12.7, +2.54), symbol at (100, 100),
    # rotation 0: the tool answered (87.3, 97.46) and the report expected
    # (87.3, 102.54). The tool was right; the helpers now agree with it.
    sym = {"x": 100.0, "y": 100.0, "rotation": 0, "mirror_x": False, "mirror_y": False}
    positions = _compute_pin_positions_direct(sym, {"VIN": {"x": -12.7, "y": 2.54}})
    assert positions["VIN"] == pytest.approx((87.3, 97.46))


# ---------------------------------------------------------------------------
# End to end through a real schematic file
# ---------------------------------------------------------------------------


def _symbol_sexp(lib_id: str, ref: str, x: float, y: float, rotation: int) -> str:
    return f"""
  (symbol (lib_id "{lib_id}") (at {x} {y} {rotation}) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{uuid.uuid4()}")
    (property "Reference" "{ref}" (at {x} {y} 0) (effects (font (size 1.27 1.27))))
    (property "Value" "{ref}" (at {x} {y} 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "~" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "{uuid.uuid4()}"))
    (pin "2" (uuid "{uuid.uuid4()}"))
    (instances (project "test" (path "/" (reference "{ref}") (unit 1))))
  )
"""


def _schematic_with(extra: str) -> Path:
    """Copy empty.kicad_sch (which carries Device:R and Device:LED in its
    lib_symbols) to a temp file and append ``extra`` before the final paren."""
    path = Path(tempfile.mkdtemp()) / "test.kicad_sch"
    shutil.copy(TEMPLATE, path)
    text = path.read_text(encoding="utf-8")
    idx = text.rfind(")")
    path.write_text(text[:idx] + "\n" + extra + "\n)", encoding="utf-8")
    return path


def test_get_elements_in_region_reports_true_pin_positions_for_a_rotated_led():
    # Device:LED: pin 1 (K) at library (-3.81, 0), pin 2 (A) at (3.81, 0).
    # Rotated 90 degrees at (100, 100), pin 1 is at (100, 103.81) and pin 2
    # at (100, 96.19). The old helper swapped them.
    path = _schematic_with(_symbol_sexp("Device:LED", "D1", 100.0, 100.0, 90))
    region = get_elements_in_region(path, 90.0, 90.0, 110.0, 110.0)
    (d1,) = [s for s in region["symbols"] if s["reference"] == "D1"]
    assert d1["pins"]["1"] == {"x": 100.0, "y": 103.81}
    assert d1["pins"]["2"] == {"x": 100.0, "y": 96.19}


# ---------------------------------------------------------------------------
# add_schematic_wire: say so when an endpoint snapped to nothing
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        return KiCADInterface.__new__(KiCADInterface)


def _wires(path: Path) -> list:
    data = sexpdata.loads(path.read_text(encoding="utf-8"))
    out = []
    for item in data:
        if isinstance(item, list) and item and item[0] == Symbol("wire"):
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == Symbol("pts"):
                    out.append([[float(pt[1]), float(pt[2])] for pt in sub[1:]])
    return out


class TestAddSchematicWireSnapReport:
    """R1 (Device:R) at (100, 100), rotation 0: pin 1 at (100, 96.19), pin 2
    at (100, 103.81)."""

    def setup_method(self) -> None:
        self.path = _schematic_with(_symbol_sexp("Device:R", "R1", 100.0, 100.0, 0))
        self.iface = _make_iface()

    def test_endpoint_outside_tolerance_is_reported_not_silently_left_floating(self):
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.path),
                # start is 3 mm above pin 1; end is 0.31 mm from pin 2
                "waypoints": [[100.0, 93.19], [100.3, 103.9]],
            }
        )
        assert result["success"] is True

        start = result["endpoints"]["start"]
        assert start["snapped"] is False
        assert start["position"] == [100.0, 93.19]
        assert start["nearestPin"] == {"reference": "R1", "pin": "1", "position": [100.0, 96.19]}
        assert start["nearestPinDistance"] == pytest.approx(3.0)

        end = result["endpoints"]["end"]
        assert end["snapped"] is True
        assert end["position"] == [100.0, 103.81]
        assert end["nearestPin"]["pin"] == "2"

        (warning,) = result["warnings"]
        assert "start point [100.0, 93.19]" in warning
        assert "R1/1" in warning
        assert "snapTolerance" in warning
        assert warning in result["message"]

        # The file got exactly what the response describes.
        assert _wires(self.path) == [[[100.0, 93.19], [100.0, 103.81]]]

    def test_both_endpoints_snapped_carries_no_warning(self):
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.path),
                "waypoints": [[100.2, 96.0], [110.0, 96.0], [110.0, 104.0], [100.1, 103.7]],
            }
        )
        assert result["success"] is True
        assert "warnings" not in result
        assert result["endpoints"]["start"]["snapped"] is True
        assert result["endpoints"]["end"]["snapped"] is True
        assert result["endpoints"]["start"]["position"] == [100.0, 96.19]
        assert result["endpoints"]["end"]["position"] == [100.0, 103.81]
        # Intermediate waypoints are never snapped.
        assert _wires(self.path) == [
            [[100.0, 96.19], [110.0, 96.0]],
            [[110.0, 96.0], [110.0, 104.0]],
            [[110.0, 104.0], [100.0, 103.81]],
        ]

    def test_snapping_off_reports_positions_without_a_pin_search(self):
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.path),
                "waypoints": [[100.0, 93.19], [100.3, 103.9]],
                "snapToPins": False,
            }
        )
        assert result["success"] is True
        assert "warnings" not in result
        assert result["endpoints"] == {
            "start": {"position": [100.0, 93.19], "snapped": False},
            "end": {"position": [100.3, 103.9], "snapped": False},
        }
        assert _wires(self.path) == [[[100.0, 93.19], [100.3, 103.9]]]

    def test_schematic_without_pins_warns_for_both_endpoints(self):
        path = _schematic_with("")
        result = self.iface._handle_add_schematic_wire(
            {"schematicPath": str(path), "waypoints": [[10.0, 10.0], [20.0, 10.0]]}
        )
        assert result["success"] is True
        assert len(result["warnings"]) == 2
        assert all("no symbol pins" in w for w in result["warnings"])
        assert result["endpoints"]["start"]["snapped"] is False
        assert "nearestPin" not in result["endpoints"]["start"]
