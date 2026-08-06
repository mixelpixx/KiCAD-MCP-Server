"""Tests for find_duplicate_symbols — the same part stored twice in a library."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.find_duplicate_symbols import (  # noqa: E402
    count_symbol_usage,
    find_duplicate_symbols,
    read_library_symbols,
    resolve_library_nicknames,
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


def placements(*lib_ids):
    """A schematic placing each lib_id once, in order."""
    out = "(kicad_sch\n"
    for i, lib_id in enumerate(lib_ids):
        out += f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {i} 10 0)\n\t)\n'
    return out + ")\n"


def sheet_block(name, file_name):
    return (
        "\t(sheet\n\t\t(at 0 0)\n"
        f'\t\t(property "Sheetname" "{name}")\n'
        f'\t\t(property "Sheetfile" "{file_name}")\n\t)\n'
    )


def sheets_sch(*blocks):
    return "(kicad_sch\n" + "".join(blocks) + ")\n"


def sym_lib_table(nickname, uri):
    return (
        "(sym_lib_table\n\t(version 7)\n"
        f'\t(lib (name "{nickname}")(type "KiCad")(uri "{uri}")(options "")(descr ""))\n'
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
    alone put 78 resistor symbols, spanning 53 distinct values, in one group.
    It has to be asked for."""
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


# --- placeholder values ---------------------------------------------------- #


def test_a_placeholder_mpn_does_not_group_unrelated_parts(tmp_path):
    """N/A is what an importer writes for a part with no MPN, not an MPN.

    Six parts sharing nothing but that marker were reported as one group of six
    under the default strategies -- the failure graphics has on passives,
    happening where it cannot be turned off.
    """
    path = tmp_path / "Imported.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + "".join(
            sym(f"PART_{i}", {"Value": f"V{i}", "Footprint": f"FP_{i}", "MPN": "N/A"}, unit_x=i)
            for i in range(6)
        )
        + ")\n",
        encoding="utf-8",
    )
    r = find_duplicate_symbols({"libraryPath": str(path)})
    assert r["groupCount"] == 0
    assert r["duplicateSymbolCount"] == 0


@pytest.mark.parametrize("marker", ["~", "-", "--", "N/A", "n/a", "NA", "None", "TBD", "?", "X"])
def test_every_known_placeholder_is_rejected_as_an_mpn(tmp_path, marker):
    path = tmp_path / f"Lib{abs(hash(marker))}.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("A", {"Value": "1", "Footprint": "f:1", "MPN": marker}, unit_x=1)
        + sym("B", {"Value": "2", "Footprint": "f:2", "MPN": marker}, unit_x=2)
        + ")\n",
        encoding="utf-8",
    )
    assert find_duplicate_symbols({"libraryPath": str(path), "matchBy": ["mpn"]})["groupCount"] == 0


def test_kicads_empty_field_marker_is_not_a_value_footprint_key(tmp_path):
    """~ is how KiCad spells an empty field."""
    path = tmp_path / "Tilde.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + "".join(sym(f"U_{i}", {"Value": "~", "Footprint": "~"}, unit_x=i) for i in range(4))
        + ")\n",
        encoding="utf-8",
    )
    r = find_duplicate_symbols({"libraryPath": str(path), "matchBy": ["value_footprint"]})
    assert r["groupCount"] == 0


def test_a_real_part_number_wins_over_a_placeholder_in_another_spelling(tmp_path):
    """MPN is N/A but PART NUMBER is real, so the real one decides the match."""
    path = tmp_path / "Mixed.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("A", {"Value": "1", "Footprint": "f:1", "MPN": "N/A", "PART NUMBER": "REAL-1"})
        + sym("B", {"Value": "2", "Footprint": "f:2", "MPN": "REAL-1"}, unit_x=2)
        + ")\n",
        encoding="utf-8",
    )
    r = find_duplicate_symbols({"libraryPath": str(path), "matchBy": ["mpn"]})
    assert r["groupCount"] == 1
    assert r["groups"][0]["evidence"][0]["key"] == "REAL-1"
    member = next(m for m in r["groups"][0]["members"] if m["name"] == "A")
    assert member["mpn"] == "REAL-1"
    assert member["mpnProperty"] == "PART NUMBER"


# --- overlapping groups ---------------------------------------------------- #


def test_overlapping_groups_merge_into_one_component(tmp_path):
    """A and B share an MPN; A, B and C share Value + Footprint.

    Merging on the exact member set made those two separate groups, so A and B
    were reported twice and three of three symbols were called redundant.
    """
    path = tmp_path / "Overlap.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("A", {"Value": "10K", "Footprint": "R0402", "MPN": "SHARED"})
        + sym("B", {"Value": "10K", "Footprint": "R0402", "MPN": "SHARED"})
        + sym("C", {"Value": "10K", "Footprint": "R0402", "MPN": "OTHER-C"})
        + ")\n",
        encoding="utf-8",
    )
    r = find_duplicate_symbols({"libraryPath": str(path)})
    assert r["groupCount"] == 1
    assert r["duplicateSymbolCount"] == 2
    group = r["groups"][0]
    assert [m["name"] for m in group["members"]] == ["A", "B", "C"]
    assert group["matchedBy"] == ["mpn", "value_footprint"]
    assert [e["key"] for e in group["evidence"]] == ["SHARED", "10K @ R0402"]


def test_no_symbol_appears_in_two_groups(tmp_path):
    """A caller iterating groups must not process the same symbol twice."""
    path = tmp_path / "Chain.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("A", {"Value": "1u", "Footprint": "C0402", "MPN": "M-AB"})
        + sym("B", {"Value": "1u", "Footprint": "C0402", "MPN": "M-AB"})
        + sym("C", {"Value": "1u", "Footprint": "C0402", "MPN": "M-CD"})
        + sym("D", {"Value": "1u", "Footprint": "C0402", "MPN": "M-CD"})
        + ")\n",
        encoding="utf-8",
    )
    r = find_duplicate_symbols({"libraryPath": str(path)})
    seen = [m["name"] for g in r["groups"] for m in g["members"]]
    assert sorted(seen) == ["A", "B", "C", "D"]
    assert r["duplicateSymbolCount"] <= r["symbolCount"] - r["groupCount"]


# --- the name strategy ----------------------------------------------------- #


def test_the_name_strategy_matches_across_separators(tmp_path):
    path = tmp_path / "Names.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("R_10K_0402", {"Value": "10K"})
        + sym("R-10K-0402", {"Value": "10K"}, unit_x=2)
        + ")\n",
        encoding="utf-8",
    )
    r = find_duplicate_symbols({"libraryPath": str(path), "matchBy": ["name"]})
    assert r["groupCount"] == 1
    assert r["groups"][0]["evidence"][0]["from"] == "name"


def test_the_name_strategy_keeps_the_decimal_point(tmp_path):
    """Stripping it made C_1.0uF_0805 and C_10uF_0805 -- and R_1.5K and R_15K -- one key."""
    path = tmp_path / "Decimals.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("C_1.0uF_0805", {"Value": "1.0uF"}, unit_x=1)
        + sym("C_10uF_0805", {"Value": "10uF"}, unit_x=2)
        + sym("R_1.5K", {"Value": "1.5K"}, unit_x=3)
        + sym("R_15K", {"Value": "15K"}, unit_x=4)
        + ")\n",
        encoding="utf-8",
    )
    assert (
        find_duplicate_symbols({"libraryPath": str(path), "matchBy": ["name"]})["groupCount"] == 0
    )


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
    usage = count_symbol_usage([sheet], ["FOG"])
    assert usage.counts["R_0402_10K"] == {"board.kicad_sch": 2}


def test_another_librarys_placements_are_not_counted_as_this_librarys(tmp_path):
    """OtherNick:LED_RED is not FOG's LED_RED, however alike the names are."""
    sheet = tmp_path / "board.kicad_sch"
    sheet.write_text(SCH, encoding="utf-8")
    usage = count_symbol_usage([sheet], ["FOG"])
    assert "LED_RED" not in usage.counts
    assert usage.nicknames_seen == ["FOG", "OtherNick"]


def test_a_stock_library_does_not_make_an_unused_symbol_look_popular(tmp_path):
    """Bare one-letter names collide with Device:/Switch:/power: constantly.

    Crediting Device:R's 50 placements to this library's R recommended keeping
    the symbol nothing references and retiring the only one actually placed.
    """
    path = tmp_path / "MyLib.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym("R", {"Value": "10K", "Footprint": "R_0402", "MPN": "RC0402-10K"})
        + sym("R_10K_0402", {"Value": "10K", "Footprint": "R_0402", "MPN": "RC0402-10K"})
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "board.kicad_sch").write_text(
        placements(*(["Device:R"] * 50 + ["MyLib:R_10K_0402"] * 3)), encoding="utf-8"
    )
    g = run(path, schematicPaths=[str(tmp_path)])["groups"][0]
    by_name = {m["name"]: m for m in g["members"]}
    assert by_name["R"]["usageCount"] == 0
    assert by_name["R_10K_0402"]["usageCount"] == 3
    assert g["suggestedKeep"] == "R_10K_0402"
    assert g["unusedMembers"] == ["R"]


def test_a_lib_id_with_no_nickname_is_counted_by_name(tmp_path):
    """A bare id names no library, so its name is all there is to go on."""
    sheet = tmp_path / "board.kicad_sch"
    sheet.write_text(placements("R_0402_10K", "R_0402_10K"), encoding="utf-8")
    usage = count_symbol_usage([sheet], ["FOG"])
    assert usage.counts["R_0402_10K"] == {"board.kicad_sch": 2}
    assert usage.nicknames_seen == []


def test_the_nickname_is_taken_from_sym_lib_table(tmp_path):
    """sym-lib-table decides the nickname, and it need not be the file name."""
    lib_path = tmp_path / "FOG_components.kicad_sym"
    lib_path.write_text(LIB, encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "sym-lib-table").write_text(
        sym_lib_table("FOGSYM", "${KIPRJMOD}/../FOG_components.kicad_sym"), encoding="utf-8"
    )
    (project / "board.kicad_sch").write_text(
        placements("FOGSYM:R_0402_10K", "FOGSYM:R_0402_10K"), encoding="utf-8"
    )
    r = run(lib_path, schematicPaths=[str(project)])
    assert sorted(r["libraryNicknames"]) == ["FOGSYM", "FOG_components"]
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] == 2


def test_a_sym_lib_table_entry_for_another_library_is_not_adopted(tmp_path):
    lib_path = tmp_path / "FOG.kicad_sym"
    lib_path.write_text(LIB, encoding="utf-8")
    (tmp_path / "sym-lib-table").write_text(
        sym_lib_table("Elsewhere", "${KIPRJMOD}/other.kicad_sym"), encoding="utf-8"
    )
    (tmp_path / "board.kicad_sch").write_text(SCH, encoding="utf-8")
    assert run(lib_path, schematicPaths=[str(tmp_path)])["libraryNicknames"] == ["FOG"]


def test_library_nicknames_can_be_given_explicitly(tmp_path):
    """The escape hatch for a library no scanned project's table registers."""
    lib_path = tmp_path / "FOG.kicad_sym"
    lib_path.write_text(LIB, encoding="utf-8")
    (tmp_path / "board.kicad_sch").write_text(
        placements("Renamed:R_0402_10K", "Renamed:R_0402_10K"), encoding="utf-8"
    )
    r = run(lib_path, schematicPaths=[str(tmp_path)], libraryNicknames=["Renamed"])
    assert r["libraryNicknames"] == ["Renamed"]
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] == 2


def test_a_nickname_mismatch_is_said_out_loud(tmp_path):
    """Attributing nothing must not read the same as "nothing is used"."""
    lib_path = tmp_path / "FOG.kicad_sym"
    lib_path.write_text(LIB, encoding="utf-8")
    (tmp_path / "board.kicad_sch").write_text(
        placements("Renamed:R_0402_10K", "Renamed:RES-10K-0402"), encoding="utf-8"
    )
    r = run(lib_path, schematicPaths=[str(tmp_path)])
    assert r["nicknamesSeen"] == ["Renamed"]
    assert "no usage was attributed to this library" in r["message"]
    assert "libraryNicknames" in r["message"]


def test_resolve_library_nicknames_defaults_to_the_file_stem(tmp_path):
    assert resolve_library_nicknames(tmp_path / "FOG.kicad_sym", []) == {"FOG"}


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


def test_an_autosave_sheet_is_not_counted(project, lib):
    """eeschema writes _autosave-<sheet> while the project is open; it is a copy
    of a sheet already being scanned, so counting it doubles every number."""
    (project / "_autosave-board.kicad_sch").write_text(SCH, encoding="utf-8")
    r = run(lib, schematicPaths=[str(project)])
    assert r["sheetsScanned"] == ["board.kicad_sch"]
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] == 2


def test_backup_and_history_directories_are_not_scanned(project, lib):
    for folder in ("proj-backups", ".history"):
        (project / folder).mkdir()
        (project / folder / "board.kicad_sch").write_text(SCH, encoding="utf-8")
    r = run(lib, schematicPaths=[str(project)])
    assert r["sheetsScanned"] == ["board.kicad_sch"]
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] == 2


def test_an_explicitly_named_autosave_sheet_is_still_read(tmp_path, lib):
    """Skipping them is for directory expansion; naming one is deliberate."""
    autosave = tmp_path / "_autosave-board.kicad_sch"
    autosave.write_text(SCH, encoding="utf-8")
    r = run(lib, schematicPaths=[str(autosave)])
    assert r["sheetsScanned"] == ["_autosave-board.kicad_sch"]


def test_a_sheet_instantiated_four_times_counts_four_times(tmp_path, lib):
    """A four-channel design built from one reused sheet file has four of every
    part on it, which is what KiCad's own netlist and BOM report."""
    (tmp_path / "root.kicad_sch").write_text(
        sheets_sch(*(sheet_block(f"channel{i + 1}", "channel.kicad_sch") for i in range(4))),
        encoding="utf-8",
    )
    (tmp_path / "channel.kicad_sch").write_text(placements("FOG:R_0402_10K"), encoding="utf-8")
    r = run(lib, schematicPaths=[str(tmp_path)])
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] == 4
    assert r["sheetInstances"] == {"channel.kicad_sch": 4}


def test_a_flat_design_counts_each_sheet_once(project, lib):
    r = run(lib, schematicPaths=[str(project)])
    assert r["sheetInstances"] == {}
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] == 2


def test_nested_sheet_instances_multiply(tmp_path, lib):
    """Two boards, each with three of the same channel: six instances."""
    (tmp_path / "root.kicad_sch").write_text(
        sheets_sch(*(sheet_block(f"board{i + 1}", "board.kicad_sch") for i in range(2))),
        encoding="utf-8",
    )
    (tmp_path / "board.kicad_sch").write_text(
        sheets_sch(*(sheet_block(f"ch{i + 1}", "channel.kicad_sch") for i in range(3))),
        encoding="utf-8",
    )
    (tmp_path / "channel.kicad_sch").write_text(placements("FOG:R_0402_10K"), encoding="utf-8")
    r = run(lib, schematicPaths=[str(tmp_path)])
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] == 6


def test_a_sheet_cycle_does_not_hang(tmp_path, lib):
    """KiCad rejects a recursive hierarchy; a file on disk can still hold one."""
    (tmp_path / "a.kicad_sch").write_text(
        sheets_sch(sheet_block("b", "b.kicad_sch")) + placements("FOG:R_0402_10K"),
        encoding="utf-8",
    )
    (tmp_path / "b.kicad_sch").write_text(
        sheets_sch(sheet_block("a", "a.kicad_sch")), encoding="utf-8"
    )
    r = run(lib, schematicPaths=[str(tmp_path)])
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usageCount"] >= 1


def test_used_in_distinguishes_sheets_with_the_same_basename(tmp_path, lib):
    for folder in ("analog", "digital"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "power.kicad_sch").write_text(
            placements("FOG:R_0402_10K"), encoding="utf-8"
        )
    r = run(lib, schematicPaths=[str(tmp_path)])
    used = next(m for m in group_named(r, "R_0402_10K")["members"] if m["name"] == "R_0402_10K")
    assert used["usedIn"] == ["analog/power.kicad_sch", "digital/power.kicad_sch"]
    assert used["usageCount"] == 2


def test_an_escaped_quote_in_a_lib_id_still_matches(tmp_path):
    r"""A library symbol name is read unescaped, so the lib_id must be too."""
    path = tmp_path / "Odd.kicad_sym"
    path.write_text(
        "(kicad_symbol_lib\n"
        + sym('R_2\\"_LONG', {"Value": "10K", "Footprint": "f:1", "MPN": "M-1"})
        + sym("R_ALT", {"Value": "10K", "Footprint": "f:1", "MPN": "M-1"}, unit_x=2)
        + ")\n",
        encoding="utf-8",
    )
    (tmp_path / "board.kicad_sch").write_text(
        '(kicad_sch\n\t(symbol\n\t\t(lib_id "Odd:R_2\\"_LONG")\n\t)\n)\n', encoding="utf-8"
    )
    r = find_duplicate_symbols({"libraryPath": str(path), "schematicPaths": [str(tmp_path)]})
    used = next(m for m in r["groups"][0]["members"] if m["name"] == 'R_2"_LONG')
    assert used["usageCount"] == 1


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


@pytest.mark.parametrize("bad", ["abc", None, [2]])
def test_a_non_numeric_min_group_size_is_refused(lib, bad):
    """The TS layer types it as a number; the Python dispatch is reachable directly."""
    r = run(lib, minGroupSize=bad)
    assert not r["success"]
    assert "minGroupSize" in r["message"]


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
    assert r["missingPaths"] == [str(project / "ghost.kicad_sch")]


def test_a_schematic_path_that_resolves_to_nothing_is_not_read_as_unused(lib, tmp_path):
    """A typo'd directory used to produce an empty scan and a confident report
    that every member of every group could be retired."""
    typo = tmp_path / "schematiks"
    r = run(lib, schematicPaths=[str(typo)])
    assert r["success"]
    assert r["sheetsScanned"] == []
    assert r["missingPaths"] == [str(typo)]
    assert "pass schematicPaths" not in r["message"]
    assert "none of the 1 schematicPaths given exist" in r["message"]
    assert "no symbol should be retired" in r["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
