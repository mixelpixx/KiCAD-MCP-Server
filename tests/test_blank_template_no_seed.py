"""
Regression tests for issue #221 (and #243):

    create_project / create_schematic seeded new files with _TEMPLATE_* symbols

New projects and schematics must start from a *blank* KiCad 10 file: an empty
``lib_symbols`` block and no placed ``_TEMPLATE_*`` symbol instances. The live
``add_schematic_component`` tool synthesizes its own ``lib_symbols`` via the
dynamic loader, so the previously pre-seeded template symbols only leaked into
user files.

These tests run the real ``shutil.copy`` + file writing against a temp dir
(only stubbing the heavy ``Schematic`` / ``pcbnew`` dependencies), then read the
produced ``.kicad_sch`` back and assert it is genuinely blank.
"""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# pcbnew and skip are only available inside KiCAD — stub them so the command
# modules can be imported in a plain Python environment.
sys.modules.setdefault("pcbnew", MagicMock())
sys.modules.setdefault("skip", MagicMock())

# project.py imports `from utils.kicad_project import ...`, which needs the
# python/ package root on sys.path.
_PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(_PYTHON_DIR))

_COMMANDS_DIR = _PYTHON_DIR / "commands"


def _load(module_name: str, filename: str):
    """Import a command module directly, bypassing python/commands/__init__.py."""
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(_COMMANDS_DIR, filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sch_mod = _load("schematic_module", "schematic.py")
_proj_mod = _load("project_module", "project.py")
SchematicManager = _sch_mod.SchematicManager
ProjectCommands = _proj_mod.ProjectCommands


def _assert_blank(sch_text: str) -> None:
    assert "_TEMPLATE_" not in sch_text, "new schematic must not seed _TEMPLATE_* symbols"
    # No placed symbol instances at all in a blank schematic.
    assert "(symbol (lib_id" not in sch_text, "new schematic must not place any symbols"
    # lib_symbols must be present but empty (no seeded Device:R/C/LED etc.).
    assert "(lib_symbols" in sch_text
    assert "Device:R" not in sch_text
    assert '(symbol "' not in sch_text, "lib_symbols must be empty"
    # And it must carry the current KiCad 10 header.
    assert "(version 20260306)" in sch_text
    assert "20250114" not in sch_text


def test_blank_template_file_is_blank():
    """The bundled blank.kicad_sch template itself is empty and KiCad 10."""
    blank = Path(__file__).parent.parent / "python" / "templates" / "blank.kicad_sch"
    _assert_blank(blank.read_text(encoding="utf-8"))


def test_create_schematic_produces_blank_file(tmp_path):
    """create_schematic copies the blank template; result has no seeded symbols."""
    with patch.object(_sch_mod, "Schematic", MagicMock()):
        SchematicManager.create_schematic("fresh", path=str(tmp_path))

    produced = tmp_path / "fresh.kicad_sch"
    assert produced.exists(), "schematic file was not written"
    _assert_blank(produced.read_text(encoding="utf-8"))


def test_create_project_produces_blank_schematic(tmp_path):
    """create_project writes a blank schematic alongside the project."""
    cmds = ProjectCommands()
    with patch.object(_proj_mod, "pcbnew", MagicMock()):
        result = cmds.create_project({"name": "Fresh", "path": str(tmp_path)})

    assert result["success"] is True, result
    produced = tmp_path / "Fresh.kicad_sch"
    assert produced.exists(), f"schematic not found at {produced}"
    _assert_blank(produced.read_text(encoding="utf-8"))
