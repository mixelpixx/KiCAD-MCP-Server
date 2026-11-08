"""add_copper_pour: net validation, pad connection and point units, on SWIG and IPC."""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.routing import RoutingCommands  # noqa: E402

SQUARE = [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}, {"x": 0, "y": 10}]


def _board(nets=("GND", "VBUS")) -> MagicMock:
    board = MagicMock(name="board")
    board.GetLayerID.return_value = 0
    nets_map = MagicMock()
    nets_map.has_key.side_effect = lambda n: n in nets
    nets_map.__getitem__.side_effect = lambda n: f"net:{n}"
    board.GetNetInfo.return_value.NetsByName.return_value = nets_map
    return board


def _pour(params: dict) -> tuple:
    board = _board()
    with patch("commands.routing.pcbnew") as pcb:
        pcb.ZONE_CONNECTION_THERMAL = 1
        pcb.ZONE_CONNECTION_FULL = 2
        pcb.ZONE_CONNECTION_NONE = 0
        result = RoutingCommands(board).add_copper_pour(params)
        zone = pcb.ZONE.return_value
    return result, zone, board


@pytest.mark.unit
def test_unknown_net_is_an_error_not_a_netless_zone() -> None:
    result, zone, board = _pour({"layer": "F.Cu", "net": "VBSU", "outline": SQUARE})
    assert result["success"] is False
    assert "VBSU" in result["errorDetails"]
    board.Add.assert_not_called()


@pytest.mark.unit
def test_known_net_is_assigned() -> None:
    result, zone, board = _pour({"layer": "F.Cu", "net": "GND", "outline": SQUARE})
    assert result["success"] is True
    zone.SetNet.assert_called_once_with("net:GND")
    board.Add.assert_called_once_with(zone)


@pytest.mark.unit
@pytest.mark.parametrize("mode, value", [("solid", 2), ("thermal", 1), ("none", 0)])
def test_pad_connection_is_applied(mode: str, value: int) -> None:
    result, zone, _ = _pour(
        {"layer": "F.Cu", "net": "VBUS", "outline": SQUARE, "padConnection": mode}
    )
    assert result["success"] is True
    zone.SetPadConnection.assert_called_once_with(value)
    assert result["pour"]["padConnection"] == mode


@pytest.mark.unit
def test_pad_connection_defaults_to_kicad_default() -> None:
    result, zone, _ = _pour({"layer": "F.Cu", "net": "VBUS", "outline": SQUARE})
    zone.SetPadConnection.assert_not_called()
    assert result["pour"]["padConnection"] == "thermal"


@pytest.mark.unit
def test_invalid_pad_connection_is_rejected() -> None:
    result, _, board = _pour(
        {"layer": "F.Cu", "net": "VBUS", "outline": SQUARE, "padConnection": "full"}
    )
    assert result["success"] is False
    board.Add.assert_not_called()


@pytest.mark.unit
def test_priority_is_applied() -> None:
    _, zone, _ = _pour({"layer": "F.Cu", "net": "VBUS", "outline": SQUARE, "priority": 3})
    zone.SetAssignedPriority.assert_called_once_with(3)


def _ipc_iface(nets=("GND", "VBUS")) -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface: Any = KiCADInterface.__new__(KiCADInterface)
    iface.ipc_board_api = MagicMock()
    iface.ipc_board_api.add_zone.return_value = True
    iface.ipc_board_api.get_nets.return_value = [{"name": n, "code": i} for i, n in enumerate(nets)]
    return iface


@pytest.mark.unit
def test_ipc_handler_reads_the_schema_outline_key() -> None:
    # The tool schema sends `outline`; the IPC handler read only `points`, so
    # every add_copper_pour over IPC failed with "At least 3 points".
    iface = _ipc_iface()

    result = iface._ipc_add_copper_pour({"layer": "F.Cu", "net": "GND", "outline": SQUARE})

    assert result["success"] is True
    points = iface.ipc_board_api.add_zone.call_args.kwargs["points"]
    assert points == [{"x": p["x"], "y": p["y"]} for p in SQUARE]


@pytest.mark.unit
@pytest.mark.parametrize("unit, mm", [("mil", 0.254), ("inch", 254.0), ("mm", 10.0)])
def test_ipc_handler_converts_point_units_to_mm(unit: str, mm: float) -> None:
    # add_zone forwards its points with their unit; ipc_board_api.add_zone takes mm.
    iface = _ipc_iface()
    outline = [{**p, "unit": unit} for p in SQUARE]

    result = iface._ipc_add_copper_pour({"layer": "F.Cu", "net": "GND", "outline": outline})

    assert result["success"] is True
    points = iface.ipc_board_api.add_zone.call_args.kwargs["points"]
    assert points[2] == {"x": pytest.approx(mm), "y": pytest.approx(mm)}


@pytest.mark.unit
def test_ipc_handler_rejects_an_unknown_point_unit() -> None:
    iface = _ipc_iface()
    outline = [{**p, "unit": "cm"} for p in SQUARE]

    result = iface._ipc_add_copper_pour({"layer": "F.Cu", "net": "GND", "outline": outline})

    assert result["success"] is False
    iface.ipc_board_api.add_zone.assert_not_called()


@pytest.mark.unit
def test_ipc_handler_unknown_net_is_an_error() -> None:
    iface = _ipc_iface()

    result = iface._ipc_add_copper_pour({"layer": "F.Cu", "net": "VBSU", "outline": SQUARE})

    assert result["success"] is False
    assert "VBSU" in result["errorDetails"]
    iface.ipc_board_api.add_zone.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["solid", "thermal", "none"])
def test_ipc_handler_passes_pad_connection(mode: str) -> None:
    iface = _ipc_iface()

    result = iface._ipc_add_copper_pour(
        {"layer": "F.Cu", "net": "VBUS", "outline": SQUARE, "padConnection": mode}
    )

    assert result["success"] is True
    assert iface.ipc_board_api.add_zone.call_args.kwargs["pad_connection"] == mode
    assert result["pour"]["padConnection"] == mode


@pytest.mark.unit
def test_ipc_handler_rejects_invalid_pad_connection() -> None:
    iface = _ipc_iface()

    result = iface._ipc_add_copper_pour(
        {"layer": "F.Cu", "net": "VBUS", "outline": SQUARE, "padConnection": "full"}
    )

    assert result["success"] is False
    iface.ipc_board_api.add_zone.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "mode, style", [("solid", "ZCS_FULL"), ("thermal", "ZCS_THERMAL"), ("none", "ZCS_NONE")]
)
def test_ipc_backend_writes_pad_connection_to_the_zone(mode: str, style: str) -> None:
    pytest.importorskip("kipy.board_types", reason="kipy (kicad-python) not installed")
    from kicad_api.ipc_backend import IPCBoardAPI
    from kipy.proto.board.board_types_pb2 import ZoneConnectionStyle

    created = []
    board = MagicMock()
    board.get_nets.return_value = []
    board.create_items.side_effect = created.append
    api: Any = IPCBoardAPI.__new__(IPCBoardAPI)
    api._get_board = lambda: board
    api._notify = MagicMock()

    assert api.add_zone(points=SQUARE, layer="F.Cu", pad_connection=mode) is True

    (zone,) = created
    assert zone._proto.copper_settings.connection.zone_connection == getattr(
        ZoneConnectionStyle, style
    )
