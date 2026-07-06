"""
Tests for add_library_symbol_property — add custom properties to lib_symbols entries.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.add_library_symbol_property import (  # noqa: E402
    add_library_symbol_property,
    _find_symbol_in_lib_symbols,
    _has_property,
)

_MINIMAL_SCH = """(kicad_sch
\t(version 20260306)
\t(generator "eeschema")
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
\t\t(uuid "11111111-2222-3333-4444-555555555555")
\t\t(property "Reference" "R1" (at 50.8 48.26 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left))
\t\t)
\t\t(property "Value" "10k" (at 50.8 53.34 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left))
\t\t)
\t\t(pin "1" (uuid "bbbbbbbb-1111-2222-3333-444444444444"))
\t\t(pin "2" (uuid "bbbbbbbb-5555-6666-7777-888888888888"))
\t\t(instances
\t\t\t(project "test" (path "/aaa" (reference "R1") (unit 1)))
\t\t)
\t)
\t(sheet_instances (path "/" (page "1")))
)
"""


class TestFindSymbolInLibSymbols:
    def test_finds_existing_symbol(self):
        start, end, block = _find_symbol_in_lib_symbols(_MINIMAL_SCH, "Device", "R")
        assert start >= 0
        assert end > start
        assert '(symbol "Device:R"' in block

    def test_returns_none_for_missing_symbol(self):
        assert _find_symbol_in_lib_symbols(_MINIMAL_SCH, "Device", "C") is None

    def test_returns_none_for_wrong_library(self):
        assert _find_symbol_in_lib_symbols(_MINIMAL_SCH, "power", "GND") is None


class TestHasProperty:
    def test_detects_existing_property(self):
        _, _, block = _find_symbol_in_lib_symbols(_MINIMAL_SCH, "Device", "R")
        assert _has_property(block, "Reference") is True
        assert _has_property(block, "Footprint") is True

    def test_detects_missing_property(self):
        _, _, block = _find_symbol_in_lib_symbols(_MINIMAL_SCH, "Device", "R")
        assert _has_property(block, "Manufacturer") is False


class TestAddLibrarySymbolProperty:
    def test_adds_new_property(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property({
            "schematicPath": str(sch),
            "libraryName": "Device",
            "symbolName": "R",
            "propertyName": "Manufacturer",
            "propertyValue": "YAGEO",
        })

        assert result["success"] is True
        assert "Manufacturer" in result["message"]

        updated = sch.read_text(encoding="utf-8")
        assert 'property "Manufacturer" "YAGEO"' in updated
        assert '(reference "R1")' in updated

    def test_adds_property_at_position(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property({
            "schematicPath": str(sch),
            "libraryName": "Device",
            "symbolName": "R",
            "propertyName": "MPN",
            "propertyValue": "CRCW040210K0",
            "position": {"x": 0, "y": -7.62},
        })

        assert result["success"] is True
        updated = sch.read_text(encoding="utf-8")
        assert '(at 0 -7.62 0)' in updated

    def test_updates_existing_property(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property({
            "schematicPath": str(sch),
            "libraryName": "Device",
            "symbolName": "R",
            "propertyName": "Reference",
            "propertyValue": "RR",
        })

        assert result["success"] is True
        updated = sch.read_text(encoding="utf-8")
        assert 'property "Reference" "RR"' in updated

    def test_adds_hidden_property(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property({
            "schematicPath": str(sch),
            "libraryName": "Device",
            "symbolName": "R",
            "propertyName": "ki_description",
            "propertyValue": "Test resistor",
            "hide": True,
        })

        assert result["success"] is True
        updated = sch.read_text(encoding="utf-8")
        assert 'property "ki_description" "Test resistor"' in updated
        assert "(hide yes)" in updated

    def test_fails_for_missing_symbol(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property({
            "schematicPath": str(sch),
            "libraryName": "Device",
            "symbolName": "C",
            "propertyName": "Foo",
            "propertyValue": "Bar",
        })

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_fails_for_missing_lib_symbols(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch (version 20260306))", encoding="utf-8")

        result = add_library_symbol_property({
            "schematicPath": str(sch),
            "libraryName": "Device",
            "symbolName": "R",
            "propertyName": "Foo",
            "propertyValue": "Bar",
        })

        assert result["success"] is False

    def test_preserves_instances_after_add(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        add_library_symbol_property({
            "schematicPath": str(sch),
            "libraryName": "Device",
            "symbolName": "R",
            "propertyName": "Manufacturer",
            "propertyValue": "YAGEO",
        })

        updated = sch.read_text(encoding="utf-8")
        assert "bbbbbbbb-1111-2222-3333-444444444444" in updated
        assert "bbbbbbbb-5555-6666-7777-888888888888" in updated
        assert '(reference "R1")' in updated
        assert "(instances" in updated
