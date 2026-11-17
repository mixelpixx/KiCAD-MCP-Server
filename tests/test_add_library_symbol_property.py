"""
Tests for add_library_symbol_property — add custom properties to lib_symbols entries.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.add_library_symbol_property import (  # noqa: E402
    _find_symbol_in_lib_symbols,
    _has_property,
    add_library_symbol_property,
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

        result = add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "R",
                "propertyName": "Manufacturer",
                "propertyValue": "YAGEO",
            }
        )

        assert result["success"] is True
        assert "Manufacturer" in result["message"]

        updated = sch.read_text(encoding="utf-8")
        assert 'property "Manufacturer" "YAGEO"' in updated
        assert '(reference "R1")' in updated

    def test_adds_property_at_position(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "R",
                "propertyName": "MPN",
                "propertyValue": "CRCW040210K0",
                "position": {"x": 0, "y": -7.62},
            }
        )

        assert result["success"] is True
        updated = sch.read_text(encoding="utf-8")
        assert "(at 0 -7.62 0)" in updated

    def test_updates_existing_property(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "R",
                "propertyName": "Reference",
                "propertyValue": "RR",
            }
        )

        assert result["success"] is True
        updated = sch.read_text(encoding="utf-8")
        assert 'property "Reference" "RR"' in updated

    def test_adds_hidden_property(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "R",
                "propertyName": "ki_description",
                "propertyValue": "Test resistor",
                "hide": True,
            }
        )

        assert result["success"] is True
        updated = sch.read_text(encoding="utf-8")
        assert 'property "ki_description" "Test resistor"' in updated
        assert "(hide yes)" in updated

    def test_fails_for_missing_symbol(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "C",
                "propertyName": "Foo",
                "propertyValue": "Bar",
            }
        )

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_fails_for_missing_lib_symbols(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch (version 20260306))", encoding="utf-8")

        result = add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "R",
                "propertyName": "Foo",
                "propertyValue": "Bar",
            }
        )

        assert result["success"] is False

    def test_preserves_instances_after_add(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "R",
                "propertyName": "Manufacturer",
                "propertyValue": "YAGEO",
            }
        )

        updated = sch.read_text(encoding="utf-8")
        assert "bbbbbbbb-1111-2222-3333-444444444444" in updated
        assert "bbbbbbbb-5555-6666-7777-888888888888" in updated
        assert '(reference "R1")' in updated
        assert "(instances" in updated


# --- regression (#379): updates replace the whole property block ------------ #


def _lib_symbol(content: str, full_name: str) -> list:
    """The parsed ``(symbol "LIB:NAME" ...)`` entry under ``(lib_symbols ...)``."""
    tree = sexpdata.loads(content)
    lib_symbols = next(
        child
        for child in tree
        if isinstance(child, list) and child and child[0] == sexpdata.Symbol("lib_symbols")
    )
    return next(
        child
        for child in lib_symbols
        if isinstance(child, list) and len(child) > 1 and child[1] == full_name
    )


def _heads(node: list) -> list[str]:
    """Head names of every direct child list of *node*."""
    return [str(child[0]) for child in node if isinstance(child, list) and child]


def _property(node: list, name: str) -> list:
    matches = [
        child
        for child in node
        if isinstance(child, list)
        and child
        and child[0] == sexpdata.Symbol("property")
        and child[1] == name
    ]
    assert len(matches) == 1, f"expected one {name!r} property, found {len(matches)}"
    return matches[0]


def _set(sch: Path, name: str, value: str, **extra) -> dict:
    params = {
        "schematicPath": str(sch),
        "libraryName": "Device",
        "symbolName": "R",
        "propertyName": name,
        "propertyValue": value,
    }
    params.update(extra)
    return add_library_symbol_property(params)


class TestUpdateReplacesWholeProperty:
    """The old update regex stopped at the first ``)`` -- the ``(at x y angle)``."""

    def test_update_leaves_no_orphaned_effects(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = _set(sch, "Reference", "RR")

        assert result["success"] is True
        updated = sch.read_text(encoding="utf-8")
        symbol = _lib_symbol(updated, "Device:R")
        # An orphaned tail shows up as an (effects ...) directly under the symbol.
        assert "effects" not in _heads(symbol)
        assert "hide" not in _heads(symbol)
        ref = _property(symbol, "Reference")
        assert ref[2] == "RR"
        assert "effects" in _heads(ref)
        # The unit and the rest of the file stay where they were.
        assert '(symbol "R_1_1"' in updated
        assert _heads(sexpdata.loads(updated)).count("symbol") == 1
        assert '(reference "R1")' in updated

    def test_update_keeps_position_and_hidden_state(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        assert _set(sch, "Reference", "RR")["success"] is True
        assert _set(sch, "Footprint", "Resistor_SMD:R_0402_1005Metric")["success"] is True

        symbol = _lib_symbol(sch.read_text(encoding="utf-8"), "Device:R")
        ref = _property(symbol, "Reference")
        assert [str(a) for a in next(c for c in ref if isinstance(c, list))] == [
            "at",
            "0",
            "2.54",
            "0",
        ]
        footprint = _property(symbol, "Footprint")
        assert footprint[2] == "Resistor_SMD:R_0402_1005Metric"
        assert "hide" in _heads(footprint)

    def test_update_keeps_effects_hide_and_justify(self, tmp_path):
        """KiCad 8/9 write (hide yes) inside (effects ...); it must survive an edit."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(
            _MINIMAL_SCH.replace(
                '(property "Value" "R" (at 0 -2.54 0)\n'
                "\t\t\t\t(effects (font (size 1.27 1.27)))",
                '(property "Value" "R" (at 0 -2.54 90)\n'
                "\t\t\t\t(effects (font (size 1.5 1.5)) (justify left) (hide yes))",
            ),
            encoding="utf-8",
        )

        assert _set(sch, "Value", "10k")["success"] is True

        updated = sch.read_text(encoding="utf-8")
        value = _property(_lib_symbol(updated, "Device:R"), "Value")
        assert value[2] == "10k"
        assert "hide" in _heads(value)
        assert "(at 0 -2.54 90)" in updated
        assert "(size 1.5 1.5)" in updated
        assert "(justify left)" in updated

    def test_update_value_with_parens(self, tmp_path):
        """Parens inside a quoted value are text, not structure."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        assert _set(sch, "Value", "Ceramic (X7R")["success"] is True
        assert _set(sch, "Value", "Ceramic (X7R) 50V")["success"] is True

        symbol = _lib_symbol(sch.read_text(encoding="utf-8"), "Device:R")
        assert _property(symbol, "Value")[2] == "Ceramic (X7R) 50V"
        assert "effects" not in _heads(symbol)


# --- regression (#379): new properties land on the symbol, before its units -- #

_COMPACT_SCH = (
    '(kicad_sch (version 20260306) (generator "eeschema")\n'
    '\t(lib_symbols (symbol "Device:R" (property "Reference" "R" (at 0 0 0)'
    " (effects (font (size 1.27 1.27))))"
    ' (symbol "R_0_1" (rectangle (start -1 1) (end 1 -1)))))\n'
    ")\n"
)


def test_new_property_precedes_units_in_compact_symbol(tmp_path):
    """The old anchor needed a unit at exactly three tabs; otherwise it appended
    the property after the units."""
    sch = tmp_path / "compact.kicad_sch"
    sch.write_text(_COMPACT_SCH, encoding="utf-8")

    assert _set(sch, "MPN", "RC0402")["success"] is True

    symbol = _lib_symbol(sch.read_text(encoding="utf-8"), "Device:R")
    heads = _heads(symbol)
    assert heads == ["property", "property", "symbol"]
    assert _property(symbol, "MPN")[2] == "RC0402"


def test_update_ignores_same_named_property_in_unit(tmp_path):
    """Only the symbol's own property is rewritten, not a unit's."""
    sch = tmp_path / "unit.kicad_sch"
    sch.write_text(
        _COMPACT_SCH.replace(
            '(property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))',
            "",
        ).replace(
            '(symbol "R_0_1" ',
            '(symbol "R_0_1" (property "MPN" "unit" (at 0 0 0)) ',
        ),
        encoding="utf-8",
    )

    assert _set(sch, "MPN", "RC0402")["success"] is True

    symbol = _lib_symbol(sch.read_text(encoding="utf-8"), "Device:R")
    assert _property(symbol, "MPN")[2] == "RC0402"
    unit = next(c for c in symbol if isinstance(c, list) and c[0] == sexpdata.Symbol("symbol"))
    assert _property(unit, "MPN")[2] == "unit"


# --- write guards ------------------------------------------------------------ #


def test_unbalanced_edit_is_refused(tmp_path, monkeypatch):
    import commands.add_library_symbol_property as mod

    monkeypatch.setattr(mod, "_build_property", lambda *a, **k: '(property "MPN" "X1"')
    sch = tmp_path / "test.kicad_sch"
    sch.write_text(_MINIMAL_SCH, encoding="utf-8")

    result = _set(sch, "MPN", "X1")

    assert result["success"] is False
    assert "unbalance" in result["message"]
    assert sch.read_text(encoding="utf-8") == _MINIMAL_SCH


def test_property_outside_symbol_is_refused(tmp_path, monkeypatch):
    """A balanced splice at the wrong depth passes the balance guard; the
    direct-child re-check must still stop it."""
    import commands.add_library_symbol_property as mod

    monkeypatch.setattr(
        mod,
        "_splice_child",
        lambda block, anchor, indent, tail_indent, new_prop: new_prop + "\n" + block,
    )
    sch = tmp_path / "compact.kicad_sch"
    sch.write_text(_COMPACT_SCH, encoding="utf-8")

    result = _set(sch, "MPN", "RC0402")

    assert result["success"] is False
    assert "direct child" in result["message"]
    assert sch.read_text(encoding="utf-8") == _COMPACT_SCH
