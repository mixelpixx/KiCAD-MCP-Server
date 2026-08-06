"""Tests for find_duplicate_symbols — the same part stored twice in a library."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.find_duplicate_symbols import (  # noqa: E402
    count_symbol_usage,
    find_duplicate_symbols,
    read_library_symbols,
)


def prop(name, value):
    return f'\t\t(property "{name}" "{value}"\n\t\t\t(at 0 0 0)\n\t\t)\n'


def body(unit_name, x=0):
    return (
        f'\t\t(symbol "{unit_name}"\n'
        f"\t\t\t(rectangle\n\t\t\t\t(start {x} 1)\n\t\t\t\t(end 2 -1)\n\t\t\t)\n"
        "\t\t\t(pin passive line\n\t\t\t\t(at -3 0 0)\n\t\t\t\t(length 1)\n"
        '\t\t\t\t(name "~")\n\t\t\t\t(number "1")\n\t\t\t)\n'
        "\t\t\t(pin passive line\n\t\t\t\t(at 3 0 180)\n\t\t\t\t(length 1)\n"
        '\t\t\t\t(name "~")\n\t\t\t\t(number "2")\n\t\t\t)\n'
        "\t\t)\n"
    )


def sym(name, props, unit_x=0, extends=None):
    out = f'\t(symbol "{name}"\n'
    if extends:
        out += f'\t\t(extends "{extends}")\n'
    for k, v in props.items():
        out += prop(k, v)
    if not extends:
        out += body(f"{name}_1_1", unit_x)
    return out + "\t)\n"


LIB = (
    "(kicad_symbol_lib\n\t(version 20241209)\n"
    # Same part, two names, MPN written under two different property names.
    + sym(
        "R_0402_10K",
        {
            "Reference": "R",
            "Value": "10K",
            "Footprint": "FOG:0402",
            "MPN": "RC0402FR-0710KL",
            "Datasheet": "http://x",
            "Description": "10K 1%",
        },
    )
    + sym(
        "RES-10K-0402",
        {
            "Reference": "R",
            "Value": "10k",
            "Footprint": "FOG:0402",
            "MANUFACTURER PART NUMBER": "rc0402fr-0710kl",
        },
    )
    # Same body copied under a new name, no MPN anywhere.
    + sym("LED_RED", {"Reference": "D", "Value": "RED", "Footprint": "FOG:0603"}, unit_x=5)
    + sym("LED_ROT", {"Reference": "D", "Value": "ROT", "Footprint": "FOG:0603"}, unit_x=5)
    # Alone in every dimension.
    + sym(
        "CONN_USB",
        {"Reference": "J", "Value": "USB", "Footprint": "FOG:USB", "MPN": "USB4085"},
        unit_x=9,
    )
    # A derived symbol: shares the base's body on purpose.
    + sym("R_0402_10K_ALT", {"Reference": "R", "Value": "10K"}, extends="R_0402_10K")
    + ")\n"
)

SCH = (
    "(kicad_sch\n"
    "\t(lib_symbols\n"
    '\t\t(symbol "FOG:R_0402_10K"\n\t\t\t(property "Value" "10K"\n\t\t\t)\n\t\t)\n'
    "\t)\n"
    '\t(symbol\n\t\t(lib_id "FOG:R_0402_10K")\n\t\t(at 10 10 0)\n\t)\n'
    '\t(symbol\n\t\t(lib_id "FOG:R_0402_10K")\n\t\t(at 20 10 0)\n\t)\n'
    '\t(symbol\n\t\t(lib_id "OtherNick:LED_RED")\n\t\t(at 30 10 0)\n\t)\n'
    ")\n"
)


@pytest.fixture
def lib(tmp_path):
    path = tmp_path / "FOG.kicad_sym"
    path.write_text(LIB, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path, lib):
    (tmp_path / "board.kicad_sch").write_text(SCH, encoding="utf-8")
    return tmp_path


def run(lib, **kw):
    return find_duplicate_symbols({"libraryPath": str(lib), **kw})


def group_named(result, name):
    for g in result["groups"]:
        if name in [m["name"] for m in g["members"]]:
            return g
    return None


# --- reading --------------------------------------------------------------- #


def test_reads_every_top_level_symbol():
    names = [s["name"] for s in read_library_symbols(LIB)]
    assert names == [
        "R_0402_10K",
        "RES-10K-0402",
        "LED_RED",
        "LED_ROT",
        "CONN_USB",
        "R_0402_10K_ALT",
    ]


def test_unit_sub_symbols_are_not_top_level_symbols():
    assert all("_1_1" not in s["name"] for s in read_library_symbols(LIB))


def test_property_names_are_normalized_for_lookup():
    by_name = {s["name"]: s for s in read_library_symbols(LIB)}
    assert by_name["RES-10K-0402"]["normalized"]["MANUFACTURERPARTNUMBER"] == "rc0402fr-0710kl"


def test_extends_is_recorded_and_has_no_fingerprint():
    by_name = {s["name"]: s for s in read_library_symbols(LIB)}
    assert by_name["R_0402_10K_ALT"]["extends"] == "R_0402_10K"
    assert by_name["R_0402_10K_ALT"]["fingerprint"] == ""


def test_identical_bodies_under_different_names_hash_the_same():
    by_name = {s["name"]: s for s in read_library_symbols(LIB)}
    assert by_name["LED_RED"]["fingerprint"] == by_name["LED_ROT"]["fingerprint"]
    assert by_name["LED_RED"]["fingerprint"] != by_name["CONN_USB"]["fingerprint"]


def test_indentation_does_not_change_the_fingerprint():
    by_name = {s["name"]: s for s in read_library_symbols(LIB)}
    reindented = {s["name"]: s for s in read_library_symbols(LIB.replace("\t", "  "))}
    assert reindented["LED_RED"]["fingerprint"] == by_name["LED_RED"]["fingerprint"]


# --- matching -------------------------------------------------------------- #


def test_mpn_match_survives_inconsistent_property_names(lib):
    """The same field is MPN in one symbol and MANUFACTURER PART NUMBER in the other."""
    r = run(lib, matchBy=["mpn"])
    g = group_named(r, "R_0402_10K")
    assert sorted(m["name"] for m in g["members"]) == ["RES-10K-0402", "R_0402_10K"]
    assert "mpn" in g["matchedBy"]


def test_mpn_match_is_case_insensitive_by_default(lib):
    assert run(lib, matchBy=["mpn"])["groupCount"] == 1
    assert run(lib, matchBy=["mpn"], ignoreCase=False)["groupCount"] == 0


def test_value_footprint_match(lib):
    g = group_named(run(lib, matchBy=["value_footprint"]), "R_0402_10K")
    assert sorted(m["name"] for m in g["members"]) == ["RES-10K-0402", "R_0402_10K"]


def test_value_footprint_ignores_symbols_missing_either_field(lib):
    """R_0402_10K_ALT has a Value but no Footprint, so it cannot be compared."""
    r = run(lib, matchBy=["value_footprint"])
    assert all("R_0402_10K_ALT" not in [m["name"] for m in g["members"]] for g in r["groups"])


def test_graphics_match_finds_a_copy_with_different_fields(lib):
    """LED_RED and LED_ROT share no field values; only the body gives them away."""
    g = group_named(run(lib, matchBy=["graphics"]), "LED_RED")
    assert sorted(m["name"] for m in g["members"]) == ["LED_RED", "LED_ROT"]


def test_graphics_is_off_by_default(lib):
    """Every resistor in a library shares one body; on a real library graphics
    alone grouped 78 different values together. It has to be asked for."""
    r = run(lib)
    assert all("LED_RED" not in [m["name"] for m in g["members"]] for g in r["groups"])
    assert r["matchBy"] == ["mpn", "value_footprint"]


def test_a_derived_symbol_is_not_a_graphics_duplicate(lib):
    """extends exists to share a body; reporting it would be noise."""
    r = run(lib, matchBy=["graphics"])
    assert all("R_0402_10K_ALT" not in [m["name"] for m in g["members"]] for g in r["groups"])


def test_a_unique_symbol_is_not_reported(lib):
    r = run(lib)
    assert all("CONN_USB" not in [m["name"] for m in g["members"]] for g in r["groups"])


def test_strategies_agreeing_produce_one_group_not_three(lib):
    """R_0402_10K and RES-10K-0402 match on mpn, value_footprint and graphics."""
    r = run(lib, matchBy=["mpn", "value_footprint", "graphics"])
    matching = [g for g in r["groups"] if "R_0402_10K" in [m["name"] for m in g["members"]]]
    assert len(matching) == 1
    assert matching[0]["matchedBy"] == ["graphics", "mpn", "value_footprint"]


def test_evidence_records_which_property_supplied_the_key(lib):
    g = group_named(run(lib, matchBy=["mpn"]), "R_0402_10K")
    assert g["evidence"][0]["from"] == "MPN"
    assert g["evidence"][0]["key"] == "RC0402FR-0710KL"


def test_member_reports_which_property_its_mpn_came_from(lib):
    g = group_named(run(lib, matchBy=["mpn"]), "RES-10K-0402")
    member = next(m for m in g["members"] if m["name"] == "RES-10K-0402")
    assert member["mpnProperty"] == "MANUFACTURER PART NUMBER"


# --- usage ----------------------------------------------------------------- #


def test_usage_counts_instances_not_cache_entries(tmp_path):
    sheet = tmp_path / "board.kicad_sch"
    sheet.write_text(SCH, encoding="utf-8")
    usage = count_symbol_usage([sheet])
    assert usage["R_0402_10K"] == {"board.kicad_sch": 2}


def test_usage_ignores_the_library_nickname(tmp_path):
    """The same library is registered under different nicknames per project."""
    sheet = tmp_path / "board.kicad_sch"
    sheet.write_text(SCH, encoding="utf-8")
    assert count_symbol_usage([sheet])["LED_RED"] == {"board.kicad_sch": 1}


def test_usage_is_attached_to_members(project, lib):
    g = group_named(run(lib, schematicPaths=[str(project)]), "R_0402_10K")
    used = next(m for m in g["members"] if m["name"] == "R_0402_10K")
    unused = next(m for m in g["members"] if m["name"] == "RES-10K-0402")
    assert used["usageCount"] == 2
    assert used["usedIn"] == ["board.kicad_sch"]
    assert unused["usageCount"] == 0


def test_a_directory_of_sheets_is_expanded(project, lib):
    (project / "sub.kicad_sch").write_text(
        '(kicad_sch\n\t(symbol\n\t\t(lib_id "FOG:RES-10K-0402")\n\t)\n)\n', encoding="utf-8"
    )
    r = run(lib, schematicPaths=[str(project)])
    assert sorted(r["sheetsScanned"]) == ["board.kicad_sch", "sub.kicad_sch"]


def test_the_used_symbol_is_the_one_suggested(project, lib):
    g = group_named(run(lib, schematicPaths=[str(project)]), "R_0402_10K")
    assert g["suggestedKeep"] == "R_0402_10K"
    assert "only one in use" in g["keepReason"]
    assert g["unusedMembers"] == ["RES-10K-0402"]


def test_without_schematics_the_richer_symbol_is_suggested(lib):
    """No usage data, so fall back to the one carrying a datasheet and description."""
    g = group_named(run(lib, matchBy=["mpn"]), "R_0402_10K")
    assert g["suggestedKeep"] == "R_0402_10K"
    assert "none are used" in g["keepReason"]


def test_the_message_says_when_usage_data_is_missing(lib):
    assert "pass schematicPaths" in run(lib)["message"]


def test_the_message_counts_retirable_symbols(project, lib):
    assert "unused across 1 sheet(s)" in run(lib, schematicPaths=[str(project)])["message"]


# --- options and errors ---------------------------------------------------- #


def test_min_group_size(lib):
    assert run(lib, matchBy=["mpn"], minGroupSize=3)["groupCount"] == 0


def test_unknown_strategy_is_refused(lib):
    r = run(lib, matchBy=["vibes"])
    assert not r["success"]
    assert "vibes" in r["message"]
    assert "graphics" in r["validStrategies"]


def test_a_schematic_is_not_a_symbol_library(tmp_path):
    path = tmp_path / "board.kicad_sch"
    path.write_text(SCH, encoding="utf-8")
    r = find_duplicate_symbols({"libraryPath": str(path)})
    assert not r["success"]
    assert "kicad_symbol_lib" in r["message"]


def test_missing_library(tmp_path):
    r = find_duplicate_symbols({"libraryPath": str(tmp_path / "nope.kicad_sym")})
    assert not r["success"]


def test_empty_library(tmp_path):
    path = tmp_path / "empty.kicad_sym"
    path.write_text("(kicad_symbol_lib\n\t(version 20241209)\n)\n", encoding="utf-8")
    r = find_duplicate_symbols({"libraryPath": str(path)})
    assert r["success"]
    assert r["symbolCount"] == 0


def test_a_library_with_no_duplicates(tmp_path):
    path = tmp_path / "clean.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("A", {"Value": "1", "Footprint": "f:1", "MPN": "AA"}, unit_x=1)
        + sym("B", {"Value": "2", "Footprint": "f:2", "MPN": "BB"}, unit_x=2)
        + ")\n",
        encoding="utf-8",
    )
    r = find_duplicate_symbols({"libraryPath": str(path)})
    assert r["success"]
    assert r["groupCount"] == 0
    assert "No duplicates" in r["message"]


def test_a_missing_sheet_path_does_not_abort_the_scan(lib, project):
    r = run(lib, schematicPaths=[str(project), str(project / "ghost.kicad_sch")])
    assert r["success"]
    assert r["sheetsScanned"] == ["board.kicad_sch"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
