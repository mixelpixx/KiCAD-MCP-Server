"""
Unit tests for create_project returned-path normalization (issue #224).

create_project builds its returned paths with os.path.join, which on Windows
mixes separators when the caller passes a path using forward slashes (the
joined filename gets a backslash while the rest keep forward slashes). The
returned path fields should use a single, consistent separator.
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, mock_open, patch

# pcbnew is only available inside KiCAD — stub it so the project module can be
# imported in a plain Python environment.
sys.modules.setdefault("pcbnew", MagicMock())

# Import the module directly (bypasses python/commands/__init__.py which would
# otherwise pull in board/component commands that also need pcbnew/skip).
_spec = importlib.util.spec_from_file_location(
    "project_module",
    os.path.join(os.path.dirname(__file__), "..", "python", "commands", "project.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ProjectCommands = _mod.ProjectCommands


def test_create_project_returns_paths_without_mixed_separators():
    """
    Returned project/board/schematic paths must not contain backslashes
    (issue #224 reported "C:/.../EspDinIoT\\EspDinIoT.kicad_pro").
    """
    cmds = ProjectCommands()
    with patch.object(_mod, "pcbnew", MagicMock()), \
         patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", mock_open()):
        result = cmds.create_project(
            {
                "name": "EspDinIoT",
                "path": "C:/Users/piete/Source/Repos/ptr727/EspDinIoT",
            }
        )

    assert result["success"] is True, result
    project = result["project"]
    for key in ("path", "boardPath", "schematicPath"):
        value = project[key]
        assert "\\" not in value, f"{key} still has a backslash: {value!r}"

    # Sanity: the normalized paths keep their expected extensions.
    assert project["path"].endswith("EspDinIoT.kicad_pro")
    assert project["boardPath"].endswith("EspDinIoT.kicad_pcb")
    assert project["schematicPath"].endswith("EspDinIoT.kicad_sch")


def test_create_project_fallback_schematic_uses_kicad10_header():
    """
    Issue #221: when the schematic template is missing, the fallback writer in
    create_project must emit the KiCad 10 header rather than the stale KiCad 9
    (20250114) token.
    """
    cmds = ProjectCommands()
    m = mock_open()
    with patch.object(_mod, "pcbnew", MagicMock()), \
         patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", m):
        result = cmds.create_project(
            {"name": "EspDinIoT", "path": "C:/tmp/EspDinIoT"}
        )

    assert result["success"] is True, result
    written = "".join(call.args[0] for call in m().write.call_args_list)
    assert "(version 20260101)" in written, written
    assert 'generator "eeschema"' in written
    assert "20250114" not in written
