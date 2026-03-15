"""
Tests for move_schematic_component with wire preservation (WireDragger).

Unit tests use synthetic sexpdata lists — no disk I/O, no KiCAD install needed.
Integration tests copy empty.kicad_sch to a tempdir and exercise the full handler.
"""

import sys
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sexpdata
from sexpdata import Symbol

# Make python/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands.wire_dragger import WireDragger, EPS, _rotate

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "empty.kicad_sch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sym(name: str) -> Symbol:
    return Symbol(name)


def _make_wire(x1, y1, x2, y2):
    return [
        _sym("wire"),
        [_sym("pts"), [_sym("xy"), x1, y1], [_sym("xy"), x2, y2]],
        [_sym("stroke"), [_sym("width"), 0], [_sym("type"), _sym("default")]],
        [_sym("uuid"), "00000000-0000-0000-0000-000000000000"],
    ]


def _make_junction(x, y):
    return [
        _sym("junction"),
        [_sym("at"), x, y],
        [_sym("diameter"), 0],
        [_sym("color"), 0, 0, 0, 0],
        [_sym("uuid"), "00000000-0000-0000-0000-000000000001"],
    ]


def _make_symbol(ref, x, y, rotation=0, lib_id="Device:R", mirror=None):
    """Build a minimal placed-symbol s-expression."""
    item = [
        _sym("symbol"),
        [_sym("lib_id"), lib_id],
        [_sym("at"), x, y, rotation],
        [_sym("unit"), 1],
        [_sym("property"), "Reference", ref,
         [_sym("at"), x + 2, y, 0]],
        [_sym("property"), "Value", "10k",
         [_sym("at"), x, y, 0]],
    ]
    if mirror:
        item.append([_sym("mirror"), _sym(mirror)])
    return item


def _make_lib_symbol_r():
    """Minimal Device:R lib_symbols entry — pins at (0, 3.81) and (0, -3.81)."""
    return [
        _sym("symbol"), "Device:R",
        [_sym("symbol"), "R_1_1",
            [_sym("pin"), _sym("passive"), _sym("line"),
             [_sym("at"), 0, 3.81, 270], [_sym("length"), 1.27],
             [_sym("name"), "~", [_sym("effects"), [_sym("font"), [_sym("size"), 1.27, 1.27]]]],
             [_sym("number"), "1", [_sym("effects"), [_sym("font"), [_sym("size"), 1.27, 1.27]]]]],
            [_sym("pin"), _sym("passive"), _sym("line"),
             [_sym("at"), 0, -3.81, 90], [_sym("length"), 1.27],
             [_sym("name"), "~", [_sym("effects"), [_sym("font"), [_sym("size"), 1.27, 1.27]]]],
             [_sym("number"), "2", [_sym("effects"), [_sym("font"), [_sym("size"), 1.27, 1.27]]]]],
        ],
    ]


def _make_sch_data(extra_items=None):
    """Build a minimal sch_data list with lib_symbols and sheet_instances."""
    data = [
        _sym("kicad_sch"),
        [_sym("lib_symbols"), _make_lib_symbol_r()],
        [_sym("sheet_instances"), [_sym("path"), "/", [_sym("page"), "1"]]],
    ]
    if extra_items:
        # Insert before sheet_instances (last item)
        for item in extra_items:
            data.insert(len(data) - 1, item)
    return data


# ---------------------------------------------------------------------------
# TestRotatePoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRotatePoint:
    def test_zero_rotation(self):
        assert _rotate(1.0, 2.0, 0) == (1.0, 2.0)

    def test_90_degrees(self):
        rx, ry = _rotate(1.0, 0.0, 90)
        assert abs(rx - 0.0) < 1e-9
        assert abs(ry - 1.0) < 1e-9

    def test_180_degrees(self):
        rx, ry = _rotate(1.0, 0.0, 180)
        assert abs(rx - (-1.0)) < 1e-9
        assert abs(ry - 0.0) < 1e-9

    def test_270_degrees(self):
        rx, ry = _rotate(0.0, 1.0, 270)
        assert abs(rx - 1.0) < 1e-6
        assert abs(ry - 0.0) < 1e-6


# ---------------------------------------------------------------------------
# TestFindSymbol
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFindSymbol:
    def test_returns_none_for_missing_reference(self):
        sch = _make_sch_data([_make_symbol("R1", 10, 20)])
        assert WireDragger.find_symbol(sch, "R99") is None

    def test_returns_item_and_position(self):
        sch = _make_sch_data([_make_symbol("R1", 10.5, 20.5, rotation=90)])
        result = WireDragger.find_symbol(sch, "R1")
        assert result is not None
        _, old_x, old_y, rotation, lib_id, mirror_x, mirror_y = result
        assert abs(old_x - 10.5) < EPS
        assert abs(old_y - 20.5) < EPS
        assert abs(rotation - 90) < EPS
        assert lib_id == "Device:R"
        assert mirror_x is False
        assert mirror_y is False

    def test_detects_mirror_x(self):
        sch = _make_sch_data([_make_symbol("R1", 0, 0, mirror="x")])
        result = WireDragger.find_symbol(sch, "R1")
        assert result is not None
        assert result[5] is True   # mirror_x
        assert result[6] is False  # mirror_y

    def test_detects_mirror_y(self):
        sch = _make_sch_data([_make_symbol("R1", 0, 0, mirror="y")])
        result = WireDragger.find_symbol(sch, "R1")
        assert result is not None
        assert result[5] is False  # mirror_x
        assert result[6] is True   # mirror_y


# ---------------------------------------------------------------------------
# TestComputePinPositions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestComputePinPositions:
    def test_resistor_at_origin_no_rotation(self):
        """Device:R at (0, 0) rot=0 — pins at (0, 3.81) and (0, -3.81)."""
        sch = _make_sch_data([_make_symbol("R1", 0, 0)])
        positions = WireDragger.compute_pin_positions(sch, "R1", 10, 20)
        assert "1" in positions and "2" in positions
        old1, new1 = positions["1"]
        old2, new2 = positions["2"]
        # Pin 1 old: (0 + 0, 0 + 3.81)
        assert abs(old1[0] - 0) < 1e-4
        assert abs(old1[1] - 3.81) < 1e-4
        # Pin 2 old: (0 + 0, 0 - 3.81)
        assert abs(old2[0] - 0) < 1e-4
        assert abs(old2[1] - (-3.81)) < 1e-4
        # New positions shifted by (10, 20)
        assert abs(new1[0] - 10) < 1e-4
        assert abs(new1[1] - 23.81) < 1e-4
        assert abs(new2[0] - 10) < 1e-4
        assert abs(new2[1] - 16.19) < 1e-4

    def test_resistor_rotated_90(self):
        """Device:R at (100, 100) rot=90 — pins should be at (100+3.81, 100) and (100-3.81, 100)."""
        sch = _make_sch_data([_make_symbol("R1", 100, 100, rotation=90)])
        positions = WireDragger.compute_pin_positions(sch, "R1", 100, 100)
        old1, _ = positions["1"]
        old2, _ = positions["2"]
        # rotate(0, 3.81, 90) = (0*cos90 - 3.81*sin90, 0*sin90 + 3.81*cos90) = (-3.81, 0)
        # Wait — pin 1 is at local (0, 3.81), rotated 90° CCW:
        # x' = 0*cos90 - 3.81*sin90 = -3.81, y' = 0*sin90 + 3.81*cos90 ≈ 0
        # world: (100 - 3.81, 100 + 0) = (96.19, 100)
        assert abs(old1[0] - 96.19) < 1e-3
        assert abs(old1[1] - 100) < 1e-3

    def test_returns_empty_for_missing_component(self):
        sch = _make_sch_data()
        result = WireDragger.compute_pin_positions(sch, "MISSING", 0, 0)
        assert result == {}

    def test_delta_is_consistent(self):
        """new_xy - old_xy should equal (new_x - old_x, new_y - old_y) for any rotation."""
        sch = _make_sch_data([_make_symbol("R1", 50, 50, rotation=45)])
        positions = WireDragger.compute_pin_positions(sch, "R1", 60, 70)
        for pin_num, (old_xy, new_xy) in positions.items():
            dx = new_xy[0] - old_xy[0]
            dy = new_xy[1] - old_xy[1]
            assert abs(dx - 10) < 1e-4, f"Pin {pin_num}: dx={dx}"
            assert abs(dy - 20) < 1e-4, f"Pin {pin_num}: dy={dy}"


# ---------------------------------------------------------------------------
# TestDragWires
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDragWires:
    def test_no_wires_returns_zero_counts(self):
        sch = _make_sch_data()
        result = WireDragger.drag_wires(sch, {(0.0, 0.0): (10.0, 10.0)})
        assert result["endpoints_moved"] == 0
        assert result["wires_removed"] == 0

    def test_wire_start_endpoint_moved(self):
        wire = _make_wire(0, 3.81, 0, 10)
        sch = _make_sch_data([wire])
        result = WireDragger.drag_wires(sch, {(0.0, 3.81): (10.0, 23.81)})
        assert result["endpoints_moved"] == 1
        assert result["wires_removed"] == 0
        # Find the updated wire in sch_data
        updated = next(i for i in sch if isinstance(i, list) and i and i[0] == Symbol("wire"))
        pts = next(s for s in updated[1:] if isinstance(s, list) and s and s[0] == Symbol("pts"))
        xy1 = pts[1]
        assert abs(xy1[1] - 10.0) < EPS
        assert abs(xy1[2] - 23.81) < EPS

    def test_wire_end_endpoint_moved(self):
        wire = _make_wire(0, 10, 0, -3.81)
        sch = _make_sch_data([wire])
        result = WireDragger.drag_wires(sch, {(0.0, -3.81): (10.0, 16.19)})
        assert result["endpoints_moved"] == 1
        updated = next(i for i in sch if isinstance(i, list) and i and i[0] == Symbol("wire"))
        pts = next(s for s in updated[1:] if isinstance(s, list) and s and s[0] == Symbol("pts"))
        xy2 = pts[2]
        assert abs(xy2[1] - 10.0) < EPS
        assert abs(xy2[2] - 16.19) < EPS

    def test_zero_length_wire_removed(self):
        """When both endpoints of a wire are moved to the same point, wire is deleted."""
        wire = _make_wire(0, 3.81, 0, -3.81)
        sch = _make_sch_data([wire])
        # Both pins land at same position (degenerate move)
        result = WireDragger.drag_wires(sch, {
            (0.0, 3.81): (5.0, 5.0),
            (0.0, -3.81): (5.0, 5.0),
        })
        assert result["wires_removed"] == 1
        wires_remaining = [i for i in sch if isinstance(i, list) and i and i[0] == Symbol("wire")]
        assert len(wires_remaining) == 0

    def test_unrelated_wire_not_touched(self):
        """A wire whose endpoints don't match any old pin is not changed."""
        wire = _make_wire(50, 50, 60, 50)
        sch = _make_sch_data([wire])
        original_start = (50.0, 50.0)
        result = WireDragger.drag_wires(sch, {(0.0, 3.81): (10.0, 23.81)})
        assert result["endpoints_moved"] == 0
        updated = next(i for i in sch if isinstance(i, list) and i and i[0] == Symbol("wire"))
        pts = next(s for s in updated[1:] if isinstance(s, list) and s and s[0] == Symbol("pts"))
        xy1 = pts[1]
        assert abs(xy1[1] - 50.0) < EPS
        assert abs(xy1[2] - 50.0) < EPS

    def test_both_endpoints_on_moved_component(self):
        """Wire connecting two pins of same component — both endpoints shift together."""
        wire = _make_wire(0, 3.81, 0, -3.81)
        sch = _make_sch_data([wire])
        result = WireDragger.drag_wires(sch, {
            (0.0, 3.81): (10.0, 23.81),
            (0.0, -3.81): (10.0, 16.19),
        })
        assert result["endpoints_moved"] == 2
        assert result["wires_removed"] == 0

    def test_junction_moved_with_endpoint(self):
        junction = _make_junction(0, 3.81)
        sch = _make_sch_data([junction])
        WireDragger.drag_wires(sch, {(0.0, 3.81): (10.0, 23.81)})
        updated_j = next(
            i for i in sch if isinstance(i, list) and i and i[0] == Symbol("junction")
        )
        at_sub = next(s for s in updated_j[1:] if isinstance(s, list) and s and s[0] == Symbol("at"))
        assert abs(at_sub[1] - 10.0) < EPS
        assert abs(at_sub[2] - 23.81) < EPS

    def test_junction_at_unrelated_position_not_touched(self):
        junction = _make_junction(99, 99)
        sch = _make_sch_data([junction])
        WireDragger.drag_wires(sch, {(0.0, 3.81): (10.0, 23.81)})
        updated_j = next(
            i for i in sch if isinstance(i, list) and i and i[0] == Symbol("junction")
        )
        at_sub = next(s for s in updated_j[1:] if isinstance(s, list) and s and s[0] == Symbol("at"))
        assert abs(at_sub[1] - 99.0) < EPS
        assert abs(at_sub[2] - 99.0) < EPS


# ---------------------------------------------------------------------------
# TestUpdateSymbolPosition
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUpdateSymbolPosition:
    def test_updates_position(self):
        sch = _make_sch_data([_make_symbol("R1", 10, 20)])
        result = WireDragger.update_symbol_position(sch, "R1", 30, 40)
        assert result is True
        found = WireDragger.find_symbol(sch, "R1")
        assert abs(found[1] - 30) < EPS
        assert abs(found[2] - 40) < EPS

    def test_returns_false_for_missing(self):
        sch = _make_sch_data()
        assert WireDragger.update_symbol_position(sch, "MISSING", 0, 0) is False

    def test_preserves_rotation(self):
        sch = _make_sch_data([_make_symbol("R1", 10, 20, rotation=90)])
        WireDragger.update_symbol_position(sch, "R1", 30, 40)
        found = WireDragger.find_symbol(sch, "R1")
        assert abs(found[3] - 90) < EPS  # rotation preserved


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMoveWithWirePreservation:
    """Integration tests using a real .kicad_sch file."""

    def _make_schematic(self, extra_sexp=""):
        """Copy empty.kicad_sch to a temp file and optionally append content."""
        tmp = Path(tempfile.mkdtemp()) / "test.kicad_sch"
        shutil.copy(TEMPLATE_PATH, tmp)
        if extra_sexp:
            content = tmp.read_text(encoding="utf-8")
            idx = content.rfind(")")
            content = content[:idx] + "\n" + extra_sexp + "\n)"
            tmp.write_text(content, encoding="utf-8")
        return tmp

    def _add_resistor(self, path: Path, ref: str, x: float, y: float, rotation: float = 0) -> Path:
        """Append a Device:R symbol to the schematic file."""
        import uuid
        u = str(uuid.uuid4())
        sexp = f"""
  (symbol (lib_id "Device:R") (at {x} {y} {rotation}) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{u}")
    (property "Reference" "{ref}" (at {x + 2.032} {y} 90)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at {x} {y} 90)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at {x - 1.778} {y} 90)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (pin "1" (uuid "{uuid.uuid4()}"))
    (pin "2" (uuid "{uuid.uuid4()}"))
    (instances (project "test" (path "/" (reference "{ref}") (unit 1))))
  )"""
        content = path.read_text(encoding="utf-8")
        idx = content.rfind(")")
        path.write_text(content[:idx] + "\n" + sexp + "\n)", encoding="utf-8")
        return path

    def _add_wire(self, path: Path, x1, y1, x2, y2) -> Path:
        """Append a wire to the schematic file."""
        import uuid
        wire_sexp = f"""
  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))
    (stroke (width 0) (type default))
    (uuid "{uuid.uuid4()}")
  )"""
        content = path.read_text(encoding="utf-8")
        idx = content.rfind(")")
        path.write_text(content[:idx] + "\n" + wire_sexp + "\n)", encoding="utf-8")
        return path

    def _parse_wires(self, path: Path):
        """Return list of ((x1,y1),(x2,y2)) for every wire in the file."""
        content = path.read_text(encoding="utf-8")
        data = sexpdata.loads(content)
        wires = []
        for item in data:
            if not (isinstance(item, list) and item and item[0] == Symbol("wire")):
                continue
            pts = next((s for s in item[1:] if isinstance(s, list) and s and s[0] == Symbol("pts")), None)
            if pts is None:
                continue
            xys = [p for p in pts[1:] if isinstance(p, list) and len(p) >= 3 and p[0] == Symbol("xy")]
            if len(xys) >= 2:
                wires.append(((float(xys[0][1]), float(xys[0][2])),
                               (float(xys[-1][1]), float(xys[-1][2]))))
        return wires

    def _get_symbol_pos(self, path: Path, ref: str):
        content = path.read_text(encoding="utf-8")
        data = sexpdata.loads(content)
        found = WireDragger.find_symbol(data, ref)
        if found is None:
            return None
        return found[1], found[2]

    def test_symbol_position_updated(self):
        sch = self._make_schematic()
        self._add_resistor(sch, "R1", 100, 100)
        # Call handler directly
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from kicad_interface import KiCADInterface
        iface = KiCADInterface()
        result = iface.handle_command("move_schematic_component", {
            "schematicPath": str(sch),
            "reference": "R1",
            "position": {"x": 120, "y": 130},
        })
        assert result["success"], result.get("message")
        pos = self._get_symbol_pos(sch, "R1")
        assert abs(pos[0] - 120) < EPS
        assert abs(pos[1] - 130) < EPS

    def test_connected_wire_endpoint_follows_pin(self):
        """Wire endpoint at pin 1 of R1 should move with the component."""
        sch = self._make_schematic()
        # R1 at (100, 100) — pin 1 at (100, 103.81)
        self._add_resistor(sch, "R1", 100, 100)
        self._add_wire(sch, 100, 103.81, 100, 120)  # wire from pin 1 upward

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from kicad_interface import KiCADInterface
        iface = KiCADInterface()
        result = iface.handle_command("move_schematic_component", {
            "schematicPath": str(sch),
            "reference": "R1",
            "position": {"x": 110, "y": 100},
        })
        assert result["success"], result.get("message")
        assert result["wiresMoved"] >= 1

        wires = self._parse_wires(sch)
        assert len(wires) == 1
        # Pin 1 new world position: (110 + 0, 100 + 3.81) = (110, 103.81)
        w = wires[0]
        endpoints = {w[0], w[1]}
        new_pin1 = (110.0, 103.81)
        assert any(abs(ep[0] - new_pin1[0]) < 0.01 and abs(ep[1] - new_pin1[1]) < 0.01
                   for ep in endpoints), f"Expected pin endpoint near {new_pin1}, got {endpoints}"

    def test_unrelated_wire_unchanged(self):
        """A wire not connected to R1 must not be modified."""
        sch = self._make_schematic()
        self._add_resistor(sch, "R1", 100, 100)
        self._add_wire(sch, 50, 50, 60, 50)  # unrelated wire

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from kicad_interface import KiCADInterface
        iface = KiCADInterface()
        iface.handle_command("move_schematic_component", {
            "schematicPath": str(sch),
            "reference": "R1",
            "position": {"x": 110, "y": 110},
        })

        wires = self._parse_wires(sch)
        unrelated = [(s, e) for s, e in wires
                     if abs(s[0] - 50) < 0.01 and abs(s[1] - 50) < 0.01]
        assert len(unrelated) == 1

    def test_no_zero_length_wires_after_move(self):
        """No zero-length wires should appear in the file after a move."""
        sch = self._make_schematic()
        self._add_resistor(sch, "R1", 100, 100)
        # Wire from pin 1 to pin 2 of same component (intra-component wire)
        self._add_wire(sch, 100, 103.81, 100, 96.19)

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from kicad_interface import KiCADInterface
        iface = KiCADInterface()
        iface.handle_command("move_schematic_component", {
            "schematicPath": str(sch),
            "reference": "R1",
            "position": {"x": 110, "y": 100},
        })

        wires = self._parse_wires(sch)
        for start, end in wires:
            assert not (abs(start[0] - end[0]) < EPS and abs(start[1] - end[1]) < EPS), \
                f"Zero-length wire found at {start}"

    def test_preserve_wires_false_skips_wire_update(self):
        """preserveWires=False should move the symbol but leave wires alone."""
        sch = self._make_schematic()
        self._add_resistor(sch, "R1", 100, 100)
        self._add_wire(sch, 100, 103.81, 100, 120)

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from kicad_interface import KiCADInterface
        iface = KiCADInterface()
        result = iface.handle_command("move_schematic_component", {
            "schematicPath": str(sch),
            "reference": "R1",
            "position": {"x": 110, "y": 100},
            "preserveWires": False,
        })
        assert result["success"]
        assert result["wiresMoved"] == 0

        # Wire should still start at old pin position
        wires = self._parse_wires(sch)
        assert len(wires) == 1
        endpoints = {wires[0][0], wires[0][1]}
        old_pin1 = (100.0, 103.81)
        assert any(abs(ep[0] - old_pin1[0]) < 0.01 and abs(ep[1] - old_pin1[1]) < 0.01
                   for ep in endpoints), f"Wire should still be at {old_pin1}, got {endpoints}"

    def test_missing_component_returns_error(self):
        sch = self._make_schematic()
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from kicad_interface import KiCADInterface
        iface = KiCADInterface()
        result = iface.handle_command("move_schematic_component", {
            "schematicPath": str(sch),
            "reference": "NOTHERE",
            "position": {"x": 0, "y": 0},
        })
        assert not result["success"]
        assert "not found" in result.get("message", "").lower()
