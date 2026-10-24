"""Unit tests for get_stackup.

The stackup is what a DC copper solve and a near-field model both need:
copper thickness, the dielectric gap, and the layer name stored on the
board. These tests mock pcbnew so they run without KiCad installed.
"""

from types import SimpleNamespace

import pytest
from commands.stackup import StackupCommands

pytestmark = pytest.mark.unit


def _item(type_id, layer_id, thickness_nm, **extra):
    """One BOARD_STACKUP_ITEM. Thickness is nanometres, as pcbnew returns it."""

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


def _board(items, names, board_thickness_nm=None):
    settings = SimpleNamespace(
        GetStackup=lambda: SimpleNamespace(
            GetCount=lambda: len(items), GetLayer=lambda i: items[i]
        ),
        GetBoardThickness=(lambda: board_thickness_nm) if board_thickness_nm is not None else None,
    )
    if board_thickness_nm is None:
        # Attribute missing, not a mock that would answer anything.
        del settings.GetBoardThickness
    return SimpleNamespace(
        GetDesignSettings=lambda: settings,
        GetLayerName=lambda layer_id: names[layer_id],
    )


def test_custom_names_and_dielectric_gap():
    """A renamed outer layer keeps its board name next to F.Cu, and 139 µm is 0.139 mm."""
    items = [
        _item(1, 0, 35_000),
        _item(2, -1, 139_000, epsilon=4.5, loss=0.02, material="FR4"),
        _item(1, 31, 35_000),
    ]
    names = {0: "Top Side", 31: "Bottom Side"}
    result = StackupCommands(_board(items, names, board_thickness_nm=1_610_000)).get_stackup({})

    assert result["success"] is True
    assert result["copperCount"] == 2
    assert result["boardThicknessMm"] == pytest.approx(1.61)
    top, gap, bottom = result["layers"]
    assert top["type"] == "copper"
    assert top["name"] == "Top Side"
    assert top["canonical"] == "F.Cu"
    assert top["thicknessMm"] == pytest.approx(0.035)
    assert gap["type"] == "dielectric"
    assert gap["thicknessMm"] == pytest.approx(0.139)
    assert gap["epsilonR"] == pytest.approx(4.5)
    assert gap["lossTangent"] == pytest.approx(0.02)
    assert gap["material"] == "FR4"
    assert "name" not in gap
    assert bottom["canonical"] == "B.Cu"
    assert bottom["name"] == "Bottom Side"


def test_dielectric_sublayers_are_summed():
    """Two dielectric sublayers add. The total is what a plane-to-ground gap uses."""
    gap = _item(2, -1, 0)
    gap.GetSublayersCount = lambda: 2

    def thickness(index):
        return {0: 100_000, 1: 39_000}[index]

    def epsilon(index):
        return {0: 4.0, 1: 3.5}[index]

    gap.GetThickness = thickness
    gap.GetEpsilonR = epsilon
    gap.GetLossTangent = lambda index: 0.01
    gap.GetMaterial = lambda index: "FR4" if index == 0 else "prepreg"

    result = StackupCommands(_board([gap], {})).get_stackup({})
    entry = result["layers"][0]
    assert entry["thicknessMm"] == pytest.approx(0.139)
    assert entry["sublayers"][1]["material"] == "prepreg"
    assert result["boardThicknessMm"] == pytest.approx(0.139)


def test_missing_stackup_is_an_error():
    board = SimpleNamespace(GetDesignSettings=lambda: SimpleNamespace())
    result = StackupCommands(board).get_stackup({})
    assert result["success"] is False
    assert result["message"] == "Board has no stackup"


def test_no_board():
    result = StackupCommands(None).get_stackup({})
    assert result["success"] is False
    assert result["message"] == "No board is loaded"
