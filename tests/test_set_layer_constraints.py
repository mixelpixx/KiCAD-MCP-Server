"""Tests for issue: set_layer_constraints was registered as an MCP tool
(full Zod schema in design-rules.ts, listed in the router's "drc" category)
but had no entry in kicad_interface.py's command dispatch table — calling it
always returned {"success": false, "message": "Unknown command: ..."}.

Unlike assign_net_to_class/check_clearance (see #315), there is no pcbnew
SWIG API for per-layer DRC constraints at all — the fix writes a
project-scoped .kicad_dru custom-rules file instead of mutating a live
board. These tests exercise DesignRuleCommands.set_layer_constraints against
a mocked board (only board.GetFileName() is used, to derive the sibling
.kicad_dru path); the pure rule-text transform is covered separately in
tests/test_kicad_dru.py.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.design_rules import DesignRuleCommands  # noqa: E402
from utils.kicad_dru import build_layer_constraint_rule, rule_name_for_layer  # noqa: E402


def _board(tmp_path, filename="p.kicad_pcb"):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / filename)
    return board


def test_set_layer_constraints_success_creates_dru_file(tmp_path):
    board = _board(tmp_path)
    result = DesignRuleCommands(board).set_layer_constraints(
        {"layer": "F.Cu", "minTrackWidth": 0.2, "minClearance": 0.15}
    )
    assert result["success"] is True
    assert result["layer"] == "F.Cu"
    assert result["ruleName"] == "mcp_layer_constraint_F.Cu"
    dru = tmp_path / "p.kicad_dru"
    assert dru.exists()
    content = dru.read_text(encoding="utf-8")
    assert '(layer "F.Cu")' in content
    assert "(constraint track_width (min 0.2mm))" in content
    assert "(constraint clearance (min 0.15mm))" in content


def test_set_layer_constraints_single_param_is_sufficient(tmp_path):
    board = _board(tmp_path)
    result = DesignRuleCommands(board).set_layer_constraints({"layer": "B.Cu", "minViaDrill": 0.3})
    assert result["success"] is True
    content = (tmp_path / "p.kicad_dru").read_text(encoding="utf-8")
    assert "(constraint hole_size (min 0.3mm))" in content


def test_set_layer_constraints_second_call_replaces_not_duplicates(tmp_path):
    board = _board(tmp_path)
    cmds = DesignRuleCommands(board)
    cmds.set_layer_constraints({"layer": "F.Cu", "minTrackWidth": 0.1})
    cmds.set_layer_constraints({"layer": "F.Cu", "minTrackWidth": 0.3})
    content = (tmp_path / "p.kicad_dru").read_text(encoding="utf-8")
    assert content.count('rule "mcp_layer_constraint_F.Cu"') == 1
    assert "0.1mm" not in content
    assert "0.3mm" in content


def test_set_layer_constraints_different_layers_coexist(tmp_path):
    board = _board(tmp_path)
    cmds = DesignRuleCommands(board)
    cmds.set_layer_constraints({"layer": "F.Cu", "minTrackWidth": 0.2})
    cmds.set_layer_constraints({"layer": "B.Cu", "minTrackWidth": 0.3})
    content = (tmp_path / "p.kicad_dru").read_text(encoding="utf-8")
    assert 'rule "mcp_layer_constraint_F.Cu"' in content
    assert 'rule "mcp_layer_constraint_B.Cu"' in content


def test_set_layer_constraints_missing_layer_returns_error():
    result = DesignRuleCommands(MagicMock()).set_layer_constraints({"minTrackWidth": 0.2})
    assert result["success"] is False
    assert "layer" in result["errorDetails"]


def test_set_layer_constraints_no_constraints_provided_returns_error():
    result = DesignRuleCommands(MagicMock()).set_layer_constraints({"layer": "F.Cu"})
    assert result["success"] is False
    assert "errorDetails" in result


def test_set_layer_constraints_no_board_loaded():
    result = DesignRuleCommands(None).set_layer_constraints({"layer": "F.Cu", "minTrackWidth": 0.2})
    assert result["success"] is False
    assert "No board is loaded" in result["message"]


def test_set_layer_constraints_unresolvable_dru_path_fails_gracefully():
    board = MagicMock()
    board.GetFileName.return_value = ""  # no board file on disk yet
    result = DesignRuleCommands(board).set_layer_constraints(
        {"layer": "F.Cu", "minTrackWidth": 0.2}
    )
    assert result["success"] is False
    assert "errorDetails" in result


# ---------------------------------------------------------------------------
# Layer-name injection guard (added at merge time)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_layer",
    ['F.Cu" (rule "evil"', "F.Cu\\", "F.Cu)", "F.Cu(", "F.Cu\nmore"],
)
def test_layer_name_with_sexpr_metacharacters_is_rejected(bad_layer):
    """The layer name lands inside two quoted .kicad_dru tokens, so a quote,
    backslash or paren would corrupt the file AND break the by-name lookup a
    later update uses to replace the rule. Reject rather than write it."""
    cmds = DesignRuleCommands(board=MagicMock())
    result = cmds.set_layer_constraints({"layer": bad_layer, "minTrackWidth": 0.2})
    assert result["success"] is False
    assert "Invalid layer name" in result["message"]


def test_alternate_valid_layer_spellings_are_accepted(tmp_path, monkeypatch):
    """Guard against over-tightening: KiCad 10 reports "F.Silkscreen" while
    .kicad_dru and kicad-cli also accept "F.SilkS", and user layers can be
    renamed — so validation must not be an allowlist of known names."""
    for layer in ("F.Cu", "F.SilkS", "F.Silkscreen", "In1.Cu", "User.Comments"):
        rule = build_layer_constraint_rule(layer, min_track_width=0.2)
        assert f'(layer "{layer}")' in rule
        assert rule_name_for_layer(layer) in rule
