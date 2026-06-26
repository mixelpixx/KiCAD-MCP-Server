"""
Unit tests for create_schematic path parameter bug fix.

Verifies that create_schematic respects the `path` argument and writes
the schematic file to the correct directory instead of the process cwd.
"""

import os
import sys
import importlib.util
import tempfile
from unittest.mock import patch, MagicMock, mock_open

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


def test_create_schematic_accepts_full_sch_path_in_path_arg():
    """
    Issue #242: when `path` is itself a full ".kicad_sch" file path, it must be
    used as-is and not treated as a directory (which doubled the file name into
    ".../V4.kicad_sch/V4.kicad_sch" and then failed with "No such file").
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        full_path = os.path.join(tmpdir, "V4.kicad_sch")
        with patch.object(_mod, "Schematic") as mock_sch_cls, \
             patch("shutil.copy"), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", _OPEN_MOCK):
            mock_sch_cls.return_value = MagicMock()

            SchematicManager.create_schematic("V4", path=full_path)

            used_path = mock_sch_cls.call_args[0][0]
            assert used_path == full_path, (
                f"Expected the full path {full_path!r} used as-is, got {used_path!r}"
            )
            assert "V4.kicad_sch/V4.kicad_sch" not in used_path.replace(os.sep, "/")


def test_create_schematic_fallback_writes_kicad10_header():
    """
    Issue #221: when the template file is missing, the fallback writer must emit
    the KiCad 10 schematic header, not the stale KiCad 9 (20250114) token.
    """
    m = mock_open()
    with patch.object(_mod, "Schematic"), \
         patch("shutil.copy"), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", m):
        SchematicManager.create_schematic("myschematic")

    written = "".join(call.args[0] for call in m().write.call_args_list)
    assert "(version 20260306)" in written, written
    assert 'generator "eeschema"' in written
    assert "20250114" not in written
