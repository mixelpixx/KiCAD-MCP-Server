"""
Tests for the wire_connectivity module and the get_wire_connections handler.

Covers:
  - Schema shape (TestSchema)
  - Handler dispatch registration (TestHandlerDispatch)
  - Parameter validation in the handler (TestHandlerParamValidation)
  - Core logic: _to_iu, _parse_wires, _build_adjacency, _find_connected_wires,
    get_wire_connections (TestCoreLogic)
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure the python package root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

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


def _make_schematic(*wires) -> MagicMock:
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

    def test_schema_registered(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "get_wire_connections" in TOOL_SCHEMAS

    def test_schema_required_fields(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["get_wire_connections"]
        required = schema["inputSchema"]["required"]
        assert "schematicPath" in required
        assert "x" in required
        assert "y" in required

    def test_schema_has_title_and_description(self):
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

    def test_get_wire_connections_in_routes(self):
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
            iface.__init__()

        assert "get_wire_connections" in iface.command_routes
        assert callable(iface.command_routes["get_wire_connections"])


# ---------------------------------------------------------------------------
# TestHandlerParamValidation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerParamValidation:
    """Handler returns error responses for bad or missing parameters."""

    def _make_handler(self):
        """Return a bound _handle_get_wire_connections without full init."""
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_get_wire_connections

    def test_missing_schematic_path(self):
        handler = self._make_handler()
        result = handler({"x": 1.0, "y": 2.0})
        assert result["success"] is False
        assert "schematicPath" in result["message"] or "Missing" in result["message"]

    def test_missing_x(self):
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "y": 2.0})
        assert result["success"] is False

    def test_missing_y(self):
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": 1.0})
        assert result["success"] is False

    def test_non_numeric_x(self):
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": "bad", "y": 2.0})
        assert result["success"] is False
        assert "numeric" in result["message"].lower() or "x" in result["message"]

    def test_non_numeric_y(self):
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

    def test_to_iu_integer_mm(self):
        assert _to_iu(1.0, 2.0) == (10_000, 20_000)

    def test_to_iu_fractional_mm(self):
        assert _to_iu(0.5, 0.25) == (5_000, 2_500)

    def test_to_iu_zero(self):
        assert _to_iu(0.0, 0.0) == (0, 0)

    def test_to_iu_negative(self):
        assert _to_iu(-1.0, -2.0) == (-10_000, -20_000)

    # --- _parse_wires ---

    def test_parse_wires_single_wire(self):
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = _parse_wires(sch)
        assert len(result) == 1
        assert result[0] == [(0, 0), (10_000, 0)]

    def test_parse_wires_empty_schematic(self):
        sch = MagicMock()
        sch.wire = []
        assert _parse_wires(sch) == []

    def test_parse_wires_multiple_wires(self):
        sch = _make_schematic(
            _make_wire(0.0, 0.0, 1.0, 0.0),
            _make_wire(1.0, 0.0, 2.0, 0.0),
        )
        assert len(_parse_wires(sch)) == 2

    def test_parse_wires_skips_wire_without_pts(self):
        bad_wire = MagicMock(spec=[])  # no `pts` attribute
        sch = MagicMock()
        sch.wire = [bad_wire]
        assert _parse_wires(sch) == []

    # --- _build_adjacency ---

    def test_build_adjacency_two_connected_wires(self):
        # wire0: (0,0)-(1,0), wire1: (1,0)-(2,0) — share endpoint (1,0)
        wires = [
            [(0, 0), (10_000, 0)],
            [(10_000, 0), (20_000, 0)],
        ]
        adjacency, iu_to_wires = _build_adjacency(wires)
        assert 1 in adjacency[0]
        assert 0 in adjacency[1]

    def test_build_adjacency_two_disconnected_wires(self):
        wires = [
            [(0, 0), (10_000, 0)],
            [(20_000, 0), (30_000, 0)],
        ]
        adjacency, _ = _build_adjacency(wires)
        assert adjacency[0] == set()
        assert adjacency[1] == set()

    def test_build_adjacency_iu_to_wires_maps_correctly(self):
        wires = [
            [(0, 0), (10_000, 0)],
            [(10_000, 0), (20_000, 0)],
        ]
        _, iu_to_wires = _build_adjacency(wires)
        assert iu_to_wires[(10_000, 0)] == {0, 1}
        assert iu_to_wires[(0, 0)] == {0}

    def test_build_adjacency_three_wires_at_junction(self):
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

    def test_find_connected_wires_no_wire_at_point(self):
        wires = [[(0, 0), (10_000, 0)]]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, net_points = _find_connected_wires(
            5.0, 0.0, wires, iu_to_wires, adjacency
        )
        assert visited is None
        assert net_points is None

    def test_find_connected_wires_single_wire(self):
        wires = [[(0, 0), (10_000, 0)]]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, net_points = _find_connected_wires(
            0.0, 0.0, wires, iu_to_wires, adjacency
        )
        assert visited == {0}
        assert (0, 0) in net_points
        assert (10_000, 0) in net_points

    def test_find_connected_wires_flood_fills_chain(self):
        # Three wires in a chain: A-B-C-D
        wires = [
            [(0, 0), (10_000, 0)],
            [(10_000, 0), (20_000, 0)],
            [(20_000, 0), (30_000, 0)],
        ]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, net_points = _find_connected_wires(
            0.0, 0.0, wires, iu_to_wires, adjacency
        )
        assert visited == {0, 1, 2}

    def test_find_connected_wires_does_not_cross_gap(self):
        # Two disconnected segments; query on segment 0 should not reach segment 1
        wires = [
            [(0, 0), (10_000, 0)],
            [(20_000, 0), (30_000, 0)],
        ]
        adjacency, iu_to_wires = _build_adjacency(wires)
        visited, _ = _find_connected_wires(0.0, 0.0, wires, iu_to_wires, adjacency)
        assert visited == {0}

    # --- get_wire_connections (integration of internal functions) ---

    def test_get_wire_connections_no_wires(self):
        sch = MagicMock()
        sch.wire = []
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result == {"pins": [], "wires": []}

    def test_get_wire_connections_no_wire_at_point_returns_none(self):
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 5.0, 0.0)
        assert result is None

    def test_get_wire_connections_returns_wire_data(self):
        sch = _make_schematic(_make_wire(0.0, 0.0, 1.0, 0.0))
        # Prevent _find_pins_on_net from iterating symbols
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert result["pins"] == []
        assert len(result["wires"]) == 1
        wire = result["wires"][0]
        assert wire["start"] == {"x": 0.0, "y": 0.0}
        assert wire["end"] == {"x": 1.0, "y": 0.0}

    def test_get_wire_connections_chain_returns_all_wires(self):
        sch = _make_schematic(
            _make_wire(0.0, 0.0, 1.0, 0.0),
            _make_wire(1.0, 0.0, 2.0, 0.0),
        )
        result = get_wire_connections(sch, "/fake/path.kicad_sch", 0.0, 0.0)
        assert result is not None
        assert len(result["wires"]) == 2
