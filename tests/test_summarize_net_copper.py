"""Unit tests for summarize_net_copper.

The check that matters on a switch node is short: vias only, no tracks and
no zones. The answer has to be counts, not a dump of every object.
"""

from types import SimpleNamespace

import pcbnew
import pytest
from commands.net_copper import NetCopperCommands

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def via_marker():
    previous = pcbnew.PCB_VIA_T
    pcbnew.PCB_VIA_T = "VIA"
    yield
    pcbnew.PCB_VIA_T = previous


def _mm(value):
    return int(round(value * 1_000_000))


def _pos(x, y):
    return SimpleNamespace(x=_mm(x), y=_mm(y))


def _via(net, x, y, top=0, bottom=31):
    return SimpleNamespace(
        Type=lambda: "VIA",
        GetNetname=lambda: net,
        GetPosition=lambda: _pos(x, y),
        TopLayer=lambda: top,
        BottomLayer=lambda: bottom,
    )


def _track(net, x1, y1, x2, y2, layer=0):
    return SimpleNamespace(
        Type=lambda: "TRACK",
        GetNetname=lambda: net,
        GetLayer=lambda: layer,
        GetStart=lambda: _pos(x1, y1),
        GetEnd=lambda: _pos(x2, y2),
    )


def _zone(net, layer=0):
    box = SimpleNamespace(
        GetLeft=lambda: _mm(0),
        GetTop=lambda: _mm(0),
        GetRight=lambda: _mm(4),
        GetBottom=lambda: _mm(5),
    )
    zone = SimpleNamespace(
        GetNetname=lambda: net,
        GetLayer=lambda: layer,
        GetBoundingBox=lambda: box,
    )
    zone.GetLayerSet = lambda: (_ for _ in ()).throw(AttributeError("no layer set"))
    return zone


def _board(tracks, zones):
    names = {0: "Top Side", 31: "Bottom Side"}
    return SimpleNamespace(
        Tracks=lambda: tracks,
        Zones=lambda: zones,
        GetLayerName=lambda layer_id: names[layer_id],
    )


def test_vias_only_has_no_tracks_and_no_zones():
    board = _board([_via("NetL2_1", 1, 1), _via("NetL2_1", 3, 4)], [])
    result = NetCopperCommands(board).summarize_net_copper({"net": "NetL2_1"})

    assert result["success"] is True
    assert result["shape"] == "vias_only"
    assert result["summary"] == "Vias only, no tracks and no zones."
    assert result["trackCount"] == 0
    assert result["viaCount"] == 2
    assert result["zoneCount"] == 0
    assert result["layers"] == ["Bottom Side", "Top Side"]
    assert result["boundingBox"]["x1"] == pytest.approx(1)
    assert result["boundingBox"]["y2"] == pytest.approx(4)


def test_mixed_net_counts_each_kind():
    board = _board(
        [_track("GND", 0, 0, 2, 0), _via("GND", 2, 1)],
        [_zone("GND")],
    )
    result = NetCopperCommands(board).summarize_net_copper({"net": "GND"})

    assert result["shape"] == "mixed"
    assert result["trackCount"] == 1
    assert result["viaCount"] == 1
    assert result["zoneCount"] == 1
    assert "Top Side" in result["layers"]
    assert result["summary"] == "1 track, 1 via, 1 zone."


def test_empty_net_and_missing_name():
    board = _board([_via("GND", 0, 0)], [])
    empty = NetCopperCommands(board).summarize_net_copper({"net": "NetL2_2"})
    assert empty["shape"] == "empty"
    assert empty["boundingBox"] is None
    assert empty["viaCount"] == 0

    missing = NetCopperCommands(board).summarize_net_copper({})
    assert missing["success"] is False
    assert missing["message"] == "Missing net"

    unloaded = NetCopperCommands(None).summarize_net_copper({"net": "GND"})
    assert unloaded["message"] == "No board is loaded"
