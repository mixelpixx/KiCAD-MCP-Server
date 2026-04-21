"""
Tests for add_schematic_component handler, focusing on the unit parameter
for multi-unit symbols (e.g. quad optocouplers, dual op-amps).
"""

import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATES_DIR = Path(__file__).parent.parent / "python" / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"


def _write_temp_sch(content: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        suffix=".kicad_sch", delete=False, mode="w", encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit_values_in_file(path: Path) -> list[int]:
    """Return all (unit N) values written for symbol instances in the schematic."""
    content = path.read_text()
    # Match top-level symbol instances: (symbol (lib_id ...) (at ...) (unit N) ...)
    return [int(n) for n in re.findall(r"\(symbol \(lib_id [^)]+\) \(at [^)]+\) \(unit (\d+)\)", content)]


# ---------------------------------------------------------------------------
# Unit tests – create_component_instance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateComponentInstanceUnit:
    """Tests for DynamicSymbolLoader.create_component_instance unit parameter."""

    def setup_method(self) -> None:
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        self.DynamicSymbolLoader = DynamicSymbolLoader

    def _loader(self) -> Any:
        return self.DynamicSymbolLoader()

    def test_default_unit_is_1(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = self._loader()
        loader.create_component_instance(
            sch, "Device", "R", reference="R1", value="10k", x=10, y=10
        )
        units = _unit_values_in_file(sch)
        assert 1 in units

    def test_explicit_unit_1(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = self._loader()
        loader.create_component_instance(
            sch, "Device", "R", reference="R1", value="10k", x=10, y=10, unit=1
        )
        units = _unit_values_in_file(sch)
        assert units.count(1) >= 1

    def test_unit_2_written_correctly(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = self._loader()
        loader.create_component_instance(
            sch, "Device", "R", reference="U1", value="TLP291-4", x=10, y=10, unit=2
        )
        units = _unit_values_in_file(sch)
        assert 2 in units

    def test_unit_4_written_correctly(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = self._loader()
        loader.create_component_instance(
            sch, "Device", "R", reference="U1", value="TLP291-4", x=10, y=10, unit=4
        )
        units = _unit_values_in_file(sch)
        assert 4 in units

    def test_instances_block_uses_same_unit(self, tmp_path: Any) -> None:
        """The (instances ...) path block must also record the correct unit number."""
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = self._loader()
        loader.create_component_instance(
            sch, "Device", "R", reference="U1", value="val", x=5, y=5, unit=3
        )
        content = sch.read_text()
        # The (unit 3) inside the (instances ...) block
        assert "(unit 3)" in content
        # Count occurrences — should appear at least twice (symbol header + instances)
        assert content.count("(unit 3)") >= 2

    def test_multiple_units_same_reference(self, tmp_path: Any) -> None:
        """Placing units A and B of the same reference produces two distinct unit entries."""
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = self._loader()
        loader.create_component_instance(
            sch, "Device", "R", reference="U10", value="TLP291-4", x=10, y=10, unit=1
        )
        loader.create_component_instance(
            sch, "Device", "R", reference="U10", value="TLP291-4", x=10, y=35, unit=2
        )
        units = _unit_values_in_file(sch)
        assert 1 in units
        assert 2 in units


# ---------------------------------------------------------------------------
# Handler-level tests – _handle_add_schematic_component
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerAddSchematicComponent:
    """Tests for KiCADInterface._handle_add_schematic_component unit plumbing."""

    def _call_handler(self, params: dict) -> dict:
        from kicad_interface import KiCADInterface

        iface = KiCADInterface()
        return iface._handle_add_schematic_component(params)

    def test_missing_schematic_path_returns_error(self) -> None:
        result = self._call_handler({"component": {"type": "R", "library": "Device"}})
        assert result["success"] is False
        assert "path" in result["message"].lower() or "schematic" in result["message"].lower()

    def test_missing_component_returns_error(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        result = self._call_handler({"schematicPath": str(sch)})
        assert result["success"] is False

    def test_unit_defaults_to_1_in_handler(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        result = self._call_handler({
            "schematicPath": str(sch),
            "component": {
                "library": "Device",
                "type": "R",
                "reference": "R99",
                "value": "1k",
                "x": 10,
                "y": 10,
                # no "unit" key — should default to 1
            },
        })
        assert result["success"] is True
        units = _unit_values_in_file(sch)
        assert 1 in units

    def test_unit_2_passed_through_handler(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        result = self._call_handler({
            "schematicPath": str(sch),
            "component": {
                "library": "Device",
                "type": "R",
                "reference": "U10",
                "value": "TLP291-4",
                "x": 25,
                "y": 35,
                "unit": 2,
            },
        })
        assert result["success"] is True
        units = _unit_values_in_file(sch)
        assert 2 in units
