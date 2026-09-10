"""Tests for set_net_color: a net's display color override lives only in
``<project>.kicad_pro`` (``net_settings.net_colors``, a flat
``{net_name: "rgb(r, g, b)"}`` map) — there is no SWIG mirror to update,
since ``NETINFO_ITEM`` has no color getter/setter. Same persistence model
(and same historical dispatch-table pitfall, see test_assign_net_to_class.py)
as ``assign_net_to_class``.

These tests exercise the hex parser, the pure JSON transform, the atomic
file round-trip, and the ``RoutingCommands.set_net_color`` wiring without
needing a live KiCad / SWIG board.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.routing import (  # noqa: E402
    RoutingCommands,
    _hex_to_kicad_rgb,
    apply_net_color_to_project_settings,
    persist_net_color_to_project,
)


def _project_with_colors():
    return {
        "net_settings": {
            "classes": [{"name": "Default", "clearance": 0.2}],
            "net_colors": {"GND": "rgb(0, 100, 100)"},
        }
    }


# --- _hex_to_kicad_rgb ------------------------------------------------------


@pytest.mark.parametrize(
    "hex_in,expected",
    [
        ("#FF7D00", "rgb(255, 125, 0)"),
        ("FF7D00", "rgb(255, 125, 0)"),
        ("#000000", "rgb(0, 0, 0)"),
        ("#ffffff", "rgb(255, 255, 255)"),
    ],
)
def test_hex_to_kicad_rgb_valid(hex_in, expected):
    assert _hex_to_kicad_rgb(hex_in) == expected


@pytest.mark.parametrize("bad", ["", "red", "#FFF", "#GGGGGG", "#FF7D0000"])
def test_hex_to_kicad_rgb_rejects_invalid(bad):
    with pytest.raises(ValueError):
        _hex_to_kicad_rgb(bad)


# --- pure transform ----------------------------------------------------------


def test_apply_adds_new_color():
    data = _project_with_colors()
    apply_net_color_to_project_settings(data, "VCC_3V3", "rgb(255, 0, 0)")
    assert data["net_settings"]["net_colors"]["VCC_3V3"] == "rgb(255, 0, 0)"


def test_apply_overwrites_existing_color_for_same_net():
    data = _project_with_colors()
    apply_net_color_to_project_settings(data, "GND", "rgb(1, 2, 3)")
    assert data["net_settings"]["net_colors"]["GND"] == "rgb(1, 2, 3)"


def test_apply_clears_color_by_removing_the_key():
    data = _project_with_colors()
    apply_net_color_to_project_settings(data, "GND", None)
    assert "GND" not in data["net_settings"]["net_colors"]


def test_apply_clear_on_net_without_a_color_is_a_noop():
    data = _project_with_colors()
    apply_net_color_to_project_settings(data, "NOT_SET", None)
    assert "NOT_SET" not in data["net_settings"]["net_colors"]


def test_apply_creates_net_settings_and_net_colors_when_absent():
    data = {}
    apply_net_color_to_project_settings(data, "GND", "rgb(0, 100, 100)")
    assert data["net_settings"]["net_colors"]["GND"] == "rgb(0, 100, 100)"


def test_apply_handles_present_but_null_net_colors():
    """Same real-project shape as netclass_assignments: KiCad can write
    ``"net_colors": null`` when a project has no explicit overrides yet."""
    data = {"net_settings": {"net_colors": None}}
    apply_net_color_to_project_settings(data, "GND", "rgb(0, 100, 100)")
    assert data["net_settings"]["net_colors"]["GND"] == "rgb(0, 100, 100)"


def test_apply_handles_null_net_settings():
    data = {"net_settings": None}
    apply_net_color_to_project_settings(data, "GND", "rgb(0, 100, 100)")
    assert data["net_settings"]["net_colors"]["GND"] == "rgb(0, 100, 100)"


# --- file persistence ---------------------------------------------------------


def test_persist_round_trips_through_a_real_file(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text(json.dumps(_project_with_colors()))
    result = persist_net_color_to_project(str(pro), "VCC_3V3", "rgb(255, 0, 0)")
    assert result["persisted"] is True
    assert result["projectFile"] == str(pro)
    reloaded = json.loads(pro.read_text())
    assert reloaded["net_settings"]["net_colors"]["VCC_3V3"] == "rgb(255, 0, 0)"


def test_persist_preserves_unrelated_project_content(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    project = _project_with_colors()
    project["board"] = {"design_settings": {"rules": {"min_clearance": 0.1}}}
    pro.write_text(json.dumps(project))
    persist_net_color_to_project(str(pro), "VCC_3V3", "rgb(255, 0, 0)")
    reloaded = json.loads(pro.read_text())
    assert reloaded["board"]["design_settings"]["rules"]["min_clearance"] == 0.1
    assert reloaded["net_settings"]["net_colors"]["GND"] == "rgb(0, 100, 100)"
    assert reloaded["net_settings"]["net_colors"]["VCC_3V3"] == "rgb(255, 0, 0)"


def test_persist_writes_atomically_leaving_no_temp_file(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text(json.dumps(_project_with_colors()))
    persist_net_color_to_project(str(pro), "VCC_3V3", "rgb(255, 0, 0)")
    assert [p.name for p in tmp_path.iterdir()] == ["proj.kicad_pro"]


def test_persist_warns_when_no_project_file():
    result = persist_net_color_to_project(None, "VCC_3V3", "rgb(255, 0, 0)")
    assert result["persisted"] is False
    assert "warning" in result


def test_persist_warns_on_malformed_json_and_leaves_file_intact(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text("{not valid json")
    result = persist_net_color_to_project(str(pro), "VCC_3V3", "rgb(255, 0, 0)")
    assert result["persisted"] is False
    assert str(pro) in result["warning"]
    assert pro.read_text() == "{not valid json"  # never half-written


# --- RoutingCommands.set_net_color wiring -------------------------------------


def _board_with_net(tmp_path, net_name="VCC_3V3"):
    pro = tmp_path / "p.kicad_pro"
    pro.write_text(json.dumps(_project_with_colors()))

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "p.kicad_pcb")

    nets_map = MagicMock()
    nets_map.has_key.side_effect = lambda n: n == net_name
    netinfo = MagicMock()
    netinfo.NetsByName.return_value = nets_map
    board.GetNetInfo.return_value = netinfo

    return board, pro


def test_set_net_color_success(tmp_path):
    board, pro = _board_with_net(tmp_path)
    result = RoutingCommands(board).set_net_color({"net": "VCC_3V3", "color": "#FF7D00"})
    assert result["success"] is True
    assert result["persisted"] is True
    assert result["color"] == "rgb(255, 125, 0)"
    reloaded = json.loads(pro.read_text())
    assert reloaded["net_settings"]["net_colors"]["VCC_3V3"] == "rgb(255, 125, 0)"


def test_set_net_color_clear(tmp_path):
    board, pro = _board_with_net(tmp_path, net_name="GND")
    result = RoutingCommands(board).set_net_color({"net": "GND", "clear": True})
    assert result["success"] is True
    assert result["persisted"] is True
    assert result["color"] is None
    reloaded = json.loads(pro.read_text())
    assert "GND" not in reloaded["net_settings"]["net_colors"]


def test_set_net_color_missing_net_returns_error():
    result = RoutingCommands(MagicMock()).set_net_color({"color": "#FF7D00"})
    assert result["success"] is False


def test_set_net_color_missing_color_without_clear_returns_error(tmp_path):
    board, _pro = _board_with_net(tmp_path)
    result = RoutingCommands(board).set_net_color({"net": "VCC_3V3"})
    assert result["success"] is False
    assert "color" in result["errorDetails"]


def test_set_net_color_invalid_hex_returns_error(tmp_path):
    board, _pro = _board_with_net(tmp_path)
    result = RoutingCommands(board).set_net_color({"net": "VCC_3V3", "color": "not-a-color"})
    assert result["success"] is False
    assert "Invalid color" in result["message"]


def test_set_net_color_net_not_found_returns_error(tmp_path):
    board, _pro = _board_with_net(tmp_path)
    result = RoutingCommands(board).set_net_color({"net": "NOT_A_REAL_NET", "color": "#FF7D00"})
    assert result["success"] is False
    assert "NOT_A_REAL_NET" in result["errorDetails"]


def test_set_net_color_no_board_loaded():
    result = RoutingCommands(None).set_net_color({"net": "VCC_3V3", "color": "#FF7D00"})
    assert result["success"] is False
    assert "No board is loaded" in result["message"]
