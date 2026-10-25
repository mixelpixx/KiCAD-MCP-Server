"""Tests for the check_courtyard_overlaps MCP tool.

The test suite uses mocked footprint and board objects (matching the
pcbnew API surface the tool actually touches) so the tests run under
both the conftest pcbnew stub and a real pcbnew install.

Approach ported from morningfire-pcb-automation
(https://github.com/NiNjA-CodE/morningfire-pcb-automation,
scripts/placement/check_overlaps.py). The upstream uses a static AABB
lookup table; the version in this PR reads real courtyard polygons
from pcbnew. These tests cover the AABB-and-translation logic
deterministically without depending on real polygon geometry.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from commands.component import ComponentCommands  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers: build mock footprints/boards whose courtyard bboxes are exactly
# what we declare. We bypass the real pcbnew API by patching
# ComponentCommands._footprint_courtyard_bbox via the fp mock's identity.
# ---------------------------------------------------------------------------


def _mm_to_nm(v):
    return int(round(v * 1_000_000))


def _make_fp(ref, x_mm, y_mm, half_w_mm=2.0, half_h_mm=1.5, rotation_deg=0.0):
    """Mock footprint with predictable courtyard bbox.

    The mock returns a SHAPE_POLY_SET-like object whose BBox() reports
    a rectangle of (2*half_w_mm) by (2*half_h_mm) centred on (x_mm, y_mm)
    in nanometre units, matching the real pcbnew API contract.
    """
    fp = MagicMock(name=f"footprint_{ref}")
    fp.GetReference.return_value = ref

    pos = MagicMock()
    pos.x = _mm_to_nm(x_mm)
    pos.y = _mm_to_nm(y_mm)
    fp.GetPosition.return_value = pos

    fp.GetOrientationDegrees.return_value = rotation_deg

    ct = MagicMock()
    ct.OutlineCount.return_value = 1
    bbox = MagicMock()
    bbox.GetLeft.return_value = _mm_to_nm(x_mm - half_w_mm)
    bbox.GetTop.return_value = _mm_to_nm(y_mm - half_h_mm)
    bbox.GetRight.return_value = _mm_to_nm(x_mm + half_w_mm)
    bbox.GetBottom.return_value = _mm_to_nm(y_mm + half_h_mm)
    ct.BBox.return_value = bbox
    fp.GetCourtyard.return_value = ct

    fp_bbox = MagicMock()
    fp_bbox.GetLeft.return_value = _mm_to_nm(x_mm - half_w_mm)
    fp_bbox.GetTop.return_value = _mm_to_nm(y_mm - half_h_mm)
    fp_bbox.GetRight.return_value = _mm_to_nm(x_mm + half_w_mm)
    fp_bbox.GetBottom.return_value = _mm_to_nm(y_mm + half_h_mm)
    fp.GetBoundingBox.return_value = fp_bbox

    return fp


def _make_board(footprints, outline_mm=(0, 0, 50, 30)):
    board = MagicMock(name="board")
    board.GetFootprints.return_value = footprints

    edge_bb = MagicMock()
    edge_bb.GetLeft.return_value = _mm_to_nm(outline_mm[0])
    edge_bb.GetTop.return_value = _mm_to_nm(outline_mm[1])
    edge_bb.GetRight.return_value = _mm_to_nm(outline_mm[2])
    edge_bb.GetBottom.return_value = _mm_to_nm(outline_mm[3])
    board.GetBoardEdgesBoundingBox.return_value = edge_bb

    return board


def _cmd(board):
    cc = ComponentCommands.__new__(ComponentCommands)
    cc.board = board
    return cc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_overlaps_when_components_are_spaced():
    board = _make_board(
        [
            _make_fp("U1", 10, 10, 2, 1.5),
            _make_fp("U2", 25, 10, 2, 1.5),  # 15mm apart
        ]
    )
    out = _cmd(board).check_courtyard_overlaps({})
    assert out["success"], out
    assert out["overlaps"] == []
    assert out["boundary_violations"] == []
    assert out["summary"]["checked"] == 2


@pytest.mark.unit
def test_overlap_detected_when_courtyards_intersect():
    board = _make_board(
        [
            _make_fp("U1", 10, 10, 2, 1.5),  # x: 8..12
            _make_fp("U2", 11, 10, 2, 1.5),  # x: 9..13 -> overlap x=9..12 (3mm)
        ]
    )
    out = _cmd(board).check_courtyard_overlaps({})
    assert out["success"]
    assert len(out["overlaps"]) == 1
    o = out["overlaps"][0]
    assert {o["a"], o["b"]} == {"U1", "U2"}
    assert o["overlap_x_mm"] == pytest.approx(3.0)
    assert o["overlap_y_mm"] == pytest.approx(3.0)
    assert o["overlap_area_mm2"] == pytest.approx(9.0)


@pytest.mark.unit
def test_margin_pushes_borderline_pairs_into_overlap():
    # 4.1mm centre-to-centre, half-w 2 → gap is 0.1mm
    fps_clean = [_make_fp("U1", 10, 10, 2, 1.5), _make_fp("U2", 14.1, 10, 2, 1.5)]
    clean = _cmd(_make_board(fps_clean)).check_courtyard_overlaps({})
    assert clean["overlaps"] == []

    fps_margin = [_make_fp("U1", 10, 10, 2, 1.5), _make_fp("U2", 14.1, 10, 2, 1.5)]
    with_margin = _cmd(_make_board(fps_margin)).check_courtyard_overlaps({"margin": 0.5})
    assert len(with_margin["overlaps"]) == 1, "0.5mm margin should expose the 0.1mm gap as overlap"


@pytest.mark.unit
def test_refs_filter_restricts_to_subset():
    board = _make_board(
        [
            _make_fp("U1", 10, 10, 2, 1.5),
            _make_fp("U2", 11, 10, 2, 1.5),
            _make_fp("U3", 30, 20, 2, 1.5),
        ]
    )
    out = _cmd(board).check_courtyard_overlaps({"refs": ["U1", "U3"]})
    assert out["success"]
    assert out["summary"]["checked"] == 2
    assert out["overlaps"] == []


@pytest.mark.unit
def test_boundary_violation_flagged():
    board = _make_board(
        [_make_fp("U1", 19, 10, 2, 1.5)],  # courtyard right = 21mm
        outline_mm=(0, 0, 20, 20),  # board right = 20mm
    )
    out = _cmd(board).check_courtyard_overlaps({})
    assert len(out["boundary_violations"]) == 1
    v = out["boundary_violations"][0]
    assert v["ref"] == "U1"
    assert "right" in v["exceeds"]
    assert v["exceeds"]["right"] == pytest.approx(1.0)


@pytest.mark.unit
def test_include_boundary_false_suppresses_boundary_check():
    board = _make_board(
        [_make_fp("U1", 19, 10, 2, 1.5)],
        outline_mm=(0, 0, 20, 20),
    )
    out = _cmd(board).check_courtyard_overlaps({"include_boundary": False})
    assert out["boundary_violations"] == []


@pytest.mark.unit
def test_virtual_position_does_not_mutate_footprint():
    """The `positions` parameter must not modify the underlying footprint."""
    fp = _make_fp("U1", 10, 10, 2, 1.5)
    fp_other = _make_fp("U2", 25, 10, 2, 1.5)
    board = _make_board([fp, fp_other])

    out = _cmd(board).check_courtyard_overlaps(
        {
            "positions": {"U1": [25.0, 10.0]},  # virtually move U1 onto U2
        }
    )
    assert len(out["overlaps"]) == 1, "virtual placement must surface the overlap"

    # SetPosition must NEVER be called by this tool.
    fp.SetPosition.assert_not_called()
    fp_other.SetPosition.assert_not_called()


@pytest.mark.unit
def test_virtual_rotation_swaps_aabb_extents():
    """Rotating a tall-narrow footprint 90° should swap its x/y extents."""
    # half_w 1, half_h 5 → 2mm × 10mm courtyard.
    # At U1=(10,10), without rotation its right edge is at x=11.
    # Place U2 at x=14, half_w 0.5 → left edge x=13.5. No overlap.
    fp1 = _make_fp("U1", 10, 10, half_w_mm=1.0, half_h_mm=5.0)
    fp2 = _make_fp("U2", 14, 10, half_w_mm=0.5, half_h_mm=0.5)
    board = _make_board([fp1, fp2])

    clean = _cmd(board).check_courtyard_overlaps({})
    assert clean["overlaps"] == []

    # Rotating U1 90° makes its courtyard 10mm × 2mm → right edge x=15
    # → overlap with U2 (right edge at x=14.5).
    rotated = _cmd(board).check_courtyard_overlaps(
        {
            "positions": {"U1": [10.0, 10.0, 90.0]},
        }
    )
    assert (
        len(rotated["overlaps"]) == 1
    ), "90° rotation of 2x10mm footprint must expose overlap with U2"


@pytest.mark.unit
def test_no_board_loaded_returns_error_payload():
    out = ComponentCommands(board=None).check_courtyard_overlaps({})
    assert out["success"] is False
    assert "No board" in out["message"]


@pytest.mark.unit
def test_bad_position_spec_is_rejected_cleanly():
    board = _make_board([_make_fp("U1", 10, 10)])
    out = _cmd(board).check_courtyard_overlaps({"positions": {"U1": [10, 10, 0, 99]}})
    assert out["success"] is False
    assert "Bad position spec" in out["message"]


@pytest.mark.unit
def test_courtyard_fallback_to_bounding_box():
    """When no F/B.CrtYd polygon is present, fall back to GetBoundingBox()."""
    fp = _make_fp("U1", 10, 10, 2, 1.5)
    # Drop the courtyard
    empty_ct = MagicMock()
    empty_ct.OutlineCount.return_value = 0
    fp.GetCourtyard.return_value = empty_ct
    board = _make_board([fp, _make_fp("U2", 11, 10, 2, 1.5)])
    out = _cmd(board).check_courtyard_overlaps({})
    # The bbox is the same as the courtyard, so overlap is still detected via fallback.
    assert len(out["overlaps"]) == 1, "fallback to GetBoundingBox() must still detect overlap"


@pytest.mark.unit
def test_board_outline_override_replaces_edge_cuts_bbox():
    """Custom board outline takes precedence over Edge.Cuts bbox."""
    board = _make_board(
        [_make_fp("U1", 5, 5, 2, 1.5)],
        outline_mm=(0, 0, 100, 100),
    )
    out = _cmd(board).check_courtyard_overlaps(
        {
            "board_outline": {"x1": 0, "y1": 0, "x2": 5, "y2": 5, "unit": "mm"},
        }
    )
    # U1's right edge at x=7 violates the override (right edge x=5)
    assert len(out["boundary_violations"]) == 1
    assert out["boundary_violations"][0]["exceeds"]["right"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Courtyards with several disjoint outlines (#406)
# ---------------------------------------------------------------------------


def _mock_box(x1, y1, x2, y2):
    box = MagicMock()
    box.GetLeft.return_value = _mm_to_nm(x1)
    box.GetTop.return_value = _mm_to_nm(y1)
    box.GetRight.return_value = _mm_to_nm(x2)
    box.GetBottom.return_value = _mm_to_nm(y2)
    return box


def _make_multi_outline_fp(ref, x_mm, y_mm, outlines):
    """Mock footprint whose courtyard is several outlines.

    ``outlines`` holds (x1, y1, x2, y2) boxes relative to the footprint
    position. ``BBox()`` reports their union, as SHAPE_POLY_SET does, and
    ``Outline(i).BBox()`` reports outline i.
    """
    fp = _make_fp(ref, x_mm, y_mm)
    absolute = [(x_mm + a, y_mm + b, x_mm + c, y_mm + d) for a, b, c, d in outlines]
    ct = MagicMock()
    ct.OutlineCount.return_value = len(absolute)
    ct.BBox.return_value = _mock_box(
        min(o[0] for o in absolute),
        min(o[1] for o in absolute),
        max(o[2] for o in absolute),
        max(o[3] for o in absolute),
    )
    chains = []
    for o in absolute:
        chain = MagicMock()
        chain.BBox.return_value = _mock_box(*o)
        chains.append(chain)
    ct.Outline.side_effect = lambda i: chains[i]
    fp.GetCourtyard.return_value = ct
    return fp


# Two header rows 20 x 2 mm, 10 mm apart: the module's courtyard covers
# y = 0..2 and y = 10..12 (relative), leaving y = 2..10 free underneath.
_TWO_ROWS = [(0, 0, 20, 2), (0, 10, 20, 12)]


@pytest.mark.unit
def test_part_in_gap_between_courtyard_outlines_is_not_an_overlap():
    module = _make_multi_outline_fp("A1", 10, 10, _TWO_ROWS)
    probe = _make_fp("R1", 20, 16, 1.0, 0.5)  # y 15.5..16.5, inside the 12..20 gap
    out = _cmd(_make_board([module, probe])).check_courtyard_overlaps({})
    assert out["success"], out
    assert out["overlaps"] == [], "a part in the gap between outlines is not an overlap"


@pytest.mark.unit
def test_part_on_one_courtyard_outline_reports_that_outline():
    module = _make_multi_outline_fp("A1", 10, 10, _TWO_ROWS)
    probe = _make_fp("R1", 20, 12, 1.0, 1.0)  # y 11..13, x 19..21 -> crosses row 1 (y 10..12)
    out = _cmd(_make_board([module, probe])).check_courtyard_overlaps({})
    assert len(out["overlaps"]) == 1
    o = out["overlaps"][0]
    assert {o["a"], o["b"]} == {"A1", "R1"}
    assert o["overlap_x_mm"] == pytest.approx(2.0)
    assert o["overlap_y_mm"] == pytest.approx(1.0)
    assert o["bbox"] == {"x1": 19.0, "y1": 11.0, "x2": 21.0, "y2": 12.0, "unit": "mm"}


@pytest.mark.unit
def test_two_multi_outline_footprints_overlap_only_through_their_outlines():
    a = _make_multi_outline_fp("A1", 10, 10, _TWO_ROWS)
    # Same module shifted 5 mm down: its rows sit at y 15..17 and 25..27,
    # inside A1's gap and below A1. The combined boxes (y 10..22, 15..27)
    # intersect; no pair of outlines does.
    b = _make_multi_outline_fp("A2", 10, 15, _TWO_ROWS)
    out = _cmd(_make_board([a, b], outline_mm=(0, 0, 50, 50))).check_courtyard_overlaps({})
    assert out["overlaps"] == []


@pytest.mark.unit
def test_margin_applies_to_each_courtyard_outline():
    module = _make_multi_outline_fp("A1", 10, 10, _TWO_ROWS)
    probe = _make_fp("R1", 20, 16, 1.0, 0.5)  # 3.5 mm from row 0 (y 12) and row 1 (y 20)
    board = _make_board([module, probe])
    assert _cmd(board).check_courtyard_overlaps({"margin": 1.5})["overlaps"] == []
    out = _cmd(board).check_courtyard_overlaps({"margin": 2.0})
    assert len(out["overlaps"]) == 1, "4 mm of combined margin closes a 3.5 mm gap"


@pytest.mark.unit
def test_virtual_position_moves_every_courtyard_outline():
    module = _make_multi_outline_fp("A1", 10, 10, _TWO_ROWS)
    probe = _make_fp("R1", 20, 30, 1.0, 0.5)  # y 29.5..30.5, below the module
    board = _make_board([module, probe], outline_mm=(0, 0, 50, 50))
    assert _cmd(board).check_courtyard_overlaps({})["overlaps"] == []

    # Move A1 so its gap (relative y 2..10) lands on the probe: still clear.
    gap = _cmd(board).check_courtyard_overlaps({"positions": {"A1": [10.0, 24.0]}})
    assert gap["overlaps"] == []

    # Move A1 so its second row (relative y 10..12) lands on the probe.
    row = _cmd(board).check_courtyard_overlaps({"positions": {"A1": [10.0, 19.0]}})
    assert len(row["overlaps"]) == 1
    module.SetPosition.assert_not_called()


@pytest.mark.unit
def test_boundary_check_still_uses_the_combined_courtyard():
    module = _make_multi_outline_fp("A1", 10, 10, _TWO_ROWS)  # y 10..22
    out = _cmd(_make_board([module], outline_mm=(0, 0, 50, 21))).check_courtyard_overlaps({})
    assert len(out["boundary_violations"]) == 1
    assert out["boundary_violations"][0]["exceeds"] == {"bottom": pytest.approx(1.0)}
