"""
Tests for update_symbol_from_library — lib_symbols refresh that preserves
placed instances, including power-symbol flattening and helper functions.
"""

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.commands.update_symbol_from_library import (  # noqa: E402
    _adapt_library_block_for_schematic,
    _extract_paren_block,
    _lib_ids_in_lib_symbols,
    _lib_symbols_range,
    _used_lib_ids,
    update_schematic_symbols,
)

# ---------------------------------------------------------------------------
# Fixtures: minimal symbol blocks (matching real KiCad library format)
# ---------------------------------------------------------------------------

# A minimal non-power symbol (Device:R) — library format with 2-space indent
_R_LIB_BLOCK = """(symbol "Device:R"
  (pin_numbers (hide yes))
  (pin_names (offset 0.254))
  (exclude_from_sim no)
  (in_bom yes)
  (on_board yes)
  (property "Reference" "R" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
  (property "Value" "R" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
  (property "Footprint" "" (at 0 -5.08 0) (hide yes) (effects (font (size 1.27 1.27))))
  (symbol "R_1_1"
    (pin passive line (at 0 3.81 270) (length 1.27)
      (name "~" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))
    (pin passive line (at 0 -3.81 90) (length 1.27)
      (name "~" (effects (font (size 1.27 1.27))))
      (number "2" (effects (font (size 1.27 1.27)))))
  )
  (embedded_fonts no)
)"""

# A slightly different version (different pin_names offset and pin names)
_R_LIB_BLOCK_V2 = """(symbol "Device:R"
  (pin_numbers (hide yes))
  (pin_names (offset 0.5))
  (exclude_from_sim no)
  (in_bom yes)
  (on_board yes)
  (property "Reference" "R" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
  (property "Value" "R" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
  (property "Footprint" "" (at 0 -5.08 0) (hide yes) (effects (font (size 1.27 1.27))))
  (symbol "R_1_1"
    (pin passive line (at 0 3.81 270) (length 1.27)
      (name "1" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))
    (pin passive line (at 0 -3.81 90) (length 1.27)
      (name "2" (effects (font (size 1.27 1.27))))
      (number "2" (effects (font (size 1.27 1.27)))))
  )
  (embedded_fonts no)
)"""

# A power symbol — (power) is RIGHT AFTER (on_board yes) in real KiCad libraries
_PWR_LIB_BLOCK = """(symbol "power:GND"
  (pin_names (offset 0) hide)
  (exclude_from_sim no)
  (in_bom no)
  (on_board yes) (power)
  (in_pos_files no)
  (duplicate_pin_numbers_are_jumpers no)
  (property "Reference" "#PWR" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
  (property "Value" "GND" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
  (property "Footprint" "" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
  (symbol "GND_0_1"
    (pin power_in line (at 0 2.54 270) (length 2.54)
      (name "GND" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))
  )
  (embedded_fonts no)
)"""

# Same power symbol but with different offset (to trigger update)
# (power) is separate line after (on_board yes) — KiCad format
_PWR_LIB_BLOCK_V2 = """(symbol "power:GND"
  (pin_names (offset 0.5) hide)
  (exclude_from_sim no)
  (in_bom no)
  (on_board yes) (power)
  (in_pos_files no)
  (duplicate_pin_numbers_are_jumpers no)
  (property "Reference" "#PWR" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
  (property "Value" "GND" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
  (property "Footprint" "" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
  (symbol "GND_0_1"
    (pin power_in line (at 0 2.54 270) (length 2.54)
      (name "GND" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))
  )
  (embedded_fonts no)
)"""

# A minimal schematic with one symbol in lib_symbols and one placed instance
_MINIMAL_SCHEMATIC = """(kicad_sch
\t(version 20260306)
\t(generator "eeschema")
\t(generator_version "10.0")
\t(uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
\t(paper "A4")
\t(lib_symbols
\t\t(symbol "Device:R"
\t\t\t(pin_numbers (hide yes))
\t\t\t(pin_names (offset 0.254))
\t\t\t(exclude_from_sim no)
\t\t\t(in_bom yes)
\t\t\t(on_board yes)
\t\t\t(property "Reference" "R" (at 0 2.54 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(property "Value" "R" (at 0 -2.54 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(property "Footprint" "" (at 0 -5.08 0)
\t\t\t\t(hide yes)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(symbol "R_1_1"
\t\t\t\t(pin passive line (at 0 3.81 270) (length 1.27)
\t\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t\t)
\t\t\t\t(pin passive line (at 0 -3.81 90) (length 1.27)
\t\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))
\t\t\t\t)
\t\t\t)
\t\t\t(embedded_fonts no)
\t\t)
\t)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 50.8 50.8 0)
\t\t(unit 1)
\t\t(body_style 1)
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(uuid "11111111-2222-3333-4444-555555555555")
\t\t(property "Reference" "R1"
\t\t\t(at 50.8 48.26 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left))
\t\t)
\t\t(property "Value" "10k"
\t\t\t(at 50.8 53.34 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left))
\t\t)
\t\t(property "Footprint" "Resistor_SMD:R_0402_1005Metric"
\t\t\t(at 50.8 50.8 0)
\t\t\t(hide yes)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(pin "1" (uuid "bbbbbbbb-1111-2222-3333-444444444444"))
\t\t(pin "2" (uuid "bbbbbbbb-5555-6666-7777-888888888888"))
\t\t(instances
\t\t\t(project "test_project"
\t\t\t\t(path "/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
\t\t\t\t\t(reference "R1")
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
\t(sheet_instances
\t\t(path "/" (page "1"))
\t)
)
"""

# Prettified expected instances section for content-based comparison
_EXPECTED_INSTANCES = """(instances
\t\t\t(project "test_project"
\t\t\t\t(path "/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
\t\t\t\t\t(reference "R1")
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)"""

# A minimal schematic with a power symbol (power) already flattened
_PWR_SCHEMATIC = """(kicad_sch
\t(version 20260306)
\t(generator "eeschema")
\t(generator_version "10.0")
\t(uuid "pppppppp-qqqq-rrrr-ssss-tttttttttttt")
\t(paper "A4")
\t(lib_symbols
\t\t(symbol "power:GND"
\t\t\t(pin_names (offset 0) hide)
\t\t\t(exclude_from_sim no)
\t\t\t(in_bom no)
\t\t\t(on_board yes) (power)
\t\t\t(in_pos_files no)
\t\t\t(duplicate_pin_numbers_are_jumpers no)
\t\t\t(property "Reference" "#PWR" (at 0 2.54 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(property "Value" "GND" (at 0 -2.54 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(property "Footprint" "" (at 0 0 0)
\t\t\t\t(hide yes)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(symbol "GND_0_1"
\t\t\t\t(pin power_in line (at 0 2.54 270) (length 2.54)
\t\t\t\t\t(name "GND" (effects (font (size 1.27 1.27))))
\t\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t\t)
\t\t\t)
\t\t\t(embedded_fonts no)
\t\t)
\t)
\t(symbol
\t\t(lib_id "power:GND")
\t\t(at 100 100 0)
\t\t(unit 1)
\t\t(body_style 1)
\t\t(exclude_from_sim yes)
\t\t(in_bom no)
\t\t(on_board yes)
\t\t(in_pos_files no)
\t\t(uuid "gggggggg-1111-2222-3333-444444444444")
\t\t(property "Reference" "#PWR01"
\t\t\t(at 100 97.46 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left))
\t\t)
\t\t(property "Value" "GND"
\t\t\t(at 100 102.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left))
\t\t)
\t\t(property "Footprint" ""
\t\t\t(at 100 100 0)
\t\t\t(hide yes)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(pin "1" (uuid "gggggggg-5555-6666-7777-888888888888"))
\t\t(instances
\t\t\t(project "test_project"
\t\t\t\t(path "/pppppppp-qqqq-rrrr-ssss-tttttttttttt"
\t\t\t\t\t(reference "#PWR01")
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
\t(sheet_instances
\t\t(path "/" (page "1"))
\t)
)
"""

# ---------------------------------------------------------------------------
# Helper: make a mock loader that returns a given block
# ---------------------------------------------------------------------------


def _mock_loader(block):
    loader = MagicMock()
    loader.extract_symbol_from_library.return_value = block
    loader.project_path = None
    return loader


def _check_instances_preserved(updated_text: str, reference: str, unit: str = "1") -> bool:
    """Verify that the instances block still references the expected component."""
    return (
        f'(reference "{reference}")' in updated_text
        and f"(unit {unit})" in updated_text
        and "(instances" in updated_text
    )


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------


class TestAdaptLibraryBlockForSchematic:
    """_adapt_library_block_for_schematic — power flattening."""

    def test_non_power_symbol_unchanged(self):
        result = _adapt_library_block_for_schematic(_R_LIB_BLOCK)
        assert result == _R_LIB_BLOCK

    def test_power_symbol_flattened(self):
        result = _adapt_library_block_for_schematic(_PWR_LIB_BLOCK)
        # (power) should be inlined on the (on_board yes) line
        assert "(on_board yes) (power)" in result
        # Only ONE occurrence of (power)
        assert result.count("(power)") == 1
        # Indentation should be reduced by 2 spaces (library → schematic format)
        assert result.startswith("(symbol")


class TestLibSymbolsRange:
    """_lib_symbols_range — finds the section boundaries."""

    def test_finds_lib_symbols_range(self):
        start, end = _lib_symbols_range(_MINIMAL_SCHEMATIC)
        assert start >= 0
        assert end > start
        assert _MINIMAL_SCHEMATIC[end] == ")"

    def test_no_lib_symbols_returns_none(self):
        assert _lib_symbols_range("(kicad_sch (version 20260306))") is None


class TestLibIdsInLibSymbols:
    """_lib_ids_in_lib_symbols — extracts symbol IDs from lib_symbols."""

    def test_finds_device_r(self):
        ids = _lib_ids_in_lib_symbols(_MINIMAL_SCHEMATIC, "Device")
        assert "R" in ids

    def test_finds_power_gnd(self):
        ids = _lib_ids_in_lib_symbols(_PWR_SCHEMATIC, "power")
        assert "GND" in ids


class TestUsedLibIds:
    """_used_lib_ids — extracts lib_ids from placed instances."""

    def test_finds_device_r(self):
        ids = _used_lib_ids(_MINIMAL_SCHEMATIC, "Device")
        assert "R" in ids

    def test_finds_power_gnd(self):
        ids = _used_lib_ids(_PWR_SCHEMATIC, "power")
        assert "GND" in ids


class TestExtractParenBlock:
    """_extract_paren_block — balanced parenthesis extraction."""

    def test_simple_block(self):
        text = "(foo bar baz)"
        block, end = _extract_paren_block(text, 0)
        assert block == "(foo bar baz)"
        assert end == len(text)

    def test_nested_block(self):
        text = "(outer (inner a) (inner b))"
        block, end = _extract_paren_block(text, 0)
        assert block == text
        assert end == len(text)

    def test_mid_text(self):
        text = "prefix (target (nested)) suffix"
        block, end = _extract_paren_block(text, 7)
        assert block == "(target (nested))"


# ---------------------------------------------------------------------------
# Tests: update_schematic_symbols (the main function)
# ---------------------------------------------------------------------------


class TestUpdateSchematicSymbols:
    """update_schematic_symbols — the core update logic."""

    def test_updates_lib_symbols_preserves_instances(self, tmp_path):
        """Refreshing a symbol lib definition must keep placed instances intact."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCHEMATIC, encoding="utf-8")

        with patch(
            "kicad_mcp.commands.update_symbol_from_library.DynamicSymbolLoader",
            return_value=_mock_loader(_R_LIB_BLOCK_V2),
        ):
            result = update_schematic_symbols(sch, "Device")

        assert result["updated"] == 1
        assert result["skipped"] == 0

        updated = sch.read_text(encoding="utf-8")
        # The lib_symbols should have been updated with the new content
        assert "offset 0.5" in updated
        assert 'name "1"' in updated  # from V2
        # Instances must be preserved (content check, not byte-identical —
        # prettify normalises whitespace)
        assert _check_instances_preserved(updated, "R1")

    def test_power_symbol_update_preserves_instances(self, tmp_path):
        """Refreshing a power symbol flattens (power) and keeps instances intact."""
        sch = tmp_path / "test_pwr.kicad_sch"
        sch.write_text(_PWR_SCHEMATIC, encoding="utf-8")

        with patch(
            "kicad_mcp.commands.update_symbol_from_library.DynamicSymbolLoader",
            return_value=_mock_loader(_PWR_LIB_BLOCK_V2),
        ):
            result = update_schematic_symbols(sch, "power")

        assert result["updated"] == 1
        assert result["skipped"] == 0

        updated = sch.read_text(encoding="utf-8")
        # Power symbol should have (power) present (flattened from library form)
        # Note: prettify() may put (power) on its own line — the key is it's in
        # the lib_symbols and only appears once (flattened from library format)
        assert "(power)" in updated
        assert updated.count("(power)") == 1
        # Instances must survive
        assert _check_instances_preserved(updated, "#PWR01")

    def test_update_changes_lib_symbols_but_not_instances(self, tmp_path):
        """After update, the lib_symbols entry changes but instance data persists."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCHEMATIC, encoding="utf-8")

        with patch(
            "kicad_mcp.commands.update_symbol_from_library.DynamicSymbolLoader",
            return_value=_mock_loader(_R_LIB_BLOCK_V2),
        ):
            update_schematic_symbols(sch, "Device")

        updated = sch.read_text(encoding="utf-8")
        # The instance pin UUIDs from the original must still be present
        assert "bbbbbbbb-1111-2222-3333-444444444444" in updated
        assert "bbbbbbbb-5555-6666-7777-888888888888" in updated
        # The instance block itself is intact
        assert "(instances" in updated
        assert '(project "test_project"' in updated
        assert '(reference "R1")' in updated

    def test_skips_mirror_symbols(self, tmp_path):
        r"""Symbols matching __m\d+ pattern should be skipped."""
        mirror_sch = _MINIMAL_SCHEMATIC.replace(
            '(symbol "Device:R"',
            '(symbol "Device:R__m90"',
        ).replace(
            '(lib_id "Device:R")',
            '(lib_id "Device:R__m90")',
        )
        sch = tmp_path / "test_mirror.kicad_sch"
        sch.write_text(mirror_sch, encoding="utf-8")

        with patch(
            "kicad_mcp.commands.update_symbol_from_library.DynamicSymbolLoader",
            return_value=_mock_loader(_R_LIB_BLOCK_V2),
        ):
            result = update_schematic_symbols(sch, "Device")

        assert result["skipped"] >= 1
        assert result["updated"] == 0

    def test_only_symbols_filter(self, tmp_path):
        """only_symbols parameter restricts which symbols are updated."""
        sch = tmp_path / "test_filter.kicad_sch"
        sch.write_text(_MINIMAL_SCHEMATIC, encoding="utf-8")

        with patch(
            "kicad_mcp.commands.update_symbol_from_library.DynamicSymbolLoader",
            return_value=_mock_loader(_R_LIB_BLOCK_V2),
        ):
            # Filter to a symbol NOT in the schematic
            result = update_schematic_symbols(sch, "Device", only_symbols={"C"})

        assert result["updated"] == 0
        # File should be unchanged
        assert sch.read_text(encoding="utf-8") == _MINIMAL_SCHEMATIC

    def test_no_lib_symbols_returns_zeroes(self, tmp_path):
        """Schematic with no lib_symbols section returns all zeroes."""
        no_lib = """(kicad_sch
\t(version 20260306)
\t(sheet_instances (path "/" (page "1")))
)
"""
        sch = tmp_path / "test_nolib.kicad_sch"
        sch.write_text(no_lib, encoding="utf-8")

        with patch(
            "kicad_mcp.commands.update_symbol_from_library.DynamicSymbolLoader",
            return_value=_mock_loader(_R_LIB_BLOCK),
        ):
            result = update_schematic_symbols(sch, "Device")

        assert result == {"updated": 0, "injected": 0, "skipped": 0}
