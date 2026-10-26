"""Region and pad options on get_component_list.

A shield can is a rectangle on the board. The footprint list already takes a
bounding box; these options also keep a part whose pad centre sits inside the
can, and return the net on each pad. Layer names come from the board, so a
user-named bottom copper still matches B.Cu.
"""

from types import SimpleNamespace

import pytest
from commands.component import ComponentCommands

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


def _bbox():
    return SimpleNamespace(
        GetLeft=lambda: 0,
        GetTop=lambda: 0,
        GetRight=lambda: _mm(1),
        GetBottom=lambda: _mm(1),
    )


def _footprint(ref, value, x, y, layer, pads):
    return SimpleNamespace(
        GetReference=lambda: ref,
        GetValue=lambda: value,
        GetFPIDAsString=lambda: "Lib:FP",
        GetPosition=lambda: _pos(x, y),
        GetOrientation=lambda: SimpleNamespace(AsDegrees=lambda: 0),
        GetLayer=lambda: layer,
        GetBoundingBox=_bbox,
        Pads=lambda: pads,
    )


def _board(parts, names, standard):
    return SimpleNamespace(
        GetFootprints=lambda: parts,
        GetLayerName=lambda layer_id: names[layer_id],
        GetStandardLayerName=lambda layer_id: standard[layer_id],
    )


def _shield_board():
    parts = [
        _footprint("U5", "TPS63070", 15, 15, 0, [_pad("1", "VCC", 15.5, 15.5)]),
        _footprint("EMI4", "S0941-46R", 30, 30, 0, [_pad("1", "GND", 12, 12)]),
        _footprint("R1", "10k", 30, 30, 2, [_pad("1", "NetL2_1", 31, 31)]),
    ]
    names = {0: "Top Side", 2: "Bottom Side"}
    standard = {0: "F.Cu", 2: "B.Cu"}
    return _board(parts, names, standard)


CAN = {"x1": 10, "y1": 10, "x2": 20, "y2": 20}


def test_pad_centre_keeps_a_part_whose_anchor_is_outside():
    result = ComponentCommands(_shield_board()).get_component_list(
        {"boundingBox": CAN, "matchPadCenter": True, "includePads": True}
    )

    assert result["success"] is True
    by_ref = {row["reference"]: row for row in result["components"]}
    assert set(by_ref) == {"EMI4", "U5"}
    assert by_ref["U5"]["value"] == "TPS63070"
    assert by_ref["U5"]["layer"] == "Top Side"
    assert by_ref["U5"]["position"]["x"] == pytest.approx(15)
    assert by_ref["U5"]["pads"][0]["net"] == "VCC"
    assert by_ref["EMI4"]["position"]["x"] == pytest.approx(30)
    assert by_ref["EMI4"]["pads"][0]["net"] == "GND"
    assert "boundingBox" in by_ref["U5"]


def test_anchor_filter_leaves_the_shield_clip_out():
    result = ComponentCommands(_shield_board()).get_component_list({"boundingBox": CAN})

    refs = [row["reference"] for row in result["components"]]
    assert refs == ["U5"]
    assert "pads" not in result["components"][0]


def test_mil_box_and_unfiltered_list():
    board = _board(
        [_footprint("C1", "100n", 0.254, 0.254, 0, [])],
        {0: "Top Side"},
        {0: "F.Cu"},
    )
    hit = ComponentCommands(board).get_component_list(
        {"boundingBox": {"x1": 0, "y1": 0, "x2": 20, "y2": 20, "unit": "mil"}}
    )
    assert [row["reference"] for row in hit["components"]] == ["C1"]

    everything = ComponentCommands(_shield_board()).get_component_list({})
    assert everything["success"] is True
    assert len(everything["components"]) == 3
    assert "pads" not in everything["components"][0]

    empty = ComponentCommands(None).get_component_list({"boundingBox": CAN})
    assert empty["message"] == "No board is loaded"


def test_layer_matches_the_canonical_name_and_the_board_name():
    cmd = ComponentCommands(_shield_board())

    bottom = cmd.get_component_list({"layer": "B.Cu"})
    assert [row["reference"] for row in bottom["components"]] == ["R1"]
    assert bottom["components"][0]["layer"] == "Bottom Side"

    by_user_name = cmd.get_component_list({"layer": "Bottom Side"})
    assert [row["reference"] for row in by_user_name["components"]] == ["R1"]

    renamed_inner = cmd.get_component_list({"layer": "In2.Cu"})
    assert renamed_inner["components"] == []
