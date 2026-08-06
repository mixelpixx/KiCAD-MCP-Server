"""Tests for backannotate_footprints — PCB footprint assignments -> schematic."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.backannotate_footprints import (  # noqa: E402
    backannotate_footprints,
    read_board_footprints,
)


def footprint(reference, lib_id, extra=""):
    return f"""\t(footprint "{lib_id}"
\t\t(layer "F.Cu")
\t\t(property "Reference" "{reference}"
\t\t\t(at 0 1.25 0)
\t\t\t(effects (font (size 1 1)))
\t\t)
\t\t(property "Value" "x"
\t\t\t(at 0 0 0)
\t\t\t(effects (font (size 1 1)))
\t\t){extra}
\t)
"""


BOARD = (
    '(kicad_pcb\n\t(version 20240108)\n\t(generator "pcbnew")\n'
    + footprint("R1", "FOG_components:0402")
    + footprint("C1", "FOG_components:0603")
    + footprint("J2", "FOG_components:HRS_U.FL-R-SMT-1(10)")
    + footprint("U1", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
    + ")\n"
)


def instance(reference, value, footprint_value, unit=1):
    field = (
        ""
        if footprint_value is None
        else f"""\t\t(property "Footprint" "{footprint_value}"
\t\t\t(at 5 6 0)
\t\t\t(hide yes)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
"""
    )
    return f"""\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 100 100 0)
\t\t(unit {unit})
\t\t(uuid "uuid-{reference}-{unit}")
\t\t(property "Reference" "{reference}"
\t\t\t(at 1 2 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Value" "{value}"
\t\t\t(at 3 4 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
{field}\t)
"""


LIB_SYMBOLS = """\t(lib_symbols
\t\t(symbol "Device:R"
\t\t\t(property "Footprint" "STALE:should_not_be_touched"
\t\t\t\t(at 0 0 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t)
\t)
"""

SCH = (
    '(kicad_sch\n\t(version 20231120)\n\t(generator "eeschema")\n'
    + LIB_SYMBOLS
    + instance("R1", "10K", "eagle_import:0402HF")
    + instance("C1", "100n", "FOG_components:0603")
    + instance("J2", "conn", "wrong:thing")
    + instance("U1", "opamp", None)
    + instance("#GND1", "GND", "")
    + instance("R99", "1K", "orphan:fp")
    + ")\n"
)


def balance(text):
    depth, in_string, i = 0, False, 0
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
def project(tmp_path):
    (tmp_path / "b.kicad_pcb").write_text(BOARD, encoding="utf-8")
    (tmp_path / "b.kicad_sch").write_text(SCH, encoding="utf-8")
    return tmp_path


def run(project, **kw):
    return backannotate_footprints({"boardPath": str(project / "b.kicad_pcb"), **kw})


def sch_text(project):
    return (project / "b.kicad_sch").read_text(encoding="utf-8")


def by_reference(result):
    return {c["reference"]: c for c in result["changes"]}


# --- board side ------------------------------------------------------------ #


def test_read_board_footprints():
    placed = read_board_footprints(BOARD)
    assert placed["R1"] == "FOG_components:0402"
    assert placed["U1"] == "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"


def test_board_footprint_name_containing_parens():
    """HRS_U.FL-R-SMT-1(10) is a real part; naive paren counting loses it."""
    assert read_board_footprints(BOARD)["J2"] == "FOG_components:HRS_U.FL-R-SMT-1(10)"


def test_board_with_legacy_fp_text_reference():
    legacy = (
        "(kicad_pcb\n"
        '\t(footprint "Lib:FP"\n'
        '\t\t(fp_text reference "R7" (at 0 0))\n'
        "\t)\n)\n"
    )
    assert read_board_footprints(legacy) == {"R7": "Lib:FP"}


def test_board_indentation_is_ignored():
    """KiCad writes board files whose indentation does not match nesting."""
    ragged = BOARD.replace(
        '\t(footprint "FOG_components:0402"', '\t\t\t(footprint "FOG_components:0402"'
    )
    assert read_board_footprints(ragged)["R1"] == "FOG_components:0402"


# --- schematic side -------------------------------------------------------- #


def test_updates_a_mismatched_footprint(project):
    r = run(project)
    assert r["success"]
    assert by_reference(r)["R1"]["from"] == "eagle_import:0402HF"
    assert by_reference(r)["R1"]["to"] == "FOG_components:0402"
    assert '"Footprint" "FOG_components:0402"' in sch_text(project)


def test_leaves_a_matching_footprint_alone(project):
    r = run(project)
    assert "C1" not in by_reference(r)


def test_adds_a_missing_footprint_field(project):
    r = run(project)
    assert by_reference(r)["U1"]["action"] == "added"
    text = sch_text(project)
    assert '"Footprint" "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"' in text
    assert balance(text) == 0


def test_added_field_lands_inside_its_instance(project):
    run(project)
    text = sch_text(project)
    start = text.index('"Reference" "U1"')
    end = text.index('"Reference" "#GND1"')
    assert start < text.index('"Package_SO:SOIC-8') < end


def test_add_missing_can_be_turned_off(project):
    r = run(project, addMissing=False)
    assert "U1" not in by_reference(r)
    assert {s["reference"] for s in r["skipped"]} >= {"U1"}


def test_power_symbols_are_skipped(project):
    r = run(project)
    assert "#GND1" not in by_reference(r)
    assert "#GND1" not in {s["reference"] for s in r["skipped"]}


def test_symbol_absent_from_the_board_is_reported_not_changed(project):
    r = run(project)
    assert "R99" not in by_reference(r)
    assert any(s["reference"] == "R99" and "not on the board" in s["reason"] for s in r["skipped"])
    assert '"orphan:fp"' in sch_text(project)


def test_lib_symbols_cache_is_not_touched(project):
    """Instance fields override the cache; rewriting the cache is a different tool."""
    run(project)
    assert '"STALE:should_not_be_touched"' in sch_text(project)


def test_result_stays_balanced(project):
    run(project)
    assert balance(sch_text(project)) == 0


def test_footprint_with_parens_is_written_back(project):
    run(project)
    assert '"FOG_components:HRS_U.FL-R-SMT-1(10)"' in sch_text(project)
    assert balance(sch_text(project)) == 0


def test_every_unit_of_a_multi_unit_symbol_is_updated(tmp_path):
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("X1", "FOG_components:BUL") + ")\n", encoding="utf-8"
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n"
        + instance("X1", "BUL", "old:fp", unit=1)
        + instance("X1", "BUL", "old:fp", unit=2)
        + ")\n",
        encoding="utf-8",
    )
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert r["changeCount"] == 2
    text = (tmp_path / "b.kicad_sch").read_text(encoding="utf-8")
    assert text.count('"FOG_components:BUL"') == 2
    assert "old:fp" not in text


def test_hidden_and_position_are_preserved_on_update(project):
    run(project)
    text = sch_text(project)
    block = text[text.index('"Reference" "R1"') :]
    field = block[block.index('"Footprint"') : block.index('"Footprint"') + 200]
    assert "(at 5 6 0)" in field
    assert "(hide yes)" in field


# --- options and errors ---------------------------------------------------- #


def test_dry_run_changes_nothing(project):
    before = sch_text(project)
    r = run(project, dryRun=True)
    assert r["dryRun"] is True
    assert r["changeCount"] > 0
    assert "Would update" in r["message"]
    assert sch_text(project) == before
    assert r["updatedFiles"] == []


def test_references_filter(project):
    r = run(project, references=["R1"])
    assert list(by_reference(r)) == ["R1"]
    assert '"wrong:thing"' in sch_text(project)


def test_second_run_is_a_no_op(project):
    run(project)
    r = run(project)
    assert r["changeCount"] == 0
    assert "already matches" in r["message"]


def test_all_sheets_beside_the_board_are_scanned(project):
    (project / "sub.kicad_sch").write_text(
        "(kicad_sch\n" + instance("C1", "100n", "stale:0603") + ")\n", encoding="utf-8"
    )
    r = run(project)
    assert "sub.kicad_sch" in r["sheetsScanned"]
    assert any(c["sheet"] == "sub.kicad_sch" for c in r["changes"])


def test_a_single_sheet_can_be_targeted(project):
    (project / "sub.kicad_sch").write_text(
        "(kicad_sch\n" + instance("C1", "100n", "stale:0603") + ")\n", encoding="utf-8"
    )
    r = run(project, schematicPath=str(project / "sub.kicad_sch"))
    assert r["sheetsScanned"] == ["sub.kicad_sch"]
    assert '"eagle_import:0402HF"' in sch_text(project)


def test_board_not_found(tmp_path):
    r = backannotate_footprints({"boardPath": str(tmp_path / "nope.kicad_pcb")})
    assert not r["success"]


def test_board_without_footprints(tmp_path):
    (tmp_path / "b.kicad_pcb").write_text("(kicad_pcb\n)\n", encoding="utf-8")
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert not r["success"]
    assert "No placed footprints" in r["message"]


def test_no_schematic_beside_the_board(tmp_path):
    (tmp_path / "b.kicad_pcb").write_text(BOARD, encoding="utf-8")
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert not r["success"]
    assert ".kicad_sch" in r["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
