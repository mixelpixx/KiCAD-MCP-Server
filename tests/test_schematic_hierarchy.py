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


class TestRemoveHierarchicalSheet:
    # A two-sheet parent in the legacy (kiutils) format: 'Sheetname'/'Sheetfile'
    # with a per-sheet (instances (project (path ...))) block; top-level
    # sheet_instances carries only the root page.
    LEGACY_PARENT = (
        "(kicad_sch (uuid root-uuid)\n"
        "  (sheet (at 38 114) (size 45 15)\n"
        "    (uuid 11111111-1111-1111-1111-111111111111)\n"
        '    (property "Sheetname" "Discovery Interface" (at 1 1 0))\n'
        '    (property "Sheetfile" "interface.kicad_sch" (at 1 2 0))\n'
        '    (instances (project "p" (path "/11111111-1111-1111-1111-111111111111" (page "2"))))\n'
        "  )\n"
        "  (sheet (at 101 114) (size 45 15)\n"
        "    (uuid 22222222-2222-2222-2222-222222222222)\n"
        '    (property "Sheetname" "Analog Mux" (at 1 1 0))\n'
        '    (property "Sheetfile" "mux.kicad_sch" (at 1 2 0))\n'
        '    (instances (project "p" (path "/22222222-2222-2222-2222-222222222222" (page "8"))))\n'
        "  )\n"
        '  (sheet_instances (path "/" (page "1")))\n'
        ")\n"
    )

    def test_requires_identifier(self, tmp_path):
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(self.LEGACY_PARENT)
        r = _cmds().remove_hierarchical_sheet({"schematicPath": str(parent)})
        assert r["success"] is False

    def test_remove_by_name_legacy_keeps_siblings(self, tmp_path):
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(self.LEGACY_PARENT)
        r = _cmds().remove_hierarchical_sheet(
            {"schematicPath": str(parent), "sheetName": "Analog Mux"}
        )
        assert r["success"] is True
        assert r["sheet_uuid"] == "22222222-2222-2222-2222-222222222222"
        content = parent.read_text()
        assert "mux.kicad_sch" not in content  # removed
        assert "Analog Mux" not in content
        assert "interface.kicad_sch" in content  # sibling preserved
        assert content.count("(sheet ") == 1

    def test_remove_by_subsheet_path_basename(self, tmp_path):
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(self.LEGACY_PARENT)
        r = _cmds().remove_hierarchical_sheet(
            {"schematicPath": str(parent), "subsheetPath": "/anywhere/mux.kicad_sch"}
        )
        assert r["success"] is True
        assert "mux.kicad_sch" not in parent.read_text()

    def test_no_match_fails(self, tmp_path):
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(self.LEGACY_PARENT)
        r = _cmds().remove_hierarchical_sheet(
            {"schematicPath": str(parent), "sheetName": "Nonexistent"}
        )
        assert r["success"] is False

    def test_roundtrip_add_then_remove_modern(self, tmp_path):
        # add_hierarchical_sheet writes the modern format with a top-level
        # sheet_instances path entry; remove must clean both the block and that entry.
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(
            '(kicad_sch (uuid abcd-1234)\n  (sheet_instances (path "/" (page "1")))\n)'
        )
        c = _cmds()
        add = c.add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(tmp_path / "power.kicad_sch"),
                "sheetName": "Power",
            }
        )
        assert add["success"] is True
        assert add["sheet_uuid"] in parent.read_text()

        rem = c.remove_hierarchical_sheet({"schematicPath": str(parent), "sheetName": "Power"})
        assert rem["success"] is True
        assert rem["removed_instance_path"] is True
        content = parent.read_text()
        assert "power.kicad_sch" not in content
        assert add["sheet_uuid"] not in content  # sheet_instances path entry gone too
        assert '(path "/" (page "1"))' in content  # root page entry preserved


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
