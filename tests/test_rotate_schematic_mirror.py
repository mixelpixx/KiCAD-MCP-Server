"""
Unit tests for rotate_schematic_component mirror fix.

Verifies that _apply_mirror_to_symbol_sexp correctly adds, removes
and toggles (mirror x/y) in .kicad_sch S-expression files.
"""

import os
import sys
import importlib.util
import tempfile
import textwrap
from unittest.mock import patch, MagicMock

# Stub KiCad-only and server-only modules so kicad_interface can be
# imported in a plain Python environment.
_pcbnew_mock = MagicMock()
_pcbnew_mock.__file__ = "/fake/pcbnew.so"       # prevents AttributeError at module level
_pcbnew_mock.GetBuildVersion.return_value = "9.0.0"
sys.modules.setdefault("pcbnew", _pcbnew_mock)

for _modname in ("skip", "resources", "schemas",
                 "resources.resource_definitions", "schemas.tool_schemas"):
    sys.modules.setdefault(_modname, MagicMock())

sys.modules["resources.resource_definitions"].RESOURCE_DEFINITIONS = {}
sys.modules["resources.resource_definitions"].handle_resource_read = MagicMock()
sys.modules["schemas.tool_schemas"].TOOL_SCHEMAS = []

# Import KiCADInterface directly, bypassing package __init__ chains
_spec = importlib.util.spec_from_file_location(
    "kicad_interface",
    os.path.join(os.path.dirname(__file__), "..", "python", "kicad_interface.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
KiCADInterface = _mod.KiCADInterface
SchematicManager = _mod.SchematicManager

# ---------------------------------------------------------------------------
# Minimal .kicad_sch snippets
# ---------------------------------------------------------------------------

SCHEMATIC_TEMPLATE = textwrap.dedent("""\
    (kicad_sch (version 20250114) (generator "test")
      (symbol (lib_id "Transistor_BJT:MMBT3904")
              (at 75 105 0)
              (unit 1)
              (property "Reference" "Q1" (at 0 0 0))
              (property "Value" "MMBT3904" (at 0 0 0))
      )
    )
""")

SCHEMATIC_TEMPLATE_MIRRORED_X = textwrap.dedent("""\
    (kicad_sch (version 20250114) (generator "test")
      (symbol (lib_id "Transistor_BJT:MMBT3904")
              (at 75 105 0) (mirror x)
              (unit 1)
              (property "Reference" "Q1" (at 0 0 0))
              (property "Value" "MMBT3904" (at 0 0 0))
      )
    )
""")


def _write_temp_sch(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".kicad_sch")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Tests for _apply_mirror_to_symbol_sexp
# ---------------------------------------------------------------------------

def test_apply_mirror_x_adds_token():
    """mirror='x' should insert (mirror x) after the (at ...) token."""
    path = _write_temp_sch(SCHEMATIC_TEMPLATE)
    try:
        result = KiCADInterface._apply_mirror_to_symbol_sexp(path, "Q1", "x")
        assert result is True
        content = _read(path)
        assert "(mirror x)" in content
        assert "(mirror y)" not in content
    finally:
        os.unlink(path)


def test_apply_mirror_y_adds_token():
    """mirror='y' should insert (mirror y) after the (at ...) token."""
    path = _write_temp_sch(SCHEMATIC_TEMPLATE)
    try:
        result = KiCADInterface._apply_mirror_to_symbol_sexp(path, "Q1", "y")
        assert result is True
        content = _read(path)
        assert "(mirror y)" in content
        assert "(mirror x)" not in content
    finally:
        os.unlink(path)


def test_apply_mirror_none_removes_existing():
    """mirror=None should remove an existing (mirror x) token."""
    path = _write_temp_sch(SCHEMATIC_TEMPLATE_MIRRORED_X)
    try:
        result = KiCADInterface._apply_mirror_to_symbol_sexp(path, "Q1", None)
        assert result is True
        content = _read(path)
        assert "(mirror x)" not in content
        assert "(mirror y)" not in content
    finally:
        os.unlink(path)


def test_apply_mirror_x_replaces_existing_y():
    """mirror='x' should replace an existing (mirror y) without duplication."""
    path = _write_temp_sch(SCHEMATIC_TEMPLATE_MIRRORED_X.replace("mirror x", "mirror y"))
    try:
        result = KiCADInterface._apply_mirror_to_symbol_sexp(path, "Q1", "x")
        assert result is True
        content = _read(path)
        assert content.count("(mirror x)") == 1
        assert "(mirror y)" not in content
    finally:
        os.unlink(path)


def test_apply_mirror_returns_false_for_unknown_reference():
    """Should return False gracefully when reference not found."""
    path = _write_temp_sch(SCHEMATIC_TEMPLATE)
    try:
        result = KiCADInterface._apply_mirror_to_symbol_sexp(path, "U99", "x")
        assert result is False
        assert "(mirror x)" not in _read(path)
    finally:
        os.unlink(path)


def test_rotate_handler_no_mirror_still_works(tmp_path):
    """rotate_schematic_component without mirror param should not crash."""
    sch_path = str(tmp_path / "test.kicad_sch")
    with open(sch_path, "w") as f:
        f.write(SCHEMATIC_TEMPLATE)

    iface = KiCADInterface.__new__(KiCADInterface)

    with patch.object(_mod.SchematicManager, "load_schematic") as mock_load, \
         patch.object(_mod.SchematicManager, "save_schematic"):
        mock_sym = MagicMock()
        mock_sym.property.Reference.value = "Q1"
        mock_sym.at.value = [75, 105, 0]
        mock_sch = MagicMock()
        mock_sch.symbol = [mock_sym]
        mock_load.return_value = mock_sch

        result = iface._handle_rotate_schematic_component({
            "schematicPath": sch_path,
            "reference": "Q1",
            "angle": 90,
        })

    assert result["success"] is True
    assert result["angle"] == 90
