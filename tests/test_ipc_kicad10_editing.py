"""Regression coverage for KiCad 10 live-edit handler compatibility."""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", True):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)

    iface.use_ipc = True
    iface.board = None
    iface.ipc_board_api = MagicMock()
    iface.ipc_board_api.add_track.return_value = True
    iface.ipc_board_api.add_arc_track.return_value = True
    iface.ipc_board_api.add_via.return_value = True
    iface.ipc_board_api.add_text.return_value = True
    iface.ipc_board_api.add_zone.return_value = True
    return iface


def test_route_trace_converts_per_point_units():
    iface = _make_iface()
    result = iface._ipc_route_trace(
        {
            "start": {"x": 1000, "y": 500, "unit": "mil"},
            "end": {"x": 1, "y": 2, "unit": "inch"},
            "layer": "F.Cu",
            "width": 0.25,
        }
    )

    assert result["success"] is True
    _, kwargs = iface.ipc_board_api.add_track.call_args
    assert kwargs["start_x"] == pytest.approx(25.4)
    assert kwargs["start_y"] == pytest.approx(12.7)
    assert kwargs["end_x"] == pytest.approx(25.4)
    assert kwargs["end_y"] == pytest.approx(50.8)


def test_add_via_forwards_type_span_and_converted_geometry():
    iface = _make_iface()
    result = iface._ipc_add_via(
        {
            "position": {"x": 100, "y": 200, "unit": "mil"},
            "size": 40,
            "drill": 20,
            "viaType": "blind",
            "fromLayer": "F.Cu",
            "toLayer": "In1.Cu",
            "net": "GND",
        }
    )

    assert result["success"] is True
    _, kwargs = iface.ipc_board_api.add_via.call_args
    assert kwargs["x"] == pytest.approx(2.54)
    assert kwargs["y"] == pytest.approx(5.08)
    assert kwargs["diameter"] == pytest.approx(1.016)
    assert kwargs["drill"] == pytest.approx(0.508)
    assert kwargs["via_type"] == "blind"
    assert kwargs["from_layer"] == "F.Cu"
    assert kwargs["to_layer"] == "In1.Cu"


def test_add_text_converts_units_and_forwards_style():
    iface = _make_iface()
    result = iface._ipc_add_text(
        {
            "text": "LIVE",
            "position": {"x": 1, "y": 2, "unit": "inch"},
            "layer": "F.Fab",
            "size": 0.05,
            "thickness": 0.01,
            "rotation": 90,
            "style": "italic",
        }
    )

    assert result["success"] is True
    _, kwargs = iface.ipc_board_api.add_text.call_args
    assert kwargs["x"] == pytest.approx(25.4)
    assert kwargs["y"] == pytest.approx(50.8)
    assert kwargs["size"] == pytest.approx(1.27)
    assert kwargs["thickness"] == pytest.approx(0.254)
    assert kwargs["style"] == "italic"


def test_copper_pour_accepts_outline_schema_and_converts_units():
    iface = _make_iface()
    result = iface._ipc_add_copper_pour(
        {
            "layer": "F.Cu",
            "net": "GND",
            "unit": "inch",
            "outline": [
                {"x": 0, "y": 0},
                {"x": 1, "y": 0},
                {"x": 1, "y": 1},
            ],
            "clearance": 0.01,
            "minWidth": 0.02,
        }
    )

    assert result["success"] is True
    _, kwargs = iface.ipc_board_api.add_zone.call_args
    assert kwargs["points"][1] == pytest.approx({"x": 25.4, "y": 0})
    assert kwargs["points"][2] == pytest.approx({"x": 25.4, "y": 25.4})
    assert kwargs["clearance"] == pytest.approx(0.254)
    assert kwargs["min_thickness"] == pytest.approx(0.508)


def test_add_zone_uses_the_live_ipc_handler():
    from kicad_interface import KiCADInterface

    assert KiCADInterface.IPC_CAPABLE_COMMANDS["add_zone"] == "_ipc_add_copper_pour"


def test_layer_resolver_supports_full_kicad10_layer_names_and_aliases():
    from kicad_api.ipc_backend import IPCBoardAPI
    from kipy.proto.board.board_types_pb2 import BoardLayer

    assert IPCBoardAPI._resolve_board_layer("F.Fab") == BoardLayer.BL_F_Fab
    assert IPCBoardAPI._resolve_board_layer("In30.Cu") == BoardLayer.BL_In30_Cu
    assert IPCBoardAPI._resolve_board_layer("Top Layer") == BoardLayer.BL_F_Cu
    assert IPCBoardAPI._resolve_board_layer("Bottom Layer") == BoardLayer.BL_B_Cu
