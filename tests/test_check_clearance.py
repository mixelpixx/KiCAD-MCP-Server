"""Tests for issue: check_clearance was registered as an MCP tool (full Zod
schema in design-rules.ts, listed in the router's "drc" category) but had no
entry in kicad_interface.py's command dispatch table — calling it always
returned {"success": false, "message": "Unknown command: check_clearance"}.

``DesignRuleCommands.check_clearance`` resolves each item to a board object
(by UUID, or by reference for components) and measures the gap between their
axis-aligned bounding boxes — the same AABB approximation
``check_courtyard_overlaps`` already uses for footprint-to-footprint checks.
These tests exercise the pure gap-distance geometry and the item-resolution
logic against a mocked board, without needing a live KiCad / SWIG board.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.design_rules import DesignRuleCommands  # noqa: E402

SCALE = 1_000_000  # mm to nm, matches DesignRuleCommands


def _box(left, top, right, bottom):
    box = MagicMock(name="BOX2I")
    box.GetLeft.return_value = left
    box.GetTop.return_value = top
    box.GetRight.return_value = right
    box.GetBottom.return_value = bottom
    return box


# --- _bbox_gap_nm: pure geometry --------------------------------------------


def test_bbox_gap_overlapping_boxes_is_zero():
    a = _box(0, 0, 10, 10)
    b = _box(5, 5, 15, 15)
    assert DesignRuleCommands._bbox_gap_nm(a, b) == 0


def test_bbox_gap_touching_boxes_is_zero():
    a = _box(0, 0, 10, 10)
    b = _box(10, 0, 20, 10)
    assert DesignRuleCommands._bbox_gap_nm(a, b) == 0


def test_bbox_gap_separated_on_x_axis():
    a = _box(0, 0, 10, 10)
    b = _box(13, 0, 20, 10)
    assert DesignRuleCommands._bbox_gap_nm(a, b) == 3


def test_bbox_gap_separated_on_y_axis():
    a = _box(0, 0, 10, 10)
    b = _box(0, 14, 10, 20)
    assert DesignRuleCommands._bbox_gap_nm(a, b) == 4


def test_bbox_gap_diagonal_separation_is_euclidean():
    a = _box(0, 0, 0, 0)
    b = _box(3, 4, 3, 4)  # dx=3, dy=4 -> hypot = 5
    assert DesignRuleCommands._bbox_gap_nm(a, b) == 5


def test_bbox_gap_is_symmetric():
    a = _box(0, 0, 10, 10)
    b = _box(13, 14, 20, 20)
    assert DesignRuleCommands._bbox_gap_nm(a, b) == DesignRuleCommands._bbox_gap_nm(b, a)


# --- _resolve_clearance_item -------------------------------------------------


def _fake_footprint(ref: str, uuid: str) -> MagicMock:
    fp = MagicMock(name=f"fp_{ref}")
    fp.GetReference.return_value = ref
    fp.m_Uuid.AsString.return_value = uuid
    return fp


def test_resolve_component_by_reference():
    board = MagicMock()
    fp = _fake_footprint("R1", "uuid-r1")
    board.FindFootprintByReference.side_effect = lambda ref: fp if ref == "R1" else None
    item, err = DesignRuleCommands(board)._resolve_clearance_item(
        {"type": "component", "reference": "R1"}
    )
    assert err is None
    assert item is fp


def test_resolve_component_not_found_by_reference():
    board = MagicMock()
    board.FindFootprintByReference.return_value = None
    item, err = DesignRuleCommands(board)._resolve_clearance_item(
        {"type": "component", "reference": "R99"}
    )
    assert item is None
    assert "R99" in err


def test_resolve_component_by_id():
    board = MagicMock()
    fp = _fake_footprint("R1", "uuid-r1")
    board.GetFootprints.return_value = [fp]
    item, err = DesignRuleCommands(board)._resolve_clearance_item(
        {"type": "component", "id": "uuid-r1"}
    )
    assert err is None
    assert item is fp


def test_resolve_component_requires_reference_or_id():
    item, err = DesignRuleCommands(MagicMock())._resolve_clearance_item({"type": "component"})
    assert item is None
    assert "reference" in err or "id" in err


def test_resolve_track_by_id():
    board = MagicMock()
    track = MagicMock(name="track1")
    track.m_Uuid.AsString.return_value = "uuid-track1"
    board.GetTracks.return_value = [track]
    item, err = DesignRuleCommands(board)._resolve_clearance_item(
        {"type": "track", "id": "uuid-track1"}
    )
    assert err is None
    assert item is track


def test_resolve_track_requires_id():
    item, err = DesignRuleCommands(MagicMock())._resolve_clearance_item({"type": "track"})
    assert item is None
    assert "id" in err


def test_resolve_via_not_found_by_id():
    board = MagicMock()
    board.GetTracks.return_value = []
    item, err = DesignRuleCommands(board)._resolve_clearance_item({"type": "via", "id": "missing"})
    assert item is None
    assert "missing" in err


def test_resolve_pad_by_id():
    board = MagicMock()
    pad = MagicMock(name="pad1")
    pad.m_Uuid.AsString.return_value = "uuid-pad1"
    fp = MagicMock()
    fp.Pads.return_value = [pad]
    board.GetFootprints.return_value = [fp]
    item, err = DesignRuleCommands(board)._resolve_clearance_item(
        {"type": "pad", "id": "uuid-pad1"}
    )
    assert err is None
    assert item is pad


def test_resolve_zone_by_id():
    board = MagicMock()
    zone = MagicMock(name="zone1")
    zone.m_Uuid.AsString.return_value = "uuid-zone1"
    board.Zones.return_value = [zone]
    item, err = DesignRuleCommands(board)._resolve_clearance_item(
        {"type": "zone", "id": "uuid-zone1"}
    )
    assert err is None
    assert item is zone


def test_resolve_unknown_type():
    item, err = DesignRuleCommands(MagicMock())._resolve_clearance_item({"type": "spaceship"})
    assert item is None
    assert "spaceship" in err


# --- check_clearance end-to-end (mocked board) ------------------------------


def _board_with_two_components(gap_nm: float, min_clearance_mm: float = 0.2) -> MagicMock:
    board = MagicMock()
    fp_a = _fake_footprint("R1", "uuid-r1")
    fp_a.GetBoundingBox.return_value = _box(0, 0, 10, 10)
    fp_b = _fake_footprint("R2", "uuid-r2")
    fp_b.GetBoundingBox.return_value = _box(10 + gap_nm, 0, 20 + gap_nm, 10)
    board.FindFootprintByReference.side_effect = {"R1": fp_a, "R2": fp_b}.get
    design_settings = MagicMock()
    design_settings.m_MinClearance = int(min_clearance_mm * SCALE)
    board.GetDesignSettings.return_value = design_settings
    return board


def test_check_clearance_reports_actual_and_required_and_meets():
    # 0.5mm gap, 0.2mm required -> meets requirement
    board = _board_with_two_components(gap_nm=int(0.5 * SCALE))
    result = DesignRuleCommands(board).check_clearance(
        {
            "item1": {"type": "component", "reference": "R1"},
            "item2": {"type": "component", "reference": "R2"},
        }
    )
    assert result["success"] is True
    assert abs(result["actualClearance"] - 0.5) < 1e-6
    assert abs(result["requiredClearance"] - 0.2) < 1e-6
    assert result["meetsRequirement"] is True
    assert result["unit"] == "mm"


def test_check_clearance_violation_does_not_meet_requirement():
    # 0.05mm gap, 0.2mm required -> violates
    board = _board_with_two_components(gap_nm=int(0.05 * SCALE), min_clearance_mm=0.2)
    result = DesignRuleCommands(board).check_clearance(
        {
            "item1": {"type": "component", "reference": "R1"},
            "item2": {"type": "component", "reference": "R2"},
        }
    )
    assert result["success"] is True
    assert result["meetsRequirement"] is False


def test_check_clearance_missing_items_returns_error():
    result = DesignRuleCommands(MagicMock()).check_clearance({"item1": {"type": "component"}})
    assert result["success"] is False


def test_check_clearance_unresolvable_item_returns_error():
    board = MagicMock()
    board.FindFootprintByReference.return_value = None
    result = DesignRuleCommands(board).check_clearance(
        {
            "item1": {"type": "component", "reference": "R404"},
            "item2": {"type": "component", "reference": "R1"},
        }
    )
    assert result["success"] is False
    assert "item1" in result["message"]


def test_check_clearance_no_board_loaded():
    result = DesignRuleCommands(None).check_clearance(
        {
            "item1": {"type": "component", "reference": "R1"},
            "item2": {"type": "component", "reference": "R2"},
        }
    )
    assert result["success"] is False
    assert "No board is loaded" in result["message"]
