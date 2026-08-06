"""Tests for validate_schematic / validate_symbol_library."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.validate_kicad_files import (  # noqa: E402
    _scan,
    validate_schematic,
    validate_symbol_library,
)
from utils.kicad_cli import resolve_kicad_cli  # noqa: E402

needs_cli = pytest.mark.skipif(
    resolve_kicad_cli() is None, reason="kicad-cli not installed on this machine"
)

GOOD_LIB = """(kicad_symbol_lib
\t(version 20231120)
\t(generator "eeschema")
\t(symbol "R"
\t\t(property "Reference" "R"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Description" "Resistor (thick film) 1%"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(symbol "R_0_1"
\t\t\t(rectangle (start -1 -2.5) (end 1 2.5))
\t\t)
\t\t(symbol "R_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 1.27))
\t\t)
\t)
)
"""

GOOD_SCH = """(kicad_sch
\t(version 20231120)
\t(generator "eeschema")
\t(paper "A4")
\t(lib_symbols
\t\t(symbol "Device:R"
\t\t\t(property "Reference" "R"
\t\t\t\t(at 0 0 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t)
\t)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 100 100 0)
\t\t(uuid "11111111-2222-3333-4444-555555555555")
\t)
)
"""


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def check_lib(path, **kw):
    """Structure-only by default so the suite does not need a KiCad install."""
    kw.setdefault("runKicadCli", False)
    return validate_symbol_library({"libraryPath": path, **kw})


def check_sch(path, **kw):
    kw.setdefault("runKicadCli", False)
    return validate_schematic({"schematicPath": path, **kw})


def codes(result):
    return [i["code"] for i in result["issues"]]


# --- structural scanner ---------------------------------------------------- #


def test_scan_accepts_parens_inside_strings():
    nodes, issues = _scan('(lib (property "Cap (X7R) 50V") )')
    assert issues == []
    assert [n.name for n in nodes] == ["lib", "property"]


def test_scan_reports_unclosed_form_with_position():
    _, issues = _scan('(kicad_symbol_lib\n\t(symbol "R"\n\t\t(pin)\n)\n')
    assert [i["code"] for i in issues] == ["unclosed_form"]
    assert issues[0]["line"] == 1


def test_scan_reports_extra_close():
    _, issues = _scan("(a (b))\n)")
    assert [i["code"] for i in issues] == ["unbalanced_close"]
    assert issues[0]["line"] == 2


def test_scan_reports_unterminated_string():
    _, issues = _scan('(a "never closed\n')
    assert [i["code"] for i in issues] == ["unterminated_string"]


def test_scan_reports_trailing_content():
    _, issues = _scan("(a)\n(b)\n")
    assert [i["code"] for i in issues] == ["trailing_content"]
    assert issues[0]["line"] == 2


def test_scan_records_depth_and_parent():
    nodes, _ = _scan('(kicad_sch (symbol (lib_id "X")))')
    by_name = {n.name: n for n in nodes}
    assert by_name["symbol"].depth == 1
    assert by_name["lib_id"].parent == "symbol"


def test_scan_column_is_one_based():
    _, issues = _scan("(a)\n  )")
    assert issues[0]["line"] == 2
    assert issues[0]["column"] == 3


# --- symbol library -------------------------------------------------------- #


def test_valid_library(tmp_path):
    r = check_lib(write(tmp_path, "ok.kicad_sym", GOOD_LIB))
    assert r["success"]
    assert r["valid"], r["issues"]
    assert r["symbolCount"] == 1
    assert r["errorCount"] == 0


def test_missing_paren_is_located(tmp_path):
    """The exact damage add_symbol_property used to cause: one ')' short."""
    broken = GOOD_LIB.replace("\t\t\t(effects (font (size 1.27 1.27)))\n\t\t)\n", "", 1)
    r = check_lib(write(tmp_path, "bad.kicad_sym", broken))
    assert not r["valid"]
    assert "unclosed_form" in codes(r)
    assert all(i["line"] > 0 for i in r["issues"])


def test_missing_paren_points_at_the_break_not_just_line_one(tmp_path):
    """unclosed_form can only ever blame the root; the indent hint locates it."""
    broken = GOOD_LIB.replace("\t\t\t(effects (font (size 1.27 1.27)))\n\t\t)\n", "", 1)
    r = check_lib(write(tmp_path, "bad.kicad_sym", broken))
    hint = next(i for i in r["issues"] if i["code"] == "indent_depth_mismatch")
    # First line whose nesting outran its indentation: the one after the break.
    assert hint["line"] == 7


def test_a_single_missing_paren_does_not_cascade(tmp_path):
    """Every node past the break nests one level too deep; reporting each is noise."""
    broken = GOOD_LIB.replace("\t\t\t(effects (font (size 1.27 1.27)))\n\t\t)\n", "", 1)
    r = check_lib(write(tmp_path, "bad.kicad_sym", broken))
    assert r["semanticChecksRan"] is False
    assert r["errorCount"] == 2
    assert "unit_name_mismatch" not in codes(r)


def test_extra_paren_is_located(tmp_path):
    r = check_lib(write(tmp_path, "x.kicad_sym", GOOD_LIB + ")\n"))
    assert not r["valid"]
    assert "unbalanced_close" in codes(r)


def test_orphan_property_under_library_root(tmp_path):
    broken = GOOD_LIB.replace(
        '\t(symbol "R"', '\t(property "MPN" "X1"\n\t\t(at 0 0 0)\n\t)\n\t(symbol "R"', 1
    )
    r = check_lib(write(tmp_path, "o.kicad_sym", broken))
    assert not r["valid"]
    assert "orphan_fragment" in codes(r)


def test_duplicate_symbol_is_a_warning(tmp_path):
    dup = GOOD_LIB.replace("\n)\n", '\n\t(symbol "R"\n\t)\n)\n', 1)
    r = check_lib(write(tmp_path, "d.kicad_sym", dup))
    assert r["valid"]
    assert "duplicate_symbol" in codes(r)
    assert r["warningCount"] == 1


def test_unit_left_behind_by_a_rename_is_an_error(tmp_path):
    """Renaming "R" without renaming "R_0_1" makes the library unloadable."""
    renamed = GOOD_LIB.replace('(symbol "R"', '(symbol "R_SMALL"', 1)
    r = check_lib(write(tmp_path, "r.kicad_sym", renamed))
    assert not r["valid"]
    assert codes(r).count("unit_name_mismatch") == 2


def test_units_of_correctly_renamed_symbol_pass(tmp_path):
    renamed = GOOD_LIB.replace('"R', '"R_SMALL')
    r = check_lib(write(tmp_path, "r2.kicad_sym", renamed))
    assert r["valid"], r["issues"]


def test_wrong_root_form(tmp_path):
    r = check_lib(write(tmp_path, "w.kicad_sym", GOOD_SCH))
    assert not r["valid"]
    assert "wrong_root" in codes(r)


def test_library_not_found():
    r = validate_symbol_library({"libraryPath": "/no/such/lib.kicad_sym"})
    assert not r["success"]


def test_cli_is_skipped_when_not_requested(tmp_path):
    r = check_lib(write(tmp_path, "ok.kicad_sym", GOOD_LIB))
    assert r["kicadCli"]["ran"] is False
    assert r["valid"]


def test_message_names_the_first_error(tmp_path):
    r = check_lib(write(tmp_path, "b.kicad_sym", GOOD_LIB + ")\n"))
    assert "invalid" in r["message"]
    assert "line" in r["message"]


# --- schematic ------------------------------------------------------------- #


def test_valid_schematic(tmp_path):
    r = check_sch(write(tmp_path, "ok.kicad_sch", GOOD_SCH))
    assert r["valid"], r["issues"]
    assert r["componentCount"] == 1


def test_orphan_property_under_schematic_root(tmp_path):
    """What a truncated property rewrite leaves behind; eeschema will not open it."""
    broken = GOOD_SCH.replace(
        '\t(paper "A4")',
        '\t(paper "A4")\n\t(property "MANUFACTURER" "TDK"\n\t\t(at 0 0 0)\n\t)',
        1,
    )
    r = check_sch(write(tmp_path, "o.kicad_sch", broken))
    assert not r["valid"]
    assert "orphan_fragment" in codes(r)
    assert r["issues"][0]["line"] == 5


def test_orphan_effects_fragment(tmp_path):
    broken = GOOD_SCH.replace(
        '\t(paper "A4")', '\t(paper "A4")\n\t(effects (font (size 1.27 1.27)))', 1
    )
    r = check_sch(write(tmp_path, "e.kicad_sch", broken))
    assert not r["valid"]
    assert "orphan_fragment" in codes(r)


def test_nested_property_is_not_flagged(tmp_path):
    r = check_sch(write(tmp_path, "n.kicad_sch", GOOD_SCH))
    assert "orphan_fragment" not in codes(r)


def test_missing_lib_symbols_is_a_warning(tmp_path):
    stripped = GOOD_SCH.replace(
        '\t(lib_symbols\n\t\t(symbol "Device:R"\n'
        '\t\t\t(property "Reference" "R"\n'
        "\t\t\t\t(at 0 0 0)\n"
        "\t\t\t\t(effects (font (size 1.27 1.27)))\n"
        "\t\t\t)\n\t\t)\n\t)\n",
        "",
        1,
    )
    r = check_sch(write(tmp_path, "m.kicad_sch", stripped))
    assert r["valid"]
    assert "missing_lib_symbols" in codes(r)


def test_schematic_not_found():
    r = validate_schematic({"schematicPath": "/no/such/sheet.kicad_sch"})
    assert not r["success"]


def test_issues_are_ordered_by_position(tmp_path):
    broken = GOOD_SCH.replace(
        '\t(paper "A4")',
        '\t(paper "A4")\n\t(at 0 0 0)\n\t(property "A" "b"\n\t\t(at 0 0 0)\n\t)\n\t(hide yes)',
        1,
    )
    r = check_sch(write(tmp_path, "s.kicad_sch", broken))
    lines = [i["line"] for i in r["issues"]]
    assert lines == sorted(lines)
    assert len(lines) == 3


# --- kicad-cli integration ------------------------------------------------- #


@needs_cli
def test_cli_confirms_a_good_library(tmp_path):
    r = validate_symbol_library({"libraryPath": write(tmp_path, "ok.kicad_sym", GOOD_LIB)})
    assert r["kicadCli"]["ran"] is True
    assert r["kicadCli"]["ok"] is True
    assert r["valid"]


@needs_cli
def test_cli_does_not_modify_the_validated_file(tmp_path):
    """upgrade rewrites in place, so it has to run on a copy."""
    path = write(tmp_path, "ok.kicad_sym", GOOD_LIB)
    validate_symbol_library({"libraryPath": path})
    assert Path(path).read_text(encoding="utf-8") == GOOD_LIB


@needs_cli
def test_cli_agrees_a_stale_unit_name_is_fatal(tmp_path):
    """Evidence for grading unit_name_mismatch as an error rather than a warning.

    The file is perfectly balanced, so only KiCad itself can say whether it
    loads -- and it does not.
    """
    renamed = GOOD_LIB.replace('(symbol "R"', '(symbol "R_SMALL"', 1)
    r = validate_symbol_library({"libraryPath": write(tmp_path, "r.kicad_sym", renamed)})
    assert r["kicadCli"]["ran"] is True
    assert r["kicadCli"]["ok"] is False
    assert not r["valid"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
