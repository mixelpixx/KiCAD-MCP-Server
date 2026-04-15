"""
Tests for net label pin-snapping and connect_to_net richer response.

Covers:
  - add_schematic_net_label with componentRef+pinNumber snaps to exact pin coords
  - add_schematic_net_label without position and without pin ref returns error
  - add_schematic_net_label with unknown pin returns an informative error
  - connect_to_net returns pin_location, label_location, wire_stub on success
  - connect_to_net returns success=False with message on failure
  - connect_passthrough uses new dict return from connect_to_net correctly
  - tool_schemas.py reflects new optional fields
"""

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup – mirror existing test files
# ---------------------------------------------------------------------------

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    """Return a KiCADInterface instance with __init__ stubbed out."""
    for mod in ["pcbnew", "skip"]:
        sys.modules.setdefault(mod, types.ModuleType(mod))
    from kicad_interface import KiCADInterface

    with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
        return KiCADInterface.__new__(KiCADInterface)


# ---------------------------------------------------------------------------
# 1. Schema tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddNetLabelSchema:
    """Verify tool_schemas.py reflects the new add_schematic_net_label API."""

    @pytest.fixture(autouse=True)
    def load_schemas(self) -> Any:
        from schemas.tool_schemas import SCHEMATIC_TOOLS

        self.tools = {t["name"]: t for t in SCHEMATIC_TOOLS}

    def test_position_is_optional(self) -> None:
        schema = self.tools["add_schematic_net_label"]["inputSchema"]
        assert "position" not in schema["required"], "position must not be required"

    def test_component_ref_property_exists(self) -> None:
        schema = self.tools["add_schematic_net_label"]["inputSchema"]
        assert "componentRef" in schema["properties"]

    def test_pin_number_property_exists(self) -> None:
        schema = self.tools["add_schematic_net_label"]["inputSchema"]
        assert "pinNumber" in schema["properties"]

    def test_only_schematic_path_and_net_name_required(self) -> None:
        schema = self.tools["add_schematic_net_label"]["inputSchema"]
        assert set(schema["required"]) == {"schematicPath", "netName"}


@pytest.mark.unit
class TestConnectToNetSchema:
    """Verify tool_schemas.py reflects the richer connect_to_net description."""

    @pytest.fixture(autouse=True)
    def load_schemas(self) -> Any:
        from schemas.tool_schemas import SCHEMATIC_TOOLS

        self.tools = {t["name"]: t for t in SCHEMATIC_TOOLS}

    def test_description_mentions_pin_location(self) -> None:
        desc = self.tools["connect_to_net"]["description"]
        assert "pin_location" in desc

    def test_description_mentions_label_location(self) -> None:
        desc = self.tools["connect_to_net"]["description"]
        assert "label_location" in desc


# ---------------------------------------------------------------------------
# 2. _handle_add_schematic_net_label – unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleAddSchematicNetLabelSnapping:
    """Unit tests for the pin-snapping path of _handle_add_schematic_net_label."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Any:
        self.iface = _make_iface()

    # -- happy-path: snap to pin -----------------------------------------

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.pin_locator.PinLocator.get_pin_location", return_value=[42.0, 13.5])
    def test_snap_uses_pin_coords(self, mock_pin_loc: Any, mock_add_label: Any) -> None:
        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "VCC",
                "componentRef": "U1",
                "pinNumber": "1",
            }
        )
        assert result["success"] is True
        assert result["actual_position"] == [42.0, 13.5]
        assert result["snapped_to_pin"] == {"component": "U1", "pin": "1"}
        # WireManager.add_label must have been called with the pin coords
        mock_add_label.assert_called_once()
        call_args = mock_add_label.call_args
        assert call_args[0][2] == [42.0, 13.5]  # position positional arg

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.pin_locator.PinLocator.get_pin_location", return_value=[10.0, 20.0])
    def test_snap_ignores_provided_position(self, mock_pin_loc: Any, mock_add_label: Any) -> None:
        """If both position and componentRef/pinNumber are given, pin coords win."""
        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "GND",
                "position": [999.0, 999.0],
                "componentRef": "R1",
                "pinNumber": "2",
            }
        )
        assert result["success"] is True
        assert result["actual_position"] == [10.0, 20.0]

    # -- error: pin not found --------------------------------------------

    @patch("commands.pin_locator.PinLocator.get_pin_location", return_value=None)
    def test_snap_unknown_pin_returns_error(self, mock_pin_loc: Any) -> None:
        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "VCC",
                "componentRef": "U99",
                "pinNumber": "99",
            }
        )
        assert result["success"] is False
        assert "U99" in result["message"] or "pin" in result["message"].lower()

    # -- error: no position and no pin ref --------------------------------

    def test_no_position_no_ref_returns_error(self) -> None:
        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "VCC",
            }
        )
        assert result["success"] is False
        assert "position" in result["message"].lower() or "componentRef" in result["message"]

    # -- happy-path: explicit position ------------------------------------

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    def test_explicit_position_used_when_no_ref(self, mock_add_label: Any) -> None:
        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "CLK",
                "position": [55.0, 77.0],
            }
        )
        assert result["success"] is True
        assert result["actual_position"] == [55.0, 77.0]
        assert "snapped_to_pin" not in result

    # -- missing required params -----------------------------------------

    def test_missing_net_name_returns_error(self) -> None:
        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "position": [10.0, 20.0],
            }
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 3. connect_to_net – unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectToNetRicherResponse:
    """connect_to_net now returns coordinates instead of a bare bool."""

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.wire_manager.WireManager.add_wire", return_value=True)
    @patch("commands.pin_locator.PinLocator.get_pin_angle", return_value=0.0)
    @patch("commands.pin_locator.PinLocator.get_pin_location", return_value=[100.0, 50.0])
    def test_success_returns_coordinates(
        self,
        mock_pin_loc: Any,
        mock_pin_angle: Any,
        mock_add_wire: Any,
        mock_add_label: Any,
    ) -> None:
        from commands.connection_schematic import ConnectionManager

        result = ConnectionManager.connect_to_net(Path("/fake/sch.kicad_sch"), "U1", "5", "VCC")
        assert result["success"] is True
        assert result["pin_location"] == [100.0, 50.0]
        assert "label_location" in result
        assert "wire_stub" in result
        # wire_stub is [[pin_x, pin_y], [label_x, label_y]]
        assert result["wire_stub"][0] == [100.0, 50.0]
        assert result["wire_stub"][1] == result["label_location"]

    @patch("commands.pin_locator.PinLocator.get_pin_location", return_value=None)
    def test_unknown_pin_returns_failure_dict(self, mock_pin_loc: Any) -> None:
        from commands.connection_schematic import ConnectionManager

        result = ConnectionManager.connect_to_net(Path("/fake/sch.kicad_sch"), "U99", "99", "VCC")
        assert result["success"] is False
        assert "message" in result

    @patch("commands.wire_manager.WireManager.add_wire", return_value=False)
    @patch("commands.pin_locator.PinLocator.get_pin_angle", return_value=0.0)
    @patch("commands.pin_locator.PinLocator.get_pin_location", return_value=[10.0, 20.0])
    def test_wire_failure_returns_failure_dict(
        self, mock_pin_loc: Any, mock_pin_angle: Any, mock_add_wire: Any
    ) -> None:
        from commands.connection_schematic import ConnectionManager

        result = ConnectionManager.connect_to_net(Path("/fake/sch.kicad_sch"), "R1", "1", "GND")
        assert result["success"] is False
        assert "message" in result


# ---------------------------------------------------------------------------
# 4. connect_passthrough – uses dict return correctly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectPassthroughUsesDict:
    """connect_passthrough must handle the dict returned by connect_to_net."""

    @patch(
        "commands.connection_schematic.ConnectionManager.connect_to_net",
        return_value={
            "success": True,
            "pin_location": [0, 0],
            "label_location": [2.54, 0],
            "wire_stub": [[0, 0], [2.54, 0]],
            "message": "ok",
        },
    )
    @patch(
        "commands.pin_locator.PinLocator.get_all_symbol_pins",
        side_effect=[{"1": [0.0, 0.0]}, {"1": [10.0, 10.0]}],
    )
    def test_passthrough_succeeds_with_dict_return(self, mock_pins: Any, mock_connect: Any) -> None:
        from commands.connection_schematic import ConnectionManager

        result = ConnectionManager.connect_passthrough(
            Path("/fake/sch.kicad_sch"), "J1", "J2", net_prefix="PIN"
        )
        assert len(result["connected"]) == 1
        assert len(result["failed"]) == 0

    @patch(
        "commands.connection_schematic.ConnectionManager.connect_to_net",
        return_value={"success": False, "message": "pin not found"},
    )
    @patch(
        "commands.pin_locator.PinLocator.get_all_symbol_pins",
        side_effect=[{"1": [0.0, 0.0]}, {"1": [10.0, 10.0]}],
    )
    def test_passthrough_records_failure_with_dict_return(
        self, mock_pins: Any, mock_connect: Any
    ) -> None:
        from commands.connection_schematic import ConnectionManager

        result = ConnectionManager.connect_passthrough(
            Path("/fake/sch.kicad_sch"), "J1", "J2", net_prefix="PIN"
        )
        assert len(result["failed"]) >= 1
