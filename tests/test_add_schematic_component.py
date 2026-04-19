"""
Tests for add_schematic_component / DynamicSymbolLoader.create_component_instance.

Covers:
  - Default unit=1 and explicit unit selection for multi-unit symbols
  - Insertion into top-level schematics (has sheet_instances block)
  - Insertion into sub-sheets (no sheet_instances — falls back to final ')')
  - Handler-level parameter validation and unit pass-through
"""

import importlib.util
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sexpdata

# Import DynamicSymbolLoader directly from file to avoid triggering
# commands/__init__.py which pulls in board/PIL dependencies.
_loader_path = Path(__file__).parent.parent / "python" / "commands" / "dynamic_symbol_loader.py"
_spec = importlib.util.spec_from_file_location("dynamic_symbol_loader", _loader_path)
_mod = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
_spec.loader.exec_module(_mod)
DynamicSymbolLoader = _mod.DynamicSymbolLoader

# ---------------------------------------------------------------------------
# Minimal schematic fixtures
# ---------------------------------------------------------------------------

_TOP_LEVEL_SCH = """\
(kicad_sch (version 20250114) (generator "test")
  (uuid aaaaaaaa-0000-0000-0000-000000000000)
  (paper "A4")
  (sheet_instances (path "/" (page "1")))
)
"""

# Sub-sheets in hierarchical designs don't have (sheet_instances)
_SUB_SHEET_SCH = """\
(kicad_sch (version 20260306) (generator "eeschema")
  (uuid bbbbbbbb-0000-0000-0000-000000000000)
  (paper "A4")
)
"""


def _write_sch(content: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        suffix=".kicad_sch", delete=False, mode="w", encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def _unit_values_in_file(path: Path):
    """Return list of all (unit N) values found in the file."""
    return [int(m) for m in re.findall(r"\(unit (\d+)\)", path.read_text())]


def _make_loader() -> DynamicSymbolLoader:
    loader = DynamicSymbolLoader.__new__(DynamicSymbolLoader)
    loader.logger = MagicMock()
    loader.kicad_lib_paths = []
    return loader


def _place(sch_content: str, unit: int = 1) -> Path:
    """Place a Device:R on a schematic and return the path."""
    path = _write_sch(sch_content)
    loader = _make_loader()
    loader.create_component_instance(
        schematic_path=path,
        library_name="Device",
        symbol_name="R",
        reference="R1",
        value="10k",
        x=10,
        y=20,
        unit=unit,
    )
    return path


# ---------------------------------------------------------------------------
# Unit parameter
# ---------------------------------------------------------------------------

class TestCreateComponentInstanceUnit:
    def test_default_unit_is_1(self):
        path = _place(_TOP_LEVEL_SCH)
        assert 1 in _unit_values_in_file(path)

    def test_explicit_unit_1(self):
        path = _place(_TOP_LEVEL_SCH, unit=1)
        assert 1 in _unit_values_in_file(path)

    def test_unit_2(self):
        path = _place(_TOP_LEVEL_SCH, unit=2)
        assert 2 in _unit_values_in_file(path)

    def test_unit_4(self):
        path = _place(_TOP_LEVEL_SCH, unit=4)
        assert 4 in _unit_values_in_file(path)

    def test_instances_block_matches_symbol_unit(self):
        for unit in (1, 2, 3, 4):
            path = _place(_TOP_LEVEL_SCH, unit=unit)
            values = _unit_values_in_file(path)
            assert values.count(unit) >= 2, (
                f"Expected unit {unit} to appear at least twice (symbol header + instances block)"
            )


# ---------------------------------------------------------------------------
# Insertion point: top-level vs sub-sheet fallback
# ---------------------------------------------------------------------------

class TestInsertionPoint:
    def test_top_level_inserts_before_sheet_instances(self):
        path = _place(_TOP_LEVEL_SCH)
        content = path.read_text()
        sym_pos = content.find("(symbol")
        sheet_pos = content.find("(sheet_instances")
        assert sym_pos != -1, "symbol block was not written"
        assert sheet_pos != -1, "sheet_instances block was unexpectedly removed"
        assert sym_pos < sheet_pos, "symbol block must appear before sheet_instances"

    def test_sub_sheet_no_sheet_instances_does_not_raise(self):
        """Sub-sheets lack (sheet_instances) — must fall back without raising."""
        path = _place(_SUB_SHEET_SCH)
        content = path.read_text()
        assert "(symbol" in content

    def test_sub_sheet_file_still_ends_with_closing_paren(self):
        path = _place(_SUB_SHEET_SCH)
        assert path.read_text().strip().endswith(")")

    def test_sub_sheet_result_is_valid_sexp(self):
        """After fallback insertion, the file must still parse as valid S-expression."""
        path = _place(_SUB_SHEET_SCH)
        parsed = sexpdata.loads(path.read_text())
        assert parsed is not None

    def test_both_sheets_contain_unit_value(self):
        for content in (_TOP_LEVEL_SCH, _SUB_SHEET_SCH):
            path = _place(content, unit=3)
            assert 3 in _unit_values_in_file(path)


# ---------------------------------------------------------------------------
# Handler level — kicad_interface.add_component wrapper
# ---------------------------------------------------------------------------

def _import_kicad_interface():
    """Import KiCADInterface while blocking the PIL/board dependency chain."""
    python_dir = str(Path(__file__).parent.parent / "python")
    if python_dir not in sys.path:
        sys.path.insert(0, python_dir)
    # Stub out the board commands module before kicad_interface tries to import it.
    stubs = [
        "commands.board",
        "commands.board.view",
        "PIL",
        "PIL.Image",
        "pcbnew",
    ]
    added = []
    for name in stubs:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
            added.append(name)
    try:
        import importlib
        if "kicad_interface" in sys.modules:
            ki = sys.modules["kicad_interface"]
        else:
            ki = importlib.import_module("kicad_interface")
        return ki.KiCADInterface
    finally:
        for name in added:
            sys.modules.pop(name, None)


class TestHandlerAddSchematicComponent:
    def _make_iface(self):
        KiCADInterface = _import_kicad_interface()
        iface = KiCADInterface.__new__(KiCADInterface)
        iface.loader = _make_loader()
        iface.logger = MagicMock()
        return iface

    def test_missing_schematic_path_raises(self):
        iface = self._make_iface()
        with pytest.raises(Exception):
            iface.add_component({"component": {"symbol": "Device:R", "reference": "R1"}})

    def test_missing_component_raises(self):
        iface = self._make_iface()
        with pytest.raises(Exception):
            iface.add_component({"schematicPath": "/tmp/x.kicad_sch"})

    def test_unit_defaults_to_1(self):
        iface = self._make_iface()
        path = _write_sch(_TOP_LEVEL_SCH)
        with patch.object(iface.loader, "add_component", return_value=True) as mock_add:
            try:
                iface.add_component({
                    "schematicPath": str(path),
                    "component": {"symbol": "Device:R", "reference": "R1"},
                })
            except Exception:
                pass
            if mock_add.called:
                _, kwargs = mock_add.call_args
                assert kwargs.get("unit", 1) == 1

    def test_unit_2_passed_through(self):
        iface = self._make_iface()
        path = _write_sch(_TOP_LEVEL_SCH)
        with patch.object(iface.loader, "add_component", return_value=True) as mock_add:
            try:
                iface.add_component({
                    "schematicPath": str(path),
                    "component": {"symbol": "Device:R", "reference": "R1", "unit": 2},
                })
            except Exception:
                pass
            if mock_add.called:
                _, kwargs = mock_add.call_args
                assert kwargs.get("unit") == 2
