"""Tests for list_library_table / remove_library_table_entry / set_library_table_uri."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands import library_tables  # noqa: E402
from commands.library import LibraryManager  # noqa: E402
from commands.library_symbol import SymbolLibraryManager  # noqa: E402
from commands.library_tables import (  # noqa: E402
    _field,
    _parse_entries,
    _parses,
    list_library_table,
    remove_library_table_entry,
    set_library_table_uri,
)
from utils.platform_helper import PlatformHelper  # noqa: E402

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


# A row containing a parenthesis inside a quoted value. Ordinary in a table
# imported from Eagle, and the case a raw "(lib" text scan turns into a phantom
# row nested inside the real one.
PAREN_IN_STRING_TABLE = """(sym_lib_table
  (version 7)
  (lib (name "Caps")(type "KiCad")(uri "${KIPRJMOD}/Caps.kicad_sym")(options "")(descr "Caps (X7R) 50V, see (lib old)"))
  (lib (name "Device")(type "KiCad")(uri "${KIPRJMOD}/Device.kicad_sym")(options "")(descr ""))
)
"""

# KiCad 10's global table: one (type "Table") row standing in for every stock
# library, rather than one row per library.
TABLE_REF_TABLE = """(sym_lib_table
  (version 7)
  (lib (name "KiCad")(type "Table")(uri "${KIPRJMOD}/stock/sym-lib-table")(options "")(descr "KiCad standard libraries"))
  (lib (name "house")(type "KiCad")(uri "${KIPRJMOD}/house.kicad_sym")(options "")(descr ""))
)
"""

STOCK_TABLE = """(sym_lib_table
  (version 7)
  (lib (name "4xxx")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/4xxx.kicad_sym")(options "")(descr ""))
  (lib (name "Device")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/Device.kicad_sym")(options "")(descr ""))
  (lib (name "Relay")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/Relay.kicad_sym")(options "")(descr ""))
)
"""

# A global table, used only ever as a COPY inside tmp_path. The suite must never
# write to the real %APPDATA%/kicad tables -- they are the live KiCad config for
# every project on the machine.
GLOBAL_TABLE = """(sym_lib_table
  (version 7)
  (lib (name "stock")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/stock.kicad_sym")(options "")(descr ""))
  (lib (name "bogus")(type "KiCad")(uri "${KIPRJMOD}/bogus.kicad_sym")(options "")(descr ""))
)
"""


@pytest.fixture(autouse=True)
def no_installed_kicad(monkeypatch):
    """Make URI resolution independent of whether this machine has KiCad.

    ``${KICAD*_SYMBOL_DIR}`` and friends resolve against the discovered install,
    so on a developer box they resolve and on a CI runner they do not. Default
    them to absent and let the tests that care install a fake directory.
    """
    monkeypatch.setattr(SymbolLibraryManager, "_find_kicad_symbol_dir", lambda self: None)
    monkeypatch.setattr(SymbolLibraryManager, "_find_3rd_party_dir", lambda self: None)
    monkeypatch.setattr(LibraryManager, "_find_kicad_footprint_dir", lambda self: None)
    monkeypatch.setattr(LibraryManager, "_find_kicad_3rdparty_dir", lambda self: None)
    monkeypatch.setattr(PlatformHelper, "load_kicad_env_vars", staticmethod(dict))


@pytest.fixture
def fake_global(tmp_path, monkeypatch):
    """A COPY of a global table in a fake KiCad config dir, for scope='global'."""
    config = tmp_path / "kicad-config" / "10.0"
    config.mkdir(parents=True)
    (config / "sym-lib-table").write_text(GLOBAL_TABLE, encoding="utf-8")
    monkeypatch.setattr(library_tables, "_kicad_config_dirs", lambda: [config])
    return config


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


def test_a_paren_inside_a_quoted_field_is_not_a_row():
    """`(lib old)` inside a description is text, not a third entry."""
    entries = _parse_entries(PAREN_IN_STRING_TABLE)
    assert [e["name"] for e in entries] == ["Caps", "Device"]
    assert entries[0]["descr"] == "Caps (X7R) 50V, see (lib old)"


def test_row_spans_never_nest():
    """A phantom row's span sits inside a real one, which double-cuts on remove."""
    entries = _parse_entries(PAREN_IN_STRING_TABLE)
    for earlier, later in zip(entries, entries[1:]):
        assert earlier["end"] <= later["start"]


def test_field_reads_a_value_containing_parens():
    block = '(lib (name "a")(uri "x")(descr "see (lib old) and (b)"))'
    assert _field(block, "descr") == "see (lib old) and (b)"
    assert _field(block, "name") == "a"


def test_field_tolerates_a_space_before_the_closing_paren():
    assert _field('(lib (uri "x.kicad_sym" ))', "uri") == "x.kicad_sym"


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


def test_list_does_not_claim_an_unresolved_variable_exists(tmp_path):
    """A variable nothing defines must not be reported as a literal path."""
    (tmp_path / "sym-lib-table").write_text(
        "(sym_lib_table\n"
        '  (lib (name "mystery")(type "KiCad")'
        '(uri "${NO_SUCH_KICAD_VARIABLE}/mystery.kicad_sym")(options "")(descr ""))\n'
        ")\n",
        encoding="utf-8",
    )
    r = list_library_table({"projectPath": str(tmp_path)})
    entry = r["entries"][0]
    assert entry["exists"] is False
    assert entry["resolvedPath"] == "${NO_SUCH_KICAD_VARIABLE}/mystery.kicad_sym"


def test_list_resolves_a_stock_symbol_dir_variable(tmp_path, monkeypatch):
    """KICAD*_SYMBOL_DIR is defined inside KiCad -- it is in neither
    kicad_common.json nor the environment. Resolving from those two alone
    reports every row of a stock table as missing, which reads as an
    instruction to delete 200+ good rows."""
    stock = tmp_path / "share" / "kicad" / "symbols"
    stock.mkdir(parents=True)
    for name in ("4xxx", "Device", "Relay"):
        (stock / f"{name}.kicad_sym").write_text("(kicad_symbol_lib)", encoding="utf-8")
    monkeypatch.setattr(SymbolLibraryManager, "_find_kicad_symbol_dir", lambda self: str(stock))
    (tmp_path / "sym-lib-table").write_text(STOCK_TABLE, encoding="utf-8")

    r = list_library_table({"projectPath": str(tmp_path)})
    assert r["entryCount"] == 3
    assert r["missingCount"] == 0
    entry = next(e for e in r["entries"] if e["name"] == "Device")
    assert entry["exists"] is True
    assert entry["resolvedPath"] == str((stock / "Device.kicad_sym").resolve())
    assert "not there" not in r["message"]


def test_list_resolves_a_stock_footprint_dir_variable(tmp_path, monkeypatch):
    stock = tmp_path / "share" / "kicad" / "footprints"
    (stock / "Battery.pretty").mkdir(parents=True)
    monkeypatch.setattr(LibraryManager, "_find_kicad_footprint_dir", lambda self: str(stock))
    (tmp_path / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "Battery")(type "KiCad")'
        '(uri "${KICAD10_FOOTPRINT_DIR}/Battery.pretty")(options "")(descr ""))\n'
        ")\n",
        encoding="utf-8",
    )
    r = list_library_table({"projectPath": str(tmp_path), "tableType": "footprint"})
    assert r["missingCount"] == 0
    assert r["entries"][0]["exists"] is True


def test_list_reports_a_paren_in_a_description_as_one_row(tmp_path):
    (tmp_path / "sym-lib-table").write_text(PAREN_IN_STRING_TABLE, encoding="utf-8")
    r = list_library_table({"projectPath": str(tmp_path)})
    assert r["entryCount"] == 2
    assert names(r) == ["Caps", "Device"]


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


# --- (type "Table") indirection -------------------------------------------- #


@pytest.fixture
def table_ref(tmp_path):
    (tmp_path / "sym-lib-table").write_text(TABLE_REF_TABLE, encoding="utf-8")
    stock = tmp_path / "stock"
    stock.mkdir()
    (stock / "sym-lib-table").write_text(STOCK_TABLE, encoding="utf-8")
    return tmp_path


def test_list_flags_a_table_reference_and_counts_what_it_stands_for(table_ref):
    r = list_library_table({"projectPath": str(table_ref)})
    entry = next(e for e in r["entries"] if e["name"] == "KiCad")
    assert entry["isTableReference"] is True
    assert entry["includedLibraryCount"] == 3
    assert r["tableReferenceCount"] == 1
    assert r["referencedLibraryCount"] == 3
    assert 'type "Table"' in r["message"]


def test_list_does_not_flag_an_ordinary_row_as_a_table_reference(table_ref):
    r = list_library_table({"projectPath": str(table_ref)})
    entry = next(e for e in r["entries"] if e["name"] == "house")
    assert "isTableReference" not in entry
    assert r["tableReferenceCount"] == 1


def test_removing_a_table_reference_reports_the_blast_radius(table_ref):
    r = remove_library_table_entry({"projectPath": str(table_ref), "libraryName": "KiCad"})
    assert r["success"]
    assert r["tableReferencesRemoved"] == ["KiCad"]
    assert r["referencedLibraryCount"] == 3
    assert "WARNING" in r["message"]
    assert '(type "Table")' in r["message"]
    assert "3 libraries" in r["message"]


def test_removing_an_ordinary_row_carries_no_table_warning(table_ref):
    r = remove_library_table_entry({"projectPath": str(table_ref), "libraryName": "house"})
    assert r["success"]
    assert r["tableReferencesRemoved"] == []
    assert "WARNING" not in r["message"]


# --- global scope (always against a COPY, never the real KiCad config) ----- #


def test_global_scope_resolves_through_the_kicad_config_dirs(fake_global):
    r = list_library_table({"scope": "global"})
    assert r["success"]
    assert r["tablePath"] == str(fake_global / "sym-lib-table")
    assert names(r) == ["stock", "bogus"]


def test_kiprjmod_is_left_unresolved_in_a_global_table(fake_global):
    """There is no project directory for a machine-wide table, so ${KIPRJMOD}
    must stay unresolved rather than silently mean the config directory."""
    r = list_library_table({"scope": "global"})
    entry = next(e for e in r["entries"] if e["name"] == "bogus")
    assert entry["resolvedPath"] == "${KIPRJMOD}/bogus.kicad_sym"
    assert entry["exists"] is False


def test_global_scope_removal_edits_the_resolved_table(fake_global):
    r = remove_library_table_entry({"scope": "global", "libraryName": "bogus"})
    assert r["success"]
    content = (fake_global / "sym-lib-table").read_text(encoding="utf-8")
    assert "bogus" not in content
    assert _parses(content)


def test_global_scope_reports_no_table_when_the_config_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(library_tables, "_kicad_config_dirs", lambda: [tmp_path / "nope"])
    r = list_library_table({"scope": "global"})
    assert not r["success"]
    assert "No global sym-lib-table found" in r["message"]


def test_kicad_config_dirs_prefers_appdata_and_the_newest_version(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    dirs = library_tables._kicad_config_dirs()
    assert dirs[0] == tmp_path / "kicad" / "10.0"
    assert tmp_path / "kicad" / "9.0" in dirs


# --- guarding tablePath ---------------------------------------------------- #


def test_refuses_a_file_that_is_not_a_library_table(tmp_path):
    """tablePath bypasses scope resolution, so without a root-token check a
    mutating call rewrites any balanced s-expression holding a (lib ...) row."""
    board = tmp_path / "board.kicad_pcb"
    original = '(kicad_pcb (lib (name "Device")(uri "x")))\n'
    board.write_text(original, encoding="utf-8")
    r = remove_library_table_entry({"tablePath": str(board), "libraryName": "Device"})
    assert not r["success"]
    assert "not a sym_lib_table" in r["message"]
    assert board.read_text(encoding="utf-8") == original


def test_refuses_a_footprint_table_asked_for_as_a_symbol_table(project):
    r = list_library_table({"tablePath": str(project / "fp-lib-table")})
    assert not r["success"]
    assert "not a sym_lib_table" in r["message"]


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


def test_remove_counts_are_right_when_a_description_holds_a_paren(tmp_path):
    """A phantom row inflates entryCount and remainingCount by one."""
    (tmp_path / "sym-lib-table").write_text(PAREN_IN_STRING_TABLE, encoding="utf-8")
    r = remove_library_table_entry({"projectPath": str(tmp_path), "libraryName": "Caps"})
    assert r["success"]
    assert r["remainingCount"] == 1
    content = (tmp_path / "sym-lib-table").read_text(encoding="utf-8")
    assert _parses(content)
    assert "Caps" not in content
    assert "Device" in content


# --- how the file is written ----------------------------------------------- #


def write_with_newline(path, text, newline):
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)


def test_removal_keeps_lf_line_endings(tmp_path):
    """A rewrite that flips the whole file to CRLF churns forever against
    KiCad's own saves; the diff is every line of a 200-row global table."""
    path = tmp_path / "sym-lib-table"
    write_with_newline(path, SYM_TABLE, "\n")
    remove_library_table_entry({"projectPath": str(tmp_path), "libraryName": "eagle_import"})
    assert b"\r\n" not in path.read_bytes()


def test_removal_keeps_crlf_line_endings(tmp_path):
    path = tmp_path / "sym-lib-table"
    write_with_newline(path, SYM_TABLE, "\r\n")
    remove_library_table_entry({"projectPath": str(tmp_path), "libraryName": "eagle_import"})
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_repoint_keeps_lf_line_endings(tmp_path):
    path = tmp_path / "sym-lib-table"
    write_with_newline(path, SYM_TABLE, "\n")
    set_library_table_uri(
        {"projectPath": str(tmp_path), "libraryName": "Device", "uri": "moved.kicad_sym"}
    )
    assert b"\r\n" not in path.read_bytes()


def test_a_failed_write_cannot_truncate_the_table(project, monkeypatch):
    """scope='global' points at the table every project on the machine loads;
    a truncated write there stops KiCad starting at all. The rename is the only
    step that touches the real file, so a failure leaves it byte-identical."""

    def boom(src, dst):
        raise OSError("simulated failure between temp file and rename")

    monkeypatch.setattr(os, "replace", boom)
    r = remove_library_table_entry({"projectPath": str(project), "libraryName": "eagle_import"})
    assert not r["success"]
    assert read(project) == SYM_TABLE
    assert not list(project.glob("*.mcp-tmp"))


def test_a_mutating_write_leaves_a_recoverable_backup(project):
    r = remove_library_table_entry({"projectPath": str(project), "libraryName": "eagle_import"})
    assert r["success"]
    backup = Path(r["backup"])
    assert backup.parent == project / ".mcp-backups"
    assert backup.read_text(encoding="utf-8") == SYM_TABLE


def test_repoint_leaves_a_recoverable_backup(project):
    r = set_library_table_uri(
        {"projectPath": str(project), "libraryName": "Device", "uri": "moved.kicad_sym"}
    )
    assert r["success"]
    assert Path(r["backup"]).read_text(encoding="utf-8") == SYM_TABLE


# --- dry run --------------------------------------------------------------- #


def test_remove_dry_run_reports_the_edit_without_writing(project):
    r = remove_library_table_entry(
        {"projectPath": str(project), "libraryName": "eagle_import", "dryRun": True}
    )
    assert r["success"]
    assert r["dryRun"] is True
    assert [e["name"] for e in r["removed"]] == ["eagle_import"]
    assert r["remainingCount"] == 2
    assert "Would remove" in r["message"]
    assert read(project) == SYM_TABLE
    assert not (project / ".mcp-backups").exists()


def test_remove_dry_run_still_reports_an_unknown_name(project):
    r = remove_library_table_entry(
        {"projectPath": str(project), "libraryName": "nope", "dryRun": True}
    )
    assert not r["success"]


def test_set_uri_dry_run_reports_the_edit_without_writing(project):
    r = set_library_table_uri(
        {
            "projectPath": str(project),
            "libraryName": "FOG_components",
            "uri": "${KIPRJMOD}/moved.kicad_sym",
            "dryRun": True,
        }
    )
    assert r["success"]
    assert r["dryRun"] is True
    assert r["previousUri"] == "${KIPRJMOD}/../FOG_components.kicad_sym"
    assert "would now point" in r["message"]
    assert read(project) == SYM_TABLE


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


def test_set_uri_writes_windows_backslashes_escaped(project):
    """As an re replacement template, "\\\\" means one literal backslash -- re
    undoes the doubling escape_sexpr_string just applied, and the table ends up
    holding raw \\U \\m \\l escapes inside a quoted token."""
    win = r"C:\Users\me\libs\foo.kicad_sym"
    r = set_library_table_uri({"projectPath": str(project), "libraryName": "Device", "uri": win})
    assert r["success"]
    raw = read(project)
    assert r'(uri "C:\\Users\\me\\libs\\foo.kicad_sym")' in raw
    assert _parses(raw)
    entry = next(
        e
        for e in list_library_table({"projectPath": str(project)})["entries"]
        if e["name"] == "Device"
    )
    assert entry["uri"] == win


def test_set_uri_accepts_a_path_ending_in_a_backslash(project):
    """Unescaped, the trailing backslash escapes the closing quote and the whole
    table stops parsing -- reported as a misleading 'unbalanced parentheses'."""
    r = set_library_table_uri(
        {"projectPath": str(project), "libraryName": "Device", "uri": "C:\\libs\\"}
    )
    assert r["success"], r["message"]
    assert _parses(read(project))
    entry = next(
        e
        for e in list_library_table({"projectPath": str(project)})["entries"]
        if e["name"] == "Device"
    )
    assert entry["uri"] == "C:\\libs\\"


def test_set_uri_escapes_a_quote_and_a_backslash_together(project):
    weird = 'C:\\a"b\\c.kicad_sym'
    r = set_library_table_uri({"projectPath": str(project), "libraryName": "Device", "uri": weird})
    assert r["success"]
    assert _parses(read(project))
    entry = next(
        e
        for e in list_library_table({"projectPath": str(project)})["entries"]
        if e["name"] == "Device"
    )
    assert entry["uri"] == weird


def test_set_uri_tolerates_a_space_before_the_closing_paren(tmp_path):
    """Hand-edited tables have `(uri "x" )`; that is not "no (uri ...) field"."""
    (tmp_path / "sym-lib-table").write_text(
        "(sym_lib_table\n"
        '  (lib (name "Device")(type "KiCad")(uri "old.kicad_sym" )(options "")(descr ""))\n'
        ")\n",
        encoding="utf-8",
    )
    r = set_library_table_uri(
        {"projectPath": str(tmp_path), "libraryName": "Device", "uri": "new.kicad_sym"}
    )
    assert r["success"], r["message"]
    assert r["previousUri"] == "old.kicad_sym"
    assert '(uri "new.kicad_sym")' in (tmp_path / "sym-lib-table").read_text(encoding="utf-8")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
