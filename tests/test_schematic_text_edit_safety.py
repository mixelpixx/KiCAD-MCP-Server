"""Regression tests for text-based schematic edits."""

import sexpdata

from commands.dynamic_symbol_loader import DynamicSymbolLoader
from commands.wire_manager import WireManager


def test_symbol_injection_ignores_parentheses_in_quoted_values(tmp_path, monkeypatch):
    """A quoted pin/property value must not move the lib_symbols boundary."""
    schematic = tmp_path / "quoted.kicad_sch"
    schematic.write_text(
        '(kicad_sch (version 20250114) (lib_symbols '
        '(symbol "Existing" (property "Description" "Vin(fwd) 40V"))) '
        '(sheet_instances (path "/" (page "1"))))\n',
        encoding="utf-8",
    )

    loader = DynamicSymbolLoader()
    monkeypatch.setattr(
        loader,
        "extract_symbol_from_library",
        lambda *_args: '(symbol "Device:R" (property "Reference" "R"))',
    )

    assert loader.inject_symbol_into_schematic(schematic, "Device", "R") is True
    parsed = sexpdata.loads(schematic.read_text(encoding="utf-8"))
    assert parsed[0] == sexpdata.Symbol("kicad_sch")
    assert '(symbol "Device:R"' in schematic.read_text(encoding="utf-8")


def test_repeated_label_edits_leave_a_parseable_schematic(tmp_path):
    schematic = tmp_path / "labels.kicad_sch"
    schematic.write_text(
        '(kicad_sch (version 20250114) (lib_symbols) '
        '(sheet_instances (path "/" (page "1"))))\n',
        encoding="utf-8",
    )

    for index in range(10):
        assert WireManager.add_label(schematic, f"NET_{index}", [index, index]) is True

    parsed = sexpdata.loads(schematic.read_text(encoding="utf-8"))
    labels = [
        item
        for item in parsed
        if isinstance(item, list) and item[0] == sexpdata.Symbol("label")
    ]
    assert len(labels) == 10
