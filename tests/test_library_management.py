"""Tests for LibraryManagementCommands — import, export, rename, delete."""

import importlib.util
import sys
from pathlib import Path

# Load module directly to bypass pcbnew dependency in __init__.py
_spec = importlib.util.spec_from_file_location(
    "library_management",
    Path(__file__).resolve().parent.parent / "python" / "commands" / "library_management.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
LibraryManagementCommands = _mod.LibraryManagementCommands


SAMPLE_LIB = """(kicad_symbol_lib
\t(version 20251024)
\t(generator "test")
\t(generator_version "10.0")
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
\t\t(property "Footprint" "FOG:0603S" (at 0 0 0)
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
)
"""


def _write_lib(tmp_path: Path, name: str = "test.kicad_sym") -> Path:
    p = tmp_path / name
    p.write_text(SAMPLE_LIB, encoding="utf-8", newline="\n")
    return p


# ── export_symbol ────────────────────────────────────────────────────

def test_export_symbol(tmp_path):
    """Export a symbol to a standalone .kicad_sym file."""
    lib = _write_lib(tmp_path)
    out = tmp_path / "exported.kicad_sym"
    cmd = LibraryManagementCommands()
    result = cmd.export_symbol({
        "library_path": str(lib),
        "symbol_name": "R_10K_0603",
        "output_path": str(out),
    })
    assert result["success"] is True
    content = out.read_text(encoding="utf-8")
    assert '(symbol "R_10K_0603"' in content
    assert '(symbol "C_100nF_0603"' not in content  # only the exported symbol
    assert content.startswith("(kicad_symbol_lib")


def test_export_symbol_not_found(tmp_path):
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.export_symbol({
        "library_path": str(lib),
        "symbol_name": "NonExistent",
        "output_path": str(tmp_path / "out.kicad_sym"),
    })
    assert result["success"] is False
    assert "not found" in result["error"]


# ── import_symbol ────────────────────────────────────────────────────

def test_import_symbol(tmp_path):
    """Import a symbol from one library into another (new file)."""
    lib = _write_lib(tmp_path)
    tgt = tmp_path / "target.kicad_sym"
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol({
        "source_library_path": str(lib),
        "symbol_name": "R_10K_0603",
        "target_library_path": str(tgt),
    })
    assert result["success"] is True
    content = tgt.read_text(encoding="utf-8")
    assert '(symbol "R_10K_0603"' in content
    assert "R_10K_0603_0_1" in content
    assert "R_10K_0603_1_1" in content


def test_import_symbol_with_rename(tmp_path):
    """Import and rename in one step."""
    lib = _write_lib(tmp_path)
    tgt = tmp_path / "target.kicad_sym"
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol({
        "source_library_path": str(lib),
        "symbol_name": "R_10K_0603",
        "target_library_path": str(tgt),
        "new_name": "R_10K_0805",
    })
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
    result = cmd.import_symbol({
        "source_library_path": str(lib),
        "symbol_name": "R_10K_0603",
        "target_library_path": str(tgt),
    })
    assert result["success"] is False
    assert "already exists" in result["error"]


def test_import_symbol_overwrite(tmp_path):
    """Import with overwrite replaces existing symbol."""
    lib = _write_lib(tmp_path)
    tgt = _write_lib(tmp_path, "target.kicad_sym")
    cmd = LibraryManagementCommands()
    result = cmd.import_symbol({
        "source_library_path": str(lib),
        "symbol_name": "R_10K_0603",
        "target_library_path": str(tgt),
        "overwrite": True,
    })
    assert result["success"] is True
    content = tgt.read_text(encoding="utf-8")
    # Should have exactly one R_10K_0603 block
    assert content.count('(symbol "R_10K_0603"') == 1


# ── rename_symbol ────────────────────────────────────────────────────

def test_rename_symbol(tmp_path):
    """Rename a symbol and its subsymbols."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.rename_symbol({
        "library_path": str(lib),
        "old_name": "R_10K_0603",
        "new_name": "R_10K_0805",
    })
    assert result["success"] is True
    content = lib.read_text(encoding="utf-8")
    assert '(symbol "R_10K_0805"' in content
    assert "R_10K_0805_0_1" in content
    assert "R_10K_0805_1_1" in content
    assert "R_10K_0603" not in content


def test_rename_symbol_collision(tmp_path):
    """Rename fails if target name already exists."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.rename_symbol({
        "library_path": str(lib),
        "old_name": "R_10K_0603",
        "new_name": "C_100nF_0603",
    })
    assert result["success"] is False
    assert "already exists" in result["error"]


# ── delete_symbol ────────────────────────────────────────────────────

def test_delete_symbol(tmp_path):
    """Delete a symbol from the library."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.delete_symbol({
        "library_path": str(lib),
        "symbol_name": "R_10K_0603",
    })
    assert result["success"] is True
    content = lib.read_text(encoding="utf-8")
    assert "R_10K_0603" not in content
    assert '(symbol "C_100nF_0603"' in content  # other symbols remain


def test_delete_symbol_not_found(tmp_path):
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    result = cmd.delete_symbol({
        "library_path": str(lib),
        "symbol_name": "NonExistent",
    })
    assert result["success"] is False
    assert "not found" in result["error"]


def test_delete_preserves_library_structure(tmp_path):
    """Library balance should be 0 after delete."""
    lib = _write_lib(tmp_path)
    cmd = LibraryManagementCommands()
    cmd.delete_symbol({"library_path": str(lib), "symbol_name": "R_10K_0603"})
    content = lib.read_text(encoding="utf-8")
    assert content.count("(") == content.count(")")
