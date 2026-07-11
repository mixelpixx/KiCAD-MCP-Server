"""Tests for create_netclass persisting net class definitions to ``.kicad_pro`` (#185).

Net class *definitions* live in ``<project>.kicad_pro`` (``net_settings.classes``),
not in the ``.kicad_pcb`` board file, on KiCad 7+. These tests exercise the pure
JSON transform, the atomic file round-trip, and the create_netclass wiring without
needing a live KiCad / SWIG board.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.commands.routing import (  # noqa: E402
    RoutingCommands,
    apply_netclass_to_project_settings,
    persist_netclass_to_project,
)


def _project_with_default():
    return {
        "net_settings": {
            "classes": [
                {
                    "name": "Default",
                    "clearance": 0.2,
                    "track_width": 0.2,
                    "via_diameter": 0.6,
                    "via_drill": 0.3,
                    "priority": 2147483647,
                }
            ],
            "netclass_patterns": [],
        }
    }


# --- pure transform -------------------------------------------------------


def test_apply_adds_class_with_mm_fields():
    data = _project_with_default()
    apply_netclass_to_project_settings(
        data, "HV", {"clearance": 0.5, "track_width": 0.4, "via_diameter": 1.0, "via_drill": 0.5}
    )
    hv = next(c for c in data["net_settings"]["classes"] if c["name"] == "HV")
    assert hv["clearance"] == 0.5
    assert hv["track_width"] == 0.4
    assert hv["via_diameter"] == 1.0
    assert hv["via_drill"] == 0.5
    # custom classes get priority 0; the Default class keeps its own
    assert hv["priority"] == 0


def test_apply_clones_default_field_shape():
    data = _project_with_default()
    apply_netclass_to_project_settings(data, "HV", {"clearance": 0.5})
    hv = next(c for c in data["net_settings"]["classes"] if c["name"] == "HV")
    assert "track_width" in hv and "via_diameter" in hv


def test_apply_creates_class_template_when_no_default():
    data = {"net_settings": {"classes": []}}
    apply_netclass_to_project_settings(data, "HV", {"clearance": 0.5})
    hv = next(c for c in data["net_settings"]["classes"] if c["name"] == "HV")
    # full KiCad-10 field set from the fallback template
    for key in ("bus_width", "track_width", "via_diameter", "via_drill", "line_style"):
        assert key in hv


def test_apply_updates_existing_class_without_duplicating():
    data = _project_with_default()
    apply_netclass_to_project_settings(data, "HV", {"clearance": 0.5})
    apply_netclass_to_project_settings(data, "HV", {"clearance": 0.8})
    hv = [c for c in data["net_settings"]["classes"] if c["name"] == "HV"]
    assert len(hv) == 1
    assert hv[0]["clearance"] == 0.8


def test_apply_creates_net_settings_when_absent():
    data = {}
    apply_netclass_to_project_settings(data, "HV", {"clearance": 0.5})
    assert data["net_settings"]["classes"][0]["name"] == "HV"


# --- file persistence -----------------------------------------------------


def test_persist_round_trips_through_a_real_file(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text(json.dumps(_project_with_default()))
    result = persist_netclass_to_project(str(pro), "HV", {"clearance": 0.5, "track_width": 0.4})
    assert result["persisted"] is True
    assert result["projectFile"] == str(pro)
    hv = next(
        c for c in json.loads(pro.read_text())["net_settings"]["classes"] if c["name"] == "HV"
    )
    assert hv["clearance"] == 0.5 and hv["track_width"] == 0.4


def test_persist_preserves_unrelated_project_and_net_settings_content(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    project = _project_with_default()
    project["board"] = {"design_settings": {"rules": {"min_clearance": 0.1}}}
    project["net_settings"]["meta"] = {"version": 4}
    project["net_settings"]["net_colors"] = {"GND": "rgba(1, 2, 3, 0.5)"}
    project["net_settings"]["netclass_assignments"] = {"GND": "Default"}
    pro.write_text(json.dumps(project))
    persist_netclass_to_project(str(pro), "HV", {"clearance": 0.5})
    reloaded = json.loads(pro.read_text())
    assert reloaded["board"]["design_settings"]["rules"]["min_clearance"] == 0.1
    assert reloaded["net_settings"]["meta"] == {"version": 4}
    assert reloaded["net_settings"]["net_colors"] == {"GND": "rgba(1, 2, 3, 0.5)"}
    assert reloaded["net_settings"]["netclass_assignments"] == {"GND": "Default"}
    default = next(c for c in reloaded["net_settings"]["classes"] if c["name"] == "Default")
    assert default["priority"] == 2147483647


def test_persist_writes_atomically_leaving_no_temp_file(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text(json.dumps(_project_with_default()))
    persist_netclass_to_project(str(pro), "HV", {"clearance": 0.5})
    assert [p.name for p in tmp_path.iterdir()] == ["proj.kicad_pro"]


def test_persist_warns_when_no_project_file():
    result = persist_netclass_to_project(None, "HV", {"clearance": 0.5})
    assert result["persisted"] is False
    assert "warning" in result


def test_persist_warns_on_malformed_json_and_leaves_file_intact(tmp_path):
    pro = tmp_path / "proj.kicad_pro"
    pro.write_text("{not valid json")
    result = persist_netclass_to_project(str(pro), "HV", {"clearance": 0.5})
    assert result["persisted"] is False
    assert str(pro) in result["warning"]
    assert pro.read_text() == "{not valid json"  # never half-written


def test_persist_warns_when_path_is_a_directory(tmp_path):
    # a directory passes os.path.exists() but open()-for-read fails -> hits the except
    result = persist_netclass_to_project(str(tmp_path), "HV", {"clearance": 0.5})
    assert result["persisted"] is False
    assert str(tmp_path) in result["warning"]


# --- create_netclass wiring ----------------------------------------------


def test_create_netclass_persists_canonical_trace_width(tmp_path):
    # Regression: a schema-conformant call (canonical "traceWidth") must reach
    # .kicad_pro as track_width, not the cloned Default's value.
    pro = tmp_path / "p.kicad_pro"
    pro.write_text(json.dumps(_project_with_default()))
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "p.kicad_pcb")
    result = RoutingCommands(board).create_netclass(
        {"name": "HV", "traceWidth": 5.0, "clearance": 0.5}
    )
    assert result["success"] is True
    assert result["persisted"] is True
    hv = next(
        c for c in json.loads(pro.read_text())["net_settings"]["classes"] if c["name"] == "HV"
    )
    assert hv["track_width"] == 5.0
    assert hv["clearance"] == 0.5


def test_create_netclass_persists_even_when_swig_path_fails(tmp_path):
    # The .kicad_pro write is SWIG-independent: a SWIG throw must not skip it.
    pro = tmp_path / "p.kicad_pro"
    pro.write_text(json.dumps(_project_with_default()))
    board = MagicMock()
    board.GetNetClasses.side_effect = RuntimeError("swig boom")
    board.GetFileName.return_value = str(tmp_path / "p.kicad_pcb")
    result = RoutingCommands(board).create_netclass(
        {"name": "HV", "traceWidth": 0.4, "clearance": 0.5}
    )
    assert result["success"] is True
    assert result["persisted"] is True
    assert "swig boom" in result.get("warning", "")
    hv = next(
        c for c in json.loads(pro.read_text())["net_settings"]["classes"] if c["name"] == "HV"
    )
    assert hv["track_width"] == 0.4


def test_create_netclass_fails_when_neither_memory_nor_disk_succeeds(tmp_path):
    board = MagicMock()
    board.GetNetClasses.side_effect = RuntimeError("swig boom")
    # sibling .kicad_pro does not exist -> persistence can't happen either
    board.GetFileName.return_value = str(tmp_path / "missing.kicad_pcb")
    result = RoutingCommands(board).create_netclass(
        {"name": "HV", "traceWidth": 0.4, "clearance": 0.5}
    )
    assert result["success"] is False
    assert "swig boom" in result["errorDetails"]
