import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _pos(x_mm, y_mm):
    p = MagicMock()
    p.x = int(x_mm * 1_000_000)
    p.y = int(y_mm * 1_000_000)
    return p


def _bbox(left, top, right, bottom):
    bb = MagicMock()
    bb.GetLeft.return_value = int(left * 1_000_000)
    bb.GetTop.return_value = int(top * 1_000_000)
    bb.GetRight.return_value = int(right * 1_000_000)
    bb.GetBottom.return_value = int(bottom * 1_000_000)
    return bb


def _angle(deg):
    a = MagicMock()
    a.AsDegrees.return_value = deg
    return a


def _pad(number, x, y, net):
    pad = MagicMock()
    pad.GetName.return_value = number
    pad.GetNumber.return_value = number
    pad.GetPosition.return_value = _pos(x, y)
    pad.GetSize.return_value = _pos(1, 1)
    pad.GetNetname.return_value = net
    pad.GetNetCode.return_value = 7 if net == "N$1" else 8
    pad.GetBoundingBox.return_value = _bbox(x - 0.5, y - 0.5, x + 0.5, y + 0.5)
    drill = MagicMock()
    drill.x = 0
    drill.y = 0
    pad.GetDrillSize.return_value = drill
    return pad


def _footprint(ref, x, y, pads=None):
    fp = MagicMock()
    fp.GetReference.return_value = ref
    fp.GetValue.return_value = "V"
    fp.GetFPIDAsString.return_value = "Lib:FP"
    fp.GetPosition.return_value = _pos(x, y)
    fp.GetOrientation.return_value = _angle(0)
    fp.GetLayer.return_value = 0
    fp.GetBoundingBox.return_value = _bbox(x - 1, y - 1, x + 1, y + 1)
    fp.Pads.return_value = pads or []
    fp.GraphicalItems.return_value = []
    ct = MagicMock()
    ct.OutlineCount.return_value = 1
    ct.BBox.return_value = _bbox(x - 1.2, y - 1.2, x + 1.2, y + 1.2)
    fp.GetCourtyard.return_value = ct
    fp.GetOrientationDegrees.return_value = 0
    return fp


def _board(footprints):
    board = MagicMock()
    board.GetFootprints.return_value = footprints
    board.GetLayerName.side_effect = lambda layer: "F.Cu" if layer == 0 else "Edge.Cuts"
    board.FindFootprintByReference.side_effect = lambda ref: next(
        (fp for fp in footprints if fp.GetReference() == ref), None
    )
    board.GetFileName.return_value = "/tmp/test.kicad_pcb"
    return board


def test_batch_move_components_rolls_back_on_failure(monkeypatch):
    from commands.component import ComponentCommands

    fp = _footprint("U1", 1, 1)
    board = _board([fp])

    calls = []

    def set_position(pos):
        calls.append(pos)
        if len(calls) == 1:
            raise RuntimeError("boom")

    fp.SetPosition.side_effect = set_position
    cmd = ComponentCommands(board=board)
    result = cmd.batch_move_components({"moves": {"U1": {"x": 10, "y": 20}}, "save": False})

    assert result["success"] is False
    assert fp.SetPosition.call_count == 2


def test_get_component_geometry_separates_pad_and_courtyard_bbox():
    from commands.component import ComponentCommands

    fp = _footprint("U1", 10, 20, [_pad("1", 9, 20, "N$1"), _pad("2", 11, 20, "N$2")])
    result = ComponentCommands(board=_board([fp])).get_component_geometry({"reference": "U1"})

    assert result["success"] is True
    geometry = result["geometry"]
    assert geometry["pads_bbox"]["min_x"] == pytest.approx(8.5)
    assert geometry["pads_bbox"]["max_x"] == pytest.approx(11.5)
    assert geometry["courtyard_bbox"]["min_x"] == pytest.approx(8.8)
    assert geometry["raw_bbox"]["min_x"] == pytest.approx(9.0)


def test_get_net_pads_and_ratsnest():
    from commands.component import ComponentCommands

    fp1 = _footprint("U1", 0, 0, [_pad("1", 0, 0, "N$1")])
    fp2 = _footprint("U2", 3, 4, [_pad("1", 3, 4, "N$1")])
    cmd = ComponentCommands(board=_board([fp1, fp2]))

    pads = cmd.get_net_pads({"net": "N$1"})
    assert pads["success"] is True
    assert pads["padCount"] == 2

    ratsnest = cmd.get_ratsnest({"nets": ["N$1"]})
    assert ratsnest["success"] is True
    assert ratsnest["segmentCount"] == 1
    assert ratsnest["estimatedLengthMm"] == pytest.approx(5.0)


def test_board_outline_and_graphic_crud():
    from commands.board.outline import BoardOutlineCommands

    edge = MagicMock()
    edge.GetLayer.return_value = 1
    edge_uuid = MagicMock()
    edge_uuid.AsString.return_value = "edge-1"
    edge.m_Uuid = edge_uuid
    edge.GetStart.return_value = _pos(0, 0)
    edge.GetEnd.return_value = _pos(1, 0)
    edge.GetBoundingBox.return_value = _bbox(0, 0, 1, 0)

    silk = MagicMock()
    silk.GetLayer.return_value = 0
    silk_uuid = MagicMock()
    silk_uuid.AsString.return_value = "silk-1"
    silk.m_Uuid = silk_uuid

    board = MagicMock()
    board.GetLayerID.return_value = 1
    board.GetLayerName.side_effect = lambda layer: "Edge.Cuts" if layer == 1 else "F.SilkS"
    board.GetDrawings.return_value = [edge, silk]

    cmd = BoardOutlineCommands(board=board)
    listed = cmd.list_graphics({"layer": "Edge.Cuts"})
    assert listed["success"] is True
    assert listed["count"] == 1
    assert listed["graphics"][0]["uuid"] == "edge-1"

    updated = cmd.update_graphic({"uuid": "edge-1", "width": 0.15})
    assert updated["success"] is True
    edge.SetWidth.assert_called_once_with(150000)

    deleted = cmd.delete_graphic({"uuid": "edge-1"})
    assert deleted["success"] is True
    board.Remove.assert_called_with(edge)

    cleared = cmd.clear_board_outline({})
    assert cleared["success"] is True
    assert cleared["removed"] == 1
