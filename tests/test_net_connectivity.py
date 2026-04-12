"""
Tests for connected_pin_count in list_schematic_nets and the list_floating_labels tool.

Covers:
  - Schema registration for list_floating_labels (TestListFloatingLabelsSchema)
  - Handler dispatch registration (TestListFloatingLabelsDispatch)
  - Parameter validation (TestListFloatingLabelsParamValidation)
  - Core logic: list_floating_labels (TestListFloatingLabelsCoreLogic)
  - Core logic: count_pins_on_net (TestCountPinsOnNet)
  - connected_pin_count field in list_schematic_nets handler (TestListSchematicNetsConnectedPinCount)
  - Integration: floating labels in a real schematic file (TestListFloatingLabelsIntegration)
"""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.wire_connectivity import (
    _build_adjacency,
    _parse_virtual_connections,
    _parse_wires,
    count_pins_on_net,
    list_floating_labels,
)

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"


def _make_point(x: float, y: float) -> MagicMock:
    pt = MagicMock()
    pt.value = [x, y]
    return pt


def _make_wire(x1: float, y1: float, x2: float, y2: float) -> MagicMock:
    wire = MagicMock()
    wire.pts = MagicMock()
    wire.pts.xy = [_make_point(x1, y1), _make_point(x2, y2)]
    return wire


def _make_label(name: str, x: float, y: float) -> MagicMock:
    label = MagicMock()
    label.value = name
    label.at = MagicMock()
    label.at.value = [x, y, 0]
    return label


def _make_schematic_no_labels_no_symbols(*wires: Any) -> MagicMock:
    sch = MagicMock()
    sch.wire = list(wires)
    del sch.label
    del sch.symbol
    return sch


# ---------------------------------------------------------------------------
# TestListFloatingLabelsSchema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListFloatingLabelsSchema:
    """Verify the list_floating_labels schema is registered and well-formed."""

    def test_schema_registered(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "list_floating_labels" in TOOL_SCHEMAS

    def test_schema_required_fields(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        required = TOOL_SCHEMAS["list_floating_labels"]["inputSchema"]["required"]
        assert required == ["schematicPath"]

    def test_schema_has_title_and_description(self) -> None:
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["list_floating_labels"]
        assert schema.get("title")
        assert schema.get("description")


# ---------------------------------------------------------------------------
# TestListFloatingLabelsDispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListFloatingLabelsDispatch:
    """Verify the handler is wired into KiCadInterface.command_routes."""

    def test_list_floating_labels_in_routes(self) -> None:
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

        assert "list_floating_labels" in iface.command_routes
        assert callable(iface.command_routes["list_floating_labels"])


# ---------------------------------------------------------------------------
# TestListFloatingLabelsParamValidation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListFloatingLabelsParamValidation:
    """Handler returns error for missing schematicPath."""

    def _make_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_list_floating_labels

    def test_missing_schematic_path(self) -> None:
        handler = self._make_handler()
        result = handler({})
        assert result["success"] is False
        assert "schematicPath" in result["message"]

    def test_bad_schematic_path_returns_error(self) -> None:
        handler = self._make_handler()
        result = handler({"schematicPath": "/nonexistent/path/test.kicad_sch"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestListFloatingLabelsCoreLogic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListFloatingLabelsCoreLogic:
    """Unit tests for the list_floating_labels function."""

    def test_no_labels_returns_empty(self) -> None:
        sch = _make_schematic_no_labels_no_symbols()
        result = list_floating_labels(sch, "/tmp/test.kicad_sch")
        assert result == []

    def test_label_with_no_wires_and_no_pins_is_floating(self) -> None:
        label = _make_label("SDA", 10.0, 5.0)
        sch = MagicMock()
        sch.wire = []
        sch.label = [label]
        del sch.symbol
        result = list_floating_labels(sch, "/tmp/test.kicad_sch")
        assert len(result) == 1
        assert result[0]["name"] == "SDA"
        assert result[0]["x"] == pytest.approx(10.0)
        assert result[0]["y"] == pytest.approx(5.0)
        assert result[0]["type"] == "label"

    def test_label_connected_to_pin_not_floating(self) -> None:
        """Label at (0,0) connected to a pin at (2,0) via wire should NOT be floating."""
        wire = _make_wire(0.0, 0.0, 2.0, 0.0)
        label = _make_label("SCL", 0.0, 0.0)

        sch = MagicMock()
        sch.wire = [wire]
        sch.label = [label]

        # Mock a symbol whose pin is at (2, 0)
        symbol = MagicMock()
        symbol.property = MagicMock()
        symbol.property.Reference = MagicMock()
        symbol.property.Reference.value = "U1"
        sch.symbol = [symbol]

        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            return_value={"1": (2.0, 0.0)},
        ):
            result = list_floating_labels(sch, "/tmp/test.kicad_sch")

        assert result == []

    def test_label_not_connected_to_any_pin_is_floating(self) -> None:
        """Label at (0,0) with no wires to any pin should be floating."""
        label = _make_label("MOSI", 0.0, 0.0)
        wire = _make_wire(0.0, 0.0, 1.0, 0.0)

        sch = MagicMock()
        sch.wire = [wire]
        sch.label = [label]

        # A symbol whose pin is at a completely different location
        symbol = MagicMock()
        symbol.property = MagicMock()
        symbol.property.Reference = MagicMock()
        symbol.property.Reference.value = "U2"
        sch.symbol = [symbol]

        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            return_value={"1": (99.0, 99.0)},
        ):
            result = list_floating_labels(sch, "/tmp/test.kicad_sch")

        assert len(result) == 1
        assert result[0]["name"] == "MOSI"

    def test_label_directly_on_pin_not_floating(self) -> None:
        """Label placed directly at a pin position (no wire needed) should NOT be floating."""
        label = _make_label("PWR", 5.0, 3.0)

        sch = MagicMock()
        sch.wire = []
        sch.label = [label]

        symbol = MagicMock()
        symbol.property = MagicMock()
        symbol.property.Reference = MagicMock()
        symbol.property.Reference.value = "R1"
        sch.symbol = [symbol]

        # Pin is exactly at the label position
        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            return_value={"1": (5.0, 3.0)},
        ):
            result = list_floating_labels(sch, "/tmp/test.kicad_sch")

        assert result == []

    def test_multiple_labels_mixed_floating_and_connected(self) -> None:
        """Two labels: one connected, one floating."""
        label_connected = _make_label("NET_A", 0.0, 0.0)
        label_floating = _make_label("NET_B", 20.0, 20.0)
        wire = _make_wire(0.0, 0.0, 2.0, 0.0)

        sch = MagicMock()
        sch.wire = [wire]
        sch.label = [label_connected, label_floating]

        symbol = MagicMock()
        symbol.property = MagicMock()
        symbol.property.Reference = MagicMock()
        symbol.property.Reference.value = "C1"
        sch.symbol = [symbol]

        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            return_value={"1": (2.0, 0.0)},
        ):
            result = list_floating_labels(sch, "/tmp/test.kicad_sch")

        assert len(result) == 1
        assert result[0]["name"] == "NET_B"

    def test_template_symbols_skipped(self) -> None:
        """Symbols with _TEMPLATE references should be skipped, not crash."""
        label = _make_label("VBUS", 0.0, 0.0)

        sch = MagicMock()
        sch.wire = []
        sch.label = [label]

        template_sym = MagicMock()
        template_sym.property = MagicMock()
        template_sym.property.Reference = MagicMock()
        template_sym.property.Reference.value = "_TEMPLATE_R"
        sch.symbol = [template_sym]

        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            return_value={"1": (0.0, 0.0)},
        ) as mock_pins:
            result = list_floating_labels(sch, "/tmp/test.kicad_sch")

        # _TEMPLATE_ symbols are skipped; mock_pins should not have been called
        mock_pins.assert_not_called()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestCountPinsOnNet
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCountPinsOnNet:
    """Unit tests for count_pins_on_net."""

    def _build_graph(self, sch: Any, schematic_path: str):  # type: ignore[return]
        all_wires = _parse_wires(sch)
        if all_wires:
            adjacency, iu_to_wires = _build_adjacency(all_wires)
        else:
            adjacency, iu_to_wires = [], {}
        point_to_label, label_to_points = _parse_virtual_connections(sch, schematic_path)
        return all_wires, iu_to_wires, adjacency, point_to_label, label_to_points

    def test_no_labels_returns_zero(self) -> None:
        sch = _make_schematic_no_labels_no_symbols()
        all_wires, iu_to_wires, adj, p2l, l2p = self._build_graph(sch, "/tmp/t.kicad_sch")
        count = count_pins_on_net(
            sch, "/tmp/t.kicad_sch", "VCC", all_wires, iu_to_wires, adj, p2l, l2p
        )
        assert count == 0

    def test_unknown_net_returns_zero(self) -> None:
        wire = _make_wire(0.0, 0.0, 1.0, 0.0)
        label = _make_label("SDA", 0.0, 0.0)
        sch = MagicMock()
        sch.wire = [wire]
        sch.label = [label]
        del sch.symbol
        all_wires, iu_to_wires, adj, p2l, l2p = self._build_graph(sch, "/tmp/t.kicad_sch")
        count = count_pins_on_net(
            sch, "/tmp/t.kicad_sch", "UNKNOWN_NET", all_wires, iu_to_wires, adj, p2l, l2p
        )
        assert count == 0

    def test_counts_pin_via_wire(self) -> None:
        """Label at (0,0), wire to (2,0), pin at (2,0) → count == 1."""
        wire = _make_wire(0.0, 0.0, 2.0, 0.0)
        label = _make_label("SCL", 0.0, 0.0)
        sch = MagicMock()
        sch.wire = [wire]
        sch.label = [label]
        symbol = MagicMock()
        symbol.property = MagicMock()
        symbol.property.Reference = MagicMock()
        symbol.property.Reference.value = "U1"
        sch.symbol = [symbol]
        all_wires, iu_to_wires, adj, p2l, l2p = self._build_graph(sch, "/tmp/t.kicad_sch")
        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            return_value={"3": (2.0, 0.0)},
        ):
            count = count_pins_on_net(
                sch, "/tmp/t.kicad_sch", "SCL", all_wires, iu_to_wires, adj, p2l, l2p
            )
        assert count == 1

    def test_no_symbol_attribute_returns_zero(self) -> None:
        wire = _make_wire(0.0, 0.0, 2.0, 0.0)
        label = _make_label("SDA", 0.0, 0.0)
        sch = MagicMock()
        sch.wire = [wire]
        sch.label = [label]
        del sch.symbol
        all_wires, iu_to_wires, adj, p2l, l2p = self._build_graph(sch, "/tmp/t.kicad_sch")
        count = count_pins_on_net(
            sch, "/tmp/t.kicad_sch", "SDA", all_wires, iu_to_wires, adj, p2l, l2p
        )
        assert count == 0


# ---------------------------------------------------------------------------
# TestListSchematicNetsConnectedPinCount
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListSchematicNetsConnectedPinCount:
    """Verify connected_pin_count is present in list_schematic_nets response."""

    def _make_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_list_schematic_nets

    def test_connected_pin_count_present_in_response(self) -> None:
        handler = self._make_handler()

        label = _make_label("NET1", 0.0, 0.0)
        mock_sch = MagicMock()
        mock_sch.wire = []
        mock_sch.label = [label]
        del mock_sch.global_label
        del mock_sch.symbol

        with (
            patch("kicad_interface.SchematicManager.load_schematic", return_value=mock_sch),
            patch(
                "kicad_interface.ConnectionManager.get_net_connections",
                return_value=[],
            ),
        ):
            result = handler({"schematicPath": "/tmp/test.kicad_sch"})

        assert result["success"] is True
        assert len(result["nets"]) == 1
        net = result["nets"][0]
        assert "connected_pin_count" in net
        assert isinstance(net["connected_pin_count"], int)

    def test_connected_pin_count_is_zero_when_no_pins(self) -> None:
        handler = self._make_handler()

        label = _make_label("ORPHAN_NET", 50.0, 50.0)
        mock_sch = MagicMock()
        mock_sch.wire = []
        mock_sch.label = [label]
        del mock_sch.global_label
        del mock_sch.symbol

        with (
            patch("kicad_interface.SchematicManager.load_schematic", return_value=mock_sch),
            patch(
                "kicad_interface.ConnectionManager.get_net_connections",
                return_value=[],
            ),
        ):
            result = handler({"schematicPath": "/tmp/test.kicad_sch"})

        assert result["success"] is True
        assert result["nets"][0]["connected_pin_count"] == 0


# ---------------------------------------------------------------------------
# TestListFloatingLabelsIntegration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListFloatingLabelsIntegration:
    """Integration tests using a real .kicad_sch file."""

    def _make_sch_with_floating_label(self, tmp_path: Path) -> Path:
        """Copy the empty template and append a floating label."""
        sch_path = tmp_path / "test.kicad_sch"
        shutil.copy(TEMPLATE_SCH, sch_path)
        content = sch_path.read_text(encoding="utf-8")
        floating_label = (
            '  (label "FLOATING_NET" (at 100 100 0)\n'
            "    (effects (font (size 1.27 1.27)))\n"
            "    (uuid 11111111-0000-0000-0000-000000000001)\n"
            "  )"
        )
        idx = content.rfind(")")
        content = content[:idx] + "\n" + floating_label + "\n)"
        sch_path.write_text(content, encoding="utf-8")
        return sch_path

    def test_empty_schematic_has_no_floating_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "empty.kicad_sch"
            shutil.copy(TEMPLATE_SCH, sch_path)

            with patch("kicad_interface.USE_IPC_BACKEND", False):
                from kicad_interface import KiCADInterface

                iface = KiCADInterface.__new__(KiCADInterface)
            result = iface._handle_list_floating_labels({"schematicPath": str(sch_path)})

        assert result["success"] is True
        assert result["count"] == 0
        assert result["floating_labels"] == []

    def test_schematic_with_floating_label_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sch_path = self._make_sch_with_floating_label(Path(tmp))

            with patch("kicad_interface.USE_IPC_BACKEND", False):
                from kicad_interface import KiCADInterface

                iface = KiCADInterface.__new__(KiCADInterface)
            result = iface._handle_list_floating_labels({"schematicPath": str(sch_path)})

        assert result["success"] is True
        assert result["count"] == 1
        label = result["floating_labels"][0]
        assert label["name"] == "FLOATING_NET"
        assert label["x"] == pytest.approx(100.0)
        assert label["y"] == pytest.approx(100.0)
        assert label["type"] == "label"

    def test_list_schematic_nets_has_connected_pin_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sch_path = self._make_sch_with_floating_label(Path(tmp))

            with patch("kicad_interface.USE_IPC_BACKEND", False):
                from kicad_interface import KiCADInterface

                iface = KiCADInterface.__new__(KiCADInterface)
            result = iface._handle_list_schematic_nets({"schematicPath": str(sch_path)})

        assert result["success"] is True
        assert result["count"] == 1
        net = result["nets"][0]
        assert net["name"] == "FLOATING_NET"
        assert "connected_pin_count" in net
        assert net["connected_pin_count"] == 0
