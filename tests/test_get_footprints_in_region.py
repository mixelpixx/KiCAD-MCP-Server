"""Unit tests for get_footprints_in_region.

A shield can is a rectangle on the board. The schematic region query does
not see it, so the PCB query has to return the parts whose anchor or a pad
centre sits inside.
"""

from types import SimpleNamespace

import pytest
from commands.footprints_in_region import RegionFootprintCommands

pytestmark = pytest.mark.unit


def _mm(value):
    return int(round(value * 1_000_000))


def _pos(x, y):
    return SimpleNamespace(x=_mm(x), y=_mm(y))


def _pad(number, net, x, y):
    return SimpleNamespace(
        GetNumber=lambda: number,
        GetNetname=lambda: net,
        GetPosition=lambda: _pos(x, y),
    )


def _footprint(ref, value, x, y, layer, pads):
    return SimpleNamespace(
        GetReference=lambda: ref,
        GetValue=lambda: value,
        GetPosition=lambda: _pos(x, y),
        GetLayer=lambda: layer,
        Pads=lambda: pads,
    )


def _board():
    parts = [
        _footprint("U5", "TPS63070", 15, 15, 0, [_pad("1", "VCC", 15.5, 15.5)]),
        _footprint("EMI4", "S0941-46R", 30, 30, 0, [_pad("1", "GND", 12, 12)]),
        _footprint("R1", "10k", 30, 30, 31, [_pad("1", "NetL2_1", 31, 31)]),
    ]
    names = {0: "Top Side", 31: "Bottom Side"}
    return SimpleNamespace(
        GetFootprints=lambda: parts,
        GetLayerName=lambda layer_id: names[layer_id],
    )


CAN = {"x1": 10, "y1": 10, "x2": 20, "y2": 20}


def test_anchor_or_pad_inside_the_rectangle():
    result = RegionFootprintCommands(_board()).get_footprints_in_region({"boundingBox": CAN})

    assert result["success"] is True
    assert result["count"] == 2
    by_ref = {row["reference"]: row for row in result["footprints"]}
    assert list(by_ref) == ["EMI4", "U5"]
    assert by_ref["U5"]["value"] == "TPS63070"
    assert by_ref["U5"]["layer"] == "Top Side"
    assert by_ref["U5"]["canonical"] == "F.Cu"
    assert by_ref["U5"]["pads"][0]["net"] == "VCC"
    assert by_ref["EMI4"]["x"] == pytest.approx(30)
    assert by_ref["EMI4"]["pads"][0]["net"] == "GND"
    assert "R1" not in by_ref


def test_mil_box_and_missing_box():
    board = SimpleNamespace(
        GetFootprints=lambda: [_footprint("C1", "100n", 0.254, 0.254, 0, [])],
        GetLayerName=lambda layer_id: "Top Side",
    )
    hit = RegionFootprintCommands(board).get_footprints_in_region(
        {"boundingBox": {"x1": 0, "y1": 0, "x2": 20, "y2": 20, "unit": "mil"}}
    )
    assert hit["count"] == 1

    missing = RegionFootprintCommands(board).get_footprints_in_region({})
    assert missing["success"] is False
    assert missing["message"] == "Missing boundingBox"

    empty = RegionFootprintCommands(None).get_footprints_in_region({"boundingBox": CAN})
    assert empty["message"] == "No board is loaded"
