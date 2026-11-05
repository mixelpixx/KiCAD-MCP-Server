"""Unit tests for summarize_vias.

A stitched ground net is thousands of vias. The census has to answer with
counts: drill, layer span, and how many go through every copper layer.
"""

from types import SimpleNamespace

import pcbnew
import pytest
from commands.via_summary import ViaSummaryCommands

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def via_marker():
    """Pin the via type marker, then put the pcbnew stub back."""
    previous = pcbnew.PCB_VIA_T
    pcbnew.PCB_VIA_T = "VIA"
    yield
    pcbnew.PCB_VIA_T = previous


def _mm(value):
    return int(round(value * 1_000_000))


def _via(net, x, y, drill, top, bottom):
    return SimpleNamespace(
        Type=lambda: "VIA",
        GetNetname=lambda: net,
        GetPosition=lambda: SimpleNamespace(x=_mm(x), y=_mm(y)),
        GetDrillValue=lambda: _mm(drill),
        TopLayer=lambda: top,
        BottomLayer=lambda: bottom,
    )


def _track():
    return SimpleNamespace(Type=lambda: "TRACK", GetNetname=lambda: "GND")


def _board(items, user=None, standard=None):
    # KiCad 9/10 copper ids: F.Cu=0, B.Cu=2, In1.Cu=4. KiCad 8's B.Cu=31 is wrong here.
    user_names = user or {0: "Top Side", 2: "Bottom Side", 4: "Inner Layer 1"}
    standard_names = standard or {0: "F.Cu", 2: "B.Cu", 4: "In1.Cu"}
    return SimpleNamespace(
        Tracks=lambda: items,
        GetLayerName=lambda layer_id: user_names[layer_id],
        GetStandardLayerName=lambda layer_id: standard_names[layer_id],
    )


def _sample():
    return _board(
        [
            _via("GND", 1, 1, 0.2, 0, 2),
            _via("GND", 2, 2, 0.2, 0, 2),
            _via("GND", 8, 8, 0.2, 0, 4),
            _via("VCC", 1, 1, 0.4, 0, 2),
            _track(),
        ]
    )


def test_census_groups_drill_and_span_without_listing_vias():
    result = ViaSummaryCommands(_sample()).summarize_vias({"net": "GND"})

    assert result["success"] is True
    assert result["viaCount"] == 3
    assert result["throughAllCopperCount"] == 2
    assert result["drillHistogram"] == [{"drillMm": 0.2, "count": 3}]
    assert "vias" not in result
    spans = {(row["start"], row["end"]): row for row in result["layerSpans"]}
    through = spans[("Top Side", "Bottom Side")]
    assert through["count"] == 2
    assert through["throughAllCopper"] is True
    assert through["canonicalStart"] == "F.Cu"
    assert through["canonicalEnd"] == "B.Cu"
    blind = spans[("Top Side", "Inner Layer 1")]
    assert blind["count"] == 1
    assert blind["throughAllCopper"] is False


def test_rectangle_and_drill_filters():
    board = _sample()
    inside = ViaSummaryCommands(board).summarize_vias(
        {"boundingBox": {"x1": 0, "y1": 0, "x2": 1.5, "y2": 1.5}}
    )
    assert inside["viaCount"] == 2

    small = ViaSummaryCommands(board).summarize_vias({"drillMax": 0.3})
    assert small["viaCount"] == 3
    assert small["drillHistogram"] == [{"drillMm": 0.2, "count": 3}]


def test_layer_filter_accepts_the_canonical_name():
    result = ViaSummaryCommands(_sample()).summarize_vias(
        {"startLayer": "F.Cu", "endLayer": "Bottom Side"}
    )
    assert result["viaCount"] == 3
    assert result["throughAllCopperCount"] == 3


def test_renamed_bottom_layer_matches_b_cu_and_not_in2():
    """KiCad 10's B.Cu is layer 2. The old table called that In2.Cu."""
    board = _board(
        [_via("GND", 1, 1, 0.3, 0, 2)],
        user={0: "F.Cu", 2: "bottom_layer"},
        standard={0: "F.Cu", 2: "B.Cu"},
    )
    by_canonical = ViaSummaryCommands(board).summarize_vias({"endLayer": "B.Cu"})
    by_old_name = ViaSummaryCommands(board).summarize_vias({"endLayer": "In2.Cu"})
    assert by_canonical["viaCount"] == 1
    assert by_canonical["layerSpans"][0]["end"] == "bottom_layer"
    assert by_canonical["layerSpans"][0]["canonicalEnd"] == "B.Cu"
    assert by_old_name["viaCount"] == 0


def test_bad_unit_and_missing_board():
    bad = ViaSummaryCommands(_sample()).summarize_vias(
        {"boundingBox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "unit": "cm"}}
    )
    assert bad["success"] is False
    assert "unit" in bad["message"]

    missing = ViaSummaryCommands(None).summarize_vias({})
    assert missing["message"] == "No board is loaded"
