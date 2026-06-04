"""
Unit/integration tests for the hierarchy commands (commands/schematic_hierarchy.py).

The hierarchical-sheet text manipulation is exercised against real files in tmp,
and create_hierarchical_subsheet's orchestration is checked with a stub interface.
No KiCad needed.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_hierarchy import SchematicHierarchyCommands  # noqa: E402


def _cmds(iface=None):
    return SchematicHierarchyCommands(iface or types.SimpleNamespace())


class TestAddHierarchicalSheet:
    def test_requires_params(self):
        assert _cmds().add_hierarchical_sheet({"schematicPath": "/x"})["success"] is False

    def test_inserts_sheet_block(self, tmp_path):
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(
            '(kicad_sch (uuid abcd-1234)\n  (sheet_instances (path "/" (page "1")))\n)'
        )
        r = _cmds().add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(tmp_path / "sub.kicad_sch"),
                "sheetName": "Power",
            }
        )
        assert r["success"] is True
        assert r["page"] == 2  # next page after existing "1"
        content = parent.read_text()
        assert "(sheet " in content
        assert '"Sheet name" "Power"' in content
        assert '"Sheet file" "sub.kicad_sch"' in content
        # a sheet_instances path entry for the new sheet block was added
        assert f'/{ "abcd-1234" }/{ r["sheet_uuid"] }' in content


class TestCreateHierarchicalSubsheet:
    def test_orchestrates(self):
        iface = types.SimpleNamespace(
            _handle_create_schematic=lambda p: {
                "success": True,
                "file_path": p["filename"],
                "schematic_uuid": "sub-uuid",
            }
        )
        c = SchematicHierarchyCommands(iface)
        c.add_hierarchical_sheet = lambda p: {"success": True, "sheet_uuid": "blk", "page": 2}
        r = c.create_hierarchical_subsheet(
            {
                "parentSchematicPath": "/top.kicad_sch",
                "subsheetPath": "/sub.kicad_sch",
                "sheetName": "IO",
            }
        )
        assert r["success"] is True
        assert r["sheet_block_uuid"] == "blk" and r["page"] == 2

    def test_requires_params(self):
        assert (
            _cmds().create_hierarchical_subsheet({"parentSchematicPath": "/x"})["success"] is False
        )


class TestFixSubsheetInstances:
    def test_adds_path_entry(self, tmp_path):
        sub = tmp_path / "sub.kicad_sch"
        sub.write_text(
            '(kicad_sch (symbol (lib_id "Device:R")'
            ' (instances (project "proj" (path "/old" (reference "R1") (unit 1))))))'
        )
        parent = tmp_path / "top.kicad_sch"
        parent_content = (
            "(kicad_sch (uuid abcd-1234)"
            ' (sheet (at 50 50) (uuid "sheet-blk-1")'
            ' (property "Sheet name" "Sub" (at 1 1 0))'
            ' (property "Sheet file" "sub.kicad_sch" (at 1 2 0)))'
            ' (sheet_instances (path "/" (page "1"))))'
        )
        parent.write_text(parent_content)

        modified = _cmds().fix_subsheet_instances(str(parent), parent_content)
        assert str(sub) in modified
        sub_after = sub.read_text()
        assert "/abcd-1234/sheet-blk-1" in sub_after
        assert '(reference "R1")' in sub_after
