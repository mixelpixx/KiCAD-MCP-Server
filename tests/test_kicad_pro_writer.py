"""Conformant .kicad_pro output (issue #220).

create_project used to write a 122-byte stub with only board.filename and a
sheets entry using the literal id "root". KiCad opened it, regenerated
defaults, and discarded any intended configuration. The writer must now emit
the full structure KiCad 10 itself writes for a new project (captured from
pcbnew SETTINGS_MANAGER SaveProject output), with the sheets entry carrying
the real schematic root-sheet UUID.
"""

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("pcbnew", MagicMock())
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.utils.kicad_project import new_project_settings, write_kicad_pro  # noqa: E402

pytestmark = pytest.mark.unit

# The section set KiCad 10.0 writes for a brand-new project.
_KICAD10_TOP_LEVEL_KEYS = {
    "board",
    "boards",
    "component_class_settings",
    "cvpcb",
    "libraries",
    "meta",
    "net_settings",
    "pcbnew",
    "schematic",
    "sheets",
    "text_variables",
    "tuning_profiles",
}


class TestStructure:
    def test_full_kicad10_section_set(self):
        settings = new_project_settings("X.kicad_pro")
        assert set(settings.keys()) == _KICAD10_TOP_LEVEL_KEYS

    def test_meta_matches_kicad10(self):
        settings = new_project_settings("MyBoard.kicad_pro")
        assert settings["meta"] == {"filename": "MyBoard.kicad_pro", "version": 3}

    def test_default_netclass_present(self):
        settings = new_project_settings("X.kicad_pro")
        classes = settings["net_settings"]["classes"]
        assert len(classes) == 1
        default = classes[0]
        assert default["name"] == "Default"
        assert default["clearance"] == 0.2
        assert default["track_width"] == 0.2
        assert settings["net_settings"]["meta"]["version"] == 5

    def test_sheets_uses_real_uuid_not_literal_root(self):
        uuid = "28f865a0-4433-4a53-bbd7-b62f276848e4"
        settings = new_project_settings("X.kicad_pro", sheet_uuid=uuid)
        assert settings["sheets"] == [[uuid, "Root"]]

    def test_sheets_empty_without_uuid(self):
        assert new_project_settings("X.kicad_pro")["sheets"] == []

    def test_calls_do_not_share_state(self):
        a = new_project_settings("A.kicad_pro", sheet_uuid="u-a")
        b = new_project_settings("B.kicad_pro")
        a["net_settings"]["classes"][0]["name"] = "Mutated"
        assert b["net_settings"]["classes"][0]["name"] == "Default"
        assert b["sheets"] == []


class TestFileOutput:
    def test_write_kicad_pro_round_trips(self, tmp_path):
        out = tmp_path / "Proj.kicad_pro"
        write_kicad_pro(str(out), sheet_uuid="11111111-2222-3333-4444-555555555555")
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["meta"]["filename"] == "Proj.kicad_pro"
        assert loaded["sheets"] == [["11111111-2222-3333-4444-555555555555", "Root"]]
        assert out.read_text(encoding="utf-8").endswith("}\n")


class TestCreateProjectIntegration:
    def test_create_project_writes_conformant_pro_linked_to_schematic(self, tmp_path):
        """End-to-end through ProjectCommands with real file writes: the
        .kicad_pro must parse, carry the full structure, and its sheets uuid
        must match the root uuid actually written into the .kicad_sch."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "project_module",
            str(Path(__file__).parent.parent / "python" / "commands" / "project.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.pcbnew = MagicMock()  # board creation/saving is not under test

        result = mod.ProjectCommands().create_project({"name": "EspDinIoT", "path": str(tmp_path)})
        assert result["success"] is True, result

        pro_path = tmp_path / "EspDinIoT.kicad_pro"
        sch_path = tmp_path / "EspDinIoT.kicad_sch"
        assert pro_path.exists() and sch_path.exists()

        pro = json.loads(pro_path.read_text(encoding="utf-8"))
        assert set(pro.keys()) == _KICAD10_TOP_LEVEL_KEYS
        assert pro["meta"]["version"] == 3
        assert pro["net_settings"]["classes"][0]["name"] == "Default"

        sch_uuid_match = re.search(
            r"\(uuid ([0-9a-fA-F-]+)\)", sch_path.read_text(encoding="utf-8")
        )
        assert sch_uuid_match, "schematic has no root uuid"
        assert pro["sheets"] == [[sch_uuid_match.group(1), "Root"]]
        assert "root" not in [
            s[0] for s in pro["sheets"]
        ], "sheets must use the schematic root-sheet UUID, not the literal 'root'"
