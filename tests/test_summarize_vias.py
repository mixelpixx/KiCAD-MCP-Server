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


def _board(items):
    names = {0: "Top Side", 1: "Inner Layer 1", 31: "Bottom Side"}
    return SimpleNamespace(Tracks=lambda: items, GetLayerName=lambda layer_id: names[layer_id])


def _sample():
    return _board(
        [
            _via("GND", 1, 1, 0.2, 0, 31),
            _via("GND", 2, 2, 0.2, 0, 31),
            _via("GND", 8, 8, 0.2, 0, 1),
            _via("VCC", 1, 1, 0.4, 0, 31),
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


def test_bad_unit_and_missing_board():
    bad = ViaSummaryCommands(_sample()).summarize_vias(
        {"boundingBox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "unit": "cm"}}
    )
    assert bad["success"] is False
    assert "unit" in bad["message"]

    missing = ViaSummaryCommands(None).summarize_vias({})
    assert missing["message"] == "No board is loaded"
