"""Tests for backannotate_footprints — PCB footprint assignments -> schematic."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.backannotate_footprints import (  # noqa: E402
    backannotate_footprints,
    read_board_footprints,
    read_board_placements,
)
from utils.sexpr_format import match_paren  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


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


def instance(reference, value, footprint_value, unit=1, instances="", footprint_body=None):
    if footprint_value is None:
        field = ""
    else:
        body = (
            footprint_body
            if footprint_body is not None
            else "\t\t\t(at 5 6 0)\n\t\t\t(hide yes)\n\t\t\t(effects (font (size 1.27 1.27)))\n"
        )
        field = f'\t\t(property "Footprint" "{footprint_value}"\n{body}\t\t)\n'
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
{field}{instances}\t)
"""


def instances_block(*paths):
    """An (instances ...) block: one (path ... (reference ...)) per sheet instance."""
    body = "".join(
        f'\t\t\t\t(path "{path}"\n\t\t\t\t\t(reference "{reference}")\n'
        f"\t\t\t\t\t(unit 1)\n\t\t\t\t)\n"
        for path, reference in paths
    )
    return '\t\t(instances\n\t\t\t(project "proj"\n' + body + "\t\t\t)\n\t\t)\n"


def sheet_ref(name, uuid, filename):
    return (
        f'\t(sheet\n\t\t(at 10 10)\n\t\t(uuid "{uuid}")\n'
        f'\t\t(property "Sheetname" "{name}"\n\t\t\t(at 10 9 0)\n\t\t)\n'
        f'\t\t(property "Sheetfile" "{filename}"\n\t\t\t(at 10 11 0)\n\t\t)\n\t)\n'
    )


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
    """Zero when the file is one balanced top-level list, non-zero otherwise."""
    closing = match_paren(text, text.index("("))
    return 0 if closing == len(text.rstrip()) - 1 else 1


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


def footprint_field(text, reference):
    """The Footprint field belonging to the symbol carrying *reference*."""
    block = text[text.index(f'"Reference" "{reference}"') :]
    start = block.index('(property "Footprint"')
    return block[start : match_paren(block, start) + 1]


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


# --- W4: duplicate references on the board --------------------------------- #


def test_duplicate_board_reference_keeps_both_placements():
    dup = (
        "(kicad_pcb\n"
        + footprint("R1", "FOG_components:0402")
        + footprint("R1", "FOG_components:0805")
        + ")\n"
    )
    assert read_board_placements(dup)["R1"] == [
        "FOG_components:0402",
        "FOG_components:0805",
    ]


def test_duplicate_board_reference_is_a_conflict_not_a_silent_overwrite(tmp_path):
    """Two footprints carrying R1: the earlier one used to be discarded."""
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n"
        + footprint("R1", "FOG_components:0402")
        + footprint("R1", "FOG_components:0805")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n" + instance("R1", "10K", "old:fp") + ")\n", encoding="utf-8"
    )
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert r["changeCount"] == 0
    assert '"old:fp"' in (tmp_path / "b.kicad_sch").read_text(encoding="utf-8")
    conflict = next(c for c in r["conflicts"] if c["references"] == ["R1"])
    assert conflict["footprints"] == ["FOG_components:0402", "FOG_components:0805"]
    assert "more than one footprint" in conflict["reason"]
    assert any(s["reference"] == "R1" for s in r["skipped"])


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


# --- C2: the existing field's own state survives an update ----------------- #


VISIBLE_FIELD_BODY = """\t\t\t(at 5 6 90)
\t\t\t(unlocked yes)
\t\t\t(show_name yes)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 2.54 2.54)
\t\t\t\t\t(bold yes)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
"""


@pytest.fixture
def visible_field_project(tmp_path):
    """A Footprint field the user deliberately made visible, big, bold and left."""
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("R1", "FOG_components:0402") + ")\n", encoding="utf-8"
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n" + instance("R1", "10K", "old:fp", footprint_body=VISIBLE_FIELD_BODY) + ")\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_visible_footprint_field_is_not_hidden_by_the_update(visible_field_project):
    """Rebuilding the field forced (hide yes) onto a field the user had shown."""
    backannotate_footprints({"boardPath": str(visible_field_project / "b.kicad_pcb")})
    field = footprint_field(
        (visible_field_project / "b.kicad_sch").read_text(encoding="utf-8"), "R1"
    )
    assert '"FOG_components:0402"' in field
    assert "(hide yes)" not in field


@pytest.mark.parametrize(
    "token",
    [
        "(at 5 6 90)",
        "(unlocked yes)",
        "(show_name yes)",
        "(do_not_autoplace no)",
        "(size 2.54 2.54)",
        "(bold yes)",
        "(justify left)",
    ],
)
def test_every_other_token_of_the_field_survives_the_update(visible_field_project, token):
    backannotate_footprints({"boardPath": str(visible_field_project / "b.kicad_pcb")})
    field = footprint_field(
        (visible_field_project / "b.kicad_sch").read_text(encoding="utf-8"), "R1"
    )
    assert token in field


def test_only_the_value_token_changes(visible_field_project):
    """Byte-for-byte: the whole file bar the quoted value is untouched."""
    before = (visible_field_project / "b.kicad_sch").read_bytes()
    backannotate_footprints({"boardPath": str(visible_field_project / "b.kicad_pcb")})
    after = (visible_field_project / "b.kicad_sch").read_bytes()
    assert after == before.replace(b'"old:fp"', b'"FOG_components:0402"')


def test_canonical_schematic_keeps_its_canonical_layout(tmp_path):
    """The fixture is what eeschema writes; only the value may differ after."""
    canonical = (FIXTURES / "canonical_schematic.kicad_sch").read_bytes()
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("C9", "Capacitor_SMD:C_0402_1005Metric") + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_bytes(canonical)
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert r["changeCount"] == 1
    after = (tmp_path / "b.kicad_sch").read_bytes()
    assert after == canonical.replace(
        b'"Capacitor_SMD:C_0603_1608Metric"', b'"Capacitor_SMD:C_0402_1005Metric"'
    )


def test_hidden_and_position_are_preserved_on_update(project):
    run(project)
    field = footprint_field(sch_text(project), "R1")
    assert "(at 5 6 0)" in field
    assert "(hide yes)" in field


def test_an_inserted_field_is_hidden_like_eeschema_writes_it(project):
    run(project)
    field = footprint_field(sch_text(project), "U1")
    assert "(hide yes)" in field


# --- C1: per-instance references from (instances ...) ---------------------- #


@pytest.fixture
def repeated_sheet_project(tmp_path):
    """One sub.kicad_sch placed twice; the board gives R1 an 0402 and R2 an 0805."""
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n"
        + footprint("R1", "FOG_components:0402")
        + footprint("R2", "FOG_components:0805")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_text(
        '(kicad_sch\n\t(version 20231120)\n\t(generator "eeschema")\n'
        + sheet_ref("A", "sheetA", "sub.kicad_sch")
        + sheet_ref("B", "sheetB", "sub.kicad_sch")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "sub.kicad_sch").write_text(
        '(kicad_sch\n\t(version 20231120)\n\t(generator "eeschema")\n'
        + instance(
            "R1",
            "10K",
            "old:fp",
            instances=instances_block(("/root-uuid/sheetA", "R1"), ("/root-uuid/sheetB", "R2")),
        )
        + ")\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_repeated_sheet_with_disagreeing_footprints_is_left_alone(repeated_sheet_project):
    """The two instances share one Footprint field, so neither may win."""
    r = backannotate_footprints({"boardPath": str(repeated_sheet_project / "b.kicad_pcb")})
    assert r["changeCount"] == 0
    assert '"old:fp"' in (repeated_sheet_project / "sub.kicad_sch").read_text(encoding="utf-8")


def test_a_repeated_sheet_conflict_names_both_references(repeated_sheet_project):
    r = backannotate_footprints({"boardPath": str(repeated_sheet_project / "b.kicad_pcb")})
    conflict = next(c for c in r["conflicts"] if c["sheet"] == "sub.kicad_sch")
    assert conflict["references"] == ["R1", "R2"]
    assert conflict["footprints"] == ["FOG_components:0402", "FOG_components:0805"]


def test_the_second_instance_is_never_silently_dropped(repeated_sheet_project):
    """R2 used to appear in neither changes nor skipped: the sheet never saw it."""
    r = backannotate_footprints({"boardPath": str(repeated_sheet_project / "b.kicad_pcb")})
    assert "R2" not in r["notInSchematic"]
    per_sheet = (
        {c["reference"] for c in r["changes"]}
        | {s["reference"] for s in r["skipped"]}
        | {ref for c in r["conflicts"] for ref in c["references"]}
    )
    assert "R2" in per_sheet


def test_a_repeated_sheet_that_agrees_is_updated_once(tmp_path):
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n"
        + footprint("R1", "FOG_components:0402")
        + footprint("R2", "FOG_components:0402")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n"
        + sheet_ref("A", "sheetA", "sub.kicad_sch")
        + sheet_ref("B", "sheetB", "sub.kicad_sch")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "sub.kicad_sch").write_text(
        "(kicad_sch\n"
        + instance(
            "R1",
            "10K",
            "old:fp",
            instances=instances_block(("/root-uuid/sheetA", "R1"), ("/root-uuid/sheetB", "R2")),
        )
        + ")\n",
        encoding="utf-8",
    )
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert r["changeCount"] == 1
    change = r["changes"][0]
    assert change["references"] == ["R1", "R2"]
    text = (tmp_path / "sub.kicad_sch").read_text(encoding="utf-8")
    assert text.count('"FOG_components:0402"') == 1


def test_a_reference_only_in_the_instances_block_is_matched(tmp_path):
    """The Reference property still says R? while the design is annotated R5."""
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("R5", "FOG_components:0402") + ")\n", encoding="utf-8"
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n"
        + instance("R?", "10K", "old:fp", instances=instances_block(("/root-uuid", "R5")))
        + ")\n",
        encoding="utf-8",
    )
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert by_reference(r)["R5"]["to"] == "FOG_components:0402"


def test_an_unannotated_reference_is_told_to_annotate(tmp_path):
    """'not on the board' sent the user hunting for a missing footprint."""
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("R1", "FOG_components:0402") + ")\n", encoding="utf-8"
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n" + instance("R?", "10K", "old:fp") + ")\n", encoding="utf-8"
    )
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    reason = next(s["reason"] for s in r["skipped"] if s["reference"] == "R?")
    assert "annotat" in reason
    assert "not on the board" not in reason


# --- C3: which sheets get rewritten --------------------------------------- #


@pytest.fixture
def hierarchy_with_noise(tmp_path):
    """A two-sheet design surrounded by history, backups and another project."""
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n"
        + footprint("R1", "FOG_components:0402")
        + footprint("C1", "FOG_components:0603")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n"
        + sheet_ref("power", "sheet-1", "sub.kicad_sch")
        + instance("R1", "10K", "stale:0402")
        + ")\n",
        encoding="utf-8",
    )
    noise = "(kicad_sch\n" + instance("C1", "100n", "stale:0603") + ")\n"
    (tmp_path / "sub.kicad_sch").write_text(noise, encoding="utf-8")
    for directory in (".history", "backups", "other_project"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "s.kicad_sch").write_text(noise, encoding="utf-8")
    return tmp_path


def test_the_sheet_tree_is_scanned(hierarchy_with_noise):
    r = backannotate_footprints({"boardPath": str(hierarchy_with_noise / "b.kicad_pcb")})
    assert r["sheetsScanned"] == ["b.kicad_sch", "sub.kicad_sch"]
    assert {c["sheet"] for c in r["changes"]} == {"b.kicad_sch", "sub.kicad_sch"}


@pytest.mark.parametrize("directory", [".history", "backups", "other_project"])
def test_a_sheet_outside_the_design_is_left_alone(hierarchy_with_noise, directory):
    """Rewriting the backup destroys the fallback at the moment it is needed."""
    outsider = hierarchy_with_noise / directory / "s.kicad_sch"
    before = outsider.read_bytes()
    r = backannotate_footprints({"boardPath": str(hierarchy_with_noise / "b.kicad_pcb")})
    assert outsider.read_bytes() == before
    assert not any(directory in s for s in r["sheetsScanned"])
    assert not any(directory in p for p in r["updatedFiles"])


def test_scanned_sheets_are_distinguishable(tmp_path):
    """Two sheets both named s.kicad_sch used to report as one name twice."""
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("C1", "FOG_components:0603") + ")\n", encoding="utf-8"
    )
    (tmp_path / "parts").mkdir()
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n" + sheet_ref("deep", "sheet-1", "parts/s.kicad_sch") + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "parts" / "s.kicad_sch").write_text(
        "(kicad_sch\n" + instance("C1", "100n", "stale:0603") + ")\n", encoding="utf-8"
    )
    r = backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert r["sheetsScanned"] == ["b.kicad_sch", "parts/s.kicad_sch"]
    assert r["changes"][0]["sheet"] == "parts/s.kicad_sch"


def test_a_sheet_placed_twice_is_only_written_once(repeated_sheet_project):
    """Both (sheet ...) blocks name sub.kicad_sch; it is one file on disk."""
    r = backannotate_footprints({"boardPath": str(repeated_sheet_project / "b.kicad_pcb")})
    assert r["sheetsScanned"] == ["b.kicad_sch", "sub.kicad_sch"]


def test_sheets_beside_the_board_are_used_when_there_is_no_root_sheet(tmp_path):
    (tmp_path / "board.kicad_pcb").write_text(BOARD, encoding="utf-8")
    (tmp_path / "somethingelse.kicad_sch").write_text(SCH, encoding="utf-8")
    (tmp_path / ".history").mkdir()
    outsiders = [
        tmp_path / ".history" / "somethingelse.kicad_sch",
        tmp_path / "_autosave-somethingelse.kicad_sch",
    ]
    for outsider in outsiders:
        outsider.write_text(SCH, encoding="utf-8")
    r = backannotate_footprints({"boardPath": str(tmp_path / "board.kicad_pcb")})
    assert r["sheetsScanned"] == ["somethingelse.kicad_sch"]
    for outsider in outsiders:
        assert outsider.read_text(encoding="utf-8") == SCH


def test_a_named_sheet_outside_the_project_is_flagged(project):
    other = project / "elsewhere"
    other.mkdir()
    stray = other / "unrelated.kicad_sch"
    stray.write_text("(kicad_sch\n" + instance("R1", "10K", "old:fp") + ")\n", encoding="utf-8")
    r = run(project, schematicPath=str(stray))
    assert r["warnings"]
    assert "sheet tree" in r["warnings"][0]


# --- W3: on the board, missing from the schematic -------------------------- #


def test_a_footprint_only_on_the_board_is_reported(project):
    r = run(project)
    assert r["notInSchematic"] == []
    (project / "b.kicad_sch").write_text(
        "(kicad_sch\n" + instance("R1", "10K", "old:fp") + ")\n", encoding="utf-8"
    )
    r = run(project)
    assert r["notInSchematic"] == ["C1", "J2", "U1"]


def test_notInSchematic_respects_the_references_filter(project):
    (project / "b.kicad_sch").write_text(
        "(kicad_sch\n" + instance("R1", "10K", "old:fp") + ")\n", encoding="utf-8"
    )
    r = run(project, references=["C1"])
    assert r["notInSchematic"] == ["C1"]


# --- W2: line endings ------------------------------------------------------ #


def test_an_lf_schematic_stays_lf(tmp_path):
    """Whole-file CRLF conversion turns a one-field edit into a 300-line diff."""
    canonical = (FIXTURES / "canonical_schematic.kicad_sch").read_bytes()
    assert b"\r\n" not in canonical
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("C9", "Capacitor_SMD:C_0402_1005Metric") + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_bytes(canonical)
    backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    assert b"\r\n" not in (tmp_path / "b.kicad_sch").read_bytes()


def test_a_crlf_schematic_stays_crlf(tmp_path):
    canonical = (FIXTURES / "canonical_schematic.kicad_sch").read_bytes()
    crlf = canonical.replace(b"\n", b"\r\n")
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n" + footprint("C9", "Capacitor_SMD:C_0402_1005Metric") + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_bytes(crlf)
    backannotate_footprints({"boardPath": str(tmp_path / "b.kicad_pcb")})
    after = (tmp_path / "b.kicad_sch").read_bytes()
    assert after.count(b"\r\n") == after.count(b"\n")
    assert after == crlf.replace(
        b'"Capacitor_SMD:C_0603_1608Metric"', b'"Capacitor_SMD:C_0402_1005Metric"'
    )


# --- W1: a write failure must not leave a half-edited design --------------- #


@pytest.fixture
def two_sheet_project(tmp_path):
    (tmp_path / "b.kicad_pcb").write_text(
        "(kicad_pcb\n"
        + footprint("R1", "FOG_components:0402")
        + footprint("C1", "FOG_components:0603")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_text(
        "(kicad_sch\n"
        + sheet_ref("power", "sheet-1", "sub.kicad_sch")
        + instance("R1", "10K", "stale:0402")
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "sub.kicad_sch").write_text(
        "(kicad_sch\n" + instance("C1", "100n", "stale:0603") + ")\n", encoding="utf-8"
    )
    return tmp_path


def _fail_writes_to(monkeypatch, name):
    import commands.backannotate_footprints as module

    real = module._write_text

    def guarded(path, text, newline):
        if Path(path).name == name:
            raise OSError("read-only file system")
        return real(path, text, newline)

    monkeypatch.setattr(module, "_write_text", guarded)


def test_a_write_failure_still_reports_what_was_done(two_sheet_project, monkeypatch):
    """The old code returned early and threw the whole record away."""
    _fail_writes_to(monkeypatch, "sub.kicad_sch")
    r = backannotate_footprints({"boardPath": str(two_sheet_project / "b.kicad_pcb")})
    assert r["success"] is False
    assert r["changeCount"] == 2
    assert [f["sheet"] for f in r["failures"]] == ["sub.kicad_sch"]
    assert "read-only file system" in r["failures"][0]["error"]
    assert r["updatedFiles"] == [str(two_sheet_project / "b.kicad_sch")]


def test_a_failure_on_the_first_sheet_does_not_stop_the_second(two_sheet_project, monkeypatch):
    _fail_writes_to(monkeypatch, "b.kicad_sch")
    r = backannotate_footprints({"boardPath": str(two_sheet_project / "b.kicad_pcb")})
    assert [f["sheet"] for f in r["failures"]] == ["b.kicad_sch"]
    assert '"FOG_components:0603"' in (two_sheet_project / "sub.kicad_sch").read_text(
        encoding="utf-8"
    )


def test_no_temporary_file_is_left_behind(two_sheet_project):
    backannotate_footprints({"boardPath": str(two_sheet_project / "b.kicad_pcb")})
    assert list(two_sheet_project.glob("*.mcp-tmp")) == []


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


def test_a_second_run_is_byte_identical(project):
    run(project)
    once = (project / "b.kicad_sch").read_bytes()
    run(project)
    assert (project / "b.kicad_sch").read_bytes() == once


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
