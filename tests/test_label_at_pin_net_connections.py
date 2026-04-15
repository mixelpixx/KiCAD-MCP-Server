"""
Tests for get_net_connections() — label-at-pin (no wire) fix.

Before the fix, get_net_connections() built its match-point set exclusively
from wire endpoints.  If a net label was placed directly at a pin endpoint
with no wire segment in between (a valid KiCad style), the function returned
early with 0 connections because connected_wire_points was empty.

The fix builds all_match_points as the union of wire endpoints AND label
positions, so a label placed at a pin endpoint is detected whether or not a
wire exists.

Covers:
  - Label at pin, no wire → pin IS found          (core bug fix)
  - Label connected via wire → pin IS found        (regression: existing behaviour)
  - Label with wires, pin elsewhere → no match     (regression: no false positives)
  - Multiple labels for same net, mixed styles     (regression: mixed case)
  - No labels for requested net → empty result     (edge case)
  - Schematic has no wire attribute → still works  (edge case)
"""

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))


# ---------------------------------------------------------------------------
# Mock helpers (mirrors pattern used in test_net_connectivity.py)
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


def _make_label(name: str, x: float, y: float) -> MagicMock:
    label = MagicMock()
    label.value = name
    label.at = MagicMock()
    label.at.value = [x, y, 0]
    return label


def _make_symbol(ref: str) -> MagicMock:
    sym = MagicMock()
    sym.property = MagicMock()
    sym.property.Reference = MagicMock()
    sym.property.Reference.value = ref
    sym.lib_id = MagicMock()
    sym.lib_id.value = f"Device:{ref}"
    return sym


def _make_schematic(
    labels: list[Any],
    wires: list[Any],
    symbols: list[Any],
) -> MagicMock:
    sch = MagicMock()
    sch.label = labels
    sch.wire = wires
    sch.symbol = symbols
    return sch


# ---------------------------------------------------------------------------
# Shared import helper
# ---------------------------------------------------------------------------


def _get_connection_manager() -> Any:
    for mod in ["pcbnew", "skip"]:
        sys.modules.setdefault(mod, types.ModuleType(mod))
    from commands.connection_schematic import ConnectionManager

    return ConnectionManager


# ---------------------------------------------------------------------------
# TestLabelAtPinNoWire — the core bug fix
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLabelAtPinNoWire:
    """Label placed directly at a pin endpoint, no wire segment — must be detected."""

    def test_label_at_pin_no_wire_finds_connection(self) -> None:
        """Primary regression: label at (5, 3), pin at (5, 3), no wire → connection found."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("VCC", 5.0, 3.0)
        symbol = _make_symbol("U1")
        sch = _make_schematic(labels=[label], wires=[], symbols=[symbol])

        with (
            patch(
                "commands.pin_locator.PinLocator.get_symbol_pins",
                return_value={"1": {}},
            ),
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=[5.0, 3.0],  # pin exactly at label position
            ),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "VCC",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        assert len(result) == 1
        assert result[0]["component"] == "U1"
        assert result[0]["pin"] == "1"

    def test_label_at_pin_no_wire_multiple_pins(self) -> None:
        """Two pins on the same net label, no wires — both detected."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("GND", 0.0, 0.0)
        sym_r1 = _make_symbol("R1")
        sym_c1 = _make_symbol("C1")
        sch = _make_schematic(labels=[label], wires=[], symbols=[sym_r1, sym_c1])

        def fake_get_pins(sch_path: Any, lib_id: str) -> dict:  # type: ignore[return]
            return {"2": {}}

        def fake_get_pin_loc(sch_path: Any, ref: str, pin_num: str) -> list:  # type: ignore[return]
            # Both R1 pin 2 and C1 pin 2 sit exactly at the label
            return [0.0, 0.0]

        with (
            patch("commands.pin_locator.PinLocator.get_symbol_pins", side_effect=fake_get_pins),
            patch("commands.pin_locator.PinLocator.get_pin_location", side_effect=fake_get_pin_loc),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "GND",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        refs = {r["component"] for r in result}
        assert "R1" in refs
        assert "C1" in refs

    def test_label_at_pin_within_tolerance(self) -> None:
        """Label at (5.0, 3.0), pin at (5.3, 3.0) — within 0.5 mm tolerance → found."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("NET_A", 5.0, 3.0)
        symbol = _make_symbol("D1")
        sch = _make_schematic(labels=[label], wires=[], symbols=[symbol])

        with (
            patch(
                "commands.pin_locator.PinLocator.get_symbol_pins",
                return_value={"A": {}},
            ),
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=[5.3, 3.0],  # within 0.5 mm
            ),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "NET_A",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        assert len(result) == 1

    def test_label_at_pin_outside_tolerance_no_match(self) -> None:
        """Label at (5.0, 3.0), pin at (6.0, 3.0) — outside tolerance → not found."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("NET_B", 5.0, 3.0)
        symbol = _make_symbol("Q1")
        sch = _make_schematic(labels=[label], wires=[], symbols=[symbol])

        with (
            patch(
                "commands.pin_locator.PinLocator.get_symbol_pins",
                return_value={"B": {}},
            ),
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=[6.0, 3.0],  # 1 mm away — outside 0.5 mm tolerance
            ),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "NET_B",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        assert len(result) == 0


# ---------------------------------------------------------------------------
# TestLabelViaWire — regression: existing wire-based behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLabelViaWire:
    """Wire-connected nets must still work after the fix (no regression)."""

    def test_label_connected_via_wire_finds_pin(self) -> None:
        """Label at (0,0) → wire to (5,0) → pin at (5,0) → connection found."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("SCL", 0.0, 0.0)
        wire = _make_wire(0.0, 0.0, 5.0, 0.0)
        symbol = _make_symbol("U2")
        sch = _make_schematic(labels=[label], wires=[wire], symbols=[symbol])

        with (
            patch(
                "commands.pin_locator.PinLocator.get_symbol_pins",
                return_value={"3": {}},
            ),
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=[5.0, 0.0],
            ),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "SCL",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        assert len(result) == 1
        assert result[0]["component"] == "U2"
        assert result[0]["pin"] == "3"

    def test_wire_connected_pin_elsewhere_not_matched(self) -> None:
        """Pin at (99, 99) with wire only reaching (5, 0) — pin must NOT be returned."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("SDA", 0.0, 0.0)
        wire = _make_wire(0.0, 0.0, 5.0, 0.0)
        symbol = _make_symbol("U3")
        sch = _make_schematic(labels=[label], wires=[wire], symbols=[symbol])

        with (
            patch(
                "commands.pin_locator.PinLocator.get_symbol_pins",
                return_value={"4": {}},
            ),
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=[99.0, 99.0],
            ),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "SDA",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        assert len(result) == 0


# ---------------------------------------------------------------------------
# TestMixedStyles — both styles on the same net
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMixedStyles:
    """One label wired, another label direct-at-pin — both connections found."""

    def test_mixed_wired_and_direct_label(self) -> None:
        """
        Net 'MOSI' has two labels:
          - Label A at (0,0) with wire to pin at (5,0)   [wired style]
          - Label B at (10,3) directly on pin at (10,3)  [direct style]
        Both should be found.
        """
        ConnectionManager = _get_connection_manager()

        label_a = _make_label("MOSI", 0.0, 0.0)
        label_b = _make_label("MOSI", 10.0, 3.0)
        wire = _make_wire(0.0, 0.0, 5.0, 0.0)
        sym_wired = _make_symbol("U4")
        sym_direct = _make_symbol("U5")

        sch = _make_schematic(
            labels=[label_a, label_b],
            wires=[wire],
            symbols=[sym_wired, sym_direct],
        )

        # U4 pin at wire endpoint, U5 pin at direct label position
        def fake_get_pins(sch_path: Any, lib_id: str) -> dict:  # type: ignore[return]
            return {"1": {}}

        def fake_get_pin_loc(sch_path: Any, ref: str, pin_num: str) -> list:  # type: ignore[return]
            if ref == "U4":
                return [5.0, 0.0]
            return [10.0, 3.0]

        with (
            patch("commands.pin_locator.PinLocator.get_symbol_pins", side_effect=fake_get_pins),
            patch("commands.pin_locator.PinLocator.get_pin_location", side_effect=fake_get_pin_loc),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "MOSI",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        refs = {r["component"] for r in result}
        assert "U4" in refs, "wired-style pin not found"
        assert "U5" in refs, "direct-label-at-pin not found"


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEdgeCases:
    """Boundary conditions that should not crash or return false positives."""

    def test_unknown_net_returns_empty(self) -> None:
        """Requesting a net name that doesn't exist returns []."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("VCC", 0.0, 0.0)
        sch = _make_schematic(labels=[label], wires=[], symbols=[])

        result = ConnectionManager.get_net_connections(sch, "DOES_NOT_EXIST")
        assert result == []

    def test_no_labels_on_schematic_returns_empty(self) -> None:
        """Schematic with no label attribute returns [] gracefully."""
        ConnectionManager = _get_connection_manager()

        sch = MagicMock()
        del sch.label  # simulate a schematic with no labels

        result = ConnectionManager.get_net_connections(sch, "VCC")
        assert result == []

    def test_no_wire_attribute_still_checks_label_positions(self) -> None:
        """Schematic with no wire attribute must still match label-at-pin."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("RST", 7.0, 2.0)
        symbol = _make_symbol("IC1")

        sch = MagicMock()
        sch.label = [label]
        del sch.wire  # no wire attribute at all
        sch.symbol = [symbol]

        with (
            patch(
                "commands.pin_locator.PinLocator.get_symbol_pins",
                return_value={"RST": {}},
            ),
            patch(
                "commands.pin_locator.PinLocator.get_pin_location",
                return_value=[7.0, 2.0],
            ),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "RST",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        assert len(result) == 1
        assert result[0]["component"] == "IC1"

    def test_template_symbols_skipped(self) -> None:
        """_TEMPLATE_ reference symbols must not appear in results."""
        ConnectionManager = _get_connection_manager()

        label = _make_label("PWR", 0.0, 0.0)
        template_sym = _make_symbol("_TEMPLATE_PWR")
        real_sym = _make_symbol("U6")

        sch = _make_schematic(labels=[label], wires=[], symbols=[template_sym, real_sym])

        def fake_get_pins(sch_path: Any, lib_id: str) -> dict:  # type: ignore[return]
            return {"1": {}}

        def fake_get_pin_loc(sch_path: Any, ref: str, pin_num: str) -> list:  # type: ignore[return]
            return [0.0, 0.0]

        with (
            patch("commands.pin_locator.PinLocator.get_symbol_pins", side_effect=fake_get_pins),
            patch("commands.pin_locator.PinLocator.get_pin_location", side_effect=fake_get_pin_loc),
        ):
            result = ConnectionManager.get_net_connections(
                sch,
                "PWR",
                schematic_path=Path("/fake/test.kicad_sch"),
            )

        refs = {r["component"] for r in result}
        assert "_TEMPLATE_PWR" not in refs, "_TEMPLATE_ symbol must be skipped"
        assert "U6" in refs
