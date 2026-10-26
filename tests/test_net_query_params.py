"""get_nets_list honours includeStats/unit, get_net_pads honours unit (#407).

Both tools declared these parameters in their zod schemas and the handlers ignored
them: get_nets_list never returned statistics, and get_net_pads always answered in
millimetres whatever unit was asked for.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from commands import routing as routing_mod  # noqa: E402
from commands.routing import RoutingCommands  # noqa: E402

# --- get_nets_list -------------------------------------------------------------


class _Net:
    def __init__(self, name, code):
        self._name, self._code = name, code

    def GetNetname(self):
        return self._name

    def GetNetCode(self):
        return self._code

    def GetNetClassName(self):
        return "Default"


class _NetInfo:
    def __init__(self, nets):
        self._nets = nets

    def GetNetCount(self):
        return len(self._nets)

    def GetNetItem(self, code):
        return self._nets[code]


class _Item:
    """A track (or via, when ``kind`` is pcbnew.PCB_VIA_T)."""

    def __init__(self, kind, net, length_mm=0.0):
        self._kind, self._net, self._length = kind, net, length_mm

    def Type(self):
        return self._kind

    def GetNetname(self):
        return self._net

    def GetLength(self):
        return int(self._length * 1_000_000)


TRACK = object()  # never equal to pcbnew.PCB_VIA_T


@pytest.fixture
def nets_board():
    via = routing_mod.pcbnew.PCB_VIA_T
    board = MagicMock()
    board.GetNetInfo.return_value = _NetInfo([_Net("", 0), _Net("GND", 1), _Net("VBUS", 2)])
    board.GetTracks.return_value = [
        _Item(TRACK, "GND", 10.0),
        _Item(TRACK, "GND", 15.4),
        _Item(via, "GND"),
        _Item(TRACK, "VBUS", 25.4),
    ]
    return board


def test_nets_list_without_stats_is_unchanged(nets_board):
    result = RoutingCommands(nets_board).get_nets_list({})
    assert result["success"], result
    assert "unit" not in result
    assert all("stats" not in net for net in result["nets"])
    assert [net["name"] for net in result["nets"]] == ["", "GND", "VBUS"]


def test_nets_list_stats_in_mm(nets_board):
    result = RoutingCommands(nets_board).get_nets_list({"includeStats": True})
    assert result["success"], result
    assert result["unit"] == "mm"
    by_name = {net["name"]: net["stats"] for net in result["nets"]}
    assert by_name["GND"] == {"trackCount": 2, "trackLength": pytest.approx(25.4), "viaCount": 1}
    assert by_name["VBUS"]["trackCount"] == 1
    # A net with no copper still gets a stats block, all zero
    assert by_name[""] == {"trackCount": 0, "trackLength": 0.0, "viaCount": 0}


def test_nets_list_stats_in_mil(nets_board):
    result = RoutingCommands(nets_board).get_nets_list({"includeStats": True, "unit": "mil"})
    by_name = {net["name"]: net["stats"] for net in result["nets"]}
    assert result["unit"] == "mil"
    assert by_name["VBUS"]["trackLength"] == pytest.approx(1000.0)  # 25.4 mm


def test_nets_list_rejects_unknown_unit(nets_board):
    result = RoutingCommands(nets_board).get_nets_list({"includeStats": True, "unit": "cm"})
    assert not result["success"]
    assert "inch" in result["errorDetails"]


def test_ipc_nets_list_matches_swig_stats():
    from kicad_interface import KiCADInterface

    iface = KiCADInterface.__new__(KiCADInterface)
    api = MagicMock()
    api.get_nets.return_value = [{"name": "GND", "code": 1}, {"name": "VBUS", "code": 2}]
    api.get_tracks.return_value = [
        {"net": "GND", "start": {"x": 0.0, "y": 0.0}, "end": {"x": 3.0, "y": 4.0}},
        {"net": "GND", "start": {"x": 0.0, "y": 0.0}, "end": {"x": 0.0, "y": 25.4}},
    ]
    api.get_vias.return_value = [{"net": "VBUS"}]
    iface.ipc_board_api = api

    result = iface._ipc_get_nets_list({"includeStats": True, "unit": "mil"})
    assert result["success"], result
    by_name = {net["name"]: net["stats"] for net in result["nets"]}
    assert by_name["GND"]["trackCount"] == 2
    assert by_name["GND"]["trackLength"] == pytest.approx((5.0 + 25.4) / 0.0254)
    assert by_name["VBUS"] == {"trackCount": 0, "trackLength": 0.0, "viaCount": 1}


# --- get_net_pads ----------------------------------------------------------------


def _vec(x_mm, y_mm):
    v = MagicMock()
    v.x, v.y = int(x_mm * 1_000_000), int(y_mm * 1_000_000)
    return v


def _pad(x_mm, y_mm):
    pad = MagicMock()
    pad.GetName.return_value = "1"
    pad.GetNumber.return_value = "1"
    pad.GetPosition.return_value = _vec(x_mm, y_mm)
    pad.GetSize.return_value = _vec(1.27, 2.54)
    pad.GetNetname.return_value = "GND"
    pad.GetNetCode.return_value = 7
    drill = MagicMock()
    drill.x = drill.y = 0
    pad.GetDrillSize.return_value = drill
    bbox = MagicMock()
    bbox.GetLeft.return_value = int((x_mm - 0.635) * 1_000_000)
    bbox.GetRight.return_value = int((x_mm + 0.635) * 1_000_000)
    bbox.GetTop.return_value = int((y_mm - 1.27) * 1_000_000)
    bbox.GetBottom.return_value = int((y_mm + 1.27) * 1_000_000)
    pad.GetBoundingBox.return_value = bbox
    return pad


@pytest.fixture
def pads_board():
    fp = MagicMock()
    fp.GetReference.return_value = "J1"
    fp.Pads.return_value = [_pad(25.4, 50.8)]
    board = MagicMock()
    board.GetFootprints.return_value = [fp]
    return board


def test_net_pads_default_unit_is_mm(pads_board):
    from commands.component import ComponentCommands

    result = ComponentCommands(board=pads_board).get_net_pads({"net": "GND"})
    assert result["unit"] == "mm"
    pad = result["pads"][0]
    assert pad["position"] == {"x": pytest.approx(25.4), "y": pytest.approx(50.8), "unit": "mm"}


def test_net_pads_in_inch(pads_board):
    from commands.component import ComponentCommands

    result = ComponentCommands(board=pads_board).get_net_pads({"net": "GND", "unit": "inch"})
    assert result["success"], result
    assert result["unit"] == "inch"
    pad = result["pads"][0]
    assert pad["position"] == {"x": pytest.approx(1.0), "y": pytest.approx(2.0), "unit": "inch"}
    assert pad["size"] == {"x": pytest.approx(0.05), "y": pytest.approx(0.1), "unit": "inch"}
    assert pad["bbox"]["width"] == pytest.approx(0.05)
    assert pad["bbox"]["unit"] == "inch"
    assert pad["netCode"] == 7  # not a length: must not be scaled


def test_net_pads_rejects_unknown_unit(pads_board):
    from commands.component import ComponentCommands

    result = ComponentCommands(board=pads_board).get_net_pads({"net": "GND", "unit": "um"})
    assert not result["success"]
    assert "mil" in result["errorDetails"]
