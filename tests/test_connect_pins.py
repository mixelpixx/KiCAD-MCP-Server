"""
Tests for ConnectionManager.connect_pins, connect_component_to_nets,
get_pin_net, and handler dispatch.

Covers:
  - connect_pins: empty pins, no net found, explicit netName, auto-discovery,
    human-net priority, conflict detection, already-connected, conflicting pin
  - connect_component_to_nets: empty connections, already-connected,
    conflicting net, successful connection
  - Schema: connect_pins and connect_component_to_nets in TOOL_SCHEMAS
  - Handler dispatch: both tools registered on KiCADInterface
  - _handle_connect_pins with missing schematicPath → success=False
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_iface():
    """Construct a bare KiCADInterface without calling __init__."""
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

    iface = KiCADInterface.__new__(KiCADInterface)
    iface.board = None
    return iface


# Fake schematic path — ConnectionManager.connect_pins doesn't read the file
# when get_pin_net and connect_to_net are mocked.
_FAKE_SCH = Path("/fake/test.kicad_sch")


# ===========================================================================
# Schema tests
# ===========================================================================


@pytest.mark.unit
class TestConnectPinsSchema:
    def test_connect_pins_in_tool_schemas(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "connect_pins" in TOOL_SCHEMAS

    def test_connect_component_to_nets_in_tool_schemas(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "connect_component_to_nets" in TOOL_SCHEMAS

    def test_connect_pins_requires_schematic_path_and_pins(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["connect_pins"]
        required = schema["inputSchema"].get("required", [])
        assert "schematicPath" in required
        assert "pins" in required

    def test_connect_pins_net_name_is_optional(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["connect_pins"]
        required = schema["inputSchema"].get("required", [])
        assert "netName" not in required


# ===========================================================================
# Handler dispatch tests
# ===========================================================================


@pytest.mark.unit
class TestConnectPinsHandlerDispatch:
    def test_connect_pins_handler_registered(self):
        iface = _make_iface()
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

        # Re-create with init to populate handlers dict by calling _setup_handlers
        # Instead verify handler exists as method
        assert hasattr(iface, "_handle_connect_pins")
        assert callable(iface._handle_connect_pins)

    def test_connect_component_to_nets_handler_registered(self):
        iface = _make_iface()
        assert hasattr(iface, "_handle_connect_component_to_nets")
        assert callable(iface._handle_connect_component_to_nets)

    def test_handle_connect_pins_missing_schematic_path(self):
        iface = _make_iface()
        result = iface._handle_connect_pins({})
        assert result["success"] is False
        assert "schematicPath" in result["message"] or "schematic" in result["message"].lower()

    def test_handle_connect_pins_missing_pins(self):
        iface = _make_iface()
        result = iface._handle_connect_pins({"schematicPath": "/fake.kicad_sch"})
        assert result["success"] is False

    def test_handle_connect_component_to_nets_missing_schematic(self):
        iface = _make_iface()
        result = iface._handle_connect_component_to_nets({})
        assert result["success"] is False

    def test_handle_connect_component_to_nets_missing_component_ref(self):
        iface = _make_iface()
        result = iface._handle_connect_component_to_nets({"schematicPath": "/fake.kicad_sch"})
        assert result["success"] is False


# ===========================================================================
# Unit tests — ConnectionManager.connect_pins
# ===========================================================================


@pytest.mark.unit
class TestConnectPins:
    @property
    def _CM(self):
        from commands.connection_schematic import ConnectionManager

        return ConnectionManager

    def test_empty_pins_returns_failure(self):
        result = self._CM.connect_pins(_FAKE_SCH, [])
        assert result["success"] is False
        assert "empty" in result["message"].lower()

    def test_no_existing_net_and_no_net_name_returns_failure(self):
        pins = [{"ref": "R1", "pin": "1"}, {"ref": "R1", "pin": "2"}]
        with patch.object(self._CM, "get_pin_net", return_value=None):
            result = self._CM.connect_pins(_FAKE_SCH, pins)
        assert result["success"] is False
        assert (
            "no existing net" in result["message"].lower()
            or "netName" in result["message"]
            or "no existing" in result["message"].lower()
        )

    def test_explicit_net_name_used(self):
        pins = [{"ref": "R1", "pin": "1"}, {"ref": "C1", "pin": "1"}]
        with (
            patch.object(self._CM, "get_pin_net", return_value=None),
            patch.object(self._CM, "connect_to_net", return_value={"success": True}),
        ):
            result = self._CM.connect_pins(_FAKE_SCH, pins, net_name="VCC")
        assert result["success"] is True
        assert result["net_used"] == "VCC"
        assert len(result["connected"]) == 2

    def test_auto_discovers_existing_net(self):
        pins = [{"ref": "R1", "pin": "1"}, {"ref": "C1", "pin": "1"}]

        def _get_pin_net(sch, ref, pin):
            if ref == "R1" and pin == "1":
                return "VCC"
            return None

        with (
            patch.object(self._CM, "get_pin_net", side_effect=_get_pin_net),
            patch.object(self._CM, "connect_to_net", return_value={"success": True}),
        ):
            result = self._CM.connect_pins(_FAKE_SCH, pins)

        assert result["success"] is True
        assert result["net_used"] == "VCC"

    def test_human_net_takes_priority_over_auto_generated(self):
        pins = [{"ref": "R1", "pin": "1"}, {"ref": "R2", "pin": "1"}]

        def _get_pin_net(sch, ref, pin):
            if ref == "R1":
                return "VCC"
            if ref == "R2":
                return "Net-(R2-Pad1)"
            return None

        with (
            patch.object(self._CM, "get_pin_net", side_effect=_get_pin_net),
            patch.object(self._CM, "connect_to_net", return_value={"success": True}),
        ):
            result = self._CM.connect_pins(_FAKE_SCH, pins)

        # "VCC" is human-readable; "Net-(R2-Pad1)" is auto-generated → VCC wins
        assert result["net_used"] == "VCC"

    def test_two_different_human_nets_returns_conflict_failure(self):
        pins = [{"ref": "R1", "pin": "1"}, {"ref": "R2", "pin": "1"}]

        def _get_pin_net(sch, ref, pin):
            if ref == "R1":
                return "VCC"
            if ref == "R2":
                return "GND"
            return None

        with patch.object(self._CM, "get_pin_net", side_effect=_get_pin_net):
            result = self._CM.connect_pins(_FAKE_SCH, pins)

        assert result["success"] is False
        assert "conflicting_nets" in result
        assert set(result["conflicting_nets"]) == {"VCC", "GND"}

    def test_already_connected_pin_in_already_connected_list(self):
        pins = [{"ref": "R1", "pin": "1"}, {"ref": "C1", "pin": "1"}]

        def _get_pin_net(sch, ref, pin):
            if ref == "R1":
                return "VCC"
            return None

        with (
            patch.object(self._CM, "get_pin_net", side_effect=_get_pin_net),
            patch.object(self._CM, "connect_to_net", return_value={"success": True}),
        ):
            result = self._CM.connect_pins(_FAKE_SCH, pins, net_name="VCC")

        assert "R1/1" in result["already_connected"]
        assert "R1/1" not in result["connected"]

    def test_pin_on_different_existing_net_goes_to_failed(self):
        pins = [{"ref": "R1", "pin": "1"}, {"ref": "C1", "pin": "1"}]

        def _get_pin_net(sch, ref, pin):
            if ref == "C1":
                return "GND"  # conflicts with target "VCC"
            return None

        with (
            patch.object(self._CM, "get_pin_net", side_effect=_get_pin_net),
            patch.object(self._CM, "connect_to_net", return_value={"success": True}),
        ):
            result = self._CM.connect_pins(_FAKE_SCH, pins, net_name="VCC")

        failed_pins = [f["pin"] for f in result["failed"]]
        assert "C1/1" in failed_pins

    def test_connect_to_net_failure_goes_to_failed(self):
        pins = [{"ref": "R1", "pin": "1"}]

        with (
            patch.object(self._CM, "get_pin_net", return_value=None),
            patch.object(
                self._CM,
                "connect_to_net",
                return_value={"success": False, "message": "pin not found"},
            ),
        ):
            result = self._CM.connect_pins(_FAKE_SCH, pins, net_name="VCC")

        assert result["success"] is False
        assert len(result["failed"]) == 1

    def test_wire_manager_unavailable_returns_failure(self):
        import commands.connection_schematic as cm_mod

        original = cm_mod.WIRE_MANAGER_AVAILABLE
        try:
            cm_mod.WIRE_MANAGER_AVAILABLE = False
            result = self._CM.connect_pins(_FAKE_SCH, [{"ref": "R1", "pin": "1"}])
            assert result["success"] is False
        finally:
            cm_mod.WIRE_MANAGER_AVAILABLE = original


# ===========================================================================
# Unit tests — ConnectionManager.connect_component_to_nets
# ===========================================================================


@pytest.mark.unit
class TestConnectComponentToNets:
    @property
    def _CM(self):
        from commands.connection_schematic import ConnectionManager

        return ConnectionManager

    def test_empty_connections_returns_failure(self):
        result = self._CM.connect_component_to_nets(_FAKE_SCH, "U1", {})
        assert result["success"] is False

    def test_already_connected_pin_in_already_connected_list(self):
        # Pin "1" already on "GND" — passing "GND" again → already_connected
        connections = {"1": "GND"}

        with patch.object(self._CM, "get_pin_net", return_value="GND"):
            result = self._CM.connect_component_to_nets(_FAKE_SCH, "R1", connections)

        assert "R1/1" in result["already_connected"]
        assert result["success"] is True

    def test_pin_on_different_net_goes_to_failed(self):
        connections = {"1": "VCC"}

        with patch.object(self._CM, "get_pin_net", return_value="GND"):
            result = self._CM.connect_component_to_nets(_FAKE_SCH, "R1", connections)

        assert result["success"] is False
        assert any(f["pin"] == "R1/1" for f in result["failed"])

    def test_successful_connection_in_connected_list(self):
        connections = {"8": "VCC"}

        with (
            patch.object(self._CM, "get_pin_net", return_value=None),
            patch.object(self._CM, "connect_to_net", return_value={"success": True}),
        ):
            result = self._CM.connect_component_to_nets(_FAKE_SCH, "U1", connections)

        assert result["success"] is True
        assert any("U1/8" in entry for entry in result["connected"])

    def test_multiple_pins_mixed_result(self):
        connections = {"1": "GND", "8": "VCC", "3": "OUTPUT"}

        def _get_pin_net(sch, ref, pin):
            if pin == "1":
                return "GND"  # already connected
            if pin == "8":
                return "3V3"  # conflicts
            return None  # needs connecting

        with (
            patch.object(self._CM, "get_pin_net", side_effect=_get_pin_net),
            patch.object(self._CM, "connect_to_net", return_value={"success": True}),
        ):
            result = self._CM.connect_component_to_nets(_FAKE_SCH, "U1", connections)

        assert "U1/1" in result["already_connected"]
        assert any(f["pin"] == "U1/8" for f in result["failed"])
        assert any("U1/3" in entry for entry in result["connected"])
        # Has a failed entry → success=False
        assert result["success"] is False

    def test_wire_manager_unavailable_returns_failure(self):
        import commands.connection_schematic as cm_mod

        original = cm_mod.WIRE_MANAGER_AVAILABLE
        try:
            cm_mod.WIRE_MANAGER_AVAILABLE = False
            result = self._CM.connect_component_to_nets(_FAKE_SCH, "U1", {"1": "VCC"})
            assert result["success"] is False
        finally:
            cm_mod.WIRE_MANAGER_AVAILABLE = original
