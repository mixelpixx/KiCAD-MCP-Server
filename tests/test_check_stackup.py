"""Unit tests for check_stackup.

A recipe is the stackup a fab or a solver expects. The check reports each
field that is outside its tolerance and does not edit the board.
"""

from types import SimpleNamespace

import pytest
from commands.stackup import StackupCommands

pytestmark = pytest.mark.unit


def _item(type_id, layer_id, thickness_nm, **extra):
    def _at(index, value):
        if index != 0:
            raise AssertionError(f"unexpected sublayer {index}")
        return value

    return SimpleNamespace(
        GetType=lambda: type_id,
        GetBrdLayerId=lambda: layer_id,
        GetThickness=lambda index=0: _at(index, thickness_nm),
        GetSublayersCount=lambda: 1,
        GetEpsilonR=lambda index=0: _at(index, extra.get("epsilon")),
        GetLossTangent=lambda index=0: _at(index, extra.get("loss")),
        GetMaterial=lambda index=0: _at(index, extra.get("material")),
    )


def _commands(items, names, board_thickness_nm=1_610_000):
    settings = SimpleNamespace(
        GetStackup=lambda: SimpleNamespace(
            GetCount=lambda: len(items), GetLayer=lambda i: items[i]
        ),
        GetBoardThickness=lambda: board_thickness_nm,
    )
    board = SimpleNamespace(
        GetDesignSettings=lambda: settings,
        GetLayerName=lambda layer_id: names[layer_id],
    )
    return StackupCommands(board)


def _sample():
    items = [
        _item(1, 0, 35_000),
        _item(2, -1, 139_000, epsilon=4.5, loss=0.02, material="FR4"),
        _item(1, 31, 35_000),
    ]
    return _commands(items, {0: "Top Side", 31: "Bottom Side"})


def test_matching_recipe_is_ok():
    result = _sample().check_stackup(
        {
            "expected": [
                {"layer": "Top Side", "type": "copper", "thicknessMm": 0.035},
                {"index": 1, "type": "dielectric", "thicknessMm": 0.139, "epsilonR": 4.5},
                {"layer": "B.Cu", "type": "copper", "thicknessMm": 0.035},
            ]
        }
    )
    assert result["success"] is True
    assert result["ok"] is True
    assert result["mismatches"] == []


def test_thickness_and_epsilon_outside_tolerance():
    result = _sample().check_stackup(
        {
            "expected": [
                {"layer": "F.Cu", "thicknessMm": 0.018},
                {"index": 1, "epsilonR": 4.2},
            ]
        }
    )
    assert result["success"] is True
    assert result["ok"] is False
    by_field = {item["field"]: item for item in result["mismatches"]}
    assert by_field["thicknessMm"]["layer"] == "F.Cu"
    assert by_field["thicknessMm"]["actual"] == pytest.approx(0.035)
    assert by_field["thicknessMm"]["expected"] == pytest.approx(0.018)
    assert by_field["thicknessMm"]["delta"] == pytest.approx(0.017)
    assert by_field["epsilonR"]["delta"] == pytest.approx(0.3)


def test_one_micron_is_inside_the_default_tolerance():
    result = _sample().check_stackup({"expected": [{"layer": "Top Side", "thicknessMm": 0.0355}]})
    assert result["ok"] is True


def test_wider_tolerance_accepts_a_copper_weight_step():
    """A caller who only cares about the dielectric can loosen the copper check."""
    strict = _sample().check_stackup({"expected": [{"layer": "F.Cu", "thicknessMm": 0.018}]})
    loose = _sample().check_stackup(
        {
            "expected": [{"layer": "F.Cu", "thicknessMm": 0.018}],
            "thicknessToleranceMm": 0.02,
        }
    )
    assert strict["ok"] is False
    assert loose["ok"] is True


def test_wrong_type_and_a_missing_layer():
    result = _sample().check_stackup(
        {
            "expected": [
                {"layer": "F.Cu", "type": "dielectric"},
                {"layer": "In1.Cu", "type": "copper"},
            ]
        }
    )
    assert result["ok"] is False
    type_row, missing = result["mismatches"]
    assert type_row["field"] == "type"
    assert type_row["actual"] == "copper"
    assert type_row["expected"] == "dielectric"
    assert missing["field"] == "layer"
    assert missing["actual"] is None
    assert missing["expected"] == "In1.Cu"


def test_empty_recipe_is_an_error():
    result = _sample().check_stackup({"expected": []})
    assert result["success"] is False
    assert result["message"] == "expected must list at least one row"


def test_no_board():
    result = StackupCommands(None).check_stackup(
        {"expected": [{"layer": "F.Cu", "thicknessMm": 0.035}]}
    )
    assert result["success"] is False
    assert result["message"] == "No board is loaded"
