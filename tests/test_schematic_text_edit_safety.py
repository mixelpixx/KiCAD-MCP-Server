"""Regression tests for text-based schematic edits."""

import pytest
import sexpdata
from commands.dynamic_symbol_loader import DynamicSymbolLoader
from commands.wire_manager import WireManager


def test_symbol_injection_ignores_parentheses_in_quoted_values(tmp_path, monkeypatch):
    """A quoted pin/property value must not move the lib_symbols boundary."""
    schematic = tmp_path / "quoted.kicad_sch"
    schematic.write_text(
        "(kicad_sch (version 20250114) (lib_symbols "
        '(symbol "Existing" (property "Description" "pin 1)"))) '
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
    lib_symbols = next(item for item in parsed if item[0] == sexpdata.Symbol("lib_symbols"))
    assert any(
        item[0] == sexpdata.Symbol("symbol") and item[1] == "Device:R" for item in lib_symbols[1:]
    )


def test_repeated_label_edits_leave_a_parseable_schematic(tmp_path):
    schematic = tmp_path / "labels.kicad_sch"
    schematic.write_text(
        "(kicad_sch (version 20250114) (lib_symbols) " '(sheet_instances (path "/" (page "1"))))\n',
        encoding="utf-8",
    )

    for index in range(10):
        assert WireManager.add_label(schematic, f"NET_{index}", [index, index]) is True

    parsed = sexpdata.loads(schematic.read_text(encoding="utf-8"))
    labels = [
        item for item in parsed if isinstance(item, list) and item[0] == sexpdata.Symbol("label")
    ]
    assert len(labels) == 10


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_text_edits_preserve_line_endings_and_temp_cleanup(tmp_path, newline):
    schematic = tmp_path / "line_endings.kicad_sch"
    base = '(kicad_sch (version 20250114)\n  (lib_symbols)\n  (sheet_instances (path "/" (page "1"))))\n'
    schematic.write_bytes(base.replace("\n", newline).encode("utf-8"))

    assert WireManager.add_label(schematic, "N1", [1, 1]) is True
    assert WireManager.add_wire(schematic, [0, 0], [10, 0]) is True

    raw = schematic.read_bytes()
    crlf = raw.count(b"\r\n")
    bare_lf = raw.count(b"\n") - crlf
    if newline == "\n":
        assert crlf == 0 and bare_lf > 0
    else:
        assert bare_lf == 0 and crlf > 0
    assert not list(tmp_path.glob("*.mcp-tmp"))
