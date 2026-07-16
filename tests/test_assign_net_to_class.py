"""Tests for issue: assign_net_to_class was registered as an MCP tool (full
Zod schema in design-rules.ts, listed in the router's "drc" category) but had
no entry in kicad_interface.py's command dispatch table — calling it always
returned {"success": false, "message": "Unknown command: assign_net_to_class"}.

Net class *membership* (which nets belong to which class) lives in
``<project>.kicad_pro`` (``net_settings.netclass_assignments``) on KiCad 7+,
the same persistence model ``create_netclass`` already uses for class
*definitions* (#185/#302). These tests exercise the pure JSON transform, the
atomic file round-trip, and the ``DesignRuleCommands.assign_net_to_class``
wiring without needing a live KiCad / SWIG board.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.design_rules import DesignRuleCommands  # noqa: E402
from commands.routing import (  # noqa: E402
    apply_net_assignment_to_project_settings,
    persist_net_assignment_to_project,
)


def _project_with_classes():
    return {
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.2},
                {"name": "Power", "clearance": 0.5},
            ],
            "netclass_assignments": {},
        }
    }


# --- pure transform -------------------------------------------------------


def test_apply_adds_new_assignment():
    data = _project_with_classes()
    apply_net_assignment_to_project_settings(data, "VCC_3V3", "Power")
    assert data["net_settings"]["netclass_assignments"]["VCC_3V3"] == ["Power"]


def test_apply_overwrites_existing_assignment_for_same_net():
    data = _project_with_classes()
    apply_net_assignment_to_project_settings(data, "VCC_3V3", "Default")
    apply_net_assignment_to_project_settings(data, "VCC_3V3", "Power")
    assert data["net_settings"]["netclass_assignments"]["VCC_3V3"] == ["Power"]


def test_apply_creates_net_settings_and_assignments_when_absent():
    data = {}
    apply_net_assignment_to_project_settings(data, "GND", "Power")
    assert data["net_settings"]["netclass_assignments"]["GND"] == ["Power"]


# --- file persistence -----------------------------------------------------


def test_persist_round_trips_through_a_real_file(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text(json.dumps(_project_with_classes()))
    result = persist_net_assignment_to_project(str(pro), "VCC_3V3", "Power")
    assert result["persisted"] is True
    assert result["projectFile"] == str(pro)
    reloaded = json.loads(pro.read_text())
    assert reloaded["net_settings"]["netclass_assignments"]["VCC_3V3"] == ["Power"]


def test_persist_preserves_unrelated_project_content(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    project = _project_with_classes()
    project["board"] = {"design_settings": {"rules": {"min_clearance": 0.1}}}
    project["net_settings"]["netclass_assignments"]["GND"] = ["Default"]
    pro.write_text(json.dumps(project))
    persist_net_assignment_to_project(str(pro), "VCC_3V3", "Power")
    reloaded = json.loads(pro.read_text())
    assert reloaded["board"]["design_settings"]["rules"]["min_clearance"] == 0.1
    assert reloaded["net_settings"]["netclass_assignments"]["GND"] == ["Default"]
    assert reloaded["net_settings"]["netclass_assignments"]["VCC_3V3"] == ["Power"]


def test_persist_writes_atomically_leaving_no_temp_file(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text(json.dumps(_project_with_classes()))
    persist_net_assignment_to_project(str(pro), "VCC_3V3", "Power")
    assert [p.name for p in tmp_path.iterdir()] == ["proj.kicad_pro"]


def test_persist_warns_when_no_project_file():
    result = persist_net_assignment_to_project(None, "VCC_3V3", "Power")
    assert result["persisted"] is False
    assert "warning" in result


def test_persist_warns_on_malformed_json_and_leaves_file_intact(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text("{not valid json")
    result = persist_net_assignment_to_project(str(pro), "VCC_3V3", "Power")
    assert result["persisted"] is False
    assert str(pro) in result["warning"]
    assert pro.read_text() == "{not valid json"  # never half-written


# --- DesignRuleCommands.assign_net_to_class wiring -------------------------


def _fake_net(name: str) -> MagicMock:
    net = MagicMock(name=f"net_{name}")
    net.SetClass = MagicMock()
    return net


def _board_with_net_and_class(tmp_path, net_name="VCC_3V3", class_name="Power"):
    pro = tmp_path / "p.kicad_pro"
    pro.write_text(json.dumps(_project_with_classes()))

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "p.kicad_pcb")

    net = _fake_net(net_name)
    nets_map = MagicMock()
    nets_map.has_key.side_effect = lambda n: n == net_name
    nets_map.__getitem__.side_effect = lambda n: net
    netinfo = MagicMock()
    netinfo.NetsByName.return_value = nets_map
    board.GetNetInfo.return_value = netinfo

    netclass = MagicMock(name=f"netclass_{class_name}")
    net_classes = {class_name: netclass}  # dict-like KiCad 9/10 style
    board.GetNetClasses.return_value = net_classes

    return board, pro, net, netclass


def test_assign_net_to_class_success(tmp_path):
    board, pro, net, netclass = _board_with_net_and_class(tmp_path)
    result = DesignRuleCommands(board).assign_net_to_class({"net": "VCC_3V3", "netClass": "Power"})
    assert result["success"] is True
    assert result["persisted"] is True
    net.SetClass.assert_called_once_with(netclass)
    reloaded = json.loads(pro.read_text())
    assert reloaded["net_settings"]["netclass_assignments"]["VCC_3V3"] == ["Power"]


def test_assign_net_to_class_missing_net_returns_error(tmp_path):
    board, _pro, _net, _netclass = _board_with_net_and_class(tmp_path)
    result = DesignRuleCommands(board).assign_net_to_class(
        {"net": "NOT_A_REAL_NET", "netClass": "Power"}
    )
    assert result["success"] is False
    assert "NOT_A_REAL_NET" in result["errorDetails"]


def test_assign_net_to_class_missing_class_returns_error(tmp_path):
    board, _pro, _net, _netclass = _board_with_net_and_class(tmp_path)
    result = DesignRuleCommands(board).assign_net_to_class(
        {"net": "VCC_3V3", "netClass": "NotARealClass"}
    )
    assert result["success"] is False
    assert "NotARealClass" in result["errorDetails"]


def test_assign_net_to_class_requires_both_params():
    result = DesignRuleCommands(MagicMock()).assign_net_to_class({"net": "VCC_3V3"})
    assert result["success"] is False


def test_assign_net_to_class_no_board_loaded():
    result = DesignRuleCommands(None).assign_net_to_class({"net": "V", "netClass": "P"})
    assert result["success"] is False
    assert "No board is loaded" in result["message"]


def test_assign_net_to_class_persists_even_when_swig_setclass_fails(tmp_path):
    board, pro, net, _netclass = _board_with_net_and_class(tmp_path)
    net.SetClass.side_effect = RuntimeError("swig boom")
    result = DesignRuleCommands(board).assign_net_to_class({"net": "VCC_3V3", "netClass": "Power"})
    assert result["success"] is True
    assert result["persisted"] is True
    assert "swig boom" in result.get("warning", "")
    reloaded = json.loads(pro.read_text())
    assert reloaded["net_settings"]["netclass_assignments"]["VCC_3V3"] == ["Power"]
