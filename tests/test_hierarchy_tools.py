"""
Tests for add_schematic_hierarchical_label and add_sheet_pin tools.

Covers:
  - Hierarchical label insertion with correct S-expression format
  - Sheet pin insertion into the correct sheet block
  - Parameter validation (missing required fields)
  - Orientation and justification mapping
  - Sheet-not-found error handling
"""

import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    return iface


@pytest.fixture()
def iface():
    return _make_iface()


# ---------------------------------------------------------------------------
# Minimal schematic templates
# ---------------------------------------------------------------------------

_MINIMAL_SUBSHEET = textwrap.dedent("""\
    (kicad_sch
    \t(version 20231120)
    \t(generator "eeschema")
    \t(generator_version "9.0")
    \t(sheet_instances
    \t\t(path "/"
    \t\t\t(page "1")
    \t\t)
    \t)
    )
""")

_MINIMAL_PARENT = textwrap.dedent("""\
    (kicad_sch
    \t(version 20231120)
    \t(generator "eeschema")
    \t(sheet
    \t\t(at 100 50)
    \t\t(size 40 30)
    \t\t(property "Sheetname" "Storage"
    \t\t\t(at 100 49 0)
    \t\t\t(effects
    \t\t\t\t(font
    \t\t\t\t\t(size 1.27 1.27)
    \t\t\t\t)
    \t\t\t)
    \t\t)
    \t\t(property "Sheetfile" "sheets/storage.kicad_sch"
    \t\t\t(at 100 82 0)
    \t\t\t(effects
    \t\t\t\t(font
    \t\t\t\t\t(size 1.27 1.27)
    \t\t\t\t)
    \t\t\t)
    \t\t)
    \t)
    \t(sheet_instances
    \t\t(path "/"
    \t\t\t(page "1")
    \t\t)
    \t)
    )
""")

_PARENT_TWO_SHEETS = textwrap.dedent("""\
    (kicad_sch
    \t(version 20231120)
    \t(sheet
    \t\t(at 50 50)
    \t\t(size 40 30)
    \t\t(property "Sheetname" "Power"
    \t\t\t(at 50 49 0)
    \t\t\t(effects (font (size 1.27 1.27)))
    \t\t)
    \t\t(property "Sheetfile" "sheets/power.kicad_sch"
    \t\t\t(at 50 82 0)
    \t\t\t(effects (font (size 1.27 1.27)))
    \t\t)
    \t)
    \t(sheet
    \t\t(at 150 50)
    \t\t(size 40 30)
    \t\t(property "Sheetname" "Storage"
    \t\t\t(at 150 49 0)
    \t\t\t(effects (font (size 1.27 1.27)))
    \t\t)
    \t\t(property "Sheetfile" "sheets/storage.kicad_sch"
    \t\t\t(at 150 82 0)
    \t\t\t(effects (font (size 1.27 1.27)))
    \t\t)
    \t)
    \t(sheet_instances
    \t\t(path "/" (page "1"))
    \t)
    )
""")


# ===========================================================================
# Hierarchical label tests
# ===========================================================================


@pytest.mark.unit
class TestAddHierarchicalLabel:
    def test_inserts_label_into_subsheet(self, iface, tmp_path):
        sch = tmp_path / "sub.kicad_sch"
        sch.write_text(_MINIMAL_SUBSHEET)

        result = iface._handle_add_schematic_hierarchical_label(
            {
                "schematicPath": str(sch),
                "text": "SD_CLK",
                "position": [50.8, 25.4],
                "shape": "output",
            }
        )

        assert result["success"] is True
        content = sch.read_text()
        assert '(hierarchical_label "SD_CLK"' in content
        assert "(shape output)" in content
        assert "(at 50.8 25.4 0)" in content

    def test_orientation_180_uses_right_justify(self, iface, tmp_path):
        sch = tmp_path / "sub.kicad_sch"
        sch.write_text(_MINIMAL_SUBSHEET)

        result = iface._handle_add_schematic_hierarchical_label(
            {
                "schematicPath": str(sch),
                "text": "VBUS",
                "position": [10, 20],
                "shape": "input",
                "orientation": 180,
            }
        )

        assert result["success"] is True
        content = sch.read_text()
        assert "(at 10 20 180)" in content
        assert "(justify right)" in content

    def test_orientation_0_uses_left_justify(self, iface, tmp_path):
        sch = tmp_path / "sub.kicad_sch"
        sch.write_text(_MINIMAL_SUBSHEET)

        result = iface._handle_add_schematic_hierarchical_label(
            {
                "schematicPath": str(sch),
                "text": "SDA",
                "position": [30, 40],
                "shape": "bidirectional",
                "orientation": 0,
            }
        )

        assert result["success"] is True
        content = sch.read_text()
        assert "(justify left)" in content

    def test_missing_text_fails(self, iface, tmp_path):
        sch = tmp_path / "sub.kicad_sch"
        sch.write_text(_MINIMAL_SUBSHEET)

        result = iface._handle_add_schematic_hierarchical_label(
            {
                "schematicPath": str(sch),
                "position": [10, 20],
                "shape": "input",
            }
        )

        assert result["success"] is False
        assert "text" in result["message"].lower()

    def test_invalid_shape_fails(self, iface, tmp_path):
        sch = tmp_path / "sub.kicad_sch"
        sch.write_text(_MINIMAL_SUBSHEET)

        result = iface._handle_add_schematic_hierarchical_label(
            {
                "schematicPath": str(sch),
                "text": "SIG",
                "position": [10, 20],
                "shape": "passive",
            }
        )

        assert result["success"] is False

    def test_nonexistent_file_fails(self, iface, tmp_path):
        result = iface._handle_add_schematic_hierarchical_label(
            {
                "schematicPath": str(tmp_path / "nope.kicad_sch"),
                "text": "SIG",
                "position": [10, 20],
                "shape": "input",
            }
        )

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_inserts_before_sheet_instances(self, iface, tmp_path):
        sch = tmp_path / "sub.kicad_sch"
        sch.write_text(_MINIMAL_SUBSHEET)

        iface._handle_add_schematic_hierarchical_label(
            {
                "schematicPath": str(sch),
                "text": "TEST",
                "position": [10, 20],
                "shape": "input",
            }
        )

        content = sch.read_text()
        label_pos = content.find("hierarchical_label")
        instances_pos = content.find("sheet_instances")
        assert (
            label_pos < instances_pos
        ), "Hierarchical label should be inserted before sheet_instances"


# ===========================================================================
# Sheet pin tests
# ===========================================================================


@pytest.mark.unit
class TestAddSheetPin:
    def test_inserts_pin_into_correct_sheet(self, iface, tmp_path):
        sch = tmp_path / "parent.kicad_sch"
        sch.write_text(_MINIMAL_PARENT)

        result = iface._handle_add_sheet_pin(
            {
                "schematicPath": str(sch),
                "sheetName": "Storage",
                "pinName": "SD_CLK",
                "pinType": "output",
                "position": [140, 60],
            }
        )

        assert result["success"] is True
        content = sch.read_text()
        assert '(pin "SD_CLK" output' in content
        assert "(at 140 60 0)" in content

    def test_pin_in_multi_sheet_parent_targets_correct_sheet(self, iface, tmp_path):
        sch = tmp_path / "parent.kicad_sch"
        sch.write_text(_PARENT_TWO_SHEETS)

        result = iface._handle_add_sheet_pin(
            {
                "schematicPath": str(sch),
                "sheetName": "Storage",
                "pinName": "SD_D0",
                "pinType": "bidirectional",
                "position": [190, 60],
            }
        )

        assert result["success"] is True
        content = sch.read_text()
        # Pin should be inside the Storage sheet block, not the Power block
        storage_pos = content.find('"Storage"')
        pin_pos = content.find('"SD_D0"')
        power_end = content.find('"Power"')
        assert pin_pos > storage_pos, "Pin should be after Storage sheet name"

    def test_sheet_not_found_fails(self, iface, tmp_path):
        sch = tmp_path / "parent.kicad_sch"
        sch.write_text(_MINIMAL_PARENT)

        result = iface._handle_add_sheet_pin(
            {
                "schematicPath": str(sch),
                "sheetName": "NonExistent",
                "pinName": "SIG",
                "pinType": "input",
                "position": [100, 50],
            }
        )

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_missing_pin_name_fails(self, iface, tmp_path):
        sch = tmp_path / "parent.kicad_sch"
        sch.write_text(_MINIMAL_PARENT)

        result = iface._handle_add_sheet_pin(
            {
                "schematicPath": str(sch),
                "sheetName": "Storage",
                "pinType": "input",
                "position": [100, 50],
            }
        )

        assert result["success"] is False

    def test_orientation_180_uses_right_justify(self, iface, tmp_path):
        sch = tmp_path / "parent.kicad_sch"
        sch.write_text(_MINIMAL_PARENT)

        result = iface._handle_add_sheet_pin(
            {
                "schematicPath": str(sch),
                "sheetName": "Storage",
                "pinName": "VBUS",
                "pinType": "input",
                "position": [100, 60],
                "orientation": 180,
            }
        )

        assert result["success"] is True
        content = sch.read_text()
        assert "(at 100 60 180)" in content
        assert "(justify right)" in content
