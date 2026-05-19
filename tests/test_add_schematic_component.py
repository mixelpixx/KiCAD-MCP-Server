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
    tmp = tempfile.NamedTemporaryFile(suffix=".kicad_sch", delete=False, mode="w", encoding="utf-8")
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
    return [
        int(n)
        for n in re.findall(r"\(symbol \(lib_id [^)]+\) \(at [^)]+\) \(unit (\d+)\)", content)
    ]


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
        result = self._call_handler(
            {
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
            }
        )
        assert result["success"] is True
        units = _unit_values_in_file(sch)
        assert 1 in units

    def test_unit_2_passed_through_handler(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        result = self._call_handler(
            {
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
            }
        )
        assert result["success"] is True
        units = _unit_values_in_file(sch)
        assert 2 in units


# ---------------------------------------------------------------------------
# Hierarchical sub-sheets — no (sheet_instances ...) block
# ---------------------------------------------------------------------------


# Minimal sub-sheet: same outer (kicad_sch ...) form as a root schematic but
# WITHOUT (sheet_instances ...). Hierarchical KiCad designs only carry that
# block in the root .kicad_sch — every child sheet ends after lib_symbols /
# any placed (symbol ...) blocks. The fix under test must insert new symbol
# instances before the closing paren of (kicad_sch ...) when the marker is
# missing.
SUB_SHEET_NO_SHEET_INSTANCES = """(kicad_sch
\t(version 20260306)
\t(generator "eeschema")
\t(generator_version "10.0")
\t(uuid "bbbb2222-2222-2222-2222-bbbbbbbbbbbb")
\t(paper "A4")
\t(lib_symbols)
)
"""


@pytest.mark.unit
class TestCreateComponentInstanceSubSheet:
    """Hierarchical sub-sheets don't have (sheet_instances ...).

    Before the fix, create_component_instance raised
    'Could not find insertion point in schematic' on any sub-sheet, blocking
    every add_schematic_component call into a hierarchical design's child
    sheet.
    """

    def setup_method(self) -> None:
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        self.DynamicSymbolLoader = DynamicSymbolLoader

    def _loader(self) -> Any:
        return self.DynamicSymbolLoader()

    def test_sub_sheet_insertion_succeeds(self, tmp_path: Any) -> None:
        sch = tmp_path / "child.kicad_sch"
        sch.write_text(SUB_SHEET_NO_SHEET_INSTANCES, encoding="utf-8")

        ok = self._loader().create_component_instance(
            sch, "Device", "R", reference="R_TEST", value="100k", x=50, y=50
        )

        assert ok is True
        content = sch.read_text(encoding="utf-8")
        assert '"R_TEST"' in content
        assert "100k" in content

    def test_sub_sheet_keeps_outer_form_balanced(self, tmp_path: Any) -> None:
        """The new symbol must land inside (kicad_sch ...), with parens balanced."""
        sch = tmp_path / "child.kicad_sch"
        sch.write_text(SUB_SHEET_NO_SHEET_INSTANCES, encoding="utf-8")

        self._loader().create_component_instance(
            sch, "Device", "R", reference="R_TEST", value="1k", x=10, y=10
        )

        content = sch.read_text(encoding="utf-8")
        assert content.count("(") == content.count(
            ")"
        ), "Inserting into a sub-sheet must keep parens balanced"
        # The outer form must still parse via sexpdata.
        import sexpdata

        parsed = sexpdata.loads(content)
        assert isinstance(parsed, list)
        assert parsed[0] == sexpdata.Symbol("kicad_sch")

    def test_sub_sheet_round_trips_via_sexpdata(self, tmp_path: Any) -> None:
        """The injected symbol must survive a sexpdata load+dump round-trip."""
        import sexpdata

        sch = tmp_path / "child.kicad_sch"
        sch.write_text(SUB_SHEET_NO_SHEET_INSTANCES, encoding="utf-8")

        self._loader().create_component_instance(
            sch, "Device", "R", reference="R_TEST", value="1k", x=10, y=10
        )

        parsed = sexpdata.loads(sch.read_text(encoding="utf-8"))
        # The placed (symbol (lib_id ...) ...) block must be a top-level child of kicad_sch.
        symbol_items = [
            item
            for item in parsed[1:]
            if isinstance(item, list) and len(item) > 0 and item[0] == sexpdata.Symbol("symbol")
        ]
        # Confirm at least one of those carries our reference.
        assert any(
            sexpdata.dumps(s).find('"R_TEST"') >= 0 for s in symbol_items
        ), "Reference 'R_TEST' should appear in a top-level (symbol ...) child"


# ---------------------------------------------------------------------------
# Mirror parameter — known gap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddComponentMirrorParam:
    """ComponentManager.add_component does NOT honor a 'mirror' kwarg today.

    The MCP add_schematic_component tool schema also doesn't expose mirror.
    A mirror is currently only applicable post-add via rotate_schematic_component.

    These tests pin down the silent-drop behavior so a fixture that passes
    'mirror': 'x' and then asserts something against the resulting schematic
    cannot accidentally pass for the wrong reason (the symbol ends up
    unmirrored). If/when add_component grows real mirror support, update both
    tests together — the second test then becomes the positive assertion."""

    def setup_method(self) -> None:
        from commands.component_schematic import ComponentManager
        from commands.schematic import SchematicManager

        self.ComponentManager = ComponentManager
        self.SchematicManager = SchematicManager

    def _add(self, sch_path: Path, mirror_value: Any) -> None:
        sch = self.SchematicManager.load_schematic(str(sch_path))
        params = {
            "type": "R",
            "reference": "R1",
            "value": "10k",
            "x": 100.0,
            "y": 100.0,
            "rotation": 0,
        }
        if mirror_value is not None:
            params["mirror"] = mirror_value
        self.ComponentManager.add_component(sch, params, sch_path)
        self.SchematicManager.save_schematic(sch, str(sch_path))

    def test_mirror_x_arg_is_silently_dropped(self, tmp_path: Any) -> None:
        sch = tmp_path / "mirror_x.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self._add(sch, "x")
        text = sch.read_text()
        assert "(mirror x)" not in text, (
            "ComponentManager.add_component now appears to honor mirror='x'. "
            "Update _build_mirror_case in test_pin_world_xy_eeschema_truth.py "
            "to drop the post-add mirror application and remove this test."
        )

    def test_mirror_y_arg_is_silently_dropped(self, tmp_path: Any) -> None:
        sch = tmp_path / "mirror_y.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self._add(sch, "y")
        text = sch.read_text()
        assert "(mirror y)" not in text, (
            "ComponentManager.add_component now appears to honor mirror='y'. "
            "See sibling test_mirror_x_arg_is_silently_dropped."
        )
