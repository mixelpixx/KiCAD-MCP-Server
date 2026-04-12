"""
Tests for get_schematic_component and edit_schematic_component fieldPositions support.
"""

import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Ensure python/ directory is on path so kicad_interface can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

# Minimal placed-symbol block we can embed into a schematic for testing
PLACED_RESISTOR_BLOCK = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
  )
"""


def _make_test_schematic(tmp_dir: Path, extra_block: str = "") -> Path:
    """Copy empty.kicad_sch into tmp_dir, optionally appending a placed symbol block."""
    dest = tmp_dir / "test.kicad_sch"
    src_content = TEMPLATE_SCH.read_text(encoding="utf-8")
    # Insert placed symbol block before the closing paren of the top-level form
    if extra_block:
        src_content = src_content.rstrip()
        if src_content.endswith(")"):
            src_content = src_content[:-1] + "\n" + extra_block + ")\n"
    dest.write_text(src_content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Unit tests – regex / parsing logic only (no file I/O, no KiCAD imports)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSchematicComponentParsing:
    """Unit tests for the regex logic used by _handle_get_schematic_component."""

    def _parse_fields(self, block_text: str) -> dict:
        """Mirrors the regex used in _handle_get_schematic_component."""
        prop_pattern = re.compile(
            r'\(property\s+"([^"]*)"\s+"([^"]*)"\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)'
        )
        fields = {}
        for m in prop_pattern.finditer(block_text):
            name, value, x, y, angle = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
                m.group(5),
            )
            fields[name] = {
                "value": value,
                "x": float(x),
                "y": float(y),
                "angle": float(angle),
            }
        return fields

    def _parse_comp_pos(self, block_text: str) -> Any:
        """Mirrors the regex used to extract symbol position."""
        m = re.search(
            r'\(symbol\s+\(lib_id\s+"[^"]*"\s*\)\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)',
            block_text,
        )
        if m:
            return {
                "x": float(m.group(1)),
                "y": float(m.group(2)),
                "angle": float(m.group(3)),
            }
        return None

    def test_parses_reference_field(self) -> None:
        fields = self._parse_fields(PLACED_RESISTOR_BLOCK)
        assert "Reference" in fields
        assert fields["Reference"]["value"] == "R1"
        assert fields["Reference"]["x"] == pytest.approx(51.27)
        assert fields["Reference"]["y"] == pytest.approx(47.46)
        assert fields["Reference"]["angle"] == pytest.approx(0.0)

    def test_parses_value_field(self) -> None:
        fields = self._parse_fields(PLACED_RESISTOR_BLOCK)
        assert "Value" in fields
        assert fields["Value"]["value"] == "10k"
        assert fields["Value"]["x"] == pytest.approx(51.27)
        assert fields["Value"]["y"] == pytest.approx(52.54)

    def test_parses_all_four_standard_fields(self) -> None:
        fields = self._parse_fields(PLACED_RESISTOR_BLOCK)
        assert set(fields.keys()) >= {"Reference", "Value", "Footprint", "Datasheet"}

    def test_parses_component_position(self) -> None:
        pos = self._parse_comp_pos(PLACED_RESISTOR_BLOCK)
        assert pos is not None
        assert pos["x"] == pytest.approx(50.0)
        assert pos["y"] == pytest.approx(50.0)
        assert pos["angle"] == pytest.approx(0.0)

    def test_field_position_regex_replaces_correctly(self) -> None:
        """Mirrors the regex used in _handle_edit_schematic_component for fieldPositions."""
        field_name = "Reference"
        new_x, new_y, new_angle = 99.0, 88.0, 0
        block = PLACED_RESISTOR_BLOCK
        block = re.sub(
            r'(\(property\s+"'
            + re.escape(field_name)
            + r'"\s+"[^"]*"\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*\)',
            rf"\1(at {new_x} {new_y} {new_angle})",
            block,
        )
        fields = self._parse_fields(block)
        assert fields["Reference"]["x"] == pytest.approx(99.0)
        assert fields["Reference"]["y"] == pytest.approx(88.0)
        # Value should be unchanged
        assert fields["Value"]["x"] == pytest.approx(51.27)

    def test_field_position_regex_preserves_value(self) -> None:
        """Replacing position must not change the field value string."""
        block = PLACED_RESISTOR_BLOCK
        block = re.sub(
            r'(\(property\s+"Value"\s+"[^"]*"\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*\)',
            r"\1(at 0.0 0.0 0)",
            block,
        )
        fields = self._parse_fields(block)
        assert fields["Value"]["value"] == "10k"


# ---------------------------------------------------------------------------
# Integration tests – real file I/O using the empty.kicad_sch template
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetSchematicComponentIntegration:
    """Integration tests: write a real .kicad_sch and call the handler."""

    @pytest.fixture
    def sch_with_r1(self, tmp_path: Any) -> Any:
        return _make_test_schematic(tmp_path, PLACED_RESISTOR_BLOCK)

    def _get_interface(self) -> Any:
        """Lazily import KiCADInterface to avoid pcbnew import at collection time."""
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_get_returns_success(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        assert result["success"] is True

    def test_get_returns_correct_reference(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        assert result["reference"] == "R1"

    def test_get_returns_component_position(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        assert result["position"] is not None
        assert result["position"]["x"] == pytest.approx(50.0)
        assert result["position"]["y"] == pytest.approx(50.0)

    def test_get_returns_reference_field_position(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        ref_field = result["fields"]["Reference"]
        assert ref_field["value"] == "R1"
        assert ref_field["x"] == pytest.approx(51.27)
        assert ref_field["y"] == pytest.approx(47.46)

    def test_get_returns_value_field(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        val_field = result["fields"]["Value"]
        assert val_field["value"] == "10k"
        assert val_field["x"] == pytest.approx(51.27)
        assert val_field["y"] == pytest.approx(52.54)

    def test_get_unknown_reference_returns_failure(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R99",
            },
        )
        assert result["success"] is False
        assert "R99" in result["message"]

    def test_get_missing_path_returns_failure(self) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "get_schematic_component",
            {
                "reference": "R1",
            },
        )
        assert result["success"] is False


@pytest.mark.integration
class TestEditSchematicComponentFieldPositions:
    """Integration tests for the new fieldPositions parameter."""

    @pytest.fixture
    def sch_with_r1(self, tmp_path: Any) -> Any:
        return _make_test_schematic(tmp_path, PLACED_RESISTOR_BLOCK)

    def _get_interface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_reposition_reference_label(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "fieldPositions": {"Reference": {"x": 99.0, "y": 88.0, "angle": 0}},
            },
        )
        assert result["success"] is True

        # Verify the position was actually written
        get_result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        assert get_result["fields"]["Reference"]["x"] == pytest.approx(99.0)
        assert get_result["fields"]["Reference"]["y"] == pytest.approx(88.0)

    def test_reposition_does_not_change_value(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "fieldPositions": {"Reference": {"x": 99.0, "y": 88.0}},
            },
        )
        get_result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        # Value field position must be unchanged
        assert get_result["fields"]["Value"]["x"] == pytest.approx(51.27)
        assert get_result["fields"]["Value"]["y"] == pytest.approx(52.54)

    def test_reposition_multiple_fields(self, sch_with_r1: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "fieldPositions": {
                    "Reference": {"x": 10.0, "y": 20.0, "angle": 0},
                    "Value": {"x": 10.0, "y": 30.0, "angle": 0},
                },
            },
        )
        assert result["success"] is True

        get_result = iface.handle_command(
            "get_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        assert get_result["fields"]["Reference"]["x"] == pytest.approx(10.0)
        assert get_result["fields"]["Value"]["y"] == pytest.approx(30.0)

    def test_fieldpositions_alone_is_valid(self, sch_with_r1: Any) -> None:
        """fieldPositions without value/footprint/newReference should succeed."""
        iface = self._get_interface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "fieldPositions": {"Value": {"x": 55.0, "y": 60.0}},
            },
        )
        assert result["success"] is True

    def test_no_params_still_fails(self, sch_with_r1: Any) -> None:
        """Providing no update params should return an error."""
        iface = self._get_interface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
            },
        )
        assert result["success"] is False
