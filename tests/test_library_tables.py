"""Tests for list_library_table / remove_library_table_entry / set_library_table_uri."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.library_tables import (  # noqa: E402
    _parse_entries,
    _parses,
    list_library_table,
    remove_library_table_entry,
    set_library_table_uri,
)

# The compact layout KiCad writes: every field on one line, closing paren of the
# last entry on the line above the table's own.
SYM_TABLE = """(sym_lib_table
  (version 7)
  (lib (name "eagle_import")(type "KiCad")(uri "${KIPRJMOD}/eagle_import.kicad_sym")(options "")(descr ""))
  (lib (name "FOG_components")(type "KiCad")(uri "${KIPRJMOD}/../FOG_components.kicad_sym")(options "")(descr "House library"))
  (lib (name "Device")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/Device.kicad_sym")(options "")(descr ""))
)
"""

FP_TABLE = """(fp_lib_table
  (version 7)
  (lib (name "FOG_components")(type "KiCad")(uri "${KIPRJMOD}/../FOG_components.pretty")(options "")(descr ""))
)
"""

# Multi-line rows, which newer KiCad writes and which a line-based edit breaks.
MULTILINE_TABLE = """(sym_lib_table
\t(version 7)
\t(lib
\t\t(name "alpha")
\t\t(type "KiCad")
\t\t(uri "${KIPRJMOD}/alpha.kicad_sym")
\t\t(options "")
\t\t(descr "first")
\t)
\t(lib
\t\t(name "beta")
\t\t(type "KiCad")
\t\t(uri "${KIPRJMOD}/beta.kicad_sym")
\t\t(options "")
\t\t(descr "second")
\t)
)
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "sym-lib-table").write_text(SYM_TABLE, encoding="utf-8")
    (tmp_path / "fp-lib-table").write_text(FP_TABLE, encoding="utf-8")
    (tmp_path / "eagle_import.kicad_sym").write_text("(kicad_symbol_lib)", encoding="utf-8")
    (tmp_path.parent / "FOG_components.kicad_sym").write_text(
        "(kicad_symbol_lib)", encoding="utf-8"
    )
    return tmp_path


def names(result):
    return [e["name"] for e in result["entries"]]


def read(project, filename="sym-lib-table"):
    return (project / filename).read_text(encoding="utf-8")


# --- parsing --------------------------------------------------------------- #


def test_parse_entries_reads_every_field():
    entries = _parse_entries(SYM_TABLE)
    assert [e["name"] for e in entries] == ["eagle_import", "FOG_components", "Device"]
    assert entries[1]["descr"] == "House library"
    assert entries[1]["uri"] == "${KIPRJMOD}/../FOG_components.kicad_sym"


def test_parse_entries_handles_multiline_rows():
    entries = _parse_entries(MULTILINE_TABLE)
    assert [e["name"] for e in entries] == ["alpha", "beta"]
    assert entries[0]["descr"] == "first"


def test_parse_entry_spans_are_exact():
    entries = _parse_entries(SYM_TABLE)
    for entry in entries:
        block = SYM_TABLE[entry["start"] : entry["end"]]
        assert block.startswith("(lib ")
        assert block.endswith(")")
        assert _parses(block)


def test_parses_rejects_truncated_table():
    assert not _parses(SYM_TABLE.replace("\n)\n", "\n"))


# --- list ------------------------------------------------------------------ #


def test_list_reads_project_table(project):
    r = list_library_table({"projectPath": str(project)})
    assert r["success"]
    assert names(r) == ["eagle_import", "FOG_components", "Device"]
    assert r["entryCount"] == 3


def test_list_resolves_kiprjmod(project):
    r = list_library_table({"projectPath": str(project)})
    entry = next(e for e in r["entries"] if e["name"] == "eagle_import")
    assert entry["exists"] is True
    assert entry["resolvedPath"].endswith("eagle_import.kicad_sym")


def test_list_resolves_kiprjmod_parent(project):
    r = list_library_table({"projectPath": str(project)})
    entry = next(e for e in r["entries"] if e["name"] == "FOG_components")
    assert entry["exists"] is True


def test_list_flags_an_entry_whose_file_is_gone(project):
    (project / "eagle_import.kicad_sym").unlink()
    r = list_library_table({"projectPath": str(project)})
    entry = next(e for e in r["entries"] if e["name"] == "eagle_import")
    assert entry["exists"] is False
    assert r["missingCount"] >= 1
    assert "not there" in r["message"]


def test_list_does_not_claim_an_unresolved_variable_exists(project):
    """${KICAD9_SYMBOL_DIR} is unset here; it must not resolve to a bare path."""
    r = list_library_table({"projectPath": str(project)})
    entry = next(e for e in r["entries"] if e["name"] == "Device")
    assert entry["exists"] is False


def test_list_footprint_table(project):
    r = list_library_table({"projectPath": str(project), "tableType": "footprint"})
    assert names(r) == ["FOG_components"]
    assert r["tableType"] == "footprint"


def test_list_accepts_an_explicit_table_path(project):
    r = list_library_table({"tablePath": str(project / "sym-lib-table")})
    assert r["success"]
    assert len(names(r)) == 3


def test_list_rejects_unknown_table_type(project):
    r = list_library_table({"projectPath": str(project), "tableType": "netclass"})
    assert not r["success"]
    assert "tableType" in r["message"]


def test_list_requires_project_path():
    r = list_library_table({})
    assert not r["success"]


def test_list_missing_table(tmp_path):
    r = list_library_table({"projectPath": str(tmp_path)})
    assert not r["success"]
    assert "not found" in r["message"].lower()


# --- remove ---------------------------------------------------------------- #


def test_remove_drops_the_named_entry(project):
    r = remove_library_table_entry({"projectPath": str(project), "libraryName": "eagle_import"})
    assert r["success"]
    assert names(list_library_table({"projectPath": str(project)})) == [
        "FOG_components",
        "Device",
    ]


def test_remove_keeps_the_table_parseable(project):
    remove_library_table_entry({"projectPath": str(project), "libraryName": "eagle_import"})
    assert _parses(read(project))


def test_remove_leaves_no_blank_line(project):
    remove_library_table_entry({"projectPath": str(project), "libraryName": "eagle_import"})
    assert "\n\n" not in read(project)


def test_remove_the_last_entry_keeps_the_table_close(project):
    """The row before ')' -- the case a naive rstrip-and-replace corrupts."""
    r = remove_library_table_entry({"projectPath": str(project), "libraryName": "Device"})
    assert r["success"]
    content = read(project)
    assert _parses(content)
    assert content.rstrip().endswith(")")
    assert names(list_library_table({"projectPath": str(project)})) == [
        "eagle_import",
        "FOG_components",
    ]


def test_remove_several_at_once(project):
    r = remove_library_table_entry(
        {"projectPath": str(project), "libraryNames": ["eagle_import", "Device"]}
    )
    assert r["success"]
    assert sorted(e["name"] for e in r["removed"]) == ["Device", "eagle_import"]
    assert names(list_library_table({"projectPath": str(project)})) == ["FOG_components"]
    assert _parses(read(project))


def test_remove_several_from_a_multiline_table(tmp_path):
    (tmp_path / "sym-lib-table").write_text(MULTILINE_TABLE, encoding="utf-8")
    r = remove_library_table_entry(
        {"projectPath": str(tmp_path), "libraryNames": ["alpha", "beta"]}
    )
    assert r["success"]
    content = (tmp_path / "sym-lib-table").read_text(encoding="utf-8")
    assert _parses(content)
    assert "alpha" not in content
    assert "beta" not in content


def test_remove_reports_unknown_names(project):
    r = remove_library_table_entry(
        {"projectPath": str(project), "libraryNames": ["Device", "nope"]}
    )
    assert r["success"]
    assert r["notFound"] == ["nope"]


def test_remove_nothing_matching_is_an_error(project):
    r = remove_library_table_entry({"projectPath": str(project), "libraryName": "nope"})
    assert not r["success"]
    assert "eagle_import" in r["message"]
    assert read(project) == SYM_TABLE


def test_remove_requires_a_name(project):
    r = remove_library_table_entry({"projectPath": str(project)})
    assert not r["success"]


def test_remove_from_footprint_table(project):
    r = remove_library_table_entry(
        {"projectPath": str(project), "tableType": "footprint", "libraryName": "FOG_components"}
    )
    assert r["success"]
    assert _parses(read(project, "fp-lib-table"))
    assert (
        list_library_table({"projectPath": str(project), "tableType": "footprint"})["entryCount"]
        == 0
    )


# --- repoint --------------------------------------------------------------- #


def test_set_uri_repoints_an_entry(project):
    r = set_library_table_uri(
        {
            "projectPath": str(project),
            "libraryName": "FOG_components",
            "uri": "${KIPRJMOD}/FOG_components.kicad_sym",
        }
    )
    assert r["success"]
    assert r["previousUri"] == "${KIPRJMOD}/../FOG_components.kicad_sym"
    entry = next(
        e
        for e in list_library_table({"projectPath": str(project)})["entries"]
        if e["name"] == "FOG_components"
    )
    assert entry["uri"] == "${KIPRJMOD}/FOG_components.kicad_sym"


def test_set_uri_leaves_other_fields_alone(project):
    set_library_table_uri(
        {
            "projectPath": str(project),
            "libraryName": "FOG_components",
            "uri": "${KIPRJMOD}/moved.kicad_sym",
        }
    )
    entry = next(
        e
        for e in list_library_table({"projectPath": str(project)})["entries"]
        if e["name"] == "FOG_components"
    )
    assert entry["descr"] == "House library"
    assert entry["type"] == "KiCad"


def test_set_uri_leaves_other_entries_alone(project):
    set_library_table_uri(
        {
            "projectPath": str(project),
            "libraryName": "FOG_components",
            "uri": "${KIPRJMOD}/moved.kicad_sym",
        }
    )
    assert names(list_library_table({"projectPath": str(project)})) == [
        "eagle_import",
        "FOG_components",
        "Device",
    ]
    assert _parses(read(project))


def test_set_uri_warns_when_the_target_is_not_there(project):
    r = set_library_table_uri(
        {
            "projectPath": str(project),
            "libraryName": "FOG_components",
            "uri": "${KIPRJMOD}/nowhere.kicad_sym",
        }
    )
    assert r["success"]
    assert r["exists"] is False
    assert "no file exists there yet" in r["message"]


def test_set_uri_unknown_entry(project):
    r = set_library_table_uri(
        {"projectPath": str(project), "libraryName": "nope", "uri": "x.kicad_sym"}
    )
    assert not r["success"]
    assert read(project) == SYM_TABLE


def test_set_uri_requires_a_uri(project):
    r = set_library_table_uri({"projectPath": str(project), "libraryName": "Device"})
    assert not r["success"]


def test_set_uri_escapes_quotes(project):
    r = set_library_table_uri(
        {
            "projectPath": str(project),
            "libraryName": "Device",
            "uri": 'weird"name.kicad_sym',
        }
    )
    assert r["success"]
    assert _parses(read(project))
    entry = next(
        e
        for e in list_library_table({"projectPath": str(project)})["entries"]
        if e["name"] == "Device"
    )
    assert entry["uri"] == 'weird"name.kicad_sym'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
