"""Tests for LibraryManagementCommands — import, export, rename.

Deletion is covered by the existing delete_symbol tool (SymbolCreator);
a structure-preservation test for it lives at the bottom of this file.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands import dynamic_symbol_loader as dsl_mod
from commands.dynamic_symbol_loader import DynamicSymbolLoader
from commands.library_management import LibraryManagementCommands
from commands.symbol_creator import SymbolCreator

SAMPLE_LIB = """(kicad_symbol_lib
\t(version 20241209)
\t(generator "test")
\t(generator_version "9.0")
\t(symbol "R_10K_0603"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (hide yes))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "R" (at 0 2.54 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Value" "10K" (at 0 -2.54 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Footprint" "Resistor_SMD:0603" (at 0 0 0)
\t\t\t(hide yes) (effects (font (size 1.27 1.27))))
\t\t(symbol "R_10K_0603_0_1"
\t\t\t(rectangle (start -2.54 1.27) (end 2.54 -1.27)
\t\t\t\t(stroke (width 0) (type default))
\t\t\t\t(fill (type none)))
\t\t)
\t\t(symbol "R_10K_0603_1_1"
\t\t\t(pin passive line (at -5.08 0 0) (length 2.54)
\t\t\t\t(name "1" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t\t(pin passive line (at 5.08 0 180) (length 2.54)
\t\t\t\t(name "2" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t\t(embedded_fonts no)
\t)
\t(symbol "C_100nF_0603"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (hide yes))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "C" (at 0 2.54 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Value" "100nF" (at 0 -2.54 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(symbol "C_100nF_0603_0_1"
\t\t\t(polyline (pts (xy -2.54 1.27) (xy 2.54 1.27))
\t\t\t\t(stroke (width 0) (type default)) (fill (type none)))
\t\t)
\t\t(symbol "C_100nF_0603_1_1"
\t\t\t(pin passive line (at -5.08 0 0) (length 2.54)
\t\t\t\t(name "1" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))
\t\t\t)
\t\t)
\t\t(embedded_fonts no)
\t)
\t(symbol "R_10K_0603_Derived"
\t\t(extends "R_10K_0603")
\t\t(property "Reference" "R" (at 0 2.54 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Value" "10K_1%" (at 0 -2.54 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t)
)
"""


def _write_lib(tmp_path: Path, name: str = "test.kicad_sym") -> Path:
    p = tmp_path / name
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write(SAMPLE_LIB)
    return p


# ── export_symbol ────────────────────────────────────────────────────


def test_export_symbol(tmp_path):
    """Export a symbol to a standalone .kicad_sym file."""
    lib = _write_lib(tmp_path)
    out = tmp_path / "exported.kicad_sym"
    cmd = LibraryManagementCommands()
    result = cmd.export_symbol(
        {
            "libraryPath": str(lib),
            "symbolName": "R_10K_0603",
            "outputPath": str(out),
        }
    )
    assert result["success"] is True
    content = out.read_text(encoding="utf-8")
    assert '(symbol "R_10K_0603"' in content
    assert '(symbol "C_100nF_0603"' not in content  # only the exported symbol
    assert content.startswith("(kicad_symbol_lib")
    assert "(version 20241209)" in content  # same token every writer here uses
    assert content.count("(") == content.count(")")


def test_export_symbol_not_found(tmp_path):
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.export_symbol(
        {
            "libraryPath": str(lib),
            "symbolName": "NonExistent",
            "outputPath": str(tmp_path / "out.kicad_sym"),
        }
    )
    assert result["success"] is False
    assert "not found" in result["error"]


# ── import_symbol ────────────────────────────────────────────────────


def test_import_symbol(tmp_path):
    """Import a symbol from one library into another (new file)."""
    lib = _write_lib(tmp_path)
    tgt = tmp_path / "target.kicad_sym"
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol(
        {
            "sourceLibraryPath": str(lib),
            "symbolName": "R_10K_0603",
            "targetLibraryPath": str(tgt),
        }
    )
    assert result["success"] is True
    content = tgt.read_text(encoding="utf-8")
    assert '(symbol "R_10K_0603"' in content
    assert "R_10K_0603_0_1" in content
    assert "R_10K_0603_1_1" in content
    assert content.count("(") == content.count(")")


def test_import_symbol_with_rename(tmp_path):
    """Import and rename in one step."""
    lib = _write_lib(tmp_path)
    tgt = tmp_path / "target.kicad_sym"
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol(
        {
            "sourceLibraryPath": str(lib),
            "symbolName": "R_10K_0603",
            "targetLibraryPath": str(tgt),
            "newName": "R_10K_0805",
        }
    )
    assert result["success"] is True
    content = tgt.read_text(encoding="utf-8")
    assert '(symbol "R_10K_0805"' in content
    assert "R_10K_0805_0_1" in content
    assert "R_10K_0805_1_1" in content
    assert "R_10K_0603" not in content


def test_import_symbol_duplicate(tmp_path):
    """Import fails without overwrite when symbol exists."""
    lib = _write_lib(tmp_path)
    tgt = _write_lib(tmp_path, "target.kicad_sym")
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol(
        {
            "sourceLibraryPath": str(lib),
            "symbolName": "R_10K_0603",
            "targetLibraryPath": str(tgt),
        }
    )
    assert result["success"] is False
    assert "already exists" in result["error"]


def test_import_symbol_overwrite(tmp_path):
    """Import with overwrite replaces existing symbol."""
    lib = _write_lib(tmp_path)
    tgt = _write_lib(tmp_path, "target.kicad_sym")
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol(
        {
            "sourceLibraryPath": str(lib),
            "symbolName": "R_10K_0603",
            "targetLibraryPath": str(tgt),
            "overwrite": True,
        }
    )
    assert result["success"] is True
    content = tgt.read_text(encoding="utf-8")
    assert content.count('(symbol "R_10K_0603"') == 1
    assert content.count("(") == content.count(")")


def test_import_refuses_bare_subsymbol(tmp_path):
    """Sub-symbol shards (R_10K_0603_0_1) are not importable units — a library
    holding a bare body/pin shard at top level is broken."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol(
        {
            "sourceLibraryPath": str(lib),
            "symbolName": "R_10K_0603_0_1",
            "targetLibraryPath": str(tmp_path / "target.kicad_sym"),
        }
    )
    assert result["success"] is False
    assert "not found" in result["error"]


def test_import_invalidates_loader_caches(tmp_path, monkeypatch):
    """Library mutations must clear the module-level resolution caches (#320)."""
    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(tmp_path))
    lib = _write_lib(tmp_path, "Src.kicad_sym")
    DynamicSymbolLoader().find_library_file("Src")  # prime the caches
    assert dsl_mod._LIB_DIRS_CACHE is not None
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol(
        {
            "sourceLibraryPath": str(lib),
            "symbolName": "R_10K_0603",
            "targetLibraryPath": str(tmp_path / "Tgt.kicad_sym"),
        }
    )
    assert result["success"] is True
    assert dsl_mod._LIB_DIRS_CACHE is None  # cleared by the write


# ── rename_symbol ────────────────────────────────────────────────────


def test_rename_symbol(tmp_path):
    """Rename a symbol and its subsymbols."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.rename_symbol(
        {
            "libraryPath": str(lib),
            "oldName": "C_100nF_0603",
            "newName": "C_100nF_0805",
        }
    )
    assert result["success"] is True
    content = lib.read_text(encoding="utf-8")
    assert '(symbol "C_100nF_0805"' in content
    assert "C_100nF_0805_0_1" in content
    assert "C_100nF_0805_1_1" in content
    assert "C_100nF_0603" not in content


def test_rename_symbol_collision(tmp_path):
    """Rename fails if target name already exists."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.rename_symbol(
        {
            "libraryPath": str(lib),
            "oldName": "R_10K_0603",
            "newName": "C_100nF_0603",
        }
    )
    assert result["success"] is False
    assert "already exists" in result["error"]


def test_rename_repoints_extends_references(tmp_path):
    """Renaming a parent must repoint derived symbols' (extends ...) —
    leaving them dangling orphans the children (#282's failure class)."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.rename_symbol(
        {
            "libraryPath": str(lib),
            "oldName": "R_10K_0603",
            "newName": "R_10K_0805",
        }
    )
    assert result["success"] is True
    assert result["extends_updated"] == 1
    content = lib.read_text(encoding="utf-8")
    assert '(extends "R_10K_0805")' in content
    assert '(extends "R_10K_0603")' not in content


# ── deletion stays with SymbolCreator.delete_symbol ──────────────────


def test_existing_delete_symbol_preserves_structure(tmp_path):
    """The canonical delete tool keeps the library balanced and intact."""
    lib = _write_lib(tmp_path)
    result = SymbolCreator().delete_symbol(library_path=str(lib), name="C_100nF_0603")
    assert result["success"] is True
    content = lib.read_text(encoding="utf-8")
    assert '(symbol "C_100nF_0603"' not in content
    assert '(symbol "R_10K_0603"' in content  # other symbols remain
    assert content.count("(") == content.count(")")
