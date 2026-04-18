"""
Unit tests for create_schematic path parameter bug fix.

Verifies that create_schematic respects the `path` argument and writes
the schematic file to the correct directory instead of the process cwd.
"""

import os
import sys
import importlib.util
import tempfile
from unittest.mock import patch, MagicMock

# pcbnew and skip are only available inside KiCAD — stub them so the
# schematic module can be imported in a plain Python environment.
sys.modules.setdefault("pcbnew", MagicMock())
sys.modules.setdefault("skip", MagicMock())

# Import the module directly (bypasses python/commands/__init__.py which
# would otherwise pull in board/component commands that also need pcbnew).
_spec = importlib.util.spec_from_file_location(
    "schematic_module",
    os.path.join(os.path.dirname(__file__), "..", "python", "commands", "schematic.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SchematicManager = _mod.SchematicManager

_OPEN_MOCK = MagicMock(return_value=MagicMock(
    __enter__=MagicMock(return_value=MagicMock(
        read=MagicMock(return_value="(uuid 00000000-0000-0000-0000-000000000000)")
    )),
    __exit__=MagicMock(return_value=False),
))


def test_create_schematic_uses_path_argument():
    """
    create_schematic should write the .kicad_sch file inside `path`
    when that argument is provided, not in the process working directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(_mod, "Schematic") as mock_sch_cls, \
             patch("shutil.copy"), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", _OPEN_MOCK):
            mock_sch_cls.return_value = MagicMock()

            SchematicManager.create_schematic("myschematic", path=tmpdir)

            used_path = mock_sch_cls.call_args[0][0]
            assert used_path.startswith(tmpdir), (
                f"Expected path inside {tmpdir!r}, got {used_path!r}"
            )
            assert used_path.endswith("myschematic.kicad_sch")


def test_create_schematic_without_path_uses_relative():
    """
    When no path is given, behaviour is unchanged — file goes to cwd-relative name.
    """
    with patch.object(_mod, "Schematic") as mock_sch_cls, \
         patch("shutil.copy"), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", _OPEN_MOCK):
        mock_sch_cls.return_value = MagicMock()

        SchematicManager.create_schematic("myschematic")

        used_path = mock_sch_cls.call_args[0][0]
        assert used_path == "myschematic.kicad_sch"


def test_create_schematic_accepts_full_sch_filename():
    """
    If name already ends with .kicad_sch, it should not double the suffix.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(_mod, "Schematic") as mock_sch_cls, \
             patch("shutil.copy"), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", _OPEN_MOCK):
            mock_sch_cls.return_value = MagicMock()

            SchematicManager.create_schematic("myschematic.kicad_sch", path=tmpdir)

            used_path = mock_sch_cls.call_args[0][0]
            assert used_path.endswith("myschematic.kicad_sch")
            assert "myschematic.kicad_sch.kicad_sch" not in used_path
