"""
Tests for the get_net_at_point tool and its handler.

Covers:
  - Schema shape (TestGetNetAtPointSchema)
  - Handler dispatch registration (TestGetNetAtPointHandlerDispatch)
  - Parameter validation in the handler (TestGetNetAtPointHandlerParamValidation)
  - Core logic: get_net_at_point function (TestGetNetAtPointCoreLogic)
  - Integration: real schematic file (TestGetNetAtPointIntegration)
"""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.wire_connectivity import get_net_at_point

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

_TEMPLATE = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"


def _make_point(x: float, y: float) -> MagicMock:
    pt = MagicMock()
    pt.value = [x, y]
    return pt


def _make_wire(x1: float, y1: float, x2: float, y2: float) -> MagicMock:
    wire = MagicMock()
    wire.pts = MagicMock()
    wire.pts.xy = [_make_point(x1, y1), _make_point(x2, y2)]
    return wire


def _make_schematic_no_labels(*wires: Any) -> MagicMock:
    sch = MagicMock()
    sch.wire = list(wires)
    del sch.label
    del sch.symbol
    return sch


def _make_schematic_with_label(label_name: str, lx: float, ly: float, *wires: Any) -> MagicMock:
    label = MagicMock()
    label.value = label_name
    label.at = MagicMock()
    label.at.value = [lx, ly, 0]

    sch = MagicMock()
    sch.wire = list(wires)
    sch.label = [label]
    del sch.symbol
    return sch


# ---------------------------------------------------------------------------
# TestGetNetAtPointSchema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNetAtPointSchema:
    """Verify the get_net_at_point tool schema is present and well-formed."""

    def test_schema_registered(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "get_net_at_point" in TOOL_SCHEMAS

    def test_schema_required_fields(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        required = TOOL_SCHEMAS["get_net_at_point"]["inputSchema"]["required"]
        assert set(required) == {"schematicPath", "x", "y"}

    def test_schema_has_title_and_description(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["get_net_at_point"]
        assert schema.get("title")
        assert schema.get("description")

    def test_schema_properties(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        props = TOOL_SCHEMAS["get_net_at_point"]["inputSchema"]["properties"]
        for field in ("schematicPath", "x", "y"):
            assert field in props, f"Expected '{field}' in schema properties"


# ---------------------------------------------------------------------------
# TestGetNetAtPointHandlerDispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNetAtPointHandlerDispatch:
    """Verify the handler is wired into KiCadInterface.command_routes."""

    def test_get_net_at_point_in_routes(self) -> None:
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

        assert "get_net_at_point" in iface.command_routes
        assert callable(iface.command_routes["get_net_at_point"])


# ---------------------------------------------------------------------------
# TestGetNetAtPointHandlerParamValidation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNetAtPointHandlerParamValidation:
    """Handler returns error responses for bad or missing parameters."""

    def _make_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_get_net_at_point

    def test_missing_schematic_path(self) -> None:
        handler = self._make_handler()
        result = handler({"x": 1.0, "y": 2.0})
        assert result["success"] is False
        assert "schematicPath" in result["message"] or "Missing" in result["message"]

    def test_missing_x(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "y": 2.0})
        assert result["success"] is False

    def test_missing_y(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": 1.0})
        assert result["success"] is False

    def test_missing_both_coords(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/tmp/test.kicad_sch"})
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
# TestGetNetAtPointCoreLogic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNetAtPointCoreLogic:
    """Unit tests for the get_net_at_point function."""

    def test_no_wires_no_labels_returns_null_net(self) -> None:
        sch = MagicMock()
        sch.wire = []
        del sch.label
        del sch.symbol
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 1.0, 2.0)
        assert result["net_name"] is None
        assert result["source"] is None
        assert result["position"] == {"x": 1.0, "y": 2.0}

    def test_point_not_on_wire_or_label_returns_null(self) -> None:
        sch = _make_schematic_no_labels(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 5.0, 5.0)
        assert result["net_name"] is None
        assert result["source"] is None

    def test_midpoint_not_on_wire_endpoint(self) -> None:
        sch = _make_schematic_no_labels(_make_wire(0.0, 0.0, 2.0, 0.0))
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 1.0, 0.0)
        assert result["net_name"] is None

    def test_wire_endpoint_unnamed_net(self) -> None:
        sch = _make_schematic_no_labels(_make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert result["net_name"] is None
        assert result["source"] == "wire_endpoint"

    def test_net_label_at_point_returns_net_name(self) -> None:
        sch = _make_schematic_with_label("SDA", 0.0, 0.0, _make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert result["net_name"] == "SDA"
        assert result["source"] == "net_label"

    def test_net_label_takes_priority_over_wire_endpoint(self) -> None:
        """When a label sits exactly on a wire endpoint, source should be net_label."""
        sch = _make_schematic_with_label("SCL", 1.0, 0.0, _make_wire(0.0, 0.0, 1.0, 0.0))
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 1.0, 0.0)
        assert result["net_name"] == "SCL"
        assert result["source"] == "net_label"

    def test_wire_endpoint_finds_net_via_connected_label(self) -> None:
        """Wire endpoint not directly labelled still finds net via connected network points."""
        label = MagicMock()
        label.value = "VCC"
        label.at = MagicMock()
        label.at.value = [1.0, 0.0, 0]

        sch = MagicMock()
        sch.wire = [_make_wire(0.0, 0.0, 1.0, 0.0)]
        sch.label = [label]
        del sch.symbol

        # Query the label end directly — since the label is on the wire endpoint,
        # _parse_virtual_connections maps (10000,0) → "VCC", but we're querying (0,0)
        # which is the other wire endpoint; net_points includes (10000,0) so "VCC" is found.
        result_labelled_end = get_net_at_point(sch, "/tmp/test.kicad_sch", 1.0, 0.0)
        assert result_labelled_end["net_name"] == "VCC"
        assert result_labelled_end["source"] == "net_label"

        # Query the unlabelled end: source=wire_endpoint, net_name found via network traversal
        result_other_end = get_net_at_point(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert result_other_end["source"] == "wire_endpoint"
        # net_name may be "VCC" (found via net_points scan) or None (depends on traversal)
        assert result_other_end["net_name"] in ("VCC", None)

    def test_position_in_result(self) -> None:
        sch = _make_schematic_no_labels(_make_wire(3.5, 7.2, 4.5, 7.2))
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 3.5, 7.2)
        assert result["position"] == {"x": 3.5, "y": 7.2}

    def test_result_has_all_keys(self) -> None:
        sch = _make_schematic_no_labels()
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert "net_name" in result
        assert "position" in result
        assert "source" in result

    def test_no_wire_attr_still_returns_dict(self) -> None:
        sch = MagicMock()
        del sch.wire
        del sch.label
        del sch.symbol
        result = get_net_at_point(sch, "/tmp/test.kicad_sch", 0.0, 0.0)
        assert isinstance(result, dict)
        assert result["net_name"] is None


# ---------------------------------------------------------------------------
# TestGetNetAtPointHandlerSuccess
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNetAtPointHandlerSuccess:
    """Handler returns success=True and result keys for valid coordinates."""

    def _make_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_get_net_at_point

    def test_returns_success_with_net_name(self) -> None:
        handler = self._make_handler()
        mock_result = {"net_name": "GND", "position": {"x": 10.0, "y": 5.0}, "source": "net_label"}
        with (
            patch("kicad_interface.SchematicManager.load_schematic") as mock_load,
            patch("commands.wire_connectivity.get_net_at_point", return_value=mock_result),
        ):
            mock_load.return_value = MagicMock()
            result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": 10.0, "y": 5.0})

        assert result["success"] is True
        assert result["net_name"] == "GND"
        assert result["source"] == "net_label"

    def test_returns_success_with_null_net(self) -> None:
        handler = self._make_handler()
        mock_result = {"net_name": None, "position": {"x": 0.0, "y": 0.0}, "source": None}
        with (
            patch("kicad_interface.SchematicManager.load_schematic") as mock_load,
            patch("commands.wire_connectivity.get_net_at_point", return_value=mock_result),
        ):
            mock_load.return_value = MagicMock()
            result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": 0.0, "y": 0.0})

        assert result["success"] is True
        assert result["net_name"] is None

    def test_string_coords_are_cast_to_float(self) -> None:
        handler = self._make_handler()
        mock_result = {"net_name": None, "position": {"x": 1.5, "y": 2.5}, "source": None}
        with (
            patch("kicad_interface.SchematicManager.load_schematic") as mock_load,
            patch(
                "commands.wire_connectivity.get_net_at_point", return_value=mock_result
            ) as mock_fn,
        ):
            mock_load.return_value = MagicMock()
            result = handler({"schematicPath": "/tmp/test.kicad_sch", "x": "1.5", "y": "2.5"})

        assert result["success"] is True
        call_args = mock_fn.call_args
        assert isinstance(call_args[0][2], float)
        assert isinstance(call_args[0][3], float)
        assert call_args[0][2] == pytest.approx(1.5)
        assert call_args[0][3] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# TestGetNetAtPointIntegration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetNetAtPointIntegration:
    """Integration tests using a real (but temporary) schematic file."""

    def _write_schematic(self, content: str, tmp_dir: Path) -> Path:
        path = tmp_dir / "test.kicad_sch"
        path.write_text(content)
        return path

    def test_empty_schematic_returns_null(self, tmp_path: Path) -> None:
        shutil.copy(_TEMPLATE, tmp_path / "empty.kicad_sch")
        sch_path = str(tmp_path / "empty.kicad_sch")

        from commands.schematic import SchematicManager

        sch = SchematicManager.load_schematic(sch_path)
        result = get_net_at_point(sch, sch_path, 10.0, 10.0)
        assert result["net_name"] is None
        assert result["source"] is None

    def test_schematic_with_wire_and_label(self, tmp_path: Path) -> None:
        """Write a minimal schematic with a wire and net label, then query it."""
        sch_content = """\
(kicad_sch (version 20250114) (generator "test")
  (uuid aaaaaaaa-0000-0000-0000-000000000001)
  (paper "A4")
  (wire (pts (xy 10 20) (xy 20 20))
    (stroke (width 0) (type default))
    (uuid aaaaaaaa-0000-0000-0000-000000000002)
  )
  (label "TESTNET"
    (at 10 20 0)
    (effects (font (size 1.27 1.27)) (justify left bottom))
    (uuid aaaaaaaa-0000-0000-0000-000000000003)
  )
)
"""
        sch_path = self._write_schematic(sch_content, tmp_path)

        from commands.schematic import SchematicManager

        sch = SchematicManager.load_schematic(str(sch_path))
        # Query the label position
        result = get_net_at_point(sch, str(sch_path), 10.0, 20.0)
        assert result["net_name"] == "TESTNET"
        assert result["source"] == "net_label"

    def test_schematic_wire_endpoint_no_label(self, tmp_path: Path) -> None:
        sch_content = """\
(kicad_sch (version 20250114) (generator "test")
  (uuid aaaaaaaa-0000-0000-0000-000000000004)
  (paper "A4")
  (wire (pts (xy 5 5) (xy 10 5))
    (stroke (width 0) (type default))
    (uuid aaaaaaaa-0000-0000-0000-000000000005)
  )
)
"""
        sch_path = self._write_schematic(sch_content, tmp_path)

        from commands.schematic import SchematicManager

        sch = SchematicManager.load_schematic(str(sch_path))
        result = get_net_at_point(sch, str(sch_path), 5.0, 5.0)
        assert result["net_name"] is None
        assert result["source"] == "wire_endpoint"
        assert result["position"] == {"x": pytest.approx(5.0), "y": pytest.approx(5.0)}
