"""Tests for add_symbol_property — add custom properties to .kicad_sym library files."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.add_symbol_property import (  # noqa: E402
    _find_property_span,
    _find_symbol_in_lib,
    _first_subsymbol_offset,
    _iter_children,
    _match_paren,
    _paren_balance,
    add_symbol_property,
)

_KICAD_CLI = shutil.which("kicad-cli")

# A real KiCad 9 library (version 20241209, generator_version "9.0"): its
# Footprint field is hidden via a (hide yes) *inside* (effects ...) and its
# Reference carries a (justify ...). Hand-written fixtures that put hide
# directly on the property miss both, which is how the effects-clobbering
# regression below survived the first round of tests.
KICAD9_FIXTURE = Path(__file__).parent / "fixtures" / "Simulation_SPICE_minimal.kicad_sym"

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

# Close to what eeschema writes: tabs, one property spread over several lines,
# and unit sub-symbols that repeat the parent's property names. The paren and
# insertion-point corruptions all need this shape to reproduce.
#
# Its `Manufacturer` is hidden with a property-level `(hide yes)`, which KiCad
# accepts but does not itself emit — KiCad 8/9 nest that marker inside
# `(effects ...)`. Do not read this fixture as a statement about the on-disk
# format; KICAD9_FIXTURE is the real thing, and the difference is exactly what
# let the effects-clobbering bug through.
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


def child_heads(block: str) -> list[str]:
    """Head token of each direct child of *block*.

    Net paren balance is too weak an oracle for this module: dropping the
    symbol's closer and truncating a property match are equal and opposite, so a
    file kicad-cli refuses to load can still balance to zero. What actually
    changes is the symbol's shape — orphaned ``(hide yes)``/``(effects ...)``
    fragments appear as direct children that were never there.
    """
    heads = []
    for offset in _iter_children(block):
        after = block[offset + 1 :]
        heads.append(after.split(None, 1)[0].rstrip(")") if after.strip() else "")
    return heads


def sub_block(content: str, name: str) -> str:
    """The verbatim text of the sub-symbol *name*, closing paren included."""
    _, _, block = _find_symbol_in_lib(content, name)
    return block


def newline_counts(path: Path) -> tuple[int, int]:
    """(CRLF count, lone-LF count) of the bytes on disk."""
    raw = path.read_bytes()
    return raw.count(b"\r\n"), raw.count(b"\n") - raw.count(b"\r\n")


def upgrade_with_kicad_cli(path: Path, out: Path) -> subprocess.CompletedProcess:
    """Run `kicad-cli sym upgrade`, the only oracle for "does KiCad load this"."""
    return subprocess.run(
        [_KICAD_CLI, "sym", "upgrade", str(path), "-o", str(out), "--force"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def kicad9_lib(tmp_path):
    p = tmp_path / "Simulation_SPICE_minimal.kicad_sym"
    shutil.copy(KICAD9_FIXTURE, p)
    return p


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


def test_find_property_span_hit(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert _find_property_span(c[m[0] : m[1]], "Manufacturer") is not None


def test_find_property_span_miss(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "R")
    assert _find_property_span(c[m[0] : m[1]], "Manufacturer") is None


def test_find_property_span_rejects_name_prefix(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert _find_property_span(c[m[0] : m[1]], "Man") is None


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


def test_update_keeps_symbol_shape(tabbed_lib):
    """Updating a property must not change which children the symbol has.

    Net paren balance cannot express this: truncating the property match (+1)
    and losing the symbol's closer (-1) cancel exactly, so the pre-fix output
    balanced to zero while `kicad-cli sym upgrade` still reported "Unable to
    load library". The orphaned (hide yes)/(effects ...) fragments it left
    behind do show up as extra direct children of the symbol.
    """
    before = child_heads(_find_symbol_in_lib(TABBED_LIB, "LED")[2])
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
    assert child_heads(_find_symbol_in_lib(c, "LED")[2]) == before
    # The symbol block must still stop where the symbol stops, not run to EOF.
    assert _find_symbol_in_lib(c, "LED")[1] < c.rindex(")")
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
    """LED_0_1 also carries a Reference; the parent's copy is the one to edit.

    Locating the right property was never the whole problem — the pre-fix code
    also found the parent's copy, then truncated the replacement, so the
    position-only assertions this test used to make passed on a file kicad-cli
    rejects. The sub-symbol must come back byte-identical and the parent's set of
    children must be unchanged.
    """
    before = child_heads(_find_symbol_in_lib(TABBED_LIB, "LED")[2])
    unit_before = sub_block(TABBED_LIB, "LED_0_1")
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
    assert child_heads(_find_symbol_in_lib(c, "LED")[2]) == before
    assert sub_block(c, "LED_0_1") == unit_before
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
    # Anchored on the newline: '\t\t(property' is a substring of the three-tab
    # form the pre-fix code emitted, so without the "\n" this cannot tell the
    # symbol's own level from one tab deeper inside a unit.
    assert '\n\t\t(property "MPN" "IN-P32DATRG"' in c
    assert '\n\t\t\t(property "MPN"' not in c
    assert "\n\t\t\t(hide yes)" in c
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
    """The balance guard catches a slice that gains or loses a paren.

    It is deliberately narrow: an edit that stays balanced but lands at the wrong
    nesting depth passes it untouched. That half is covered by
    test_guard_refuses_property_spliced_outside_symbol.
    """
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


# --- regression: the insertion anchor on the symbol's own first line -------- #

COMPACT_LIB = (
    '(kicad_symbol_lib (version 20231120) (generator "test")\n'
    '\t(symbol "R" (symbol "R_0_1" (rectangle (start -1 1) (end 1 -1))))\n'
    ")\n"
)

BARE_LIB = '(kicad_symbol_lib (version 20231120) (generator "test")\n' '\t(symbol "EMPTY")\n' ")\n"


@pytest.fixture(params=[COMPACT_LIB, BARE_LIB], ids=["shared-line-unit", "bare-symbol"])
def one_line_lib(request, tmp_path):
    """A symbol whose insertion anchor sits on the line that opens the symbol.

    Both shapes make ``block.rfind("\\n", 0, anchor)`` return -1, so the
    pre-fix line-start arithmetic collapsed to index 0 — the symbol's own "(".
    """
    p = tmp_path / "one_line.kicad_sym"
    p.write_text(request.param, encoding="utf-8")
    return p


def test_new_property_stays_inside_one_line_symbol(one_line_lib):
    """The property must become a child of the symbol, not a sibling of it."""
    name = "R" if 'symbol "R"' in one_line_lib.read_text(encoding="utf-8") else "EMPTY"
    r = add_symbol_property(
        {
            "libraryPath": str(one_line_lib),
            "symbolName": name,
            "propertyName": "MPN",
            "propertyValue": "RC0402",
        }
    )
    assert r["success"], r["message"]
    c = one_line_lib.read_text(encoding="utf-8")
    assert balance(c) == 0
    _, _, block = _find_symbol_in_lib(c, name)
    assert _find_property_span(block, "MPN") is not None
    # A sibling would sort before the symbol's own opening paren.
    assert c.index('"MPN"') > c.index(f'(symbol "{name}"')
    # ...and would be a direct child of (kicad_symbol_lib ...) instead.
    assert _find_property_span(c[: c.rindex(")") + 1], "MPN") is None


def test_guard_refuses_property_spliced_outside_symbol(tmp_path, monkeypatch):
    """A balanced insert at the wrong depth must still be refused.

    Reinstates the pre-fix line-start arithmetic to prove the structural guard —
    not the paren-balance one — is what stops it. The balance is unchanged by
    this mistake, so the balance guard lets it straight through.
    """
    import commands.add_symbol_property as mod

    def old_arithmetic(block, anchor, indent, tail_indent, new_prop):
        line_start = block.rfind("\n", 0, anchor) + 1
        return block[:line_start] + indent + new_prop + "\n" + block[line_start:]

    monkeypatch.setattr(mod, "_splice_child", old_arithmetic)
    p = tmp_path / "compact.kicad_sym"
    p.write_text(COMPACT_LIB, encoding="utf-8")
    r = add_symbol_property(
        {
            "libraryPath": str(p),
            "symbolName": "R",
            "propertyName": "MPN",
            "propertyValue": "RC0402",
        }
    )
    assert not r["success"]
    assert "direct child" in r["message"]
    assert p.read_text(encoding="utf-8") == COMPACT_LIB


@pytest.mark.integration
@pytest.mark.skipif(_KICAD_CLI is None, reason="kicad-cli not on PATH")
def test_kicad_cli_loads_edited_one_line_library(one_line_lib, tmp_path):
    name = "R" if 'symbol "R"' in one_line_lib.read_text(encoding="utf-8") else "EMPTY"
    r = add_symbol_property(
        {
            "libraryPath": str(one_line_lib),
            "symbolName": name,
            "propertyName": "MPN",
            "propertyValue": "RC0402",
        }
    )
    assert r["success"], r["message"]
    proc = upgrade_with_kicad_cli(one_line_lib, tmp_path / "out.kicad_sym")
    assert proc.returncode == 0, f"{proc.stdout}{proc.stderr}"


# --- regression: (effects ...) clobbered when a property is rewritten ------- #


def test_update_preserves_hide_nested_in_effects(kicad9_lib):
    """KiCad 8/9 write (hide yes) inside (effects ...), a grandchild.

    Looking for it only among the property's direct children reported every such
    field as visible, so rewriting one un-hid it.
    """
    before = KICAD9_FIXTURE.read_text(encoding="utf-8")
    add_symbol_property(
        {
            "libraryPath": str(kicad9_lib),
            "symbolName": "OPAMP",
            "propertyName": "Footprint",
            "propertyValue": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        }
    )
    c = kicad9_lib.read_text(encoding="utf-8")
    assert c.count("(hide yes)") == before.count("(hide yes)") == 16
    _, _, block = _find_symbol_in_lib(c, "OPAMP")
    start, end = _find_property_span(block, "Footprint")
    assert "(hide yes)" in block[start:end]


def test_update_preserves_justify_inside_effects(kicad9_lib):
    """(justify ...) lives inside (effects ...) and was regenerated away."""
    before = KICAD9_FIXTURE.read_text(encoding="utf-8")
    add_symbol_property(
        {
            "libraryPath": str(kicad9_lib),
            "symbolName": "OPAMP",
            "propertyName": "Reference",
            "propertyValue": "A",
        }
    )
    c = kicad9_lib.read_text(encoding="utf-8")
    assert c.count("(justify") == before.count("(justify") == 5
    _, _, block = _find_symbol_in_lib(c, "OPAMP")
    start, end = _find_property_span(block, "Reference")
    assert "(justify left)" in block[start:end]


def test_update_preserves_font_size_and_style(tmp_path):
    """Font size, thickness, bold/italic and justification survive verbatim."""
    effects = (
        "(effects\n"
        "\t\t\t\t(font\n"
        "\t\t\t\t\t(size 2.54 3.81)\n"
        "\t\t\t\t\t(thickness 0.5)\n"
        "\t\t\t\t\t(bold yes)\n"
        "\t\t\t\t\t(italic yes)\n"
        "\t\t\t\t)\n"
        "\t\t\t\t(justify right bottom)\n"
        "\t\t\t)"
    )
    p = tmp_path / "styled.kicad_sym"
    p.write_text(
        '(kicad_symbol_lib (version 20241209) (generator "test")\n'
        '\t(symbol "U1"\n'
        '\t\t(property "MPN" "OLD"\n'
        "\t\t\t(at 1 2 90)\n"
        f"\t\t\t{effects}\n"
        "\t\t)\n"
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    add_symbol_property(
        {"libraryPath": str(p), "symbolName": "U1", "propertyName": "MPN", "propertyValue": "NEW"}
    )
    c = p.read_text(encoding="utf-8")
    assert effects in c
    assert '(property "MPN" "NEW" (at 1 2 90)' in c
    # No second, template-generated effects block was appended.
    assert c.count("(effects") == 1


def test_explicit_unhide_strips_hide_nested_in_effects(kicad9_lib):
    add_symbol_property(
        {
            "libraryPath": str(kicad9_lib),
            "symbolName": "OPAMP",
            "propertyName": "Footprint",
            "propertyValue": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            "hide": False,
        }
    )
    c = kicad9_lib.read_text(encoding="utf-8")
    assert c.count("(hide yes)") == 15
    _, _, block = _find_symbol_in_lib(c, "OPAMP")
    start, end = _find_property_span(block, "Footprint")
    assert "(hide" not in block[start:end]


def test_kicad7_bare_hide_token_is_detected(tmp_path):
    """KiCad 7 spelled it as a bare `hide` atom inside (effects ...)."""
    p = tmp_path / "kicad7.kicad_sym"
    p.write_text(
        '(kicad_symbol_lib (version 20211014) (generator "test")\n'
        '\t(symbol "U1"\n'
        '\t\t(property "MPN" "OLD"\n'
        "\t\t\t(at 1 2 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) hide)\n"
        "\t\t)\n"
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    add_symbol_property(
        {"libraryPath": str(p), "symbolName": "U1", "propertyName": "MPN", "propertyValue": "NEW"}
    )
    c = p.read_text(encoding="utf-8")
    assert balance(c) == 0
    # Re-spelled as the modern property-level marker rather than dropped.
    assert "(hide yes)" in c
    assert "(font (size 1.27 1.27))" in c


def test_kicad7_bare_hide_can_be_overridden(tmp_path):
    p = tmp_path / "kicad7.kicad_sym"
    p.write_text(
        '(kicad_symbol_lib (version 20211014) (generator "test")\n'
        '\t(symbol "U1"\n'
        '\t\t(property "MPN" "OLD"\n'
        "\t\t\t(at 1 2 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) hide)\n"
        "\t\t)\n"
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    add_symbol_property(
        {
            "libraryPath": str(p),
            "symbolName": "U1",
            "propertyName": "MPN",
            "propertyValue": "NEW",
            "hide": False,
        }
    )
    c = p.read_text(encoding="utf-8")
    assert "hide" not in c


@pytest.mark.integration
@pytest.mark.skipif(_KICAD_CLI is None, reason="kicad-cli not on PATH")
def test_kicad_cli_canonical_form_changes_only_the_value(kicad9_lib, tmp_path):
    """KiCad's own serialisation is the arbiter of "nothing else was lost".

    Round-tripping both the original and the edited library through
    `sym upgrade` normalises formatting away, so any surviving difference is a
    semantic one.
    """
    before_out = tmp_path / "before.kicad_sym"
    assert upgrade_with_kicad_cli(KICAD9_FIXTURE, before_out).returncode == 0
    add_symbol_property(
        {
            "libraryPath": str(kicad9_lib),
            "symbolName": "OPAMP",
            "propertyName": "Footprint",
            "propertyValue": "Package_SO:SOIC-8",
        }
    )
    after_out = tmp_path / "after.kicad_sym"
    assert upgrade_with_kicad_cli(kicad9_lib, after_out).returncode == 0
    expected = before_out.read_text(encoding="utf-8").replace(
        '(property "Footprint" ""', '(property "Footprint" "Package_SO:SOIC-8"', 1
    )
    assert after_out.read_text(encoding="utf-8") == expected


# --- regression: (at ...) separated by something other than a space --------- #


@pytest.mark.parametrize("gap", ["\t", "\n\t\t\t\t", "  "], ids=["tab", "newline", "spaces"])
def test_update_keeps_at_with_non_space_separator(tmp_path, gap):
    """Any whitespace separates an s-expression head from its arguments.

    Testing for the literal "(at " missed those spellings and silently dropped
    the field back to (at 0 0 0).
    """
    p = tmp_path / "gap.kicad_sym"
    p.write_text(
        '(kicad_symbol_lib (version 20231120) (generator "test")\n'
        '\t(symbol "U1"\n'
        '\t\t(property "MPN" "OLD"\n'
        f"\t\t\t(at{gap}5 6 90)\n"
        "\t\t\t(effects (font (size 1.27 1.27)))\n"
        "\t\t)\n"
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    add_symbol_property(
        {"libraryPath": str(p), "symbolName": "U1", "propertyName": "MPN", "propertyValue": "NEW"}
    )
    c = p.read_text(encoding="utf-8")
    assert f"(at{gap}5 6 90)" in c
    assert "(at 0 0 0)" not in c


# --- regression: line endings and non-atomic writes ------------------------- #

_NEWLINE_LIB = (
    '(kicad_symbol_lib (version 20231120) (generator "test")\n'
    '\t(symbol "U1"\n'
    '\t\t(property "MPN" "OLD"\n'
    "\t\t\t(at 0 0 0)\n"
    "\t\t\t(effects (font (size 1.27 1.27)))\n"
    "\t\t)\n"
    "\t)\n"
    ")\n"
)


def _edit(path: Path) -> None:
    r = add_symbol_property(
        {
            "libraryPath": str(path),
            "symbolName": "U1",
            "propertyName": "MPN",
            "propertyValue": "NEW",
        }
    )
    assert r["success"], r["message"]


def test_crlf_library_stays_crlf(tmp_path):
    """A one-property edit must not rewrite every line ending in the file."""
    p = tmp_path / "crlf.kicad_sym"
    p.write_bytes(_NEWLINE_LIB.replace("\n", "\r\n").encode("utf-8"))
    _edit(p)
    crlf, lone_lf = newline_counts(p)
    assert lone_lf == 0
    assert crlf > 0


def test_lf_library_stays_lf(tmp_path):
    """Path.write_text maps "\\n" to os.linesep, so on Windows LF became CRLF."""
    p = tmp_path / "lf.kicad_sym"
    p.write_bytes(_NEWLINE_LIB.encode("utf-8"))
    _edit(p)
    crlf, lone_lf = newline_counts(p)
    assert crlf == 0
    assert lone_lf > 0


def test_write_leaves_no_temp_file(tmp_path):
    p = tmp_path / "atomic.kicad_sym"
    p.write_bytes(_NEWLINE_LIB.encode("utf-8"))
    _edit(p)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["atomic.kicad_sym"]


def test_failed_write_leaves_original_intact(tmp_path, monkeypatch):
    """The rename is the commit point: a failure before it cannot truncate."""
    import commands.add_symbol_property as mod

    p = tmp_path / "atomic.kicad_sym"
    p.write_bytes(_NEWLINE_LIB.encode("utf-8"))

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        add_symbol_property(
            {
                "libraryPath": str(p),
                "symbolName": "U1",
                "propertyName": "MPN",
                "propertyValue": "NEW",
            }
        )
    assert p.read_bytes() == _NEWLINE_LIB.encode("utf-8")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
