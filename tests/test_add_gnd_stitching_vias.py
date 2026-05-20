"""Tests for the add_gnd_stitching_vias MCP tool.

Uses mocked pcbnew objects so the suite runs under both the conftest
stub and a real pcbnew install. The math/orchestration is what we want
to lock in — the actual KiCad SWIG calls are wafer-thin wrappers.

Approach ported from morningfire-pcb-automation
(https://github.com/NiNjA-CodE/morningfire-pcb-automation,
scripts/ground/add_gnd_vias.py). These tests pin the placement
contract: all-layer collision check, in-zones membership filtering,
clump prevention, geometry validation.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

# Need pcbnew imported (real or stubbed) before RoutingCommands.
import pcbnew  # noqa: F401, E402

from commands.routing import RoutingCommands, _point_to_segment_distance_nm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers — build a fake board with controllable obstacles.
# ---------------------------------------------------------------------------


def _mm(v):
    return int(round(v * 1_000_000))


def _bbox(left_mm, top_mm, right_mm, bottom_mm):
    bb = MagicMock()
    bb.GetLeft.return_value = _mm(left_mm)
    bb.GetTop.return_value = _mm(top_mm)
    bb.GetRight.return_value = _mm(right_mm)
    bb.GetBottom.return_value = _mm(bottom_mm)
    bb.GetWidth.return_value = _mm(right_mm - left_mm)
    bb.GetHeight.return_value = _mm(bottom_mm - top_mm)
    return bb


def _vector(x_mm, y_mm):
    v = MagicMock()
    v.x = _mm(x_mm)
    v.y = _mm(y_mm)
    return v


def _track(net_code, x1, y1, x2, y2, width_mm=0.2):
    """A segment-style track on the given net."""
    t = MagicMock()
    t.GetNetCode.return_value = net_code
    t.GetStart.return_value = _vector(x1, y1)
    t.GetEnd.return_value = _vector(x2, y2)
    t.GetWidth.return_value = _mm(width_mm)
    t.GetClass.return_value = "PCB_TRACK"  # routing code checks via GetClass()
    return t


def _via(net_code, x, y, size_mm=0.8, drill_mm=0.4):
    """A through-hole via on the given net."""
    v = MagicMock()
    v.GetNetCode.return_value = net_code
    v.GetPosition.return_value = _vector(x, y)
    v.GetWidth.return_value = _mm(size_mm)
    v.GetDrill.return_value = _mm(drill_mm)
    v.GetClass.return_value = "PCB_VIA"  # routing code checks via GetClass()
    return v


def _pad(net_code, x, y, size_x_mm=1.0, size_y_mm=1.0):
    p = MagicMock()
    p.GetNetCode.return_value = net_code
    p.GetPosition.return_value = _vector(x, y)
    sz = MagicMock()
    sz.x = _mm(size_x_mm)
    sz.y = _mm(size_y_mm)
    p.GetSize.return_value = sz
    return p


def _footprint(ref, x_mm, y_mm, pads=()):
    fp = MagicMock()
    fp.GetReference.return_value = ref
    fp.GetPosition.return_value = _vector(x_mm, y_mm)
    fp.Pads.return_value = list(pads)
    return fp


def _net(code, name):
    n = MagicMock()
    n.GetNetCode.return_value = code
    n.GetNetname.return_value = name
    return n


def _board(
    *, width_mm=60.0, height_mm=40.0, gnd_code=1, gnd_name="GND",
    tracks=(), pads=(), footprints=(), other_vias=(), zones=(),
    extra_nets=None,
):
    """Build a fake pcbnew BOARD with the supplied obstacles."""
    board = MagicMock()

    nets_by_name = MagicMock()
    name_lookup = {gnd_name: _net(gnd_code, gnd_name)}
    if extra_nets:
        for code, name in extra_nets.items():
            name_lookup[name] = _net(code, name)
    nets_by_name.has_key.side_effect = lambda k: k in name_lookup  # noqa: W601
    nets_by_name.__getitem__.side_effect = lambda k: name_lookup[k]

    netinfo = MagicMock()
    netinfo.NetsByName.return_value = nets_by_name
    board.GetNetInfo.return_value = netinfo

    board.GetBoardEdgesBoundingBox.return_value = _bbox(0, 0, width_mm, height_mm)
    board.GetTracks.return_value = list(tracks) + list(other_vias)
    board.GetFootprints.return_value = list(footprints)
    board.Zones.return_value = list(zones)

    # Layer IDs (just need stable numbers)
    layer_map = {"F.Cu": 0, "B.Cu": 31}
    board.GetLayerID.side_effect = lambda n: layer_map.get(n, -1)

    return board


def _cmd(board):
    cc = RoutingCommands.__new__(RoutingCommands)
    cc.board = board
    return cc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_grid_strategy_fills_empty_board():
    board = _board(width_mm=20, height_mm=20)
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["grid"],
        "spacing": 5.0,
        "edgeMargin": 0.5,
        "dryRun": True,
    })
    assert out["success"], out
    placed = out["placed"]
    # Grid from 0.5 to 19.5 stepping 5 -> {0.5, 5.5, 10.5, 15.5} -> 4*4 = 16
    assert len(placed) == 16
    assert out["summary"]["placed_count"] == 16
    # All placements inside the edge bounds
    for p in placed:
        assert 0.5 <= p["x"] <= 19.5 and 0.5 <= p["y"] <= 19.5


@pytest.mark.unit
def test_collision_blocks_via_near_signal_track():
    # Signal track on B.Cu (net code 2) crossing the middle of the board.
    track = _track(net_code=2, x1=0, y1=10, x2=20, y2=10, width_mm=0.5)
    board = _board(width_mm=20, height_mm=20, tracks=[track])
    no_collision = _cmd(_board(width_mm=20, height_mm=20)).add_gnd_stitching_vias({
        "strategies": ["grid"], "spacing": 5.0, "edgeMargin": 0.5,
        "dryRun": True,
    })
    with_collision = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["grid"], "spacing": 5.0, "edgeMargin": 0.5,
        "dryRun": True,
    })
    assert len(with_collision["placed"]) < len(no_collision["placed"]), (
        "track at y=10 must block at least one grid point"
    )
    # Specifically the row at y=10.5 should be blocked (the only one within
    # the track's collision distance for a 5mm grid).
    for p in with_collision["placed"]:
        # via radius 0.3 + track half-width 0.25 + clearance 0.2 = 0.75mm
        # the track is at y=10, so any via with |y - 10| < 0.75 should be blocked
        assert abs(p["y"] - 10) >= 0.749, (
            f"via at y={p['y']} should have been blocked by track at y=10"
        )


@pytest.mark.unit
def test_gnd_net_obstacles_are_ignored():
    """Vias and tracks already on GND should NOT block new stitching vias."""
    gnd_track = _track(net_code=1, x1=0, y1=10, x2=20, y2=10, width_mm=2.0)
    board_gnd_only = _board(width_mm=20, height_mm=20, tracks=[gnd_track])
    out = _cmd(board_gnd_only).add_gnd_stitching_vias({
        "strategies": ["grid"], "spacing": 5.0, "edgeMargin": 0.5,
        "dryRun": True,
    })
    # No non-GND obstacles → identical to empty-board layout (16 vias)
    assert len(out["placed"]) == 16


@pytest.mark.unit
def test_around_refs_densifies_near_footprint():
    fp = _footprint("U1", 10.0, 10.0)
    board = _board(width_mm=30, height_mm=30, footprints=[fp])
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["around_refs"],
        "densifyRefs": ["U1"],
        "densifyRadius": 2,
        "spacing": 2.0,
        "edgeMargin": 0.5,
        "dryRun": True,
    })
    assert out["success"]
    # 5x5 candidate field around U1 = 25 vias if all clear
    assert out["summary"]["placed_count"] == 25
    # All placements should be within 2*2.0mm of U1's centre
    for p in out["placed"]:
        assert abs(p["x"] - 10.0) <= 4.0 + 0.001
        assert abs(p["y"] - 10.0) <= 4.0 + 0.001


@pytest.mark.unit
def test_in_zones_filter_rejects_candidates_outside_zone(monkeypatch):
    """When in_zones strategy is selected, only candidates inside a GND
    zone's HitTestFilledArea are placed."""
    # Patch pcbnew.VECTOR2I to return a real SimpleNamespace so the
    # zone's HitTestFilledArea side_effect can read pt.x as an int.
    monkeypatch.setattr(
        pcbnew, "VECTOR2I",
        lambda x, y: SimpleNamespace(x=x, y=y),
    )

    # Build a zone whose HitTestFilledArea reports True only for the LEFT
    # half of the board (x < 10mm).
    zone = MagicMock()
    zone.GetNetCode.return_value = 1
    zone.GetLayer.return_value = 0
    def _hit(layer, pt, tol):
        return pt.x < _mm(10)
    zone.HitTestFilledArea.side_effect = _hit
    # Defensive fallback: also give the zone a bbox in case the API
    # variant gets used instead.
    zone.GetBoundingBox.return_value = _bbox(0, 0, 10, 20)

    board = _board(width_mm=20, height_mm=20, zones=[zone])
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["in_zones"],
        "spacing": 5.0,
        "edgeMargin": 0.5,
        "dryRun": True,
    })
    assert out["success"], out
    # Only candidates with x < 10mm should be placed → {0.5, 5.5} -> 2 columns × 4 rows = 8
    assert all(p["x"] < 10 for p in out["placed"])
    assert out["summary"]["placed_count"] == 8
    assert out["summary"]["skipped_by_zone_membership"] > 0


@pytest.mark.unit
def test_dry_run_does_not_modify_board():
    board = _board(width_mm=20, height_mm=20)
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["grid"], "spacing": 5.0, "dryRun": True,
    })
    assert out["success"]
    assert out["summary"]["dry_run"] is True
    # No vias added: board.Add not called
    board.Add.assert_not_called()


@pytest.mark.unit
def test_actual_run_writes_vias_to_board():
    board = _board(width_mm=20, height_mm=20)
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["grid"], "spacing": 5.0, "dryRun": False,
    })
    assert out["success"]
    # Should have called board.Add once per placed via
    assert board.Add.call_count == out["summary"]["placed_count"]


@pytest.mark.unit
def test_max_vias_caps_total_placements():
    board = _board(width_mm=40, height_mm=40)
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["grid"], "spacing": 5.0, "edgeMargin": 0.5,
        "maxVias": 5, "dryRun": True,
    })
    assert out["summary"]["placed_count"] == 5


@pytest.mark.unit
def test_intra_call_clump_prevention():
    """Two passes' worth of candidates near each other should NOT clump."""
    fp1 = _footprint("U1", 10.0, 10.0)
    fp2 = _footprint("U2", 10.5, 10.0)  # very close to U1
    board = _board(width_mm=30, height_mm=30, footprints=[fp1, fp2])
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["around_refs"],
        "densifyRefs": ["U1", "U2"],
        "densifyRadius": 1,
        "spacing": 0.5,  # ridiculously tight: forces self-collision
        "viaSize": 0.6,
        "clearance": 0.2,
        "edgeMargin": 0.5,
        "dryRun": True,
    })
    placed = out["placed"]
    # Each pair must respect viaSize + clearance separation
    min_centre = 0.6 + 0.2  # 0.8mm
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            dx = placed[i]["x"] - placed[j]["x"]
            dy = placed[i]["y"] - placed[j]["y"]
            d = (dx * dx + dy * dy) ** 0.5
            assert d >= min_centre - 1e-3, (
                f"vias clumped: ({placed[i]['x']},{placed[i]['y']}) and "
                f"({placed[j]['x']},{placed[j]['y']}) distance={d:.3f}mm"
            )


@pytest.mark.unit
def test_invalid_via_geometry_rejected():
    board = _board()
    out = _cmd(board).add_gnd_stitching_vias({
        "viaSize": 0.4,
        "viaDrill": 0.4,  # equal to size — invalid
    })
    assert out["success"] is False
    assert "Invalid via geometry" in out["message"]


@pytest.mark.unit
def test_unknown_strategy_rejected():
    board = _board()
    out = _cmd(board).add_gnd_stitching_vias({
        "strategies": ["random_walk"],
    })
    assert out["success"] is False
    assert "Unknown strategy" in out["message"]


@pytest.mark.unit
def test_missing_gnd_net_returns_clear_error():
    board = _board(gnd_name="NOT_GND", gnd_code=1)
    # The build above creates a single net called NOT_GND, no GND.
    # auto-detect should fail.
    out = _cmd(board).add_gnd_stitching_vias({})
    assert out["success"] is False
    assert "No GND net detected" in out["message"]


@pytest.mark.unit
def test_no_board_returns_clear_error():
    cc = RoutingCommands.__new__(RoutingCommands)
    cc.board = None
    out = cc.add_gnd_stitching_vias({})
    assert out["success"] is False
    assert "No board" in out["message"]


@pytest.mark.unit
def test_named_gnd_net_used_when_specified():
    board = _board(
        gnd_name="VSS", gnd_code=7,
        extra_nets={1: "GND"},  # also has a GND net
    )
    out = _cmd(board).add_gnd_stitching_vias({
        "gndNet": "VSS", "strategies": ["grid"], "spacing": 10,
        "edgeMargin": 5, "dryRun": True,
    })
    assert out["success"]
    assert out["summary"]["gnd_net"] == "VSS"


# ---------------------------------------------------------------------------
# Direct tests for the geometry helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_point_to_segment_distance_endpoint():
    # Point exactly at one endpoint -> distance 0
    d = _point_to_segment_distance_nm(0, 0, 0, 0, 100, 0)
    assert d == 0


@pytest.mark.unit
def test_point_to_segment_distance_perpendicular():
    # Point above the midpoint of a horizontal segment
    d = _point_to_segment_distance_nm(50, 100, 0, 0, 100, 0)
    assert d == pytest.approx(100)


@pytest.mark.unit
def test_point_to_segment_distance_beyond_endpoint():
    # Point well past one endpoint -> distance to that endpoint
    d = _point_to_segment_distance_nm(200, 0, 0, 0, 100, 0)
    assert d == pytest.approx(100)


@pytest.mark.unit
def test_point_to_segment_distance_zero_length_segment():
    # Degenerate segment (start == end) -> distance to that point
    d = _point_to_segment_distance_nm(3, 4, 0, 0, 0, 0)
    assert d == pytest.approx(5)
