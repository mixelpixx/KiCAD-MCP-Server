"""Parentheses inside quoted strings are text, not structure.

KiCad writes them raw: the stock STM32 libraries have pin names such as
"PA13(JTMS" and "PB4(NJTRST)", and descriptions such as "Vin(fwd) 40V". A depth
counter that does not skip quoted text never rebalances on "PA13(JTMS", so it
runs to the end of the file. Before this fix, list_symbol_pins,
add_schematic_component and import_symbol all failed on every MCU_ST_STM32H5
symbol, and once such a symbol was in a schematic, adding any other symbol type
failed with "No lib_symbols section found".

These tests cover every block scanner that used such a counter, through the
public entry points where there is one.
"""

import shutil
import sys
from pathlib import Path

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATES_DIR = Path(__file__).parent.parent / "python" / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"

# Laid out the way KiCad writes a .kicad_sym: one token group per line.
MCU_LIB = """\
(kicad_symbol_lib
\t(version 20241209)
\t(generator "kicad_symbol_editor")
\t(symbol "MCU_PAREN"
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "U"
\t\t\t(at 0 12.7 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Value" "MCU_PAREN"
\t\t\t(at 0 10.16 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Footprint" ""
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes))
\t\t)
\t\t(property "Datasheet" ""
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes))
\t\t)
\t\t(property "Description" "ARM MCU, Vin(fwd) tolerant, JTAG (PA13(JTMS"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes))
\t\t)
\t\t(symbol "MCU_PAREN_0_1"
\t\t\t(rectangle (start -7.62 7.62) (end 7.62 -7.62)
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type background))
\t\t\t)
\t\t)
\t\t(symbol "MCU_PAREN_1_1"
\t\t\t(pin bidirectional line
\t\t\t\t(at -10.16 2.54 0)
\t\t\t\t(length 2.54)
\t\t\t\t(name "PA13(JTMS"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t\t(number "1"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t)
\t\t\t(pin bidirectional line
\t\t\t\t(at -10.16 0 0)
\t\t\t\t(length 2.54)
\t\t\t\t(name "PB4(NJTRST)"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t\t(number "2"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t)
\t\t\t(pin power_in line
\t\t\t\t(at 0 10.16 270)
\t\t\t\t(length 2.54)
\t\t\t\t(name "VDD"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t\t(number "3"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(embedded_fonts no)
\t)
\t(symbol "R_PLAIN"
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "R"
\t\t\t(at 2.032 0 90)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Value" "R_PLAIN"
\t\t\t(at 0 0 90)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(symbol "R_PLAIN_1_1"
\t\t\t(pin passive line
\t\t\t\t(at 0 3.81 270)
\t\t\t\t(length 1.27)
\t\t\t\t(name "~"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t\t(number "1"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t)
\t\t\t(pin passive line
\t\t\t\t(at 0 -3.81 90)
\t\t\t\t(length 1.27)
\t\t\t\t(name "~"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t\t(number "2"
\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(embedded_fonts no)
\t)
)
"""


def _sym(node):
    return (
        node[0].value()
        if isinstance(node, list) and node and isinstance(node[0], sexpdata.Symbol)
        else None
    )


@pytest.fixture
def lib_file(tmp_path: Path) -> Path:
    path = tmp_path / "ParenLib.kicad_sym"
    path.write_text(MCU_LIB, encoding="utf-8")
    return path


@pytest.fixture
def loader(lib_file: Path, monkeypatch):
    from commands.dynamic_symbol_loader import DynamicSymbolLoader

    DynamicSymbolLoader.clear_library_caches()
    ldr = DynamicSymbolLoader()
    monkeypatch.setattr(
        ldr, "find_library_file", lambda name: lib_file if name == "ParenLib" else None
    )
    return ldr


# --------------------------------------------------------------------------- #
#  The shared helpers
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_paren_delta_ignores_quoted_parens() -> None:
    from utils.sexpr_format import paren_delta

    assert paren_delta('(name "PA13(JTMS"') == 1
    assert paren_delta('(name "PB4(NJTRST)")') == 0
    assert paren_delta('(property "Description" "a \\" ( b")') == 0
    assert paren_delta(")") == -1


# --------------------------------------------------------------------------- #
#  Symbol loader: the STM32 failure seen in the module-controller benchmark
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_extract_symbol_stops_at_its_own_close(loader) -> None:
    block = loader.extract_symbol_from_library("ParenLib", "MCU_PAREN")
    assert block is not None
    assert block.lstrip().startswith('(symbol "ParenLib:MCU_PAREN"') or block.lstrip().startswith(
        '(symbol "MCU_PAREN"'
    )
    assert "R_PLAIN" not in block, "the block ran past its own end into the next symbol"
    assert sexpdata.loads(block)  # one balanced form


@pytest.mark.unit
def test_add_mcu_then_another_symbol(loader, tmp_path: Path) -> None:
    sch = tmp_path / "board.kicad_sch"
    shutil.copy(EMPTY_SCH, sch)

    assert loader.add_component(sch, "ParenLib", "MCU_PAREN", reference="U1", x=50, y=50)
    # Used to fail here: "No lib_symbols section found in schematic".
    assert loader.add_component(sch, "ParenLib", "R_PLAIN", reference="R1", value="10k", x=80, y=50)

    tree = sexpdata.loads(sch.read_text(encoding="utf-8"))
    lib_symbols = next(n for n in tree if _sym(n) == "lib_symbols")
    defined = {n[1] for n in lib_symbols if _sym(n) == "symbol"}
    assert {"ParenLib:MCU_PAREN", "ParenLib:R_PLAIN"} <= defined
    placed = [n for n in tree if _sym(n) == "symbol"]
    refs = set()
    for sym in placed:
        for prop in sym:
            if _sym(prop) == "property" and prop[1] == "Reference":
                refs.add(prop[2])
    assert {"U1", "R1"} <= refs


@pytest.mark.unit
def test_lib_property_positions_read_past_quoted_paren(loader, tmp_path: Path) -> None:
    sch = tmp_path / "board.kicad_sch"
    shutil.copy(EMPTY_SCH, sch)
    loader.inject_symbol_into_schematic(sch, "ParenLib", "MCU_PAREN")
    positions = loader._extract_lib_property_positions(sch, "ParenLib", "MCU_PAREN")
    assert {"Reference", "Value", "Description"} <= set(positions)


# --------------------------------------------------------------------------- #
#  Other block scanners
# --------------------------------------------------------------------------- #

TRICKY = '(root (item "a(b" (inner 1)) (item "c)d" (inner 2)) (tail))'


@pytest.mark.unit
@pytest.mark.parametrize(
    "module, func",
    [
        ("commands.schematic_text_utils", "_find_matching_paren"),
        ("utils.kicad_dru", "_find_matching_paren"),
    ],
)
def test_module_matchers(module: str, func: str) -> None:
    import importlib

    fn = getattr(importlib.import_module(module), func)
    first = TRICKY.index("(item")
    assert fn(TRICKY, first) == TRICKY.index("(inner 1))") + len("(inner 1)")
    assert fn(TRICKY, 0) == len(TRICKY) - 1


@pytest.mark.unit
def test_paren_block_extractors() -> None:
    from commands import library_management, update_symbol_from_library
    from commands.dynamic_symbol_loader import DynamicSymbolLoader

    first = TRICKY.index("(item")
    expected = '(item "a(b" (inner 1))'
    assert library_management._extract_paren_block(TRICKY, first) == expected
    assert update_symbol_from_library._extract_paren_block(TRICKY, first)[0] == expected
    assert DynamicSymbolLoader._extract_paren_block(TRICKY, first) == expected


@pytest.mark.unit
def test_library_management_finds_top_level_symbol_after_quoted_paren() -> None:
    from commands.library_management import _find_symbol_block

    found = _find_symbol_block(MCU_LIB, "R_PLAIN")
    assert found is not None, "depth before R_PLAIN was miscounted, so it looked nested"
    assert sexpdata.loads(found[2])


@pytest.mark.unit
def test_lib_symbols_range_spans_whole_section() -> None:
    from commands.update_symbol_from_library import _lib_symbols_range

    content = (
        '(kicad_sch (lib_symbols (symbol "X" (pin (name "PA13(JTMS")))) (symbol (lib_id "X")))'
    )
    start, end = _lib_symbols_range(content)
    assert content[start : end + 1] == '(lib_symbols (symbol "X" (pin (name "PA13(JTMS"))))'


@pytest.mark.unit
def test_symbol_creator_remove_symbol_leaves_the_next_one() -> None:
    from commands.symbol_creator import SymbolCreator

    out = SymbolCreator.__new__(SymbolCreator)._remove_symbol(MCU_LIB, "MCU_PAREN")
    assert "MCU_PAREN" not in out
    assert '(symbol "R_PLAIN"' in out
    assert sexpdata.loads(out)


@pytest.mark.unit
def test_kicad_mod_blocks_with_quoted_paren() -> None:
    from parsers.kicad_mod_parser import _extract_blocks

    mod = '(footprint "X" (pad "1(a" smd rect (at 0 0) (size 1 1)) (pad "2" smd rect (at 1 0) (size 1 1)))'
    pads = _extract_blocks(mod, "pad")
    assert pads == [
        '(pad "1(a" smd rect (at 0 0) (size 1 1))',
        '(pad "2" smd rect (at 1 0) (size 1 1))',
    ]


@pytest.mark.unit
def test_schematic_hierarchy_sheet_blocks_with_quoted_paren() -> None:
    from commands.schematic_hierarchy import SchematicHierarchyCommands

    content = (
        '(kicad_sch (sheet (at 0 0) (property "Sheetname" "HV (800V" (at 0 0 0)) (uuid "a")) '
        '(sheet (at 10 0) (property "Sheetname" "MCU" (at 0 0 0)) (uuid "b")))'
    )
    spans = SchematicHierarchyCommands._find_sheet_blocks(content)
    assert len(spans) == 2
    assert all(sexpdata.loads(content[s:e]) for s, e in spans)
