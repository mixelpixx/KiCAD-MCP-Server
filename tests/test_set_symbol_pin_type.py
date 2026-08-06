"""Tests for set_symbol_pin_type — bulk pin electrical-type edits in .kicad_sym."""

import builtins
import io
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
import commands.set_symbol_pin_type as pin_type_module  # noqa: E402
from commands.set_symbol_pin_type import (  # noqa: E402
    _BACKUP_KEEP,
    _MAX_REPORTED_CHANGES,
    _PIN_HEAD,
    _edits_landed,
    _pin_structure,
    _prune_backups,
    _splice,
    iter_library_pins,
    iter_library_symbols,
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


# --- line endings ---------------------------------------------------------- #
#
# These read and write raw bytes on purpose. A test that writes with write_text
# and reads back with read_text cannot see a newline bug at all: both sides get
# the same platform translation, so the assertion passes on a file that has had
# every line ending rewritten.


@pytest.fixture
def lf_lib(tmp_path):
    path = tmp_path / "lf.kicad_sym"
    path.write_bytes(LIB.encode("utf-8"))
    return path


@pytest.fixture
def crlf_lib(tmp_path):
    path = tmp_path / "crlf.kicad_sym"
    path.write_bytes(LIB.replace("\n", "\r\n").encode("utf-8"))
    return path


def test_an_lf_library_is_not_converted_to_crlf(lf_lib):
    """On Windows a pathlib default write turns every line ending into CRLF."""
    r = run(lf_lib, symbols=["SHIELD_CAN"], type="passive")
    assert r["changeCount"] == 3
    raw = lf_lib.read_bytes()
    assert b"\r\n" not in raw


def test_a_crlf_library_is_not_converted_to_lf(crlf_lib):
    before = crlf_lib.read_bytes()
    r = run(crlf_lib, symbols=["SHIELD_CAN"], type="passive")
    assert r["changeCount"] == 3
    raw = crlf_lib.read_bytes()
    assert raw.count(b"\r\n") == before.count(b"\r\n")
    assert b"(pin passive line" in raw


def test_a_three_pin_edit_touches_only_three_lines(lf_lib):
    """The point of preserving newlines: the diff stays the size of the edit."""
    before = lf_lib.read_bytes().split(b"\n")
    run(lf_lib, symbols=["SHIELD_CAN"], type="passive")
    after = lf_lib.read_bytes().split(b"\n")
    assert len(before) == len(after)
    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 3
    assert all(b"(pin passive line" in after[i] for i in differing)


def test_a_second_pass_over_an_lf_library_is_byte_identical(lf_lib):
    """Idempotency at the byte level, not just at the pin-type level."""
    run(lf_lib, type="passive")
    once = lf_lib.read_bytes()
    r = run(lf_lib, type="passive")
    assert r["changeCount"] == 0
    assert r["alreadyCorrect"] == 7
    assert lf_lib.read_bytes() == once


# --- the write is atomic --------------------------------------------------- #


def test_a_failed_write_leaves_the_library_intact(lib, monkeypatch):
    """A truncating write empties the library before it can fail; this must not."""
    before = lib.read_bytes()

    def refuse(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", refuse)
    r = run(lib, type="passive")
    assert not r["success"]
    assert "unchanged" in r["message"]
    assert lib.read_bytes() == before


class _FailingWrite:
    """A real file handle -- so a real truncation happens -- that cannot write."""

    def __init__(self, fh):
        self._fh = fh

    def write(self, data):
        raise OSError(28, "No space left on device")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()
        return False


def test_no_write_failure_can_truncate_the_library(lib, monkeypatch):
    """Injected at the file layer, so it holds however the write is implemented.

    Opening the library itself for writing truncates it at open time, leaving
    nothing to restore when the write then fails -- the failure that reports
    "could not write" about a file it has already emptied.
    """
    before = lib.read_bytes()
    real_open = io.open

    def opener(file, mode="r", *args, **kwargs):
        fh = real_open(file, mode, *args, **kwargs)
        return _FailingWrite(fh) if "w" in mode else fh

    monkeypatch.setattr(io, "open", opener)
    monkeypatch.setattr(builtins, "open", opener)
    r = run(lib, type="passive")
    monkeypatch.undo()

    assert not r["success"]
    assert lib.read_bytes() == before


def scratch_files(lib):
    """Anything left beside the library that is not the library or a backup."""
    return sorted(p.name for p in lib.parent.iterdir() if p.name not in (lib.name, ".mcp-backups"))


def test_a_failed_write_leaves_no_temporary_file(lib, monkeypatch):
    def refuse(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", refuse)
    run(lib, type="passive")
    assert scratch_files(lib) == []


def test_a_successful_write_leaves_no_temporary_file(lib):
    run(lib, type="passive")
    assert scratch_files(lib) == []


# --- the library is copied before it is rewritten -------------------------- #
#
# Atomicity and the backup cover different failures: the rename means a crash
# cannot truncate the library, but an edit that succeeds and was not what the
# caller meant -- omitting `symbols`, so every pin in the library is flattened
# -- is exactly what this tool makes easy, and it needs an undo.


def backups(lib):
    return sorted((lib.parent / ".mcp-backups").iterdir())


def test_the_library_is_copied_to_mcp_backups_before_editing(lib):
    before = lib.read_bytes()
    r = run(lib, type="passive")
    assert r["changeCount"] == 7
    copies = backups(lib)
    assert len(copies) == 1
    assert copies[0].name.startswith("test.kicad_sym.")
    assert copies[0].read_bytes() == before
    assert lib.read_bytes() != before


def test_the_backup_path_is_reported(lib):
    r = run(lib, type="passive")
    assert r["backupPath"] == str(backups(lib)[0])


def test_a_dry_run_writes_no_backup(lib):
    r = run(lib, type="passive", dryRun=True)
    assert r["changeCount"] == 7
    assert r["backupPath"] is None
    assert not (lib.parent / ".mcp-backups").exists()


def test_no_backup_is_written_when_nothing_changes(lib):
    run(lib, type="passive")
    assert len(backups(lib)) == 1
    r = run(lib, type="passive")
    assert r["changeCount"] == 0
    assert r["backupPath"] is None
    assert len(backups(lib)) == 1


def test_a_failed_backup_does_not_block_the_edit(lib, monkeypatch):
    """A read-only library directory must not make the library uneditable."""

    def refuse(src, dst):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(shutil, "copy2", refuse)
    r = run(lib, type="passive")
    assert r["success"]
    assert r["changeCount"] == 7
    assert r["backupPath"] is None
    assert types_in(lib) == [("passive", "line")] * 7


def test_backups_rotate(tmp_path):
    """Repeated bulk edits must not fill the directory with copies."""
    backup_dir = tmp_path / ".mcp-backups"
    backup_dir.mkdir()
    for i in range(_BACKUP_KEEP + 5):
        (backup_dir / f"x.kicad_sym.{i:04d}").write_text("old", encoding="utf-8")
    (backup_dir / "other.kicad_sym.0001").write_text("keep", encoding="utf-8")

    _prune_backups(backup_dir, "x.kicad_sym")

    remaining = sorted(p.name for p in backup_dir.iterdir())
    assert "other.kicad_sym.0001" in remaining
    assert len([n for n in remaining if n.startswith("x.kicad_sym.")]) == _BACKUP_KEEP


# --- fromType is validated like type --------------------------------------- #


def test_a_misspelled_from_type_is_refused(lib):
    """Two transposed letters must not be a silent success that changes nothing."""
    before = lib.read_bytes()
    r = run(lib, fromType="unspecfied", type="passive")
    assert not r["success"]
    assert "not a KiCad pin type" in r["message"]
    assert "unspecified" in r["validTypes"]
    assert lib.read_bytes() == before


def test_a_valid_from_type_is_still_accepted(lib):
    r = run(lib, fromType="unspecified", type="passive")
    assert r["success"]
    assert r["changeCount"] == 3


# --- derived symbols ------------------------------------------------------- #

DERIVED_LIB = (
    '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "kicad_symbol_editor")\n'
    + symbol("R_Small", [("R_Small_0_1", [pin(1, "~"), pin(2, "~")])])
    # A derived symbol: no pins of its own, they come from R_Small.
    + '\t(symbol "R_Small_US"\n'
    + '\t\t(extends "R_Small")\n'
    + '\t\t(property "Reference" "R"\n\t\t\t(at 0 0 0)\n\t\t)\n'
    + "\t)\n"
    # A graphics-only symbol: pinless, but inherits from nothing.
    + '\t(symbol "LOGO"\n'
    + '\t\t(symbol "LOGO_0_1"\n'
    + "\t\t\t(rectangle\n\t\t\t\t(start 0 0)\n\t\t\t\t(end 1 1)\n\t\t\t)\n"
    + "\t\t)\n"
    + "\t)\n"
    + ")\n"
)


@pytest.fixture
def derived_lib(tmp_path):
    path = tmp_path / "derived.kicad_sym"
    path.write_bytes(DERIVED_LIB.encode("utf-8"))
    return path


def test_top_level_symbols_are_found_structurally_not_from_pins():
    found = {s["name"]: s["extends"] for s in iter_library_symbols(DERIVED_LIB)}
    assert found == {"R_Small": None, "R_Small_US": "R_Small", "LOGO": None}


def test_a_derived_symbol_is_not_reported_as_a_missing_symbol(derived_lib):
    """It has no pins by design, so learning names from pins calls it a typo."""
    r = run(derived_lib, symbols=["R_Small_US"], type="passive")
    assert r["missingSymbols"] == []
    assert r["symbolsWithoutOwnPins"] == ["R_Small_US"]
    assert "extends R_Small" in r["message"]
    assert "not in this library" not in r["message"]


def test_a_pinless_symbol_that_extends_nothing_is_distinguished(derived_lib):
    r = run(derived_lib, symbols=["LOGO"], type="passive")
    assert r["missingSymbols"] == []
    assert r["symbolsWithoutOwnPins"] == ["LOGO"]
    assert "extends" not in r["message"]


def test_a_name_absent_from_the_library_is_still_reported_missing(derived_lib):
    """The distinction only helps if a real typo still reads as a typo."""
    r = run(derived_lib, symbols=["R_Smalll_US"], type="passive")
    assert r["missingSymbols"] == ["R_Smalll_US"]
    assert r["symbolsWithoutOwnPins"] == []
    assert "not in this library" in r["message"]


def test_the_parent_of_a_derived_symbol_is_editable(derived_lib):
    r = run(derived_lib, symbols=["R_Small"], type="passive")
    assert r["changeCount"] == 2
    assert r["symbolsWithoutOwnPins"] == []


# --- missing pin names ----------------------------------------------------- #


def test_a_misspelled_pin_name_is_reported(lib):
    """Names are free-form strings, so they are the likeliest thing to mistype."""
    r = run(lib, pinNames=["NOSUCHPIN"], type="passive")
    assert r["changeCount"] == 0
    assert r["missingPinNames"] == ["NOSUCHPIN"]
    assert "NOSUCHPIN" in r["message"]


def test_only_the_absent_pin_name_is_reported(lib):
    r = run(lib, pinNames=["IN-", "VDDA"], type="passive")
    assert r["changeCount"] == 1
    assert r["missingPinNames"] == ["VDDA"]


def test_a_matched_pin_name_reports_nothing_missing(lib):
    r = run(lib, pinNames=["SH1"], type="passive")
    assert r["missingPinNames"] == []


# --- the response is bounded ----------------------------------------------- #


def big_lib(symbols, pins_per_symbol):
    body = ""
    for s in range(symbols):
        entries = [pin(n, f"P{n}") for n in range(1, pins_per_symbol + 1)]
        body += symbol(f"IC{s}", [(f"IC{s}_1_1", entries)])
    return "(kicad_symbol_lib\n\t(version 20241209)\n" + body + ")\n"


def test_a_bulk_pass_caps_the_per_pin_change_list(tmp_path):
    """This is an MCP tool: the response is spent from the caller's context."""
    path = tmp_path / "big.kicad_sym"
    path.write_bytes(big_lib(3, 100).encode("utf-8"))
    r = set_symbol_pin_type({"libraryPath": str(path), "type": "passive"})
    assert r["changeCount"] == 300
    assert len(r["changes"]) == _MAX_REPORTED_CHANGES
    assert r["changesTruncated"] is True


def test_the_symbol_summary_survives_truncation(tmp_path):
    """symbolsChanged plus the counts are what the caller normally needs."""
    path = tmp_path / "big.kicad_sym"
    path.write_bytes(big_lib(3, 100).encode("utf-8"))
    r = set_symbol_pin_type({"libraryPath": str(path), "type": "passive"})
    assert r["symbolsChanged"] == ["IC0", "IC1", "IC2"]
    assert types_in(path) == [("passive", "line")] * 300


def test_an_edit_below_the_cap_is_not_truncated(lib):
    r = run(lib, type="passive")
    assert r["changeCount"] == 7
    assert len(r["changes"]) == 7
    assert r["changesTruncated"] is False


# --- the post-write structural check --------------------------------------- #
#
# A paren count cannot detect either of these: the tool's replacement never
# contains a paren, and moving one leaves the counts equal.


def test_a_misplaced_paren_changes_the_pin_structure():
    """Swapping a ')' with the '(' after it leaves both counts equal."""
    broken = LIB.replace(
        "\t\t\t)\n\t\t\t(pin unspecified line",
        "\t\t\t(\n\t\t\t)pin unspecified line",
        1,
    )
    assert broken != LIB
    assert broken.count("(") == LIB.count("(")
    assert broken.count(")") == LIB.count(")")
    assert _pin_structure(broken) != _pin_structure(LIB)


def test_splicing_in_the_wrong_order_is_detected():
    """Applied front-to-back the offsets slide under each other."""
    edits = [
        (m["offset"], m["offset"] + len("(pin unspecified line"), "(pin passive line")
        for m in iter_library_pins(LIB)
        if LIB.startswith("(pin unspecified line", m["offset"])
    ]
    assert len(edits) == 3

    forward = LIB
    for start, stop, replacement in edits:
        forward = forward[:start] + replacement + forward[stop:]
    assert not _edits_landed(forward, edits)

    backward = LIB
    for start, stop, replacement in reversed(edits):
        backward = backward[:start] + replacement + backward[stop:]
    assert _edits_landed(backward, edits)


def test_splicing_once_matches_a_naive_per_edit_rewrite():
    """The fast path must produce exactly what slicing per edit produced."""
    edits = [
        (m["offset"], m["offset"] + len("(pin unspecified line"), "(pin passive line")
        for m in iter_library_pins(LIB)
        if LIB.startswith("(pin unspecified line", m["offset"])
    ]
    naive = LIB
    for start, stop, replacement in reversed(edits):
        naive = naive[:start] + replacement + naive[stop:]
    assert _splice(LIB, edits) == naive


def test_the_file_is_not_recopied_once_per_edit():
    """``text[:start] + new + text[stop:]`` per edit costs pins times file size.

    On KiCad's own 16 MB MCU_ST_STM32H7 (28191 pins) that is ~440 GB of copying
    and a 169 s call, on precisely the bulk edit this tool exists for. The
    fixture below is the same shape at a size a test can afford: ~2.5 MB and
    12000 pins, which takes a few milliseconds spliced once and ~12 seconds
    spliced per edit.
    """
    text = big_lib(300, 40)
    edits = [(m.start(), m.end(), "(pin passive line") for m in _PIN_HEAD.finditer(text)]
    assert len(edits) == 12000

    started = time.perf_counter()
    updated = _splice(text, edits)
    elapsed = time.perf_counter() - started

    assert _edits_landed(updated, edits)
    assert updated.count("(pin passive line") == 12000
    assert elapsed < 2.0, f"splicing {len(edits)} edits took {elapsed:.1f}s"


def test_a_corrupted_splice_is_refused_and_nothing_is_written(lib, monkeypatch):
    """The check is live, and it refuses before the library is touched at all.

    Splicing the file in one pass requires the offsets to arrive in ascending
    order; fed them backwards, the replacements land in neighbouring tokens.
    """
    before = lib.read_bytes()
    ascending = pin_type_module.iter_library_pins
    monkeypatch.setattr(
        pin_type_module,
        "iter_library_pins",
        lambda text: iter(list(ascending(text))[::-1]),
    )
    r = run(lib, type="passive")
    monkeypatch.undo()

    assert not r["success"]
    assert "changed the file structure" in r["message"]
    assert lib.read_bytes() == before
    assert not (lib.parent / ".mcp-backups").exists()


# --- pin heads that are not pretty-printed --------------------------------- #


def test_a_space_after_the_open_paren_is_still_a_pin(tmp_path):
    """Silently dropping it is worse than either editing it or refusing to."""
    text = (
        "(kicad_symbol_lib\n"
        '\t(symbol "IC"\n\t\t(symbol "IC_1_1"\n'
        '\t\t\t( pin unspecified line (at 0 0 0) (name "A") (number "1"))\n'
        "\t\t)\n\t)\n)\n"
    )
    path = tmp_path / "x.kicad_sym"
    path.write_bytes(text.encode("utf-8"))
    r = set_symbol_pin_type({"libraryPath": str(path), "type": "passive"})
    assert r["changeCount"] == 1
    assert r["changes"][0]["number"] == "1"
    assert "(pin passive line (at 0 0 0)" in path.read_text(encoding="utf-8")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
