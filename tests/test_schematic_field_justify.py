"""
Tests for the justify directive support in edit_schematic_component fieldPositions
and set_schematic_component_property.

Covers:
  - _set_justify_on_property() helper (unit tests, no file I/O)
  - fieldPositions[field].justify via edit_schematic_component (integration)
  - justify forwarding via set_schematic_component_property (integration)
  - Backward-compat: existing calls without justify must be unaffected
"""

import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATE_SCH = Path(__file__).parent.parent / "src" / "kicad_mcp" / "templates" / "empty.kicad_sch"

# Minimal placed-symbol block used across integration tests
PLACED_RESISTOR_BLOCK = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff")
    (property "Reference" "R2" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "4k7" (at 51.27 52.54 0)
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
    dest = tmp_dir / "justify_test.kicad_sch"
    src_content = TEMPLATE_SCH.read_text(encoding="utf-8")
    if extra_block:
        src_content = src_content.rstrip()
        if src_content.endswith(")"):
            src_content = src_content[:-1] + "\n" + extra_block + ")\n"
    dest.write_text(src_content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Unit tests — exercise _set_justify_on_property() directly, no file I/O
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetJustifyOnPropertyHelper:
    """Unit tests for the _set_justify_on_property helper."""

    def _get_interface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_adds_justify_left(self) -> None:
        iface = self._get_interface()
        block = PLACED_RESISTOR_BLOCK
        result = iface._set_justify_on_property(block, "Reference", "left")
        assert "(justify left)" in result

    def test_adds_justify_right(self) -> None:
        iface = self._get_interface()
        block = PLACED_RESISTOR_BLOCK
        result = iface._set_justify_on_property(block, "Reference", "right")
        assert "(justify right)" in result

    def test_adds_combined_justify(self) -> None:
        iface = self._get_interface()
        block = PLACED_RESISTOR_BLOCK
        result = iface._set_justify_on_property(block, "Reference", "right top")
        assert "(justify right top)" in result

    def test_center_removes_directive(self) -> None:
        """Passing 'center' should remove any (justify ...) token (KiCad default)."""
        iface = self._get_interface()
        block = PLACED_RESISTOR_BLOCK
        # First set a non-center justify so there is something to remove
        block = iface._set_justify_on_property(block, "Reference", "left")
        assert "(justify left)" in block
        # Now reset to center
        block = iface._set_justify_on_property(block, "Reference", "center")
        assert "(justify" not in block

    def test_replaces_existing_justify(self) -> None:
        iface = self._get_interface()
        block = PLACED_RESISTOR_BLOCK
        block = iface._set_justify_on_property(block, "Reference", "left")
        block = iface._set_justify_on_property(block, "Reference", "right")
        # Should have exactly one justify token and it should be 'right'
        matches = re.findall(r"\(justify\s+[^)]+\)", block)
        assert len(matches) == 1
        assert "right" in matches[0]

    def test_does_not_affect_other_fields(self) -> None:
        iface = self._get_interface()
        block = PLACED_RESISTOR_BLOCK
        result = iface._set_justify_on_property(block, "Reference", "left")
        # Value field must not have acquired a justify token
        value_section = result[result.find('(property "Value"') :]
        ref_section = result[result.find('(property "Reference"') :]
        # The justify token should appear before the Value property section
        justify_pos = result.find("(justify left)")
        value_prop_pos = result.find('(property "Value"')
        assert justify_pos < value_prop_pos

    def test_unknown_field_returns_block_unchanged(self) -> None:
        iface = self._get_interface()
        block = PLACED_RESISTOR_BLOCK
        result = iface._set_justify_on_property(block, "NoSuchField", "left")
        assert result == block


# ---------------------------------------------------------------------------
# Integration tests — real file I/O through edit_schematic_component
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFieldPositionsJustify:
    """Integration tests for justify via fieldPositions in edit_schematic_component."""

    @pytest.fixture
    def sch_with_r2(self, tmp_path: Any) -> Any:
        return _make_test_schematic(tmp_path, PLACED_RESISTOR_BLOCK)

    def _get_interface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_set_justify_left_on_reference(self, sch_with_r2: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "fieldPositions": {"Reference": {"x": 51.27, "y": 47.46, "justify": "left"}},
            },
        )
        assert result["success"] is True
        content = sch_with_r2.read_text(encoding="utf-8")
        assert "(justify left)" in content

    def test_set_justify_right_on_value(self, sch_with_r2: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "fieldPositions": {"Value": {"x": 51.27, "y": 52.54, "justify": "right"}},
            },
        )
        assert result["success"] is True
        content = sch_with_r2.read_text(encoding="utf-8")
        assert "(justify right)" in content

    def test_set_justify_center_removes_directive(self, sch_with_r2: Any) -> None:
        iface = self._get_interface()
        # First add a left justify so there is something to remove
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "fieldPositions": {"Reference": {"x": 51.27, "y": 47.46, "justify": "left"}},
            },
        )
        # Now reset to center (default)
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "fieldPositions": {"Reference": {"x": 51.27, "y": 47.46, "justify": "center"}},
            },
        )
        assert result["success"] is True
        content = sch_with_r2.read_text(encoding="utf-8")
        # Check that the Reference property block itself has no (justify ...) token.
        # (The lib_symbols section may legitimately contain justify directives.)
        ref_prop_start = content.find('(property "Reference" "R2"')
        assert ref_prop_start >= 0, "Reference property block not found"
        ref_prop_end = content.find("\n    )", ref_prop_start) + len("\n    )")
        ref_prop_block = content[ref_prop_start:ref_prop_end]
        assert "(justify" not in ref_prop_block

    def test_fieldpositions_without_justify_unchanged(self, sch_with_r2: Any) -> None:
        """Omitting justify must not alter any existing justify on the field."""
        iface = self._get_interface()
        # Set a justify first
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "fieldPositions": {"Reference": {"x": 51.27, "y": 47.46, "justify": "left"}},
            },
        )
        # Reposition without passing justify — the left directive must survive
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "fieldPositions": {"Reference": {"x": 60.0, "y": 47.46}},
            },
        )
        content = sch_with_r2.read_text(encoding="utf-8")
        assert "(justify left)" in content

    def test_position_and_justify_applied_together(self, sch_with_r2: Any) -> None:
        """Both position and justify should be applied in a single call."""
        iface = self._get_interface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "fieldPositions": {"Reference": {"x": 99.0, "y": 88.0, "justify": "right"}},
            },
        )
        assert result["success"] is True
        content = sch_with_r2.read_text(encoding="utf-8")
        assert "(justify right)" in content
        assert "99.0 88.0" in content


# ---------------------------------------------------------------------------
# Integration tests — justify via set_schematic_component_property
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSetPropertyJustify:
    """Integration tests for justify via set_schematic_component_property."""

    @pytest.fixture
    def sch_with_r2(self, tmp_path: Any) -> Any:
        return _make_test_schematic(tmp_path, PLACED_RESISTOR_BLOCK)

    def _get_interface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_set_property_with_justify(self, sch_with_r2: Any) -> None:
        iface = self._get_interface()
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "name": "Tolerance",
                "value": "1%",
                "justify": "left",
            },
        )
        assert result["success"] is True
        content = sch_with_r2.read_text(encoding="utf-8")
        assert "(justify left)" in content

    def test_set_property_without_justify_no_regression(self, sch_with_r2: Any) -> None:
        """Omitting justify on set_property must not add any justify token."""
        iface = self._get_interface()
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r2),
                "reference": "R2",
                "name": "Rating",
                "value": "100mW",
            },
        )
        assert result["success"] is True
        content = sch_with_r2.read_text(encoding="utf-8")
        # No justify should appear in the newly added Rating property
        rating_start = content.find('(property "Rating"')
        rating_end = content.find(")", rating_start)
        assert "(justify" not in content[rating_start:rating_end]
