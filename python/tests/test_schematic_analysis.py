"""
Tests for schematic analysis tools (Tools 2–5).

Unit tests use mock data / synthetic S-expressions.
Integration tests parse real .kicad_sch files via sexpdata.
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sexpdata
from sexpdata import Symbol

# Ensure the python/ package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands.schematic_analysis import (
    _parse_wires,
    _parse_labels,
    _parse_symbols,
    _parse_no_connects,
    _load_sexp,
    _line_segment_intersects_aabb,
    _point_in_rect,
    _distance,
    compute_symbol_bbox,
    find_unconnected_pins,
    find_overlapping_elements,
    get_elements_in_region,
    check_wire_collisions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "empty.kicad_sch"


def _make_temp_schematic(extra_sexp: str = "") -> Path:
    """Copy empty.kicad_sch to a temp file and optionally append S-expression content."""
    tmp = Path(tempfile.mkdtemp()) / "test.kicad_sch"
    shutil.copy(TEMPLATE_PATH, tmp)
    if extra_sexp:
        content = tmp.read_text(encoding="utf-8")
        # Insert before the final closing paren
        idx = content.rfind(")")
        content = content[:idx] + "\n" + extra_sexp + "\n)"
        tmp.write_text(content, encoding="utf-8")
    return tmp


import uuid as _uuid


def _make_resistor_sexp(ref: str, x: float, y: float, rotation: float = 0) -> str:
    """Generate a proper Device:R symbol S-expression that skip can parse."""
    u = str(_uuid.uuid4())
    return f"""
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
    (pin "1" (uuid "{_uuid.uuid4()}"))
    (pin "2" (uuid "{_uuid.uuid4()}"))
    (instances
      (project "test"
        (path "/" (reference "{ref}") (unit 1))
      )
    )
  )
"""


def _make_led_sexp(ref: str, x: float, y: float, rotation: float = 0) -> str:
    """Generate a proper Device:LED symbol S-expression (horizontal pin spread)."""
    u = str(_uuid.uuid4())
    return f"""
  (symbol (lib_id "Device:LED") (at {x} {y} {rotation}) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{u}")
    (property "Reference" "{ref}" (at {x} {y - 2.54} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "LED" (at {x} {y + 2.54} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (pin "1" (uuid "{_uuid.uuid4()}"))
    (pin "2" (uuid "{_uuid.uuid4()}"))
    (instances
      (project "test"
        (path "/" (reference "{ref}") (unit 1))
      )
    )
  )
"""


# ===================================================================
# Unit tests — geometry helpers
# ===================================================================

class TestGeometryHelpers:
    """Test low-level geometry utilities."""

    def test_point_in_rect_inside(self):
        assert _point_in_rect(5, 5, 0, 0, 10, 10) is True

    def test_point_in_rect_outside(self):
        assert _point_in_rect(15, 5, 0, 0, 10, 10) is False

    def test_point_in_rect_boundary(self):
        assert _point_in_rect(0, 0, 0, 0, 10, 10) is True

    def test_distance_zero(self):
        assert _distance((0, 0), (0, 0)) == 0

    def test_distance_unit(self):
        assert abs(_distance((0, 0), (3, 4)) - 5.0) < 1e-9

    def test_aabb_intersection_crossing(self):
        # Line from (0,5) to (10,5) should intersect box (2,2)-(8,8)
        assert _line_segment_intersects_aabb(0, 5, 10, 5, 2, 2, 8, 8) is True

    def test_aabb_intersection_miss(self):
        # Line from (0,0) to (10,0) should miss box (2,2)-(8,8)
        assert _line_segment_intersects_aabb(0, 0, 10, 0, 2, 2, 8, 8) is False

    def test_aabb_intersection_inside(self):
        # Line entirely inside the box
        assert _line_segment_intersects_aabb(3, 3, 7, 7, 2, 2, 8, 8) is True

    def test_aabb_intersection_diagonal(self):
        # Diagonal line crossing through box
        assert _line_segment_intersects_aabb(0, 0, 10, 10, 2, 2, 8, 8) is True

    def test_aabb_intersection_parallel_outside(self):
        # Horizontal line above the box
        assert _line_segment_intersects_aabb(0, 9, 10, 9, 2, 2, 8, 8) is False

    def test_aabb_intersection_touching_edge(self):
        # Line ending exactly at box edge
        assert _line_segment_intersects_aabb(0, 2, 2, 2, 2, 2, 8, 8) is True


# ===================================================================
# Unit tests — S-expression parsers
# ===================================================================

class TestSexpParsers:
    """Test S-expression parsing functions with synthetic data."""

    def test_parse_wires_basic(self):
        sexp = sexpdata.loads("""(kicad_sch
            (wire (pts (xy 10 20) (xy 30 40))
                (stroke (width 0) (type default))
                (uuid "abc"))
        )""")
        wires = _parse_wires(sexp)
        assert len(wires) == 1
        assert wires[0]["start"] == (10.0, 20.0)
        assert wires[0]["end"] == (30.0, 40.0)

    def test_parse_wires_empty(self):
        sexp = sexpdata.loads("(kicad_sch)")
        assert _parse_wires(sexp) == []

    def test_parse_labels_both_types(self):
        sexp = sexpdata.loads("""(kicad_sch
            (label "VCC" (at 10 20 0))
            (global_label "GND" (at 30 40 0))
        )""")
        labels = _parse_labels(sexp)
        assert len(labels) == 2
        assert labels[0]["name"] == "VCC"
        assert labels[0]["type"] == "label"
        assert labels[1]["name"] == "GND"
        assert labels[1]["type"] == "global_label"

    def test_parse_symbols(self):
        sexp = sexpdata.loads("""(kicad_sch
            (symbol (lib_id "Device:R") (at 100 100 0)
                (property "Reference" "R1" (at 0 0 0)))
            (symbol (lib_id "power:VCC") (at 50 50 0)
                (property "Reference" "#PWR01" (at 0 0 0)))
        )""")
        symbols = _parse_symbols(sexp)
        assert len(symbols) == 2
        assert symbols[0]["reference"] == "R1"
        assert symbols[0]["is_power"] is False
        assert symbols[1]["reference"] == "#PWR01"
        assert symbols[1]["is_power"] is True

    def test_parse_no_connects(self):
        sexp = sexpdata.loads("""(kicad_sch
            (no_connect (at 10 20) (uuid "x"))
            (no_connect (at 30 40) (uuid "y"))
        )""")
        nc = _parse_no_connects(sexp)
        assert (10.0, 20.0) in nc
        assert (30.0, 40.0) in nc
        assert len(nc) == 2


# ===================================================================
# Unit tests — analysis functions with mocked PinLocator
# ===================================================================

class TestFindOverlappingElements:
    """Test overlapping detection logic."""

    def test_no_overlaps_in_empty_schematic(self):
        tmp = _make_temp_schematic()
        result = find_overlapping_elements(tmp, tolerance=0.5)
        assert result["totalOverlaps"] == 0

    def test_overlapping_symbols_detected(self):
        # Two symbols at nearly the same position
        extra = """
        (symbol (lib_id "Device:R") (at 100 100 0)
            (property "Reference" "R1" (at 0 0 0))
            (property "Value" "10k" (at 0 0 0)))
        (symbol (lib_id "Device:R") (at 100.1 100 0)
            (property "Reference" "R2" (at 0 0 0))
            (property "Value" "10k" (at 0 0 0)))
        """
        tmp = _make_temp_schematic(extra)
        result = find_overlapping_elements(tmp, tolerance=0.5)
        assert result["totalOverlaps"] >= 1
        assert len(result["overlappingSymbols"]) >= 1

    def test_well_separated_symbols_not_flagged(self):
        extra = """
        (symbol (lib_id "Device:R") (at 100 100 0)
            (property "Reference" "R1" (at 0 0 0))
            (property "Value" "10k" (at 0 0 0)))
        (symbol (lib_id "Device:R") (at 200 200 0)
            (property "Reference" "R2" (at 0 0 0))
            (property "Value" "10k" (at 0 0 0)))
        """
        tmp = _make_temp_schematic(extra)
        result = find_overlapping_elements(tmp, tolerance=0.5)
        assert result["totalOverlaps"] == 0

    def test_collinear_wire_overlap(self):
        extra = """
        (wire (pts (xy 10 50) (xy 30 50))
            (stroke (width 0) (type default))
            (uuid "w1"))
        (wire (pts (xy 20 50) (xy 40 50))
            (stroke (width 0) (type default))
            (uuid "w2"))
        """
        tmp = _make_temp_schematic(extra)
        result = find_overlapping_elements(tmp, tolerance=0.5)
        assert len(result["overlappingWires"]) >= 1


class TestGetElementsInRegion:
    """Test region query logic."""

    def test_elements_inside_region_found(self):
        extra = """
        (symbol (lib_id "Device:R") (at 50 50 0)
            (property "Reference" "R1" (at 0 0 0))
            (property "Value" "10k" (at 0 0 0)))
        (wire (pts (xy 45 50) (xy 55 50))
            (stroke (width 0) (type default))
            (uuid "w1"))
        (label "NET1" (at 50 50 0))
        """
        tmp = _make_temp_schematic(extra)
        result = get_elements_in_region(tmp, 40, 40, 60, 60)
        assert result["counts"]["symbols"] >= 1
        assert result["counts"]["wires"] >= 1
        assert result["counts"]["labels"] >= 1

    def test_elements_outside_region_excluded(self):
        extra = """
        (symbol (lib_id "Device:R") (at 200 200 0)
            (property "Reference" "R1" (at 0 0 0))
            (property "Value" "10k" (at 0 0 0)))
        """
        tmp = _make_temp_schematic(extra)
        result = get_elements_in_region(tmp, 0, 0, 50, 50)
        assert result["counts"]["symbols"] == 0


class TestComputeSymbolBbox:
    """Test bounding box computation."""

    def test_returns_none_for_unknown_symbol(self):
        tmp = _make_temp_schematic()
        from commands.pin_locator import PinLocator
        locator = PinLocator()
        result = compute_symbol_bbox(tmp, "NONEXISTENT", locator)
        assert result is None


# ===================================================================
# Integration tests — full schematic parsing
# ===================================================================

@pytest.mark.integration
class TestIntegrationFindUnconnectedPins:
    """Integration test using real schematic files."""

    def test_component_with_no_wires_has_unconnected_pins(self):
        """A resistor placed with no wires should have 2 unconnected pins."""
        extra = _make_resistor_sexp("R1", 100, 100)
        tmp = _make_temp_schematic(extra)
        result = find_unconnected_pins(tmp)
        r1_pins = [p for p in result if p["reference"] == "R1"]
        assert len(r1_pins) == 2

    def test_pin_with_wire_is_connected(self):
        """A wire endpoint exactly at a pin position should mark it connected."""
        # R1 at (100,100), rotation 0 → pin 1 at (100, 103.81), pin 2 at (100, 96.19)
        extra = _make_resistor_sexp("R1", 100, 100) + """
        (wire (pts (xy 100 103.81) (xy 100 120))
            (stroke (width 0) (type default))
            (uuid "w1"))
        """
        tmp = _make_temp_schematic(extra)
        result = find_unconnected_pins(tmp)
        r1_pins = [p for p in result if p["reference"] == "R1"]
        # Pin 1 should be connected (wire at 100, 103.81), pin 2 still unconnected
        assert len(r1_pins) == 1
        assert r1_pins[0]["pinNumber"] == "2"

    def test_no_connect_suppresses_pin(self):
        """A no_connect at a pin position should not report it as unconnected."""
        extra = _make_resistor_sexp("R1", 100, 100) + """
        (no_connect (at 100 96.19) (uuid "nc1"))
        (no_connect (at 100 103.81) (uuid "nc2"))
        """
        tmp = _make_temp_schematic(extra)
        result = find_unconnected_pins(tmp)
        r1_pins = [p for p in result if p["reference"] == "R1"]
        assert len(r1_pins) == 0


@pytest.mark.integration
class TestIntegrationCheckWireCollisions:
    """Integration test for wire collision detection."""

    def test_wire_not_touching_pins_is_collision(self):
        """A wire passing through a component bbox without pin contact → collision."""
        # LED D1 at (100,100) → pin 1 at (96.19, 100), pin 2 at (103.81, 100)
        # Vertical wire from (100, 95) to (100, 105) crosses through the body
        # without touching either horizontal pin
        extra = _make_led_sexp("D1", 100, 100) + """
        (wire (pts (xy 100 95) (xy 100 105))
            (stroke (width 0) (type default))
            (uuid "w1"))
        """
        tmp = _make_temp_schematic(extra)
        result = check_wire_collisions(tmp)
        d1_collisions = [c for c in result if c["component"]["reference"] == "D1"]
        assert len(d1_collisions) >= 1

    def test_unannotated_duplicates_not_over_reported(self):
        """
        Regression: two components with the same unannotated reference ("R?") at
        different positions should each produce independent bounding boxes.
        A wire crossing only one of them must produce exactly 1 collision, not 2.

        Before the fix, PinLocator.get_all_symbol_pins always resolved "R?" to
        the first match, so both symbols got identical bboxes and the same wire
        was counted against both.
        """
        # R? at (100, 100): Device:R pins are at (100, 96.19) and (100, 103.81).
        # Effective bbox (after expansion + margin) ≈ x=[99,101], y=[96.69,103.31].
        # R? at (200, 100): identical type but far away → no intersection with wire.
        r_at_100 = _make_resistor_sexp("R?", 100, 100)
        r_at_200 = _make_resistor_sexp("R?", 200, 100)
        # Horizontal wire crossing the body of the first R? only
        wire = """
        (wire (pts (xy 95 100) (xy 105 100))
            (stroke (width 0) (type default))
            (uuid "w-collision"))
        """
        tmp = _make_temp_schematic(r_at_100 + r_at_200 + wire)
        result = check_wire_collisions(tmp)
        # The wire must not be reported against the far-away R? at (200, 100)
        collisions_at_200 = [
            c for c in result
            if abs(c["component"]["position"]["x"] - 200) < 0.5
        ]
        assert len(collisions_at_200) == 0, (
            "Wire at x≈100 must not be flagged against the R? at x=200; "
            "likely caused by reference-lookup always returning the first 'R?'"
        )


@pytest.mark.integration
class TestIntegrationGetElementsInRegion:
    """Integration test for region query."""

    def test_region_returns_pin_data(self):
        """Symbols in region should include pin position data."""
        extra = _make_resistor_sexp("R1", 100, 100)
        tmp = _make_temp_schematic(extra)
        result = get_elements_in_region(tmp, 90, 90, 110, 110)
        assert result["counts"]["symbols"] == 1
        sym = result["symbols"][0]
        assert "pins" in sym
        assert len(sym["pins"]) == 2  # Resistor has 2 pins
