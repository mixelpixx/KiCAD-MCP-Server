"""Tests for set_symbol_pin_type — bulk pin electrical-type edits in .kicad_sym."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.set_symbol_pin_type import (  # noqa: E402
    iter_library_pins,
    set_symbol_pin_type,
)


def pin(number, name, ptype="unspecified", style="line", extra=""):
    return f"""\t\t\t(pin {ptype} {style}
\t\t\t\t(at 0 {number}.0 0)
\t\t\t\t(length 2.54)
\t\t\t\t(name "{name}"
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(number "{number}"
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
{extra}\t\t\t)
"""


def symbol(name, units):
    body = ""
    for unit_name, pins in units:
        body += f'\t\t(symbol "{unit_name}"\n' + "".join(pins) + "\t\t)\n"
    return (
        f'\t(symbol "{name}"\n'
        "\t\t(pin_numbers hide)\n"
        "\t\t(pin_names\n\t\t\t(offset 0.254)\n\t\t)\n"
        f'\t\t(property "Reference" "U"\n\t\t\t(at 0 0 0)\n\t\t)\n'
        f"{body}\t)\n"
    )


LIB = (
    '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "kicad_symbol_editor")\n'
    + symbol(
        "SHIELD_CAN",
        [("SHIELD_CAN_1_1", [pin(1, "SH1"), pin(2, "SH2"), pin(3, "SH3")])],
    )
    + symbol(
        "OPAMP_DUAL",
        [
            ("OPAMP_DUAL_1_1", [pin(1, "OUT", "output"), pin(2, "IN-", "input")]),
            ("OPAMP_DUAL_2_1", [pin(5, "OUT2", "output"), pin(6, "IN2-", "input")]),
        ],
    )
    + ")\n"
)


@pytest.fixture
def lib(tmp_path):
    path = tmp_path / "test.kicad_sym"
    path.write_text(LIB, encoding="utf-8")
    return path


def run(lib, **kw):
    return set_symbol_pin_type({"libraryPath": str(lib), **kw})


def types_in(lib):
    """Every pin head in file order, as (type, style)."""
    text = lib.read_text(encoding="utf-8")
    out = []
    for p in iter_library_pins(text):
        head = text[p["offset"] : p["offset"] + 40].split("\n")[0]
        out.append(tuple(head.replace("(pin ", "").split()[:2]))
    return out


# --- walking --------------------------------------------------------------- #


def test_pins_are_attributed_to_their_top_level_symbol():
    found = list(iter_library_pins(LIB))
    assert {p["symbol"] for p in found} == {"SHIELD_CAN", "OPAMP_DUAL"}
    assert len(found) == 7


def test_unit_sub_symbol_is_reported_separately():
    units = {p["unit"] for p in iter_library_pins(LIB) if p["symbol"] == "OPAMP_DUAL"}
    assert units == {"OPAMP_DUAL_1_1", "OPAMP_DUAL_2_1"}


def test_pin_names_and_pin_numbers_settings_are_not_pins():
    """(pin_names ...) and (pin_numbers hide) share a prefix with (pin ...)."""
    assert all(p["unit"] is not None for p in iter_library_pins(LIB))
    assert len(list(iter_library_pins(LIB))) == 7


# --- the basic edit -------------------------------------------------------- #


def test_sets_the_type_of_every_pin_in_one_symbol(lib):
    r = run(lib, symbols=["SHIELD_CAN"], type="passive")
    assert r["success"]
    assert r["changeCount"] == 3
    assert types_in(lib)[:3] == [("passive", "line")] * 3


def test_other_symbols_are_left_alone(lib):
    run(lib, symbols=["SHIELD_CAN"], type="passive")
    assert types_in(lib)[3:] == [
        ("output", "line"),
        ("input", "line"),
        ("output", "line"),
        ("input", "line"),
    ]


def test_all_symbols_when_none_named(lib):
    r = run(lib, type="passive")
    assert r["changeCount"] == 7
    assert set(types_in(lib)) == {("passive", "line")}


def test_every_unit_of_a_multi_unit_symbol_is_covered(lib):
    r = run(lib, symbols=["OPAMP_DUAL"], type="passive")
    assert r["changeCount"] == 4
    assert {c["unit"] for c in r["changes"]} == {"OPAMP_DUAL_1_1", "OPAMP_DUAL_2_1"}


def test_style_can_be_changed_on_its_own(lib):
    r = run(lib, symbols=["SHIELD_CAN"], pinNumbers=["1"], style="inverted")
    assert r["changeCount"] == 1
    assert types_in(lib)[0] == ("unspecified", "inverted")


def test_type_and_style_together(lib):
    run(lib, symbols=["SHIELD_CAN"], pinNumbers=["1"], type="output", style="output_low")
    assert types_in(lib)[0] == ("output", "output_low")


def test_file_stays_parseable(lib):
    run(lib, type="passive")
    text = lib.read_text(encoding="utf-8")
    assert text.count("(") == text.count(")")
    assert text.endswith(")\n")


# --- filters --------------------------------------------------------------- #


def test_filter_by_pin_number(lib):
    r = run(lib, symbols=["SHIELD_CAN"], pinNumbers=["1", "3"], type="passive")
    assert {c["number"] for c in r["changes"]} == {"1", "3"}
    assert types_in(lib)[1] == ("unspecified", "line")


def test_filter_by_pin_name(lib):
    r = run(lib, pinNames=["IN-", "IN2-"], type="passive")
    assert {c["name"] for c in r["changes"]} == {"IN-", "IN2-"}


def test_filter_by_current_type(lib):
    r = run(lib, fromType="output", type="power_out")
    assert r["changeCount"] == 2
    assert all(c["fromType"] == "output" for c in r["changes"])


def test_from_type_that_matches_nothing_writes_nothing(lib):
    before = lib.read_text(encoding="utf-8")
    r = run(lib, fromType="open_collector", type="passive")
    assert r["success"]
    assert r["changeCount"] == 0
    assert lib.read_text(encoding="utf-8") == before


def test_a_misspelled_symbol_name_is_reported(lib):
    """Silently doing nothing is the failure mode a typo must not have."""
    r = run(lib, symbols=["SHIELD_CANN"], type="passive")
    assert r["changeCount"] == 0
    assert r["missingSymbols"] == ["SHIELD_CANN"]
    assert "not in this library" in r["message"]


def test_a_missing_pin_number_is_reported(lib):
    r = run(lib, symbols=["SHIELD_CAN"], pinNumbers=["1", "99"], type="passive")
    assert r["changeCount"] == 1
    assert r["missingPinNumbers"] == ["99"]


def test_pins_already_correct_are_counted_not_rewritten(lib):
    run(lib, type="passive")
    r = run(lib, type="passive")
    assert r["changeCount"] == 0
    assert r["alreadyCorrect"] == 7
    assert "already have that type" in r["message"]


# --- the cases that break sed ---------------------------------------------- #


def test_a_type_word_inside_a_string_is_not_touched(tmp_path):
    """A blind substitution rewrites the Description too, and the symbol name."""
    text = (
        "(kicad_symbol_lib\n"
        '\t(symbol "XCVR_bidirectional line driver"\n'
        '\t\t(property "Description" "pin bidirectional line buffer"\n'
        "\t\t\t(at 0 0 0)\n"
        "\t\t)\n"
        '\t\t(symbol "XCVR_1_1"\n' + pin(1, "A", "bidirectional") + "\t\t)\n"
        "\t)\n)\n"
    )
    path = tmp_path / "x.kicad_sym"
    path.write_text(text, encoding="utf-8")
    r = set_symbol_pin_type({"libraryPath": str(path), "type": "passive"})
    assert r["changeCount"] == 1
    out = path.read_text(encoding="utf-8")
    assert '"XCVR_bidirectional line driver"' in out
    assert '"pin bidirectional line buffer"' in out
    assert "(pin passive line" in out


def test_alternate_pin_functions_are_not_rewritten(tmp_path):
    """(alternate "SPI_CLK" output line) is a function of the pin, not the pin."""
    alt = '\t\t\t\t(alternate "SPI_CLK" output line)\n'
    text = (
        "(kicad_symbol_lib\n"
        '\t(symbol "MCU"\n\t\t(symbol "MCU_1_1"\n'
        + pin(3, "PA5", "bidirectional", extra=alt)
        + "\t\t)\n\t)\n)\n"
    )
    path = tmp_path / "x.kicad_sym"
    path.write_text(text, encoding="utf-8")
    r = set_symbol_pin_type({"libraryPath": str(path), "type": "passive"})
    assert r["changeCount"] == 1
    out = path.read_text(encoding="utf-8")
    assert '(alternate "SPI_CLK" output line)' in out
    assert "(pin passive line" in out


def test_pin_name_containing_parens(tmp_path):
    text = (
        "(kicad_symbol_lib\n"
        '\t(symbol "IC"\n\t\t(symbol "IC_1_1"\n' + pin(1, "OUT(A)", "output") + "\t\t)\n\t)\n)\n"
    )
    path = tmp_path / "x.kicad_sym"
    path.write_text(text, encoding="utf-8")
    r = set_symbol_pin_type({"libraryPath": str(path), "pinNames": ["OUT(A)"], "type": "passive"})
    assert r["changeCount"] == 1
    assert path.read_text(encoding="utf-8").count("(") == text.count("(")


def test_single_line_pin_form(tmp_path):
    """Hand-written and script-generated libraries are not always pretty-printed."""
    text = (
        "(kicad_symbol_lib\n"
        '\t(symbol "IC"\n\t\t(symbol "IC_1_1"\n'
        "\t\t\t(pin unspecified line (at 0 0 0) (length 2.54)"
        ' (name "A" (effects)) (number "1" (effects)))\n'
        "\t\t)\n\t)\n)\n"
    )
    path = tmp_path / "x.kicad_sym"
    path.write_text(text, encoding="utf-8")
    r = set_symbol_pin_type({"libraryPath": str(path), "type": "passive"})
    assert r["changeCount"] == 1
    assert r["changes"][0]["number"] == "1"
    assert "(pin passive line (at 0 0 0)" in path.read_text(encoding="utf-8")


def test_the_font_size_name_is_not_mistaken_for_the_pin_name(lib):
    r = run(lib, symbols=["SHIELD_CAN"], type="passive")
    assert {c["name"] for c in r["changes"]} == {"SH1", "SH2", "SH3"}


# --- guards ---------------------------------------------------------------- #


def test_an_unknown_type_is_refused_before_writing(lib):
    before = lib.read_text(encoding="utf-8")
    r = run(lib, type="power")
    assert not r["success"]
    assert "not a KiCad pin type" in r["message"]
    assert "power_in" in r["validTypes"]
    assert lib.read_text(encoding="utf-8") == before


def test_an_unknown_style_is_refused(lib):
    r = run(lib, type="passive", style="dotted")
    assert not r["success"]
    assert "graphic style" in r["message"]


def test_neither_type_nor_style_is_an_error(lib):
    r = run(lib, symbols=["SHIELD_CAN"])
    assert not r["success"]
    assert "Nothing to do" in r["message"]


def test_a_schematic_is_not_a_symbol_library(tmp_path):
    path = tmp_path / "board.kicad_sch"
    path.write_text('(kicad_sch\n\t(symbol\n\t\t(pin "1" (uuid "x"))\n\t)\n)\n', encoding="utf-8")
    r = set_symbol_pin_type({"libraryPath": str(path), "type": "passive"})
    assert not r["success"]
    assert "kicad_symbol_lib" in r["message"]


def test_missing_file(tmp_path):
    r = set_symbol_pin_type({"libraryPath": str(tmp_path / "nope.kicad_sym"), "type": "passive"})
    assert not r["success"]
    assert "not found" in r["message"]


def test_dry_run_reports_without_writing(lib):
    before = lib.read_text(encoding="utf-8")
    r = run(lib, type="passive", dryRun=True)
    assert r["dryRun"] is True
    assert r["changeCount"] == 7
    assert "Would change" in r["message"]
    assert lib.read_text(encoding="utf-8") == before


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
