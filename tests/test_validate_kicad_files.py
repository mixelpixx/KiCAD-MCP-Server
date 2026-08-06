"""Tests for validate_schematic / validate_symbol_library."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
import commands.validate_kicad_files as vkf  # noqa: E402
from commands.validate_kicad_files import (  # noqa: E402
    _indent_divergence,
    _scan,
    validate_schematic,
    validate_symbol_library,
)
from utils.kicad_cli import resolve_kicad_cli  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

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


# Byte-for-byte what main's add_symbol_property produced when asked to update an
# existing "Description" property on GOOD_LIB above (hide=True). Its removal
# regex, `\(property "X"\s+"[^"]*".*?\)` non-greedy, stops at the ')' closing
# (at 0 0 0) rather than the one closing the property, so the tail of the old
# block survives; and it splices with content[:start] + block + content[end+1:]
# where block excludes the symbol's own ')', dropping one. The two cancel: the
# file stays balanced (27 '(' and 27 ')'), which is why nothing that counts
# parens can see it. Lines 13-14 are the damage: the leftover (effects ...) now
# sits directly inside (symbol "R"), whose ')' arrives a level early, promoting
# both units to the top level.
TRUNCATED_REWRITE = """(kicad_symbol_lib
\t(version 20231120)
\t(generator "eeschema")
\t(symbol "R"
\t\t(property "Reference" "R"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Description" "Resistor (thick film) 1%" (at 0 0 0)
\t\t\t(hide yes)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(symbol "R_0_1"
\t\t\t(rectangle (start -1 -2.5) (end 1 2.5))
\t\t)
\t\t(symbol "R_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 1.27))
\t\t)
\t
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
    # Anchored on '(symbol "R': an unanchored '"R' -> '"R_SMALL' also rewrites
    # "Reference" to "R_SMALLeference" and mangles the description, so the test
    # would pass on an input it does not claim to be using.
    renamed = GOOD_LIB.replace('(symbol "R', '(symbol "R_SMALL')
    assert '"Reference"' in renamed
    assert '"Resistor (thick film) 1%"' in renamed
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


# --- the truncated property rewrite, which is what all of this is for -------- #


def test_truncated_rewrite_is_not_reported_as_valid(tmp_path):
    """The corruption this module exists to catch used to pass the structure scan.

    Balanced parens, so nothing counts its way to the fault; the orphan check
    only looked at direct children of the root, and the tail lands inside the
    symbol instead.
    """
    r = check_lib(write(tmp_path, "t.kicad_sym", TRUNCATED_REWRITE))
    assert not r["valid"], r
    assert r["errorCount"] == 2


def test_truncated_rewrite_names_the_line_that_broke(tmp_path):
    """Saying WHERE is the whole point: kicad-cli only says 'Unable to load'."""
    r = check_lib(write(tmp_path, "t.kicad_sym", TRUNCATED_REWRITE))
    assert "line 13" in r["message"]
    assert [i["line"] for i in r["issues"] if i["severity"] == "error"] == [13, 13]


def test_orphan_fragment_left_inside_a_symbol_is_an_error(tmp_path):
    r = check_lib(write(tmp_path, "t.kicad_sym", TRUNCATED_REWRITE))
    orphan = next(i for i in r["issues"] if i["code"] == "orphan_fragment")
    assert orphan["line"] == 13
    assert "(symbol ...)" in orphan["message"]


def test_indent_hint_runs_when_the_scan_found_nothing(tmp_path):
    """A dropped paren offset by a spare one leaves _scan with zero issues."""
    _, issues = _scan(TRUNCATED_REWRITE)
    assert issues == [], "premise: the paren scan itself sees nothing here"
    r = check_lib(write(tmp_path, "t.kicad_sym", TRUNCATED_REWRITE))
    hint = next(i for i in r["issues"] if i["code"] == "indent_depth_mismatch")
    assert hint["line"] == 13


def test_units_promoted_to_the_top_level_are_reported(tmp_path):
    """Balanced, and kicad-cli 10.0.4 loads it (exit 0), so this is a warning.

    KiCad reads each escaped unit as a symbol of its own, which is where the
    inflated symbolCount comes from.
    """
    r = check_lib(write(tmp_path, "t.kicad_sym", TRUNCATED_REWRITE))
    escaped = [i for i in r["issues"] if i["code"] == "escaped_unit"]
    assert [i["line"] for i in escaped] == [15, 18]
    assert all(i["severity"] == "warning" for i in escaped)
    assert r["symbolCount"] == 3, "R plus the two units KiCad now sees as symbols"


def test_at_directly_inside_a_symbol_is_an_error(tmp_path):
    """Balanced, and kicad-cli 10.0.4 answers 'Unable to load library'."""
    broken = GOOD_LIB.replace('\t\t(symbol "R_0_1"', '\t\t(at 0 0 0)\n\t\t(symbol "R_0_1"', 1)
    r = check_lib(write(tmp_path, "at.kicad_sym", broken))
    assert not r["valid"]
    assert "orphan_fragment" in codes(r)


def test_at_inside_a_placed_schematic_symbol_stays_legal(tmp_path):
    """.kicad_sch is a different format: (at ...) IS a child of (symbol ...) there.

    GOOD_SCH already relies on it, so widening the .kicad_sym rule must not leak
    across.
    """
    assert "\t\t(at 100 100 0)" in GOOD_SCH
    r = check_sch(write(tmp_path, "ok.kicad_sch", GOOD_SCH))
    assert r["valid"], r["issues"]
    assert "orphan_fragment" not in codes(r)


# --- localisation must not blame an innocent line ---------------------------- #


def test_unindented_line_is_not_blamed(tmp_path):
    """A valid line at column 1 in a tab-indented file is not a paren fault.

    The guard skipped space-indented lines but not zero-indented ones, because
    "" is falsy, so this file was reported broken at line 2.
    """
    text = '(kicad_symbol_lib\n(version 20231120)\n\t(symbol "R"\n\t\t(pin)\n\t)\n)\n'
    nodes, issues = _scan(text)
    assert issues == [], "premise: the file is structurally perfect"
    assert _indent_divergence(text, nodes) is None
    r = check_lib(write(tmp_path, "flat.kicad_sym", text))
    assert r["valid"], r["issues"]


def test_unindented_line_does_not_outrank_the_real_break(tmp_path):
    """_finish sorts by line, so a bogus line-2 hint would headline the report."""
    text = '(kicad_symbol_lib\n(version 20231120)\n\t(symbol "R"\n\t\t\t(pin)\n\t)\n)\n'
    nodes, _ = _scan(text)
    hint = _indent_divergence(text, nodes)
    assert hint is not None
    assert hint["line"] == 4, "the over-indented (pin), not the un-indented (version)"


def test_indent_hint_still_ignores_space_indented_files():
    spaced = '(kicad_symbol_lib\n    (symbol "R"\n        (pin)\n    )\n)\n'
    nodes, _ = _scan(spaced)
    assert _indent_divergence(spaced, nodes) is None


def test_root_at_column_one_is_still_checked():
    """The depth-0 root has no prefix either; skipping on "" would exempt it."""
    nested = '(kicad_symbol_lib\n\t(symbol "R"\n\t\t(pin)\n\t)\n)\n'
    nodes, _ = _scan(nested)
    assert _indent_divergence(nested, nodes) is None


# --- scanner details -------------------------------------------------------- #


def test_scan_reports_quoted_trailing_content():
    """The '"' branch consumed the string and continued past the check."""
    _, issues = _scan('(kicad_symbol_lib)\n"junk"\n')
    assert [i["code"] for i in issues] == ["trailing_content"]
    assert issues[0]["line"] == 2


def test_escaped_newline_does_not_shift_later_line_numbers():
    """`\\` before a newline was skipped without counting the line it ate."""
    text = '(kicad_symbol_lib\n\t(symbol "A\\\nB")\n)\n)\n'
    assert text.split("\n")[4] == ")", "premise: the spare ')' is on line 5"
    _, issues = _scan(text)
    assert [i["code"] for i in issues] == ["unbalanced_close"]
    assert issues[0]["line"] == 5


# --- kicad-cli is run on the file itself, not on its neighbours -------------- #


def test_cli_copy_leaves_unrelated_siblings_behind(tmp_path, monkeypatch):
    """`sch upgrade` upgrades only the file named, so siblings buy nothing.

    Verified against kicad-cli 10.0.4: a root sheet whose sub-sheet is missing
    from the directory entirely still returns 0.
    """
    target = tmp_path / "sheet.kicad_sch"
    target.write_text(GOOD_SCH, encoding="utf-8")
    (tmp_path / "unrelated.kicad_sch").write_text(GOOD_SCH, encoding="utf-8")
    (tmp_path / "other_project").mkdir()
    (tmp_path / "other_project" / "deep.kicad_sch").write_text(GOOD_SCH, encoding="utf-8")

    copied = {}

    def spy(subcommand, work_dir, cli_target):
        copied["names"] = sorted(p.name for p in Path(work_dir).rglob("*"))
        return {"ran": True, "ok": True, "exitCode": 0, "output": ""}

    monkeypatch.setattr(vkf, "_cli_check", spy)
    validate_schematic({"schematicPath": str(target), "runKicadCli": True})
    assert copied["names"] == ["sheet.kicad_sch"]


def test_unrelated_sibling_cannot_disable_the_cli_check(tmp_path, monkeypatch):
    """Tripping the size cap skips the authoritative check and reports "valid".

    Letting an unrelated file in the same directory decide that is the worst
    version of this bug, so the cap must only ever see the file being validated.
    """
    monkeypatch.setattr(vkf, "_MAX_CLI_COPY_BYTES", 4096)
    target = tmp_path / "sheet.kicad_sch"
    target.write_text(GOOD_SCH, encoding="utf-8")
    assert target.stat().st_size < 4096
    (tmp_path / "huge.kicad_sch").write_text("x" * 8192, encoding="utf-8")

    monkeypatch.setattr(
        vkf,
        "_cli_check",
        lambda *a, **k: {"ran": True, "ok": True, "exitCode": 0, "output": ""},
    )
    r = validate_schematic({"schematicPath": str(target), "runKicadCli": True})
    assert r["kicadCli"]["ran"] is True, r["kicadCli"]


def test_oversized_target_still_skips_the_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(vkf, "_MAX_CLI_COPY_BYTES", 64)
    target = tmp_path / "sheet.kicad_sch"
    target.write_text(GOOD_SCH, encoding="utf-8")
    r = validate_schematic({"schematicPath": str(target), "runKicadCli": True})
    assert r["kicadCli"]["ran"] is False
    assert "too large" in r["kicadCli"]["reason"]


def test_run_kicad_cli_honours_a_string_false(tmp_path):
    """JSON has a real boolean; a script calling this dispatch directly may not.

    "false" is a non-empty string, so plain truthiness ran the CLI the caller
    asked it to skip.
    """
    path = write(tmp_path, "ok.kicad_sym", GOOD_LIB)
    for value in ("false", "False", "FALSE", "no", "0", "off", ""):
        r = validate_symbol_library({"libraryPath": path, "runKicadCli": value})
        assert r["kicadCli"] == {"ran": False, "reason": "not requested"}, value
    # "was the CLI attempted", not "did it run": this suite must pass on a
    # machine with no KiCad, where the attempt reports "kicad-cli not found".
    for value in ("true", "yes", "1"):
        r = validate_symbol_library({"libraryPath": path, "runKicadCli": value})
        assert r["kicadCli"].get("reason") != "not requested", value


# --- no false positives on real files ---------------------------------------- #


def test_repo_symbol_fixture_is_clean():
    r = check_lib(str(FIXTURES / "Simulation_SPICE_minimal.kicad_sym"))
    assert r["valid"], r["issues"]
    assert r["issues"] == []


def test_repo_schematic_fixture_is_clean():
    r = check_sch(str(FIXTURES / "canonical_schematic.kicad_sch"))
    assert r["valid"], r["issues"]
    assert r["issues"] == []


def test_minified_single_line_library_is_clean(tmp_path):
    """No newlines and no indentation at all: every check must stay quiet."""
    minified = " ".join(GOOD_LIB.split()) + "\n"
    assert "\n" not in minified.strip()
    r = check_lib(write(tmp_path, "min.kicad_sym", minified))
    assert r["valid"], r["issues"]
    assert r["issues"] == []
    assert r["symbolCount"] == 1


def test_space_indented_library_is_clean(tmp_path):
    """The one-tab-per-level rule says nothing here, so it must not guess."""
    spaced = "\n".join(
        "    " * (len(ln) - len(ln.lstrip("\t"))) + ln.lstrip("\t") for ln in GOOD_LIB.split("\n")
    )
    assert "\t" not in spaced
    r = check_lib(write(tmp_path, "sp.kicad_sym", spaced))
    assert r["valid"], r["issues"]
    assert r["issues"] == []


def test_repo_symbol_fixture_survives_reindentation(tmp_path):
    real = (FIXTURES / "Simulation_SPICE_minimal.kicad_sym").read_text(encoding="utf-8")
    spaced = "\n".join(
        "  " * (len(ln) - len(ln.lstrip("\t"))) + ln.lstrip("\t") for ln in real.split("\n")
    )
    assert "\t" not in spaced
    r = check_lib(write(tmp_path, "sp.kicad_sym", spaced))
    assert r["valid"], r["issues"]
    r2 = check_lib(write(tmp_path, "min.kicad_sym", " ".join(real.split()) + "\n"))
    assert r2["valid"], r2["issues"]


# --- kicad-cli integration ------------------------------------------------- #


@needs_cli
def test_cli_agrees_the_truncated_rewrite_is_broken(tmp_path):
    """Evidence that the file the structure scan used to pass really is broken."""
    r = validate_symbol_library({"libraryPath": write(tmp_path, "t.kicad_sym", TRUNCATED_REWRITE)})
    assert r["kicadCli"]["ran"] is True
    assert r["kicadCli"]["ok"] is False
    assert not r["valid"]
    # The point of the module: a line number, not just "Unable to load library".
    assert "line 13" in r["message"]


@needs_cli
def test_cli_agrees_promoted_units_still_load(tmp_path):
    """Why escaped_unit is a warning: the library loads, it just loads wrong."""
    hoisted = GOOD_LIB.replace(
        '\t\t(symbol "R_0_1"\n\t\t\t(rectangle (start -1 -2.5) (end 1 2.5))\n\t\t)\n',
        "",
        1,
    ).replace(
        "\n)\n",
        '\n\t(symbol "R_0_1"\n\t\t(rectangle (start -1 -2.5) (end 1 2.5))\n\t)\n)\n',
        1,
    )
    r = validate_symbol_library({"libraryPath": write(tmp_path, "h.kicad_sym", hoisted)})
    assert r["kicadCli"]["ran"] is True
    assert r["kicadCli"]["ok"] is True, r["kicadCli"]
    assert "escaped_unit" in codes(r)
    assert r["valid"], r["issues"]


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
