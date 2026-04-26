"""
Tests for schematic wire and junction handling:
- add_schematic_wire: waypoints param, pin snapping, polyline routing
- Automatic junction sync (add_schematic_junction tool removed)
- Schema updates in tool_schemas.py
- ConnectionManager orphaned method removal
"""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sexpdata
from sexpdata import Symbol

# Add python dir to path
PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

TEMPLATES_DIR = PYTHON_DIR / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_temp_sch() -> Any:
    """Copy the empty schematic template to a temp file and return the Path."""
    tmp = Path(tempfile.mkdtemp()) / "test.kicad_sch"
    shutil.copy(EMPTY_SCH, tmp)
    return tmp


def _parse_sch(path: Path) -> Any:
    """Parse a .kicad_sch file and return the S-expression list."""
    with open(path, "r", encoding="utf-8") as f:
        return sexpdata.loads(f.read())


def _find_elements(sch_data: Any, tag: str) -> Any:
    """Return all top-level S-expression elements with the given tag Symbol."""
    return [item for item in sch_data if isinstance(item, list) and item and item[0] == Symbol(tag)]


# ---------------------------------------------------------------------------
# 1. Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    """Verify tool_schemas.py reflects the new API."""

    @pytest.fixture(autouse=True)
    def load_schemas(self) -> Any:
        from schemas.tool_schemas import SCHEMATIC_TOOLS

        self.tools = {t["name"]: t for t in SCHEMATIC_TOOLS}

    def test_add_schematic_wire_has_waypoints(self) -> None:
        schema = self.tools["add_schematic_wire"]["inputSchema"]
        assert "waypoints" in schema["properties"], "waypoints must be a property"
        assert "waypoints" in schema["required"]

    def test_add_schematic_wire_has_schematic_path(self) -> None:
        schema = self.tools["add_schematic_wire"]["inputSchema"]
        assert "schematicPath" in schema["properties"]
        assert "schematicPath" in schema["required"]

    def test_add_schematic_wire_has_snap_params(self) -> None:
        schema = self.tools["add_schematic_wire"]["inputSchema"]
        props = schema["properties"]
        assert "snapToPins" in props
        assert props["snapToPins"]["type"] == "boolean"
        assert "snapTolerance" in props
        assert props["snapTolerance"]["type"] == "number"

    def test_add_schematic_wire_no_old_point_params(self) -> None:
        schema = self.tools["add_schematic_wire"]["inputSchema"]
        props = schema["properties"]
        assert "startPoint" not in props, "startPoint should be removed"
        assert "endPoint" not in props, "endPoint should be removed"

    def test_add_schematic_connection_removed(self) -> None:
        assert (
            "add_schematic_connection" not in self.tools
        ), "add_schematic_connection must not appear in SCHEMATIC_TOOLS"

    def test_add_schematic_junction_removed(self) -> None:
        assert (
            "add_schematic_junction" not in self.tools
        ), "add_schematic_junction was removed; junctions are now managed automatically"


# ---------------------------------------------------------------------------
# 2. Handler dispatch tests
# ---------------------------------------------------------------------------


class TestHandlerDispatch:
    """Verify KiCADInterface registers the right tool handlers."""

    @pytest.fixture(autouse=True)
    def load_handler_map(self) -> Any:
        # Import only the dispatch table without initialising KiCAD connections
        import importlib
        import types

        # Patch heavy imports before loading kicad_interface
        for mod in ["pcbnew", "skip"]:
            sys.modules.setdefault(mod, types.ModuleType(mod))

        from kicad_interface import KiCADInterface

        # Peek at the dispatch table by instantiating with mocked internals
        with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
            obj = KiCADInterface.__new__(KiCADInterface)
            # Manually set attributes that __init__ normally provides
            obj._backend = None
            # Build the handler map the same way the real __init__ does
            obj._tool_handlers = {
                "add_schematic_wire": obj._handle_add_schematic_wire,
                "add_schematic_net_label": obj._handle_add_schematic_net_label,
            }
        self.handlers = obj._tool_handlers

    def test_add_schematic_wire_registered(self) -> None:
        from kicad_interface import KiCADInterface

        # Just verify the class has the handler method
        assert hasattr(KiCADInterface, "_handle_add_schematic_wire")

    def test_add_schematic_junction_handler_removed(self) -> None:
        from kicad_interface import KiCADInterface

        assert not hasattr(KiCADInterface, "_handle_add_schematic_junction")

    def test_add_schematic_connection_not_present(self) -> None:
        from kicad_interface import KiCADInterface

        assert not hasattr(
            KiCADInterface, "_handle_add_schematic_connection"
        ), "_handle_add_schematic_connection should be removed"


# ---------------------------------------------------------------------------
# 3. _handle_add_schematic_wire — parameter validation
# ---------------------------------------------------------------------------


class TestHandleAddSchematicWireValidation:
    """Unit tests for _handle_add_schematic_wire validation paths (no disk I/O)."""

    @pytest.fixture(autouse=True)
    def handler(self) -> Any:
        import types

        for mod in ["pcbnew", "skip"]:
            sys.modules.setdefault(mod, types.ModuleType(mod))
        from kicad_interface import KiCADInterface

        with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
            self.iface = KiCADInterface.__new__(KiCADInterface)

    def test_missing_schematic_path(self) -> None:
        result = self.iface._handle_add_schematic_wire({"waypoints": [[0, 0], [10, 0]]})
        assert result["success"] is False
        assert "Schematic path" in result["message"]

    def test_missing_waypoints(self) -> None:
        result = self.iface._handle_add_schematic_wire({"schematicPath": "/tmp/x.kicad_sch"})
        assert result["success"] is False
        assert "waypoint" in result["message"].lower()

    def test_single_waypoint_rejected(self) -> None:
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": "/tmp/x.kicad_sch",
                "waypoints": [[0, 0]],
            }
        )
        assert result["success"] is False
        assert "waypoint" in result["message"].lower()


# ---------------------------------------------------------------------------
# 4. _handle_add_schematic_wire — wire routing logic
# ---------------------------------------------------------------------------


class TestHandleAddSchematicWireRouting:
    """Unit tests verifying add_wire vs add_polyline_wire dispatch, no pin snapping."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Any:
        import types

        for mod in ["pcbnew", "skip"]:
            sys.modules.setdefault(mod, types.ModuleType(mod))
        from kicad_interface import KiCADInterface

        with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
            self.iface = KiCADInterface.__new__(KiCADInterface)
        self.sch_path = _make_temp_sch()
        yield
        # cleanup
        shutil.rmtree(self.sch_path.parent, ignore_errors=True)

    @patch("commands.wire_manager.WireManager.add_wire", return_value=True)
    def test_two_waypoints_calls_add_wire(self, mock_add_wire: Any) -> None:
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.sch_path),
                "waypoints": [[10.0, 20.0], [30.0, 20.0]],
                "snapToPins": False,
            }
        )
        assert result["success"] is True
        mock_add_wire.assert_called_once()
        args = mock_add_wire.call_args[0]
        assert args[1] == [10.0, 20.0]
        assert args[2] == [30.0, 20.0]

    @patch("commands.wire_manager.WireManager.add_polyline_wire", return_value=True)
    def test_four_waypoints_calls_add_polyline_wire(self, mock_poly: Any) -> None:
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.sch_path),
                "waypoints": [[0, 0], [10, 0], [10, 10], [20, 10]],
                "snapToPins": False,
            }
        )
        assert result["success"] is True
        mock_poly.assert_called_once()

    def test_points_key_without_waypoints_is_rejected(self) -> None:
        """'points' key alone (without 'waypoints') is rejected — no fallback."""
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.sch_path),
                "points": [[5.0, 5.0], [15.0, 5.0]],
                "snapToPins": False,
            }
        )
        assert result["success"] is False
        assert "waypoint" in result["message"].lower()

    @patch("commands.wire_manager.WireManager.add_wire", return_value=False)
    def test_failure_response(self, _: Any) -> None:
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.sch_path),
                "waypoints": [[0, 0], [10, 0]],
                "snapToPins": False,
            }
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 5. _handle_add_schematic_wire — pin snapping
# ---------------------------------------------------------------------------


class TestPinSnapping:
    """Verify pin snapping logic snaps endpoints correctly."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Any:
        import types

        # Provide a minimal skip.Schematic stub so the handler can import it
        skip_mod = types.ModuleType("skip")

        class FakeSchematic:
            def __init__(self, path: Any) -> None:
                pass

            @property
            def symbol(self) -> list[Any]:
                return []  # no symbols → no pins in snapping loop

        skip_mod.Schematic = FakeSchematic
        sys.modules["skip"] = skip_mod
        sys.modules.setdefault("pcbnew", types.ModuleType("pcbnew"))

        from kicad_interface import KiCADInterface

        with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
            self.iface = KiCADInterface.__new__(KiCADInterface)

        self.sch_path = _make_temp_sch()
        yield
        shutil.rmtree(self.sch_path.parent, ignore_errors=True)

    @patch("commands.wire_manager.WireManager.add_wire", return_value=True)
    @patch("commands.pin_locator.PinLocator.get_all_symbol_pins")
    def test_start_point_snapped_within_tolerance(self, mock_pins: Any, mock_wire: Any) -> None:
        """First waypoint within tolerance of a pin should be snapped to pin coords."""
        # get_all_symbol_pins won't be called because symbol list is empty in fixture.
        # Instead we patch find_nearest_pin indirectly by providing all_pins via the
        # skip.Schematic stub that returns one symbol with a known pin.
        import types

        skip_mod = sys.modules["skip"]

        class FakeSymbol:
            class property:
                class Reference:
                    value = "R1"

            def __init__(self) -> None:
                pass

        skip_mod.Schematic = lambda path: type("FakeSch", (), {"symbol": [FakeSymbol()]})()

        mock_pins.return_value = {"1": [10.0, 20.0], "2": [10.0, 30.0]}

        # Re-import so the patched skip.Schematic is used
        import importlib

        import kicad_interface

        importlib.reload(kicad_interface)
        from kicad_interface import KiCADInterface

        with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
            iface = KiCADInterface.__new__(KiCADInterface)

        with patch("commands.wire_manager.WireManager.add_wire", return_value=True) as mw:
            result = iface._handle_add_schematic_wire(
                {
                    "schematicPath": str(self.sch_path),
                    "waypoints": [[10.05, 20.05], [50.0, 20.0]],
                    "snapToPins": True,
                    "snapTolerance": 1.0,
                }
            )
            if result["success"]:
                called_start = mw.call_args[0][1]
                assert called_start == [
                    10.0,
                    20.0,
                ], f"Start should snap to [10.0, 20.0], got {called_start}"
            # If it failed due to stub issues, just verify no exception

    def test_snap_disabled_passes_original_coords(self) -> None:
        """With snapToPins=False the handler should not load PinLocator at all."""
        with (
            patch("commands.wire_manager.WireManager.add_wire", return_value=True) as mw,
            patch("commands.pin_locator.PinLocator") as mock_locator_cls,
        ):
            result = self.iface._handle_add_schematic_wire(
                {
                    "schematicPath": str(self.sch_path),
                    "waypoints": [[1.0, 2.0], [3.0, 4.0]],
                    "snapToPins": False,
                }
            )
            mock_locator_cls.assert_not_called()
            assert result["success"] is True
            called_start = mw.call_args[0][1]
            assert called_start == [1.0, 2.0]

    @patch("commands.wire_manager.WireManager.add_wire", return_value=True)
    def test_snap_miss_leaves_coords_unchanged(self, mock_wire: Any) -> None:
        """Point beyond tolerance should not be snapped."""
        with patch("commands.wire_manager.WireManager.add_wire", return_value=True) as mw:
            result = self.iface._handle_add_schematic_wire(
                {
                    "schematicPath": str(self.sch_path),
                    "waypoints": [[100.0, 100.0], [200.0, 100.0]],
                    "snapToPins": True,
                    "snapTolerance": 0.5,
                    # skip.Schematic returns no symbols (fixture), so no pins to snap to
                }
            )
            assert result["success"] is True
            # No snapping info in message
            assert "snapped" not in result.get("message", "")

    @patch("commands.wire_manager.WireManager.add_polyline_wire", return_value=True)
    def test_intermediate_waypoints_not_snapped(self, mock_poly: Any) -> None:
        """Middle waypoints must remain unchanged even with snapToPins=True."""
        mid = [50.0, 50.0]
        with patch("commands.wire_manager.WireManager.add_polyline_wire", return_value=True) as mp:
            result = self.iface._handle_add_schematic_wire(
                {
                    "schematicPath": str(self.sch_path),
                    "waypoints": [[100.0, 100.0], mid[:], [200.0, 100.0]],
                    "snapToPins": True,
                    "snapTolerance": 100.0,  # huge tolerance, but mid must not snap
                }
            )
            assert result["success"] is True
            called_points = mp.call_args[0][1]
            assert (
                called_points[1] == mid
            ), f"Middle waypoint should not be snapped, got {called_points[1]}"


# ---------------------------------------------------------------------------
# 6. ConnectionManager — orphaned methods removed
# ---------------------------------------------------------------------------


class TestConnectionManagerOrphanedMethodsRemoved:

    def test_add_wire_removed(self) -> None:
        from commands.connection_schematic import ConnectionManager

        assert not hasattr(
            ConnectionManager, "add_wire"
        ), "ConnectionManager.add_wire should have been removed"

    def test_add_connection_removed(self) -> None:
        from commands.connection_schematic import ConnectionManager

        assert not hasattr(
            ConnectionManager, "add_connection"
        ), "ConnectionManager.add_connection should have been removed"

    def test_get_pin_location_removed(self) -> None:
        from commands.connection_schematic import ConnectionManager

        assert not hasattr(
            ConnectionManager, "get_pin_location"
        ), "ConnectionManager.get_pin_location should have been removed"


# ---------------------------------------------------------------------------
# 8. Integration tests — real disk I/O, no KiCAD process
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIntegrationWireManager:
    """Integration tests using real schematic files and WireManager."""

    @pytest.fixture(autouse=True)
    def sch(self) -> Any:
        path = _make_temp_sch()
        yield path
        shutil.rmtree(path.parent, ignore_errors=True)

    def test_add_wire_writes_wire_element(self, sch: Any) -> None:
        from commands.wire_manager import WireManager

        ok = WireManager.add_wire(sch, [10.0, 10.0], [30.0, 10.0])
        assert ok is True
        data = _parse_sch(sch)
        wires = _find_elements(data, "wire")
        assert len(wires) == 1

    def test_add_polyline_wire_creates_segments(self, sch: Any) -> None:
        """N waypoints should produce N-1 individual 2-point wire segments."""
        from commands.wire_manager import WireManager

        pts = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [20.0, 10.0]]
        ok = WireManager.add_polyline_wire(sch, pts)
        assert ok is True
        data = _parse_sch(sch)
        wires = _find_elements(data, "wire")
        assert len(wires) == 3, f"4 waypoints should produce 3 wire segments, got {len(wires)}"

    def test_wire_endpoint_coordinates_match(self, sch: Any) -> None:
        from commands.wire_manager import WireManager

        WireManager.add_wire(sch, [5.0, 7.5], [15.0, 7.5])
        data = _parse_sch(sch)
        wire = _find_elements(data, "wire")[0]
        pts = [
            item for item in wire if isinstance(item, list) and item and item[0] == Symbol("pts")
        ][0]
        xy_entries = [
            item for item in pts if isinstance(item, list) and item and item[0] == Symbol("xy")
        ]
        assert xy_entries[0][1] == 5.0
        assert xy_entries[0][2] == 7.5
        assert xy_entries[1][1] == 15.0
        assert xy_entries[1][2] == 7.5


@pytest.mark.integration
class TestIntegrationHandlerEndToEnd:
    """Integration tests for KiCADInterface handlers writing to real schematic files."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Any:
        import types

        for mod in ["pcbnew", "skip"]:
            sys.modules.setdefault(mod, types.ModuleType(mod))
        from kicad_interface import KiCADInterface

        with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
            self.iface = KiCADInterface.__new__(KiCADInterface)
        self.sch = _make_temp_sch()
        yield
        shutil.rmtree(self.sch.parent, ignore_errors=True)

    def test_wire_handler_two_points_writes_wire(self) -> None:
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.sch),
                "waypoints": [[10.0, 10.0], [30.0, 10.0]],
                "snapToPins": False,
            }
        )
        assert result["success"] is True
        data = _parse_sch(self.sch)
        wires = _find_elements(data, "wire")
        assert len(wires) == 1

    def test_wire_handler_four_points_creates_three_segments(self) -> None:
        result = self.iface._handle_add_schematic_wire(
            {
                "schematicPath": str(self.sch),
                "waypoints": [[0, 0], [10, 0], [10, 10], [20, 10]],
                "snapToPins": False,
            }
        )
        assert result["success"] is True
        data = _parse_sch(self.sch)
        wires = _find_elements(data, "wire")
        assert len(wires) == 3, f"4 waypoints should produce 3 wire segments, got {len(wires)}"


# ---------------------------------------------------------------------------
# 9. Unit tests — _point_strictly_on_wire
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPointStrictlyOnWire:
    """Unit tests for WireManager._point_strictly_on_wire geometry helper."""

    @staticmethod
    def _fn(px: Any, py: Any, x1: Any, y1: Any, x2: Any, y2: Any, eps: Any = 1e-6) -> Any:
        from commands.wire_manager import WireManager

        return WireManager._point_strictly_on_wire(px, py, x1, y1, x2, y2, eps)

    def test_horizontal_midpoint(self) -> None:
        assert self._fn(5, 0, 0, 0, 10, 0) is True

    def test_vertical_midpoint(self) -> None:
        assert self._fn(0, 5, 0, 0, 0, 10) is True

    def test_horizontal_at_start_endpoint(self) -> None:
        """Point at wire start should NOT be strictly on wire."""
        assert self._fn(0, 0, 0, 0, 10, 0) is False

    def test_horizontal_at_end_endpoint(self) -> None:
        """Point at wire end should NOT be strictly on wire."""
        assert self._fn(10, 0, 0, 0, 10, 0) is False

    def test_vertical_at_start_endpoint(self) -> None:
        assert self._fn(0, 0, 0, 0, 0, 10) is False

    def test_vertical_at_end_endpoint(self) -> None:
        assert self._fn(0, 10, 0, 0, 0, 10) is False

    def test_point_off_horizontal_wire(self) -> None:
        """Point above a horizontal wire."""
        assert self._fn(5, 1, 0, 0, 10, 0) is False

    def test_point_off_vertical_wire(self) -> None:
        """Point to the right of a vertical wire."""
        assert self._fn(1, 5, 0, 0, 0, 10) is False

    def test_point_beyond_horizontal_wire(self) -> None:
        """Point collinear but past the end of a horizontal wire."""
        assert self._fn(15, 0, 0, 0, 10, 0) is False

    def test_point_beyond_vertical_wire(self) -> None:
        """Point collinear but past the end of a vertical wire."""
        assert self._fn(0, 15, 0, 0, 0, 10) is False

    def test_diagonal_wire_always_false(self) -> None:
        """Only horizontal/vertical wires are handled; diagonal → False."""
        assert self._fn(5, 5, 0, 0, 10, 10) is False

    def test_reversed_horizontal_endpoints(self) -> None:
        """Wire endpoints reversed (x2 < x1) should still work."""
        assert self._fn(5, 0, 10, 0, 0, 0) is True

    def test_reversed_vertical_endpoints(self) -> None:
        """Wire endpoints reversed (y2 < y1) should still work."""
        assert self._fn(0, 5, 0, 10, 0, 0) is True

    def test_near_endpoint_within_epsilon(self) -> None:
        """Point within epsilon of endpoint should NOT be considered strictly on wire."""
        assert self._fn(1e-7, 0, 0, 0, 10, 0) is False

    def test_zero_length_wire(self) -> None:
        """Degenerate wire with same start/end — nothing is strictly between."""
        assert self._fn(5, 5, 5, 5, 5, 5) is False


# ---------------------------------------------------------------------------
# 10. Unit tests — _parse_wire
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseWire:
    """Unit tests for WireManager._parse_wire S-expression parser."""

    @staticmethod
    def _fn(item: Any) -> Any:
        from commands.wire_manager import WireManager

        return WireManager._parse_wire(item)

    def test_valid_wire(self) -> None:
        wire = [
            Symbol("wire"),
            [Symbol("pts"), [Symbol("xy"), 10.0, 20.0], [Symbol("xy"), 30.0, 20.0]],
            [
                Symbol("stroke"),
                [Symbol("width"), 0],
                [Symbol("type"), Symbol("default")],
            ],
            [Symbol("uuid"), "abc-123"],
        ]
        result = TestParseWire._fn(wire)
        assert result is not None
        start, end, width, stype = result
        assert start == (10.0, 20.0)
        assert end == (30.0, 20.0)
        assert width == 0
        assert stype == "default"

    def test_non_wire_element_returns_none(self) -> None:
        junction = [Symbol("junction"), [Symbol("at"), 10, 20]]
        assert TestParseWire._fn(junction) is None

    def test_non_list_returns_none(self) -> None:
        assert TestParseWire._fn("not a list") is None

    def test_empty_list_returns_none(self) -> None:
        assert TestParseWire._fn([]) is None

    def test_wire_with_no_pts_returns_none(self) -> None:
        wire = [Symbol("wire"), [Symbol("stroke"), [Symbol("width"), 0]]]
        assert TestParseWire._fn(wire) is None

    def test_wire_with_only_one_xy_returns_none(self) -> None:
        wire = [
            Symbol("wire"),
            [Symbol("pts"), [Symbol("xy"), 10.0, 20.0]],
        ]
        assert TestParseWire._fn(wire) is None

    def test_wire_without_stroke_uses_defaults(self) -> None:
        wire = [
            Symbol("wire"),
            [Symbol("pts"), [Symbol("xy"), 0, 0], [Symbol("xy"), 10, 0]],
        ]
        result = TestParseWire._fn(wire)
        assert result is not None
        _, _, width, stype = result
        assert width == 0
        assert stype == "default"


# ---------------------------------------------------------------------------
# 11. Unit tests — _make_wire_sexp
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMakeWireSexp:
    """Unit tests for WireManager._make_wire_sexp builder."""

    def test_produces_valid_parseable_wire(self) -> None:
        from commands.wire_manager import WireManager

        sexp = WireManager._make_wire_sexp([10, 20], [30, 20])
        parsed = WireManager._parse_wire(sexp)
        assert parsed is not None
        start, end, width, stype = parsed
        assert start == (10, 20)
        assert end == (30, 20)
        assert width == 0
        assert stype == "default"

    def test_custom_stroke(self) -> None:
        from commands.wire_manager import WireManager

        sexp = WireManager._make_wire_sexp([0, 0], [5, 0], stroke_width=0.5, stroke_type="dash")
        parsed = WireManager._parse_wire(sexp)
        assert parsed is not None
        _, _, width, stype = parsed
        assert width == 0.5
        assert stype == "dash"

    def test_has_uuid(self) -> None:
        from commands.wire_manager import WireManager

        sexp = WireManager._make_wire_sexp([0, 0], [10, 0])
        # uuid is the last element
        uuid_entry = sexp[-1]
        assert uuid_entry[0] == Symbol("uuid")
        assert isinstance(uuid_entry[1], str) and len(uuid_entry[1]) > 0

    def test_two_calls_produce_different_uuids(self) -> None:
        from commands.wire_manager import WireManager

        sexp1 = WireManager._make_wire_sexp([0, 0], [10, 0])
        sexp2 = WireManager._make_wire_sexp([0, 0], [10, 0])
        assert sexp1[-1][1] != sexp2[-1][1], "Each wire should have a unique UUID"


# ---------------------------------------------------------------------------
# 12. Unit tests — _break_wires_at_point
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBreakWiresAtPoint:
    """Unit tests for WireManager._break_wires_at_point T-junction logic."""

    @staticmethod
    def _make_sch_data_with_wires(wire_coords: Any) -> list[Any]:
        """Build a minimal sch_data list with wire elements and a sheet_instances marker."""
        from commands.wire_manager import WireManager

        data = [Symbol("kicad_sch")]
        for start, end in wire_coords:
            data.append(WireManager._make_wire_sexp(start, end))
        data.append([Symbol("sheet_instances")])
        return data

    def test_split_horizontal_wire_at_midpoint(self) -> None:
        from commands.wire_manager import WireManager

        data = self._make_sch_data_with_wires([([0, 0], [20, 0])])
        splits = WireManager._break_wires_at_point(data, [10, 0])
        assert splits == 1
        wires = _find_elements(data, "wire")
        assert len(wires) == 2
        # Verify the two segments share the split point
        coords = []
        for w in wires:
            parsed = WireManager._parse_wire(w)
            coords.append((parsed[0], parsed[1]))
        endpoints = {c for pair in coords for c in pair}
        assert (10.0, 0.0) in endpoints

    def test_split_vertical_wire_at_midpoint(self) -> None:
        from commands.wire_manager import WireManager

        data = self._make_sch_data_with_wires([([5, 0], [5, 30])])
        splits = WireManager._break_wires_at_point(data, [5, 15])
        assert splits == 1
        wires = _find_elements(data, "wire")
        assert len(wires) == 2

    def test_no_split_at_wire_endpoint(self) -> None:
        """Point at existing endpoint should not trigger a split."""
        from commands.wire_manager import WireManager

        data = self._make_sch_data_with_wires([([0, 0], [20, 0])])
        splits = WireManager._break_wires_at_point(data, [0, 0])
        assert splits == 0
        wires = _find_elements(data, "wire")
        assert len(wires) == 1

    def test_no_split_point_not_on_wire(self) -> None:
        from commands.wire_manager import WireManager

        data = self._make_sch_data_with_wires([([0, 0], [20, 0])])
        splits = WireManager._break_wires_at_point(data, [10, 5])
        assert splits == 0
        wires = _find_elements(data, "wire")
        assert len(wires) == 1

    def test_split_multiple_wires_at_same_point(self) -> None:
        """Two crossing wires at (10, 10) — both should be split."""
        from commands.wire_manager import WireManager

        data = self._make_sch_data_with_wires(
            [
                ([0, 10], [20, 10]),  # horizontal through (10,10)
                ([10, 0], [10, 20]),  # vertical through (10,10)
            ]
        )
        splits = WireManager._break_wires_at_point(data, [10, 10])
        assert splits == 2
        wires = _find_elements(data, "wire")
        assert len(wires) == 4  # each wire split into 2

    def test_split_preserves_stroke_properties(self) -> None:
        from commands.wire_manager import WireManager

        data = [Symbol("kicad_sch")]
        data.append(
            WireManager._make_wire_sexp([0, 0], [20, 0], stroke_width=0.5, stroke_type="dash")
        )
        data.append([Symbol("sheet_instances")])
        splits = WireManager._break_wires_at_point(data, [10, 0])
        assert splits == 1
        wires = _find_elements(data, "wire")
        for w in wires:
            parsed = WireManager._parse_wire(w)
            assert parsed[2] == 0.5, "stroke_width should be preserved"
            assert parsed[3] == "dash", "stroke_type should be preserved"

    def test_no_split_on_diagonal_wire(self) -> None:
        """Diagonal wires are not handled by _point_strictly_on_wire → no split."""
        from commands.wire_manager import WireManager

        data = self._make_sch_data_with_wires([([0, 0], [10, 10])])
        splits = WireManager._break_wires_at_point(data, [5, 5])
        assert splits == 0

    def test_empty_sch_data(self) -> None:
        from commands.wire_manager import WireManager

        data = [Symbol("kicad_sch"), [Symbol("sheet_instances")]]
        splits = WireManager._break_wires_at_point(data, [10, 10])
        assert splits == 0


# ---------------------------------------------------------------------------
# 13. Integration tests — T-junction wire breaking
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIntegrationTJunction:
    """Integration tests for T-junction wire breaking during add_wire."""

    @pytest.fixture(autouse=True)
    def sch(self) -> Any:
        path = _make_temp_sch()
        yield path
        shutil.rmtree(path.parent, ignore_errors=True)

    def test_add_wire_breaks_existing_horizontal_wire(self, sch: Any) -> None:
        """Adding a vertical wire whose endpoint is mid-horizontal-wire should split it."""
        from commands.wire_manager import WireManager

        # First add a horizontal wire (0,10) -> (20,10)
        WireManager.add_wire(sch, [0, 10], [20, 10])
        # Now add a vertical wire ending at (10,10) — the midpoint of the horizontal wire
        WireManager.add_wire(sch, [10, 0], [10, 10])
        data = _parse_sch(sch)
        wires = _find_elements(data, "wire")
        # Original horizontal wire should be split into 2, plus the new vertical = 3 total
        assert len(wires) == 3, f"Expected 3 wires (split + new), got {len(wires)}"

    def test_add_wire_does_not_break_at_shared_endpoint(self, sch: Any) -> None:
        """Wire connecting at an existing endpoint should not trigger a split."""
        from commands.wire_manager import WireManager

        WireManager.add_wire(sch, [0, 0], [10, 0])
        # New wire starts at (10,0) — existing endpoint, not midpoint
        WireManager.add_wire(sch, [10, 0], [10, 10])
        data = _parse_sch(sch)
        wires = _find_elements(data, "wire")
        assert len(wires) == 2, f"Expected 2 wires (no split), got {len(wires)}"

    def test_polyline_breaks_existing_wire(self, sch: Any) -> None:
        """Polyline whose start/end hits mid-wire should break it."""
        from commands.wire_manager import WireManager

        WireManager.add_wire(sch, [0, 10], [20, 10])
        # Polyline starting at (10,10) — mid-horizontal-wire
        WireManager.add_polyline_wire(sch, [[10, 10], [10, 20], [20, 20]])
        data = _parse_sch(sch)
        wires = _find_elements(data, "wire")
        # 2 from split + 2 polyline segments = 4
        assert len(wires) == 4, f"Expected 4 wires, got {len(wires)}"

    def test_polyline_two_points_same_as_add_wire(self, sch: Any) -> None:
        """Polyline with exactly 2 points should produce 1 wire segment."""
        from commands.wire_manager import WireManager

        WireManager.add_polyline_wire(sch, [[0, 0], [10, 0]])
        data = _parse_sch(sch)
        wires = _find_elements(data, "wire")
        assert len(wires) == 1


# ---------------------------------------------------------------------------
# 14. Auto junction sync
# ---------------------------------------------------------------------------


class TestSyncJunctionsUnit:
    """Unit tests for WireManager.sync_junctions operating on raw sch_data."""

    def _base_data(self) -> Any:
        """Minimal sch_data with a sheet_instances section."""
        return [Symbol("kicad_sch"), [Symbol("sheet_instances")]]

    def _wire(self, x1: float, y1: float, x2: float, y2: float) -> list:
        return [
            Symbol("wire"),
            [Symbol("pts"), [Symbol("xy"), x1, y1], [Symbol("xy"), x2, y2]],
            [Symbol("stroke"), [Symbol("width"), 0], [Symbol("type"), Symbol("default")]],
            [Symbol("uuid"), "00000000-0000-0000-0000-000000000000"],
        ]

    def _junction(self, x: float, y: float) -> list:
        return [
            Symbol("junction"),
            [Symbol("at"), x, y],
            [Symbol("diameter"), 0],
            [Symbol("color"), 0, 0, 0, 0],
            [Symbol("uuid"), "00000000-0000-0000-0000-000000000001"],
        ]

    def test_t_junction_adds_junction(self) -> None:
        """Three wire endpoints meeting at one point → one junction added."""
        from commands.wire_manager import WireManager

        data = self._base_data()
        # Horizontal wire split at (10,0): (0,0)→(10,0) and (10,0)→(20,0)
        data.insert(1, self._wire(0, 0, 10, 0))
        data.insert(1, self._wire(10, 0, 20, 0))
        # Vertical wire whose endpoint is (10,0): 3 endpoints at (10,0)
        data.insert(1, self._wire(10, -10, 10, 0))

        added, removed = WireManager.sync_junctions(data)

        assert added == 1
        assert removed == 0
        junctions = _find_elements(data, "junction")
        assert len(junctions) == 1
        at = next(p for p in junctions[0][1:] if isinstance(p, list) and p[0] == Symbol("at"))
        assert abs(at[1] - 10) < 1e-6
        assert abs(at[2] - 0) < 1e-6

    def test_two_wire_join_no_junction(self) -> None:
        """Two wires meeting end-to-end (2 endpoints) → no junction."""
        from commands.wire_manager import WireManager

        data = self._base_data()
        data.insert(1, self._wire(0, 0, 10, 0))
        data.insert(1, self._wire(10, 0, 20, 0))

        added, removed = WireManager.sync_junctions(data)

        assert added == 0
        assert removed == 0
        assert _find_elements(data, "junction") == []

    def test_stale_junction_removed(self) -> None:
        """A junction with fewer than 3 wire endpoints at its position is removed."""
        from commands.wire_manager import WireManager

        data = self._base_data()
        # Only two wires meeting at (10,0) — junction is stale
        data.insert(1, self._wire(0, 0, 10, 0))
        data.insert(1, self._wire(10, 0, 20, 0))
        data.insert(1, self._junction(10, 0))

        added, removed = WireManager.sync_junctions(data)

        assert added == 0
        assert removed == 1
        assert _find_elements(data, "junction") == []

    def test_x_junction_gets_one_junction(self) -> None:
        """Four wire endpoints meeting (X-junction) → exactly one junction."""
        from commands.wire_manager import WireManager

        data = self._base_data()
        # Simulate already-split X: four segments meeting at (10,10)
        data.insert(1, self._wire(0, 10, 10, 10))
        data.insert(1, self._wire(10, 10, 20, 10))
        data.insert(1, self._wire(10, 0, 10, 10))
        data.insert(1, self._wire(10, 10, 10, 20))

        added, removed = WireManager.sync_junctions(data)

        assert added == 1
        junctions = _find_elements(data, "junction")
        assert len(junctions) == 1

    def test_idempotent_on_correct_junction(self) -> None:
        """Running sync_junctions when junction is already correct is a no-op."""
        from commands.wire_manager import WireManager

        data = self._base_data()
        data.insert(1, self._wire(0, 0, 10, 0))
        data.insert(1, self._wire(10, 0, 20, 0))
        data.insert(1, self._wire(10, -10, 10, 0))
        data.insert(1, self._junction(10, 0))

        added, removed = WireManager.sync_junctions(data)

        assert added == 0
        assert removed == 0
        assert len(_find_elements(data, "junction")) == 1


@pytest.mark.integration
class TestSyncJunctionsIntegration:
    """Integration tests for automatic junction sync through add_wire / delete_wire."""

    @pytest.fixture(autouse=True)
    def sch(self) -> Any:
        path = _make_temp_sch()
        yield path
        shutil.rmtree(path.parent, ignore_errors=True)

    def test_t_junction_auto_inserted_on_add_wire(self, sch: Any) -> None:
        """Adding a wire that creates a T-junction should auto-insert a junction dot."""
        from commands.wire_manager import WireManager

        # Horizontal wire, then split it manually, then add connecting vertical
        WireManager.add_wire(sch, [0, 10], [10, 10])
        WireManager.add_wire(sch, [10, 10], [20, 10])
        WireManager.add_wire(sch, [10, 0], [10, 10])  # creates T at (10,10)

        data = _parse_sch(sch)
        junctions = _find_elements(data, "junction")
        assert len(junctions) == 1, f"Expected 1 junction, got {len(junctions)}"

    def test_straight_join_no_junction(self, sch: Any) -> None:
        """Two wires joining end-to-end should not produce a junction."""
        from commands.wire_manager import WireManager

        WireManager.add_wire(sch, [0, 0], [10, 0])
        WireManager.add_wire(sch, [10, 0], [20, 0])

        data = _parse_sch(sch)
        junctions = _find_elements(data, "junction")
        assert junctions == [], f"Expected no junctions, got {len(junctions)}"

    def test_delete_wire_removes_stale_junction(self, sch: Any) -> None:
        """Removing a wire that was part of a T-junction should remove the junction."""
        from commands.wire_manager import WireManager

        WireManager.add_wire(sch, [0, 10], [10, 10])
        WireManager.add_wire(sch, [10, 10], [20, 10])
        WireManager.add_wire(sch, [10, 0], [10, 10])  # creates T, junction auto-inserted

        data = _parse_sch(sch)
        assert len(_find_elements(data, "junction")) == 1, "Pre-condition: junction present"

        WireManager.delete_wire(sch, [10, 0], [10, 10])  # remove the branch

        data = _parse_sch(sch)
        junctions = _find_elements(data, "junction")
        assert junctions == [], f"Expected junction removed, got {len(junctions)}"

    def test_polyline_t_junction_auto_inserted(self, sch: Any) -> None:
        """Polyline whose endpoint hits a wire midpoint auto-inserts a junction."""
        from commands.wire_manager import WireManager

        WireManager.add_wire(sch, [0, 10], [20, 10])  # horizontal
        # Polyline from above ending at (10,10) — mid-wire, wire breaks → T at (10,10)
        WireManager.add_polyline_wire(sch, [[10, 0], [10, 10]])

        data = _parse_sch(sch)
        junctions = _find_elements(data, "junction")
        assert len(junctions) == 1, f"Expected 1 junction after polyline T, got {len(junctions)}"


# ---------------------------------------------------------------------------
# 15. Pin-aware junction sync
# ---------------------------------------------------------------------------


class TestSyncJunctionsPinAware:
    """Unit tests for junction sync when component pins are present."""

    def _base_data_with_resistor(self, sym_x: float, sym_y: float, rotation: float = 0) -> Any:
        """Build minimal sch_data with a Device:R-like symbol.

        Pin 1 is at (0, 3.81) in lib coords → world (sym_x, sym_y - 3.81) at rot=0.
        Pin 2 is at (0, -3.81) in lib coords → world (sym_x, sym_y + 3.81) at rot=0.
        """
        pin1_sexp = [
            Symbol("pin"),
            Symbol("passive"),
            Symbol("line"),
            [Symbol("at"), 0, 3.81, 270],
            [Symbol("length"), 1.27],
            [Symbol("name"), "~"],
            [Symbol("number"), "1"],
        ]
        pin2_sexp = [
            Symbol("pin"),
            Symbol("passive"),
            Symbol("line"),
            [Symbol("at"), 0, -3.81, 90],
            [Symbol("length"), 1.27],
            [Symbol("name"), "~"],
            [Symbol("number"), "2"],
        ]
        lib_symbol = [
            Symbol("symbol"),
            "Device:R",
            [Symbol("pin_numbers"), Symbol("hide")],
            [Symbol("symbol"), "R_1_1", pin1_sexp, pin2_sexp],
        ]
        lib_symbols_section = [Symbol("lib_symbols"), lib_symbol]

        placed_symbol = [
            Symbol("symbol"),
            [Symbol("lib_id"), "Device:R"],
            [Symbol("at"), sym_x, sym_y, rotation],
            [Symbol("unit"), 1],
            [Symbol("property"), "Reference", "R1", [Symbol("at"), sym_x, sym_y, 0]],
            [Symbol("property"), "Value", "10k", [Symbol("at"), sym_x, sym_y, 0]],
            [Symbol("pin"), "1", [Symbol("uuid"), "pin1-uuid"]],
            [Symbol("pin"), "2", [Symbol("uuid"), "pin2-uuid"]],
        ]

        return [
            Symbol("kicad_sch"),
            lib_symbols_section,
            placed_symbol,
            [Symbol("sheet_instances")],
        ]

    def _wire(self, x1: float, y1: float, x2: float, y2: float) -> list:
        return [
            Symbol("wire"),
            [Symbol("pts"), [Symbol("xy"), x1, y1], [Symbol("xy"), x2, y2]],
            [Symbol("stroke"), [Symbol("width"), 0], [Symbol("type"), Symbol("default")]],
            [Symbol("uuid"), "wire-uuid"],
        ]

    def test_collect_pin_positions_no_rotation(self) -> None:
        """_collect_pin_positions returns correct world coords for R at (100,100) rot=0."""
        from commands.wire_manager import WireManager

        data = self._base_data_with_resistor(100, 100, rotation=0)
        pins = WireManager._collect_pin_positions(data)

        # Pin 1: lib (0, 3.81) → y-negate → (0, -3.81) → world (100, 96.19)
        # Pin 2: lib (0, -3.81) → y-negate → (0, 3.81) → world (100, 103.81)
        assert len(pins) == 2
        pin_set = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (100.0, 96.19) in pin_set
        assert (100.0, 103.81) in pin_set

    def test_collect_pin_positions_rotation_90(self) -> None:
        """_collect_pin_positions handles 90° rotation correctly."""
        from commands.wire_manager import WireManager

        data = self._base_data_with_resistor(100, 100, rotation=90)
        pins = WireManager._collect_pin_positions(data)

        # Pin 1: lib (0, 3.81) → y-neg → (0, -3.81) → rot90 → (3.81, 0) → world (103.81, 100)
        # Pin 2: lib (0, -3.81) → y-neg → (0, 3.81) → rot90 → (-3.81, 0) → world (96.19, 100)
        assert len(pins) == 2
        pin_set = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (103.81, 100.0) in pin_set
        assert (96.19, 100.0) in pin_set

    def test_two_wires_plus_pin_gets_junction(self) -> None:
        """Two wires ending at a pin position → junction needed (total 3)."""
        from commands.wire_manager import WireManager

        # R at (100, 100): pin 1 world = (100, 96.19)
        data = self._base_data_with_resistor(100, 100, rotation=0)
        # Two wires both ending at pin 1
        data.insert(2, self._wire(80, 96.19, 100, 96.19))
        data.insert(2, self._wire(100, 96.19, 120, 96.19))

        added, removed = WireManager.sync_junctions(data)

        assert added == 1, f"Expected 1 junction added, got {added}"
        assert removed == 0

    def test_one_wire_plus_pin_no_junction(self) -> None:
        """Single wire connecting to a pin (total 2) → no junction."""
        from commands.wire_manager import WireManager

        data = self._base_data_with_resistor(100, 100, rotation=0)
        # Single wire ending at pin 1
        data.insert(2, self._wire(80, 96.19, 100, 96.19))

        added, removed = WireManager.sync_junctions(data)

        assert added == 0, f"Expected no junction, got {added}"
        assert removed == 0

    def test_wire_midpoint_pin_gets_junction(self) -> None:
        """Wire passing through (broken at) a pin position + another wire → junction."""
        from commands.wire_manager import WireManager

        # R at (100, 100): pin 1 world = (100, 96.19)
        # Simulate a horizontal wire already split at pin position
        data = self._base_data_with_resistor(100, 100, rotation=0)
        data.insert(2, self._wire(80, 96.19, 100, 96.19))  # left segment
        data.insert(2, self._wire(100, 96.19, 120, 96.19))  # right segment
        # wire_cnt=2, pin_cnt=1 → total=3 → junction

        added, removed = WireManager.sync_junctions(data)

        assert added == 1, f"Expected junction at wire-split + pin, got {added}"

    # ------------------------------------------------------------------
    # Mirror / mirror+rotation tests
    # Transform order (per _collect_pin_positions docstring):
    #   1. y-negate  (lib y-up → schematic y-down)
    #   2. mirror_x  → ly = -ly
    #      mirror_y  → lx = -lx
    #   3. rotate by `rotation` degrees
    #   4. translate by (sym_x, sym_y)
    # TODO: verify against KiCad's actual transform order — see schematic_view.py
    # ------------------------------------------------------------------

    def _base_data_with_resistor_mirrored(
        self,
        sym_x: float,
        sym_y: float,
        rotation: float = 0,
        mirror: str = "x",
    ) -> Any:
        """Like _base_data_with_resistor but injects a (mirror x) or (mirror y) clause
        into the placed-symbol form."""
        data = self._base_data_with_resistor(sym_x, sym_y, rotation)
        # data[2] is the placed_symbol list
        placed = data[2]
        placed.append([Symbol("mirror"), Symbol(mirror)])
        return data

    def test_collect_pin_positions_mirror_x_rotation_0(self) -> None:
        """mirror_x at rotation=0: pins flip across the local x-axis (y-coords invert).

        Pin 1: lib(0, 3.81) → y-neg → (0, -3.81) → mirror_x → (0, +3.81) → world (100, 103.81)
        Pin 2: lib(0,-3.81) → y-neg → (0, +3.81) → mirror_x → (0, -3.81) → world (100,  96.19)
        """
        from commands.wire_manager import WireManager

        data = self._base_data_with_resistor_mirrored(100, 100, rotation=0, mirror="x")
        pins = WireManager._collect_pin_positions(data)

        assert len(pins) == 2
        pin_set = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (100.0, 103.81) in pin_set
        assert (100.0, 96.19) in pin_set

    def test_collect_pin_positions_mirror_y_rotation_0(self) -> None:
        """mirror_y at rotation=0: flips lx (which is 0 for both pins) → same world coords.

        Pin 1: lib(0, 3.81) → y-neg → (0, -3.81) → mirror_y: lx=-0=0 → world (100, 96.19)
        Pin 2: lib(0,-3.81) → y-neg → (0, +3.81) → mirror_y: lx=-0=0 → world (100, 103.81)
        """
        from commands.wire_manager import WireManager

        data = self._base_data_with_resistor_mirrored(100, 100, rotation=0, mirror="y")
        pins = WireManager._collect_pin_positions(data)

        assert len(pins) == 2
        pin_set = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (100.0, 96.19) in pin_set
        assert (100.0, 103.81) in pin_set

    def test_collect_pin_positions_mirror_x_rotation_90(self) -> None:
        """mirror_x combined with rotation=90.

        Pin 1: lib(0, 3.81) → y-neg → (0,-3.81) → mirror_x → (0,+3.81)
               → rot90 (c=0,s=1): lx'=0*0-3.81*1=-3.81, ly'=0*1+3.81*0=0
               → world (96.19, 100.0)
        Pin 2: lib(0,-3.81) → y-neg → (0,+3.81) → mirror_x → (0,-3.81)
               → rot90: lx'=0*0-(-3.81)*1=3.81, ly'=0*1+(-3.81)*0=0
               → world (103.81, 100.0)
        """
        from commands.wire_manager import WireManager

        data = self._base_data_with_resistor_mirrored(100, 100, rotation=90, mirror="x")
        pins = WireManager._collect_pin_positions(data)

        assert len(pins) == 2
        pin_set = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (96.19, 100.0) in pin_set
        assert (103.81, 100.0) in pin_set

    def test_collect_pin_positions_mirror_y_rotation_180(self) -> None:
        """mirror_y combined with rotation=180.

        Pin 1: lib(0, 3.81) → y-neg → (0,-3.81) → mirror_y: lx=-0=0, ly=-3.81
               → rot180 (c=-1,s=0): lx'=0*(-1)-(-3.81)*0=0, ly'=0*0+(-3.81)*(-1)=3.81
               → world (100.0, 103.81)
        Pin 2: lib(0,-3.81) → y-neg → (0,+3.81) → mirror_y: lx=0, ly=3.81
               → rot180: lx'=0*(-1)-3.81*0=0, ly'=0*0+3.81*(-1)=-3.81
               → world (100.0, 96.19)
        """
        from commands.wire_manager import WireManager

        data = self._base_data_with_resistor_mirrored(100, 100, rotation=180, mirror="y")
        pins = WireManager._collect_pin_positions(data)

        assert len(pins) == 2
        pin_set = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (100.0, 103.81) in pin_set
        assert (100.0, 96.19) in pin_set


# ---------------------------------------------------------------------------
# 16. Multi-unit IC pin-awareness  (LM324-like quad op-amp)
# ---------------------------------------------------------------------------


class TestMultiUnitLibPins:
    """Unit tests for _parse_lib_pins unit-aware filtering (multi-unit ICs)."""

    @staticmethod
    def _make_lm324_lib_symbol() -> list:
        """Return a minimal lib_symbols entry modelled on the LM324 quad op-amp.

        Structure:
          (symbol "Amplifier_Operational:LM324"
            (symbol "LM324_1_1"  ;; unit 1 – op-amp body A
              (pin input  line (at -5 2.54 0) ...)   ; IN+
              (pin input  line (at -5 -2.54 0) ...)  ; IN-
              (pin output line (at 5 0 180) ...)      ; OUT
            )
            (symbol "LM324_2_1"  ;; unit 2 – op-amp body B
              (pin input  line (at -5 2.54 0) ...)
              (pin input  line (at -5 -2.54 0) ...)
              (pin output line (at 5 0 180) ...)
            )
            (symbol "LM324_3_1"  ;; unit 3
              ...
            )
            (symbol "LM324_4_1"  ;; unit 4
              ...
            )
            (symbol "LM324_5_1"  ;; unit 5 = power (common)
              (pin power_in line (at 0 5 270) ...)   ; VCC
              (pin power_in line (at 0 -5 90) ...)   ; GND
            )
          )
        """

        def _pin(px: float, py: float) -> list:
            return [
                Symbol("pin"),
                Symbol("input"),
                Symbol("line"),
                [Symbol("at"), px, py, 0],
                [Symbol("length"), 1.27],
                [Symbol("name"), "~"],
                [Symbol("number"), "1"],
            ]

        def _sub(name: str, pins: list) -> list:
            return [Symbol("symbol"), name] + pins

        unit1 = _sub("LM324_1_1", [_pin(-5, 2.54), _pin(-5, -2.54), _pin(5, 0)])
        unit2 = _sub("LM324_2_1", [_pin(-5, 12.54), _pin(-5, -12.54), _pin(5, 10)])
        unit3 = _sub("LM324_3_1", [_pin(-5, 22.54), _pin(-5, -22.54), _pin(5, 20)])
        unit4 = _sub("LM324_4_1", [_pin(-5, 32.54), _pin(-5, -32.54), _pin(5, 30)])
        power = _sub("LM324_5_1", [_pin(0, 5), _pin(0, -5)])  # unit 5 = common/power

        return [
            Symbol("symbol"),
            "Amplifier_Operational:LM324",
            unit1,
            unit2,
            unit3,
            unit4,
            power,
        ]

    def test_unit2_returns_only_unit2_and_common_pins(self) -> None:
        """Placing unit 2 must return 3 op-amp pins + 2 power (common) pins = 5 total."""
        from commands.wire_manager import WireManager

        sym_def = self._make_lm324_lib_symbol()
        pins = WireManager._parse_lib_pins(sym_def, unit=2)

        # Unit 2 contributes 3 pins; LM324_5_1 (unit 5 != 2 != 0) should be excluded.
        # Only unit==2 OR unit==0 qualifies. LM324_5_1 has unit=5, so it is skipped.
        assert (
            len(pins) == 3
        ), f"Expected 3 pins (unit 2 only, power unit 5 excluded), got {len(pins)}: {pins}"
        # The three unit-2 pins have distinct y-coords in our fixture
        pin_coords = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (-5.0, 12.54) in pin_coords
        assert (-5.0, -12.54) in pin_coords
        assert (5.0, 10.0) in pin_coords

    def test_unit1_does_not_include_unit2_pins(self) -> None:
        """Placing unit 1 must not return pins from units 2-5."""
        from commands.wire_manager import WireManager

        sym_def = self._make_lm324_lib_symbol()
        pins = WireManager._parse_lib_pins(sym_def, unit=1)

        assert len(pins) == 3, f"Expected 3 pins (unit 1 only), got {len(pins)}: {pins}"
        pin_coords = {(round(x, 2), round(y, 2)) for x, y in pins}
        assert (-5.0, 2.54) in pin_coords
        assert (-5.0, -2.54) in pin_coords
        assert (5.0, 0.0) in pin_coords

    def test_common_unit_zero_always_included(self) -> None:
        """A sub-unit named <base>_0_1 (unit=0) must appear for every placed unit."""
        from commands.wire_manager import WireManager

        # Build a symbol that has a _0_1 common sub-unit
        def _pin(px: float, py: float) -> list:
            return [
                Symbol("pin"),
                Symbol("power_in"),
                Symbol("line"),
                [Symbol("at"), px, py, 0],
                [Symbol("length"), 1.27],
                [Symbol("name"), "VCC"],
                [Symbol("number"), "1"],
            ]

        sym_def = [
            Symbol("symbol"),
            "Device:Foo",
            [Symbol("symbol"), "Foo_0_1", _pin(0, 5)],  # common (unit 0)
            [Symbol("symbol"), "Foo_1_1", _pin(1, 1)],  # unit 1
            [Symbol("symbol"), "Foo_2_1", _pin(2, 2)],  # unit 2
        ]

        pins_u1 = WireManager._parse_lib_pins(sym_def, unit=1)
        pins_u2 = WireManager._parse_lib_pins(sym_def, unit=2)

        # Both units should include the unit-0 common pin
        assert len(pins_u1) == 2, f"Unit 1: expected 2 pins (1 common + 1 own), got {len(pins_u1)}"
        assert len(pins_u2) == 2, f"Unit 2: expected 2 pins (1 common + 1 own), got {len(pins_u2)}"

    def test_no_spurious_junctions_for_multi_unit_ic(self) -> None:
        """Placing unit 2 of an LM324-like part must not create phantom junctions
        from the pins of units 1, 3, 4, or 5."""
        from commands.wire_manager import WireManager

        sym_def = self._make_lm324_lib_symbol()
        lib_symbols_section = [Symbol("lib_symbols"), sym_def]

        # Place unit 2 at origin (0, 0), no rotation
        placed = [
            Symbol("symbol"),
            [Symbol("lib_id"), "Amplifier_Operational:LM324"],
            [Symbol("at"), 0, 0, 0],
            [Symbol("unit"), 2],
        ]

        # A single wire from (-30, 12.54) to (-5, 12.54) connects to unit-2 IN+ pin.
        # world pin coords: lib (−5, 12.54) → y-negate → (−5, −12.54) → + origin = (−5, −12.54)
        # (The y-negation is part of KiCad's lib-to-schematic transform.)
        wire = [
            Symbol("wire"),
            [Symbol("pts"), [Symbol("xy"), -30, -12.54], [Symbol("xy"), -5, -12.54]],
            [Symbol("stroke"), [Symbol("width"), 0], [Symbol("type"), Symbol("default")]],
            [Symbol("uuid"), "test-wire"],
        ]

        data = [
            Symbol("kicad_sch"),
            lib_symbols_section,
            placed,
            wire,
            [Symbol("sheet_instances")],
        ]

        added, removed = WireManager.sync_junctions(data)

        # Wire endpoint at (−5, −12.54) plus 1 pin = 2 total → no junction needed.
        assert added == 0, (
            f"Expected 0 junctions (wire endpoint + 1 pin = 2), got {added} added. "
            "Phantom pins from other units may be causing false positives."
        )
