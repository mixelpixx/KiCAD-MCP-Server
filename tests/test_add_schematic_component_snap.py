"""
Tests for the grid-snapping and collision-detection logic added to
add_schematic_component.

Covers:
  - _snap_to_grid: pure math, various edge cases
  - _check_schematic_collision: reads a .kicad_sch file to detect collisions
  - _handle_add_schematic_component: handler-level snap + collision
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_schematic(tmp_dir: Path, extra_block: str = "") -> Path:
    """Copy the empty template into tmp_dir, optionally injecting a symbol block."""
    dest = tmp_dir / "test.kicad_sch"
    shutil.copy(TEMPLATE_SCH, dest)
    if extra_block:
        content = dest.read_text(encoding="utf-8")
        idx = content.rfind(")")
        content = content[:idx] + "\n" + extra_block + "\n)"
        dest.write_text(content, encoding="utf-8")
    return dest


def _symbol_block(ref: str, x: float, y: float) -> str:
    """Minimal placed-symbol block for collision testing."""
    return (
        f'  (symbol (lib_id "Device:R") (at {x} {y} 0) (unit 1)\n'
        f'    (in_bom yes) (on_board yes) (dnp no)\n'
        f'    (uuid "snap-test-{ref.lower()}-000000000000")\n'
        f'    (property "Reference" "{ref}" (at {x + 1.27} {y - 2.54} 0))\n'
        f'    (property "Value" "10k" (at {x + 1.27} {y + 2.54} 0))\n'
        f'  )\n'
    )


def _make_iface():
    """Construct a KiCADInterface instance without calling __init__."""
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface
    return KiCADInterface.__new__(KiCADInterface)


# ===========================================================================
# Unit tests — _snap_to_grid (pure math)
# ===========================================================================


@pytest.mark.unit
class TestSnapToGrid:
    def _snap(self, v, grid=1.27):
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface
        return KiCADInterface._snap_to_grid(v, grid)

    def test_already_on_grid_unchanged(self):
        assert self._snap(2.54) == pytest.approx(2.54)

    def test_already_on_1_27_unchanged(self):
        assert self._snap(1.27) == pytest.approx(1.27)

    def test_zero_stays_zero(self):
        assert self._snap(0.0) == pytest.approx(0.0)

    def test_off_grid_snapped(self):
        # 0.1 mm off a 1.27 mm grid → snaps to 0.0
        result = self._snap(0.1)
        assert result == pytest.approx(0.0)

    def test_off_grid_snaps_up(self):
        # 1.30 / 1.27 ≈ 1.024 → rounds to 1 → 1.27
        result = self._snap(1.30)
        assert result == pytest.approx(1.27)

    def test_negative_value_snapped(self):
        # -1.25 / 1.27 ≈ -0.984 → rounds to -1 → -1.27
        result = self._snap(-1.25)
        assert result == pytest.approx(-1.27)

    def test_negative_zero_adjacent(self):
        # -0.1 should round to 0.0
        result = self._snap(-0.1)
        assert result == pytest.approx(0.0)

    def test_custom_grid_size(self):
        # Grid = 2.54; value 2.60 → 2.60/2.54 ≈ 1.024 → rounds to 1 → 2.54
        result = self._snap(2.60, grid=2.54)
        assert result == pytest.approx(2.54)

    def test_custom_grid_size_large(self):
        # Grid = 5.0; value 7.0 → 7/5 = 1.4 → rounds to 1 → 5.0
        result = self._snap(7.0, grid=5.0)
        assert result == pytest.approx(5.0)

    def test_multiples_of_grid_unchanged(self):
        for n in range(1, 6):
            assert self._snap(n * 1.27) == pytest.approx(n * 1.27)


# ===========================================================================
# Unit tests — _check_schematic_collision
# ===========================================================================


@pytest.mark.unit
class TestCheckSchematicCollision:
    def _check(self, schematic_path, x, y, min_dist=1.27):
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface
        return KiCADInterface._check_schematic_collision(str(schematic_path), x, y, min_dist)

    def test_empty_schematic_no_collision(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        result = self._check(sch, 50.0, 50.0)
        assert result is None

    def test_symbol_within_min_dist_returns_string(self, tmp_path):
        # Place R1 at (10.0, 20.0); query at (10.5, 20.0) — distance 0.5 mm < 1.27
        sch = _make_test_schematic(tmp_path, _symbol_block("R1", 10.0, 20.0))
        result = self._check(sch, 10.5, 20.0)
        assert result is not None
        assert "R1" in result

    def test_symbol_within_min_dist_contains_coordinates(self, tmp_path):
        sch = _make_test_schematic(tmp_path, _symbol_block("R1", 10.0, 20.0))
        result = self._check(sch, 10.2, 20.0)
        assert result is not None
        assert "10.0" in result
        assert "20.0" in result

    def test_symbol_far_away_no_collision(self, tmp_path):
        # Place R1 at (10.0, 20.0); query at (12.0, 20.0) — distance 2.0 mm > 1.27
        sch = _make_test_schematic(tmp_path, _symbol_block("R1", 10.0, 20.0))
        result = self._check(sch, 12.0, 20.0)
        assert result is None

    def test_symbol_exactly_on_position_detected(self, tmp_path):
        sch = _make_test_schematic(tmp_path, _symbol_block("C1", 30.0, 40.0))
        result = self._check(sch, 30.0, 40.0)
        assert result is not None
        assert "C1" in result

    def test_custom_min_dist(self, tmp_path):
        # Distance = 1.5 mm; default min_dist=1.27 → no collision
        # but with min_dist=2.0 → collision detected
        sch = _make_test_schematic(tmp_path, _symbol_block("R2", 10.0, 20.0))
        assert self._check(sch, 11.5, 20.0, min_dist=1.27) is None
        assert self._check(sch, 11.5, 20.0, min_dist=2.0) is not None

    def test_nonexistent_file_returns_none(self):
        result = self._check(Path("/nonexistent/file.kicad_sch"), 0.0, 0.0)
        assert result is None


# ===========================================================================
# Unit tests — _handle_add_schematic_component (mocked DynamicSymbolLoader)
# ===========================================================================


@pytest.mark.unit
class TestHandleAddSchematicComponentSnap:
    """Handler-level tests with DynamicSymbolLoader mocked out."""

    def _build_params(self, sch_path: str, x: float, y: float, ref: str = "R1") -> dict:
        return {
            "schematicPath": sch_path,
            "component": {
                "type": "R",
                "library": "Device",
                "reference": ref,
                "value": "10k",
                "x": x,
                "y": y,
            },
        }

    def test_off_grid_coords_produce_snapped_from_and_snap_note(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        with patch("commands.dynamic_symbol_loader.DynamicSymbolLoader") as MockLoader:
            MockLoader.return_value.add_component.return_value = None
            result = iface._handle_add_schematic_component(
                self._build_params(str(sch), x=0.1, y=0.2)
            )

        assert result.get("success") is True, result.get("message")
        assert "snapped_from" in result
        assert "snap_note" in result
        assert "placed_at" in result

    def test_off_grid_placed_at_is_snapped_values(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        with patch("commands.dynamic_symbol_loader.DynamicSymbolLoader") as MockLoader:
            MockLoader.return_value.add_component.return_value = None
            result = iface._handle_add_schematic_component(
                self._build_params(str(sch), x=1.30, y=2.60)
            )

        assert result.get("success") is True, result.get("message")
        # 1.30 snaps to 1.27; 2.60 snaps to 2.54
        placed = result["placed_at"]
        assert placed[0] == pytest.approx(1.27)
        assert placed[1] == pytest.approx(2.54)

    def test_off_grid_snapped_from_contains_original_coords(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()
        x_raw, y_raw = 1.30, 2.60

        with patch("commands.dynamic_symbol_loader.DynamicSymbolLoader") as MockLoader:
            MockLoader.return_value.add_component.return_value = None
            result = iface._handle_add_schematic_component(
                self._build_params(str(sch), x=x_raw, y=y_raw)
            )

        assert result["snapped_from"] == pytest.approx([x_raw, y_raw])

    def test_on_grid_coords_no_snapped_from_key(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        with patch("commands.dynamic_symbol_loader.DynamicSymbolLoader") as MockLoader:
            MockLoader.return_value.add_component.return_value = None
            result = iface._handle_add_schematic_component(
                self._build_params(str(sch), x=2.54, y=5.08)
            )

        assert result.get("success") is True, result.get("message")
        assert "snapped_from" not in result
        assert "snap_note" not in result

    def test_on_grid_placed_at_matches_input(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        with patch("commands.dynamic_symbol_loader.DynamicSymbolLoader") as MockLoader:
            MockLoader.return_value.add_component.return_value = None
            result = iface._handle_add_schematic_component(
                self._build_params(str(sch), x=2.54, y=5.08)
            )

        assert result["placed_at"] == pytest.approx([2.54, 5.08])

    def test_missing_schematic_path_returns_failure(self, tmp_path):
        iface = _make_iface()
        result = iface._handle_add_schematic_component({"component": {"type": "R", "x": 0, "y": 0}})
        assert result["success"] is False

    def test_missing_component_returns_failure(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()
        result = iface._handle_add_schematic_component({"schematicPath": str(sch)})
        assert result["success"] is False

    def test_collision_returns_failure(self, tmp_path):
        """Handler returns failure when another component is too close."""
        sch = _make_test_schematic(tmp_path, _symbol_block("R1", 10.16, 20.32))
        iface = _make_iface()

        with patch("commands.dynamic_symbol_loader.DynamicSymbolLoader"):
            # Query at (10.16, 20.32) — exact match of existing symbol
            result = iface._handle_add_schematic_component(
                self._build_params(str(sch), x=10.16, y=20.32, ref="R2")
            )

        assert result["success"] is False
        assert "collision" in result["message"].lower()
