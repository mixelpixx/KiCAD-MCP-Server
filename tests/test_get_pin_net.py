"""
Tests for the get_pin_net tool and its handler.

Covers:
  - Schema shape (TestGetPinNetSchema)
  - Handler dispatch registration (TestGetPinNetHandlerDispatch)
  - Parameter validation in the handler (TestGetPinNetHandlerParamValidation)
  - Core logic: get_pin_net function (TestGetPinNetCoreLogic)
  - Reference+pin resolution path (TestGetPinNetHandlerRefPinResolution)
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.wire_connectivity import get_pin_net

# ---------------------------------------------------------------------------
# Shared mock helpers (mirrors test_wire_connectivity.py)
# ---------------------------------------------------------------------------


def _make_point(x: float, y: float) -> MagicMock:
    pt = MagicMock()
    pt.value = [x, y]
    return pt


def _make_wire(x1: float, y1: float, x2: float, y2: float) -> MagicMock:
    wire = MagicMock()
    wire.pts = MagicMock()
    wire.pts.xy = [_make_point(x1, y1), _make_point(x2, y2)]
    return wire


def _make_schematic(*wires: Any) -> MagicMock:
    sch = MagicMock()
    sch.wire = list(wires)
    del sch.label
    del sch.symbol
    return sch


# ---------------------------------------------------------------------------
# TestGetPinNetSchema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPinNetSchema:
    """Verify the get_pin_net tool schema is present and well-formed."""

    def test_schema_registered(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "get_pin_net" in TOOL_SCHEMAS

    def test_schema_required_fields(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        required = TOOL_SCHEMAS["get_pin_net"]["inputSchema"]["required"]
        assert required == ["schematicPath"]

    def test_schema_has_title_and_description(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["get_pin_net"]
        assert schema.get("title")
        assert schema.get("description")

    def test_schema_has_optional_fields(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        props = TOOL_SCHEMAS["get_pin_net"]["inputSchema"]["properties"]
        for field in ("reference", "pin", "x", "y"):
            assert field in props, f"Expected '{field}' in schema properties"


# ---------------------------------------------------------------------------
# TestGetPinNetHandlerDispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPinNetHandlerDispatch:
    """Verify the handler is wired into KiCadInterface.command_routes."""

    def test_get_pin_net_in_routes(self) -> None:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
            iface.board = None
            iface.project_filename = None
            iface.use_ipc = False
            iface.ipc_backend = MagicMock()
            iface.ipc_board_api = None
            iface.footprint_library = MagicMock()
            iface.project_commands = MagicMock()
            iface.board_commands = MagicMock()
            iface.component_commands = MagicMock()
            iface.routing_commands = MagicMock()
            KiCADInterface.__init__(iface)

        assert "get_pin_net" in iface.command_routes
        assert callable(iface.command_routes["get_pin_net"])


# ---------------------------------------------------------------------------
# TestGetPinNetHandlerParamValidation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPinNetHandlerParamValidation:
    """Handler returns error responses for bad or missing parameters."""

    def _make_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_get_pin_net

    def test_missing_schematic_path(self) -> None:
        handler = self._make_handler()
        result = handler({"x": 1.0, "y": 2.0})
        assert result["success"] is False
        assert "schematicPath" in result["message"] or "Missing" in result["message"]

    def test_missing_both_modes(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch"})
        assert result["success"] is False

    def test_partial_ref_only(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "reference": "U1"})
        assert result["success"] is False

    def test_partial_pin_only(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "pin": "3"})
        assert result["success"] is False

    def test_partial_x_only(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": 1.0})
        assert result["success"] is False

    def test_partial_y_only(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "y": 1.0})
        assert result["success"] is False

    def test_non_numeric_coords(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": "bad", "y": 2.0})
        assert result["success"] is False
        assert "numeric" in result["message"].lower() or "x" in result["message"]


# ---------------------------------------------------------------------------
# TestGetPinNetCoreLogic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPinNetCoreLogic:
    """Unit tests for the get_pin_net function."""

    def test_no_wires_returns_empty_dict(self) -> None:
        sch = MagicMock()
        sch.wire = []
        del sch.label
        del sch.symbol
        result = get_pin_net(sch, "/tmp/test.kicad_sch", 1.0, 2.0)
        assert result is not None
        assert result["net"] is None
        assert result["pins"] == []
        assert result["wires"] == []
        assert result["query_point"] == {"x": 1.0, "y": 2.0}

    def test_no_wire_at_point_returns_none(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        # Query a midpoint — not on a wire endpoint
        result = get_pin_net(sch, "/tmp/test.kicad_sch", 0.5, 0.0)
        assert result is None

    def test_unnamed_net_no_labels(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_pin_net(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert result["net"] is None

    def test_net_name_from_label(self) -> None:
        """Wire with a net label at one endpoint should yield that label as net name."""
        wire = _make_wire(0.0, 0.0, 1.0, 0.0)

        label = MagicMock()
        label.value = "SDA"
        label.at = MagicMock()
        label.at.value = [0.0, 0.0, 0]  # label placed at wire start

        sch = MagicMock()
        sch.wire = [wire]
        sch.label = [label]
        del sch.symbol

        result = get_pin_net(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert result["net"] == "SDA"

    def test_query_point_in_result(self) -> None:
        sch = _make_schematic(_make_wire(5.0, 3.0, 6.0, 3.0))
        result = get_pin_net(sch, "/tmp/test.kicad_sch", 5.0, 3.0)
        assert result is not None
        assert result["query_point"] == {"x": 5.0, "y": 3.0}

    def test_result_has_pins_and_wires_keys(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_pin_net(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert "pins" in result
        assert "wires" in result

    def test_wires_returned_in_mm(self) -> None:
        sch = _make_schematic(_make_wire(2.0, 3.0, 4.0, 3.0))
        result = get_pin_net(sch, "/tmp/test.kicad_sch", 2.0, 3.0)
        assert result is not None
        assert len(result["wires"]) == 1
        w = result["wires"][0]
        assert w["start"]["x"] == pytest.approx(2.0)
        assert w["start"]["y"] == pytest.approx(3.0)
        assert w["end"]["x"] == pytest.approx(4.0)
        assert w["end"]["y"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# TestGetPinNetHandlerRefPinResolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPinNetHandlerRefPinResolution:
    """Test the reference+pin → coordinate resolution path in the handler."""

    def _make_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_get_pin_net

    def test_ref_pin_resolves_to_coordinates(self) -> None:
        handler = self._make_handler()
        mock_result = {
            "net": "SDA",
            "pins": [{"component": "U1", "pin": "3"}],
            "wires": [],
            "query_point": {"x": 10.5, "y": 15.2},
        }
        with (
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=[10.5, 15.2],
            ),
            patch("kicad_interface.SchematicManager.load_schematic") as mock_load,
            patch("commands.wire_connectivity.get_pin_net", return_value=mock_result) as mock_gpn,
        ):
            mock_sch = MagicMock()
            mock_sch.wire = [_make_wire(10.5, 15.2, 11.5, 15.2)]
            mock_load.return_value = mock_sch

            result = handler(
                {"schematicPath": "/tmp/test.kicad_sch", "reference": "U1", "pin": "3"}
            )

        assert result["success"] is True
        mock_gpn.assert_called_once()
        call_args = mock_gpn.call_args
        assert call_args[0][2] == pytest.approx(10.5)
        assert call_args[0][3] == pytest.approx(15.2)

    def test_ref_pin_not_found(self) -> None:
        handler = self._make_handler()
        with patch(
            "commands.pin_locator.PinLocator.get_pin_location",
            return_value=None,
        ):
            result = handler(
                {"schematicPath": "/tmp/test.kicad_sch", "reference": "U1", "pin": "99"}
            )
        assert result["success"] is False
        assert "U1" in result["message"] or "99" in result["message"]

    def test_coordinate_mode_passes_floats(self) -> None:
        handler = self._make_handler()
        mock_result = {
            "net": None,
            "pins": [],
            "wires": [],
            "query_point": {"x": 10.5, "y": 15.2},
        }
        with (
            patch("kicad_interface.SchematicManager.load_schematic") as mock_load,
            patch("commands.wire_connectivity.get_pin_net", return_value=mock_result) as mock_gpn,
        ):
            mock_sch = MagicMock()
            mock_sch.wire = [_make_wire(10.5, 15.2, 11.5, 15.2)]
            mock_load.return_value = mock_sch

            result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": "10.5", "y": "15.2"})

        assert result["success"] is True
        call_args = mock_gpn.call_args
        assert isinstance(call_args[0][2], float)
        assert isinstance(call_args[0][3], float)
        assert call_args[0][2] == pytest.approx(10.5)
        assert call_args[0][3] == pytest.approx(15.2)
