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

    def test_sheet_block_starts_its_own_line(self, tmp_path):
        """#298: rfind gives a raw char offset; when (sheet_instances does not
        start a line (sexpdata-written files), the sheet block used to be
        spliced mid-line, where add_sheet_pin's scan could never find it."""
        import sexpdata

        parent = tmp_path / "top.kicad_sch"
        # Everything on one line: (sheet_instances shares it with the uuid.
        parent.write_text('(kicad_sch (uuid abcd-1234) (sheet_instances (path "/" (page "1"))))')
        r = _cmds().add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(tmp_path / "sub.kicad_sch"),
                "sheetName": "Power",
            }
        )
        assert r["success"] is True
        content = parent.read_text()
        # The (sheet block must start its own line (any indentation).
        sheet_lines = [ln for ln in content.split("\n") if ln.lstrip().startswith("(sheet ")]
        assert sheet_lines, f"(sheet does not start any line:\n{content}"
        # The file must still be a single balanced s-expression.
        sexpdata.loads(content)

    def test_sheet_insertion_keeps_indented_files_intact(self, tmp_path):
        """The normal KiCad-written shape ((sheet_instances starts a line)
        must keep working and stay balanced."""
        import sexpdata

        parent = tmp_path / "top.kicad_sch"
        parent.write_text(
            '(kicad_sch (uuid abcd-1234)\n\t(sheet_instances (path "/" (page "1")))\n)'
        )
        r = _cmds().add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(tmp_path / "sub.kicad_sch"),
                "sheetName": "IO",
            }
        )
        assert r["success"] is True
        content = parent.read_text()
        sheet_lines = [ln for ln in content.split("\n") if ln.lstrip().startswith("(sheet ")]
        assert sheet_lines
        # (sheet_instances keeps its own line and indentation
        assert any(ln.lstrip().startswith("(sheet_instances") for ln in content.split("\n"))
        sexpdata.loads(content)


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


class TestSheetProperties:
    """set_sheet_property / get_sheet_properties — custom metadata on
    (sheet ...) blocks (e.g. generator cell identity/params)."""

    def _parent_with_sheet(self, tmp_path, name="Power"):
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(
            '(kicad_sch (uuid abcd-1234)\n  (sheet_instances (path "/" (page "1")))\n)'
        )
        r = _cmds().add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(tmp_path / "sub.kicad_sch"),
                "sheetName": name,
            }
        )
        assert r["success"] is True
        return parent

    def test_requires_params(self, tmp_path):
        c = _cmds()
        assert c.set_sheet_property({})["success"] is False
        assert c.set_sheet_property({"schematicPath": "/x"})["success"] is False
        assert (
            c.set_sheet_property({"schematicPath": "/x", "sheetName": "A"})["success"]
            is False
        )
        assert (
            c.set_sheet_property(
                {"schematicPath": "/x", "sheetName": "A", "key": "K"}
            )["success"]
            is False
        )
        assert c.get_sheet_properties({})["success"] is False

    def test_builtin_keys_rejected(self, tmp_path):
        parent = self._parent_with_sheet(tmp_path)
        for key in ("Sheet name", "Sheet file", "Sheetname", "Sheetfile"):
            r = _cmds().set_sheet_property(
                {
                    "schematicPath": str(parent),
                    "sheetName": "Power",
                    "key": key,
                    "value": "x",
                }
            )
            assert r["success"] is False
            assert "built-in" in r["message"]

    def test_create_update_round_trip(self, tmp_path):
        parent = self._parent_with_sheet(tmp_path)
        before = parent.read_text()
        c = _cmds()

        r = c.set_sheet_property(
            {
                "schematicPath": str(parent),
                "sheetName": "Power",
                "key": "IS.Cell",
                "value": "vca_2164",
            }
        )
        assert r["success"] is True
        assert r["created"] is True

        # Formatting preserved: every original line still present verbatim
        after = parent.read_text()
        for line in before.splitlines():
            assert line in after, f"original line lost: {line!r}"

        g = c.get_sheet_properties({"schematicPath": str(parent), "sheetName": "Power"})
        assert g["success"] is True
        assert g["count"] == 1
        sheet = g["sheets"][0]
        assert sheet["name"] == "Power"
        assert sheet["properties"]["IS.Cell"] == "vca_2164"

        # Update in place: no duplicate property block
        r = c.set_sheet_property(
            {
                "schematicPath": str(parent),
                "sheetName": "Power",
                "key": "IS.Cell",
                "value": "svf_2164",
            }
        )
        assert r["success"] is True
        assert r["created"] is False
        content = parent.read_text()
        assert content.count('"IS.Cell"') == 1
        assert "svf_2164" in content and "vca_2164" not in content

    def test_identify_by_sheet_path(self, tmp_path):
        parent = self._parent_with_sheet(tmp_path)
        c = _cmds()
        r = c.set_sheet_property(
            {
                "schematicPath": str(parent),
                "sheetPath": "sub.kicad_sch",
                "key": "IS.Param.freq",
                "value": "440",
            }
        )
        assert r["success"] is True
        g = c.get_sheet_properties(
            {"schematicPath": str(parent), "sheetPath": "sub.kicad_sch"}
        )
        assert g["sheets"][0]["properties"]["IS.Param.freq"] == "440"

    def test_unknown_sheet_fails(self, tmp_path):
        parent = self._parent_with_sheet(tmp_path)
        r = _cmds().set_sheet_property(
            {
                "schematicPath": str(parent),
                "sheetName": "Nope",
                "key": "K",
                "value": "V",
            }
        )
        assert r["success"] is False
        assert "no (sheet" in r["message"]

    def test_get_all_sheets(self, tmp_path):
        parent = self._parent_with_sheet(tmp_path, name="Power")
        r = _cmds().add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(tmp_path / "io.kicad_sch"),
                "sheetName": "IO",
            }
        )
        assert r["success"] is True
        g = _cmds().get_sheet_properties({"schematicPath": str(parent)})
        assert g["success"] is True
        assert g["count"] == 2
        assert {s["name"] for s in g["sheets"]} == {"Power", "IO"}
        assert all(s["uuid"] for s in g["sheets"])
        assert all(s["position"]["x"] is not None for s in g["sheets"])

    def test_value_escaping(self, tmp_path):
        parent = self._parent_with_sheet(tmp_path)
        c = _cmds()
        tricky = 'quote " backslash \\ done'
        r = c.set_sheet_property(
            {
                "schematicPath": str(parent),
                "sheetName": "Power",
                "key": "IS.Note",
                "value": tricky,
            }
        )
        assert r["success"] is True
        g = c.get_sheet_properties({"schematicPath": str(parent), "sheetName": "Power"})
        assert g["sheets"][0]["properties"]["IS.Note"] == tricky
        # still parseable as an s-expression
        import sexpdata

        sexpdata.loads(parent.read_text())

    def test_kicad_cli_still_parses(self, tmp_path):
        """Render/parse check: kicad-cli must accept the modified parent."""
        import shutil as _shutil
        import subprocess

        import pytest as _pytest

        if _shutil.which("kicad-cli") is None:
            _pytest.skip("kicad-cli not available")

        template = (
            Path(__file__).parent.parent / "python" / "templates" / "blank.kicad_sch"
        )
        parent = tmp_path / "top.kicad_sch"
        parent.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        sub = tmp_path / "sub.kicad_sch"
        sub.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")

        c = _cmds()
        assert c.add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(sub),
                "sheetName": "Cell",
            }
        )["success"]
        assert c.set_sheet_property(
            {
                "schematicPath": str(parent),
                "sheetName": "Cell",
                "key": "IS.Cell",
                "value": "vca_2164",
            }
        )["success"]

        out_dir = tmp_path / "svg"
        out_dir.mkdir()
        result = subprocess.run(
            ["kicad-cli", "sch", "export", "svg", str(parent), "-o", str(out_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert list(out_dir.glob("*.svg"))
