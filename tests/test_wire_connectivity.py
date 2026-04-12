"""
Tests for the wire_connectivity module and the get_wire_connections handler.

Covers:
  - Schema shape (TestSchema)
  - Handler dispatch registration (TestHandlerDispatch)
  - Parameter validation in the handler (TestHandlerParamValidation)
  - Core logic: _to_iu, _parse_wires, _build_adjacency, _find_connected_wires,
    get_wire_connections (TestCoreLogic)
  - New net/query_point fields and reference+pin input mode (TestGetWireConnectionsNewFields,
    TestGetWireConnectionsHandlerRefPinMode)
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure the python package root is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
from commands.wire_connectivity import (
    _build_adjacency,
    _find_connected_wires,
    _parse_wires,
    _to_iu,
    get_wire_connections,
)

# ---------------------------------------------------------------------------
# Helpers to build minimal mock schematic objects
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
    # No net labels, no symbols by default
    del sch.label  # make hasattr(..., "label") return False
    del sch.symbol  # make hasattr(..., "symbol") return False
    return sch


# ---------------------------------------------------------------------------
# TestSchema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSchema:
    """Verify the get_wire_connections tool schema is present and well-formed."""

    def test_schema_registered(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "get_wire_connections" in TOOL_SCHEMAS

    def test_schema_required_fields(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["get_wire_connections"]
        required = schema["inputSchema"]["required"]
        assert "schematicPath" in required
        # x, y and reference, pin are all optional (dual-mode input)
        assert "x" not in required
        assert "y" not in required

    def test_schema_optional_fields(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        props = TOOL_SCHEMAS["get_wire_connections"]["inputSchema"]["properties"]
        assert "reference" in props
        assert "pin" in props
        assert "x" in props
        assert "y" in props

    def test_get_pin_net_not_registered(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "get_pin_net" not in TOOL_SCHEMAS

    def test_schema_has_title_and_description(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["get_wire_connections"]
        assert schema.get("title")
        assert schema.get("description")


# ---------------------------------------------------------------------------
# TestHandlerDispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerDispatch:
    """Verify the handler is wired into KiCadInterface.command_routes."""

    def test_get_wire_connections_in_routes(self) -> None:
        # Import lazily to avoid heavy side-effects at collection time
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

            # Build routes only (avoid full __init__ side-effects)
            # The routes dict is built in __init__; we call it directly.
            KiCADInterface.__init__(iface)

        assert "get_wire_connections" in iface.command_routes
        assert callable(iface.command_routes["get_wire_connections"])


# ---------------------------------------------------------------------------
# TestHandlerParamValidation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerParamValidation:
    """Handler returns error responses for bad or missing parameters."""

    def _make_handler(self) -> Any:
        """Return a bound _handle_get_wire_connections without full init."""
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_get_wire_connections

    def test_missing_schematic_path(self) -> None:
        handler = self._make_handler()
        result = handler({"x": 1.0, "y": 2.0})
        assert result["success"] is False
        assert "schematicPath" in result["message"] or "Missing" in result["message"]

    def test_missing_both_modes(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch"})
        assert result["success"] is False
        assert (
            "reference" in result["message"]
            or "x" in result["message"]
            or "supply" in result["message"].lower()
        )

    def test_partial_reference_without_pin(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "reference": "U1"})
        assert result["success"] is False

    def test_partial_pin_without_reference(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "pin": "3"})
        assert result["success"] is False

    def test_non_numeric_x(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": "bad", "y": 2.0})
        assert result["success"] is False
        assert "numeric" in result["message"].lower() or "x" in result["message"]

    def test_non_numeric_y(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": 1.0, "y": "bad"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestCoreLogic
# ---------------------------------------------------------------------------

_IU = 10_000  # IU per mm


@pytest.mark.unit
class TestCoreLogic:
    """Unit tests for the pure-logic functions in wire_connectivity."""

    # --- _to_iu ---

    def test_to_iu_integer_mm(self) -> None:
        assert _to_iu(1.0, 2.0) == (10_000, 20_000)

    def test_to_iu_fractional_mm(self) -> None:
        assert _to_iu(0.5, 0.25) == (5_000, 2_500)

    def test_to_iu_zero(self) -> None:
        assert _to_iu(0.0, 0.0) == (0, 0)

    def test_to_iu_negative(self) -> None:
        assert _to_iu(-1.0, -2.0) == (-10_000, -20_000)

    # --- _parse_wires ---

    def test_parse_wires_single_wire(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = _parse_wires(sch)
        assert len(result) == 1
        assert result[0] == [(0, 0), (10_000, 0)]

    def test_parse_wires_empty_schematic(self) -> None:
        sch = MagicMock()
        sch.wire = []
        assert _parse_wires(sch) == []

    def test_parse_wires_multiple_wires(self) -> None:
        sch = _make_schematic(
            _make_wire(0.0, 0.0, 1.0, 0.0),
            _make_wire(1.0, 0.0, 2.0, 0.0),
        )
        assert len(_parse_wires(sch)) == 2

    def test_parse_wires_skips_wire_without_pts(self) -> None:
        bad_wire = MagicMock(spec=[])  # no `pts` attribute
        sch = MagicMock()
        sch.wire = [bad_wire]
        assert _parse_wires(sch) == []

    # --- _build_adjacency ---

    def test_build_adjacency_two_connected_wires(self) -> None:
        # wire0: (0,0)-(1,0), wire1: (1,0)-(2,0) — share endpoint (1,0)
        wires = [
            [(0, 0), (10_000, 0)],
            [(10_000, 0), (20_000, 0)],
        ]
        adjacency, iu_to_wires = _build_adjacency(wires)
        assert 1 in adjacency[0]
        assert 0 in adjacency[1]

    def test_build_adjacency_two_disconnected_wires(self) -> None:
        wires = [
            [(0, 0), (10_000, 0)],
            [(20_000, 0), (30_000, 0)],
        ]
        adjacency, _ = _build_adjacency(wires)
        assert adjacency[0] == set()
        assert adjacency[1] == set()

    def test_build_adjacency_iu_to_wires_maps_correctly(self) -> None:
        wires = [
            [(0, 0), (10_000, 0)],
            [(10_000, 0), (20_000, 0)],
        ]
        _, iu_to_wires = _build_adjacency(wires)
        assert iu_to_wires[(10_000, 0)] == {0, 1}
        assert iu_to_wires[(0, 0)] == {0}

    def test_build_adjacency_three_wires_at_junction(self) -> None:
        # All three wires meet at (10,000, 0)
        wires = [
            [(0, 0), (10_000, 0)],
            [(10_000, 0), (20_000, 0)],
            [(10_000, 0), (10_000, 10_000)],
        ]
        adjacency, _ = _build_adjacency(wires)
        assert adjacency[0] == {1, 2}
        assert adjacency[1] == {0, 2}
        assert adjacency[2] == {0, 1}

    # --- _find_connected_wires ---

    def test_find_connected_wires_no_wire_at_point(self) -> None:
        wires = [[(0, 0), (10_000, 0)]]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, net_points = _find_connected_wires(5.0, 0.0, wires, iu_to_wires, adjacency)
        assert visited is None
        assert net_points is None

    def test_find_connected_wires_single_wire(self) -> None:
        wires = [[(0, 0), (10_000, 0)]]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, net_points = _find_connected_wires(0.0, 0.0, wires, iu_to_wires, adjacency)
        assert visited == {0}
        assert (0, 0) in net_points
        assert (10_000, 0) in net_points

    def test_find_connected_wires_flood_fills_chain(self) -> None:
        # Three wires in a chain: A-B-C-D
        wires = [
            [(0, 0), (10_000, 0)],
            [(10_000, 0), (20_000, 0)],
            [(20_000, 0), (30_000, 0)],
        ]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, net_points = _find_connected_wires(0.0, 0.0, wires, iu_to_wires, adjacency)
        assert visited == {0, 1, 2}

    def test_find_connected_wires_does_not_cross_gap(self) -> None:
        # Two disconnected segments; query on segment 0 should not reach segment 1
        wires = [
            [(0, 0), (10_000, 0)],
            [(20_000, 0), (30_000, 0)],
        ]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, _ = _find_connected_wires(0.0, 0.0, wires, iu_to_wires, adjacency)
        assert visited == {0}

    # --- get_wire_connections (integration of internal functions) ---

    def test_get_wire_connections_no_wires(self) -> None:
        sch = MagicMock()
        sch.wire = []
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert result["pins"] == []
        assert result["wires"] == []
        assert result["net"] is None
        assert result["query_point"] == {"x": 0.0, "y": 0.0}

    def test_get_wire_connections_no_wire_at_point_returns_none(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 5.0, 0.0)
        assert result is None

    def test_get_wire_connections_returns_wire_data(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert result["pins"] == []
        assert len(result["wires"]) == 1
        wire = result["wires"][0]
        assert wire["start"] == {"x": 0.0, "y": 0.0}
        assert wire["end"] == {"x": 1.0, "y": 0.0}
        assert "net" in result
        assert "query_point" in result

    def test_get_wire_connections_chain_returns_all_wires(self) -> None:
        sch = _make_schematic(
            _make_wire(0.0, 0.0, 1.0, 0.0),
            _make_wire(1.0, 0.0, 2.0, 0.0),
        )
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert len(result["wires"]) == 2


# ---------------------------------------------------------------------------
# TestGetWireConnectionsNewFields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWireConnectionsNewFields:
    """Verify net and query_point are present in all return paths."""

    def test_net_field_present_when_no_wires(self) -> None:
        sch = MagicMock()
        sch.wire = []
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 1.0, 2.0)
        assert result is not None
        assert "net" in result
        assert result["net"] is None

    def test_query_point_echoed_when_no_wires(self) -> None:
        sch = MagicMock()
        sch.wire = []
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 3.5, 7.25)
        assert result is not None
        assert result["query_point"] == {"x": 3.5, "y": 7.25}

    def test_net_is_none_for_unnamed_net(self) -> None:
        # Wire with no labels → net should be None
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert result["net"] is None

    def test_query_point_echoed_with_wire(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert result["query_point"] == {"x": 0.0, "y": 0.0}

    def test_net_none_returned_when_no_wire_at_point(self) -> None:
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 5.0, 0.0)
        assert result is None  # no match at midpoint


# ---------------------------------------------------------------------------
# TestGetWireConnectionsHandlerRefPinMode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWireConnectionsHandlerRefPinMode:
    """Handler correctly resolves reference+pin to coordinates via PinLocator."""

    def _make_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_get_wire_connections

    def test_ref_pin_resolves_to_coordinates(self) -> None:
        handler = self._make_handler()
        mock_result = {
            "net": "VCC",
            "pins": [],
            "wires": [],
            "query_point": {"x": 10.0, "y": 20.0},
        }
        with (
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=(10.0, 20.0),
            ),
            patch("commands.wire_connectivity.get_wire_connections", return_value=mock_result),
            patch(
                "kicad_interface.SchematicManager.load_schematic",
                return_value=MagicMock(wire=[MagicMock()]),
            ),
        ):
            result = handler(
                {"schematicPath": "/fake/path.kicad_sch", "reference": "U1", "pin": "3"}
            )
        assert result["success"] is True

    def test_ref_pin_not_found_returns_error(self) -> None:
        handler = self._make_handler()
        with patch(
            "commands.pin_locator.PinLocator.get_pin_location",
            return_value=None,
        ):
            result = handler(
                {"schematicPath": "/fake/path.kicad_sch", "reference": "U1", "pin": "99"}
            )
        assert result["success"] is False
        assert "99" in result["message"] or "U1" in result["message"]

    def test_missing_both_modes_returns_error(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/fake/path.kicad_sch"})
        assert result["success"] is False

    def test_partial_reference_without_pin_returns_error(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/fake/path.kicad_sch", "reference": "U1"})
        assert result["success"] is False

    def test_partial_pin_without_reference_returns_error(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/fake/path.kicad_sch", "pin": "3"})
        assert result["success"] is False

    def test_get_pin_net_not_in_routes(self) -> None:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
            KiCADInterface.__init__(iface)
        assert "get_pin_net" not in iface.command_routes
