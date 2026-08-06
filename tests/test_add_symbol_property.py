"""Tests for add_symbol_property — add custom properties to .kicad_sym library files."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.add_symbol_property import (  # noqa: E402
    _find_property_span,
    _find_symbol_in_lib,
    _first_subsymbol_offset,
    _has_property,
    _match_paren,
    _paren_balance,
    add_symbol_property,
)

LIB = """(kicad_symbol_lib (version 20231120) (generator "test")
  (symbol "R" (pin_names hide) (in_bom yes) (on_board yes)
    (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_0_1" (pin "1" passive (at 0 2.54 0)))
    (symbol "R_1_1" (pin "2" passive (at 0 -2.54 0))))
  (symbol "C" (pin_names hide) (in_bom yes) (on_board yes)
    (property "Reference" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Manufacturer" "TDK" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
    (symbol "C_0_1" (pin "1" passive (at 0 2.54 0)))
    (symbol "C_1_1" (pin "2" passive (at 0 -2.54 0))))
)
"""

# The layout eeschema actually writes: tabs, one property per several lines, and
# unit sub-symbols that repeat the parent's property names. Every corruption
# this module has caused in the field needed this shape to reproduce.
TABBED_LIB = """(kicad_symbol_lib (version 20231120) (generator "eeschema")
\t(symbol "LED"
\t\t(pin_numbers hide)
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "D"
\t\t\t(at 0 2.54 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Value" "LED"
\t\t\t(at 0 -2.54 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Manufacturer" "Osram"
\t\t\t(at 0 0 0)
\t\t\t(hide yes)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(symbol "LED_0_1"
\t\t\t(property "Reference" "D"
\t\t\t\t(at 0 0 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(polyline
\t\t\t\t(pts (xy -1.27 -1.27) (xy -1.27 1.27))
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t)
\t\t)
\t\t(symbol "LED_1_1"
\t\t\t(pin passive line (at -3.81 0 0) (length 2.54))
\t\t)
\t\t(symbol "LED_2_1"
\t\t\t(pin passive line (at 3.81 0 180) (length 2.54))
\t\t)
\t)
)
"""


def balance(text: str) -> int:
    """Net paren balance, ignoring parens inside quoted tokens."""
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return depth


@pytest.fixture
def tmp_lib(tmp_path):
    p = tmp_path / "test.kicad_sym"
    p.write_text(LIB, encoding="utf-8")
    return str(p)


@pytest.fixture
def tabbed_lib(tmp_path):
    p = tmp_path / "tabbed.kicad_sym"
    p.write_text(TABBED_LIB, encoding="utf-8")
    return str(p)


def test_add_new_property(tmp_lib):
    r = add_symbol_property(
        {
            "libraryPath": tmp_lib,
            "symbolName": "R",
            "propertyName": "Manufacturer",
            "propertyValue": "YAGEO",
            "hide": True,
        }
    )
    assert r["success"]
    assert "added" in r["message"].lower()
    assert "YAGEO" in Path(tmp_lib).read_text(encoding="utf-8")


def test_replace_existing(tmp_lib):
    r = add_symbol_property(
        {
            "libraryPath": tmp_lib,
            "symbolName": "C",
            "propertyName": "Manufacturer",
            "propertyValue": "Murata",
        }
    )
    assert r["success"]
    assert "updated" in r["message"].lower()
    c = Path(tmp_lib).read_text(encoding="utf-8")
    assert "Murata" in c
    assert "TDK" not in c


def test_symbol_not_found(tmp_lib):
    r = add_symbol_property(
        {
            "libraryPath": tmp_lib,
            "symbolName": "L",
            "propertyName": "Manufacturer",
            "propertyValue": "test",
        }
    )
    assert not r["success"]


def test_library_not_found():
    r = add_symbol_property(
        {
            "libraryPath": "/no/such/file",
            "symbolName": "R",
            "propertyName": "M",
            "propertyValue": "x",
        }
    )
    assert not r["success"]


def test_sub_symbol_not_matched(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert m is not None
    b = c[m[0] : m[1]]
    assert "Reference" in b
    assert 'symbol "C_0_1"' in b
    assert m[0] < c.find('symbol "C_0_1"')


def test_has_property_true(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert _has_property(c[m[0] : m[1]], "Manufacturer")


def test_has_property_false(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "R")
    assert not _has_property(c[m[0] : m[1]], "Manufacturer")


def test_has_property_partial(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert not _has_property(c[m[0] : m[1]], "Man")


def test_found_block_includes_closing_paren(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    start, end, block = _find_symbol_in_lib(c, "C")
    assert block == c[start : end + 1]
    assert balance(block) == 0


# --- regression: library corruption on multi-unit, tab-indented symbols ----- #


def test_add_keeps_paren_balance(tabbed_lib):
    before = balance(Path(tabbed_lib).read_text(encoding="utf-8"))
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "MPN",
            "propertyValue": "IN-P32DATRG",
            "hide": True,
        }
    )
    assert balance(Path(tabbed_lib).read_text(encoding="utf-8")) == before == 0


def test_update_keeps_paren_balance(tabbed_lib):
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "Manufacturer",
            "propertyValue": "Inolux",
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert balance(c) == 0
    assert "Inolux" in c
    assert "Osram" not in c


def test_update_replaces_whole_property_block(tabbed_lib):
    """A multi-line property must be replaced entirely, not up to its first ")".

    Truncating the match left the old (hide yes)/(effects ...) lines behind as
    orphans directly under the symbol, which eeschema refuses to load.
    """
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "Manufacturer",
            "propertyValue": "Inolux",
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert c.count("(effects (font (size 1.27 1.27)))") == TABBED_LIB.count(
        "(effects (font (size 1.27 1.27)))"
    )
    # Exactly one (hide yes) survives -- the rewritten property's own, inherited
    # from the block it replaced. A second one would be an orphaned leftover.
    assert c.count("(hide yes)") == 1


def test_update_inherits_hide_and_position(tabbed_lib):
    """Changing a value must not move or reveal an already-placed hidden field."""
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "Reference",
            "propertyValue": "LD",
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert '(property "Reference" "LD" (at 0 2.54 0)' in c


def test_update_can_override_hide_explicitly(tabbed_lib):
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "Manufacturer",
            "propertyValue": "Inolux",
            "hide": False,
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert balance(c) == 0
    assert "(hide yes)" not in c


def test_new_property_lands_on_parent_not_sub_symbol(tabbed_lib):
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "MPN",
            "propertyValue": "IN-P32DATRG",
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert c.index('"MPN"') < c.index('(symbol "LED_0_1"')
    _, _, block = _find_symbol_in_lib(c, "LED")
    assert _find_property_span(block, "MPN") is not None


def test_update_targets_parent_when_sub_symbol_shares_name(tabbed_lib):
    """LED_0_1 also carries a Reference; the parent's copy is the one to edit."""
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "Reference",
            "propertyValue": "LD",
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert balance(c) == 0
    assert c.index('"Reference" "LD"') < c.index('(symbol "LED_0_1"')
    # The unit's own Reference is untouched.
    assert c.count('"Reference" "D"') == 1


def test_new_property_uses_file_indentation(tabbed_lib):
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "MPN",
            "propertyValue": "IN-P32DATRG",
            "hide": True,
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert '\t\t(property "MPN" "IN-P32DATRG"' in c
    assert "\t\t\t(hide yes)" in c
    assert "    (property" not in c


def test_symbol_without_sub_symbols(tmp_path):
    p = tmp_path / "flat.kicad_sym"
    p.write_text(
        '(kicad_symbol_lib (version 20231120) (generator "test")\n'
        '\t(symbol "FLAT"\n'
        '\t\t(property "Reference" "U"\n'
        "\t\t\t(at 0 0 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)))\n"
        "\t\t)\n"
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    r = add_symbol_property(
        {
            "libraryPath": str(p),
            "symbolName": "FLAT",
            "propertyName": "MPN",
            "propertyValue": "X1",
        }
    )
    assert r["success"]
    c = p.read_text(encoding="utf-8")
    assert balance(c) == 0
    _, _, block = _find_symbol_in_lib(c, "FLAT")
    assert _find_property_span(block, "MPN") is not None


def test_value_with_parens_is_not_parsed_as_list(tmp_path):
    p = tmp_path / "paren.kicad_sym"
    p.write_text(
        '(kicad_symbol_lib (version 20231120) (generator "test")\n'
        '\t(symbol "CAP"\n'
        '\t\t(property "Description" "Ceramic (X7R) 50V"\n'
        "\t\t\t(at 0 0 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)))\n"
        "\t\t)\n"
        '\t\t(symbol "CAP_0_1"\n'
        "\t\t\t(pin passive line (at 0 2.54 270) (length 2.54))\n"
        "\t\t)\n"
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    r = add_symbol_property(
        {
            "libraryPath": str(p),
            "symbolName": "CAP",
            "propertyName": "Description",
            "propertyValue": "Ceramic (C0G) 100V",
        }
    )
    assert r["success"]
    c = p.read_text(encoding="utf-8")
    assert balance(c) == 0
    assert "Ceramic (C0G) 100V" in c
    assert "X7R" not in c


def test_value_with_quotes_is_escaped(tabbed_lib):
    add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "Description",
            "propertyValue": '3.2x2.8mm "PLCC-4"',
        }
    )
    c = Path(tabbed_lib).read_text(encoding="utf-8")
    assert balance(c) == 0
    assert r"3.2x2.8mm \"PLCC-4\"" in c


def test_match_paren_skips_quoted_parens():
    s = '(a "b)c" (d))'
    assert _match_paren(s, 0) == len(s) - 1


def test_match_paren_unbalanced():
    assert _match_paren("(a (b)", 0) == -1


def test_first_subsymbol_offset_none_for_flat_block():
    block = '(symbol "X" (property "Reference" "U" (at 0 0 0)))'
    assert _first_subsymbol_offset(block) is None


def test_paren_balance_ignores_quoted_parens():
    assert _paren_balance('(a "b)c" (d))') == 0
    assert _paren_balance(r'(a "he said \"hi(\"")') == 0
    assert _paren_balance("(a (b)") == 1


def test_unbalanced_edit_is_refused(tabbed_lib, monkeypatch):
    """The write guard is the backstop for any future slicing mistake."""
    import commands.add_symbol_property as mod

    monkeypatch.setattr(mod, "_build_property", lambda *a, **k: '(property "MPN" "X1"')
    original = Path(tabbed_lib).read_text(encoding="utf-8")
    r = add_symbol_property(
        {
            "libraryPath": tabbed_lib,
            "symbolName": "LED",
            "propertyName": "MPN",
            "propertyValue": "X1",
        }
    )
    assert not r["success"]
    assert "unbalance" in r["message"]
    assert Path(tabbed_lib).read_text(encoding="utf-8") == original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
