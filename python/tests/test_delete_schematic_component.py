"""
Regression tests for delete_schematic_component.

Key regression: the handler previously used a line-by-line regex that required
`(symbol` and `(lib_id` to appear on the *same* line.  KiCAD's file writer puts
them on *separate* lines, so every real-world delete returned "not found".
"""

import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

TEMPLATE_SCH = Path(__file__).parent.parent / "templates" / "empty.kicad_sch"

# Inline format (single line) – matches what tests previously used
PLACED_RESISTOR_INLINE = """\
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

# Multi-line format – as KiCAD's own file writer produces it.
# (symbol and (lib_id are on separate lines, which broke the old regex.
PLACED_RESISTOR_MULTILINE = """\
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 50 50 0)
\t\t(unit 1)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(uuid "bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
\t\t(property "Reference" "R2"
\t\t\t(at 51.27 47.46 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "4.7k"
\t\t\t(at 51.27 52.54 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
"""

# Multi-line power symbol – the exact scenario that was reported as broken.
PLACED_POWER_SYMBOL_MULTILINE = """\
\t(symbol
\t\t(lib_id "power:VCC")
\t\t(at 365.6 38.1 0)
\t\t(unit 1)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(uuid "cccccccc-dddd-eeee-ffff-000000000030")
\t\t(property "Reference" "#PWR030"
\t\t\t(at 365.6 41.91 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(hide yes)
\t\t\t)
\t\t)
\t\t(property "Value" "VCC"
\t\t\t(at 365.6 35.56 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
"""


def _make_test_schematic(tmp_path: Path, extra_block: str = "") -> Path:
    dest = tmp_path / "test.kicad_sch"
    src_content = TEMPLATE_SCH.read_text(encoding="utf-8")
    if extra_block:
        src_content = src_content.rstrip()
        if src_content.endswith(")"):
            src_content = src_content[:-1] + "\n" + extra_block + ")\n"
    dest.write_text(src_content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Unit tests – regression proof for the old regex vs the new approach
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteDetectionRegex:
    """Verify that the new content-string pattern finds blocks in both formats."""

    OLD_PATTERN = re.compile(r"^\s*\(symbol\s+\(lib_id\s+\"", re.MULTILINE)
    NEW_PATTERN = re.compile(r'\(symbol\s+\(lib_id\s+"')

    def test_old_regex_fails_on_multiline_format(self) -> None:
        """Regression: old line-by-line regex must NOT match the multi-line format."""
        # The old code used re.match on individual lines; simulate that here.
        lines = PLACED_RESISTOR_MULTILINE.split("\n")
        matches = [l for l in lines if re.match(r"\s*\(symbol\s+\(lib_id\s+\"", l)]
        assert matches == [], "Old regex should not match multi-line KiCAD format"

    def test_old_regex_matches_inline_format(self) -> None:
        """Old regex did work on single-line (inline) format."""
        lines = PLACED_RESISTOR_INLINE.split("\n")
        matches = [l for l in lines if re.match(r"\s*\(symbol\s+\(lib_id\s+\"", l)]
        assert len(matches) == 1

    def test_new_pattern_matches_multiline_format(self) -> None:
        """New content-string pattern must find blocks in multi-line format."""
        assert self.NEW_PATTERN.search(PLACED_RESISTOR_MULTILINE) is not None

    def test_new_pattern_matches_inline_format(self) -> None:
        """New content-string pattern also works on inline format."""
        assert self.NEW_PATTERN.search(PLACED_RESISTOR_INLINE) is not None

    def test_new_pattern_matches_power_symbol_multiline(self) -> None:
        """New pattern must find #PWR030 power symbol in multi-line format."""
        assert self.NEW_PATTERN.search(PLACED_POWER_SYMBOL_MULTILINE) is not None

    def test_reference_extraction_from_multiline_block(self) -> None:
        """Reference property can be found inside a multi-line block."""
        ref_pattern = re.compile(r'\(property\s+"Reference"\s+"#PWR030"')
        assert ref_pattern.search(PLACED_POWER_SYMBOL_MULTILINE) is not None


# ---------------------------------------------------------------------------
# Integration tests – real file I/O using the handler
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteSchematicComponentIntegration:
    def _get_handler(self) -> Any:
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_delete_schematic_component

    def test_delete_inline_format_succeeds(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_INLINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "R1"})
        assert result["success"] is True
        assert result["deleted_count"] == 1

    def test_delete_multiline_format_succeeds(self, tmp_path: Any) -> None:
        """Regression: must succeed when KiCAD writes (symbol and (lib_id on separate lines."""
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_MULTILINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "R2"})
        assert result["success"] is True
        assert result["deleted_count"] == 1

    def test_delete_power_symbol_multiline_succeeds(self, tmp_path: Any) -> None:
        """Regression: #PWR030 multi-line power symbol must be deletable."""
        sch = _make_test_schematic(tmp_path, PLACED_POWER_SYMBOL_MULTILINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "#PWR030"})
        assert result["success"] is True
        assert result["deleted_count"] == 1

    def test_component_absent_after_delete(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_POWER_SYMBOL_MULTILINE)
        self._get_handler()({"schematicPath": str(sch), "reference": "#PWR030"})
        remaining = sch.read_text(encoding="utf-8")
        assert '"#PWR030"' not in remaining

    def test_unknown_reference_returns_failure(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_INLINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "U99"})
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_missing_schematic_path_returns_failure(self, tmp_path: Any) -> None:
        result = self._get_handler()({"reference": "R1"})
        assert result["success"] is False

    def test_missing_reference_returns_failure(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path)
        result = self._get_handler()({"schematicPath": str(sch)})
        assert result["success"] is False
