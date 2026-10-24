"""Unit tests for set_stackup_layer.

The physical stackup (copper weight, prepreg thickness, εr) is what a DC
copper solve and a near-field model both consume. These tests mock pcbnew
so they run without KiCad installed.
"""

import pytest
from commands.stackup import StackupCommands

pytestmark = pytest.mark.unit


class _Row:
    """Mutable BOARD_STACKUP_ITEM. Thicknesses are nanometres, keyed by sublayer."""

    def __init__(
        self, type_id, layer_id, thickness, sublayers=1, epsilon=None, loss=None, material=None
    ):
        self.type_id = type_id
        self.layer_id = layer_id
        if isinstance(thickness, dict):
            self.thickness = dict(thickness)
        else:
            self.thickness = {0: thickness}
        self.sublayers = sublayers
        self.epsilon = epsilon
        self.loss = loss
        self.material = material

    def GetType(self):
        return self.type_id

    def GetBrdLayerId(self):
        return self.layer_id

    def GetSublayersCount(self):
        return self.sublayers

    def GetThickness(self, index=0):
        return self.thickness[index]

    def SetThickness(self, nm, index=0):
        self.thickness[index] = nm

    def GetEpsilonR(self, index=0):
        del index
        return self.epsilon

    def SetEpsilonR(self, value, index=0):
        if index != 0:
            raise AssertionError(index)
        self.epsilon = value

    def GetLossTangent(self, index=0):
        del index
        return self.loss

    def SetLossTangent(self, value, index=0):
        if index != 0:
            raise AssertionError(index)
        self.loss = value

    def GetMaterial(self, index=0):
        del index
        return self.material

    def SetMaterial(self, value, index=0):
        if index != 0:
            raise AssertionError(index)
        self.material = value


class _Settings:
    def __init__(self, items, board_nm):
        self.items = items
        self.board_nm = board_nm

    def GetStackup(self):
        return self

    def GetCount(self):
        return len(self.items)

    def GetLayer(self, index):
        return self.items[index]

    def GetBoardThickness(self):
        return self.board_nm

    def SetBoardThickness(self, nm):
        self.board_nm = nm


def _commands(items, names, board_nm=1_610_000):
    settings = _Settings(items, board_nm)

    class _Board:
        def GetDesignSettings(self):
            return settings

        def GetLayerName(self, layer_id):
            return names[layer_id]

    return StackupCommands(_Board()), settings


def test_renamed_copper_takes_a_new_thickness_and_the_board_tracks_it():
    """0.018 mm is half-ounce copper. The stored board thickness follows the stackup sum."""
    top = _Row(1, 0, 35_000)
    gap = _Row(2, -1, 139_000, epsilon=4.5, loss=0.02, material="FR4")
    bottom = _Row(1, 31, 35_000)
    commands, settings = _commands([top, gap, bottom], {0: "Top Side", 31: "Bottom Side"})

    result = commands.set_stackup_layer({"layer": "Top Side", "thicknessMm": 0.018})

    assert result["success"] is True
    assert result["layer"]["canonical"] == "F.Cu"
    assert result["layer"]["name"] == "Top Side"
    assert result["layer"]["thicknessMm"] == pytest.approx(0.018)
    assert top.thickness[0] == 18_000
    assert settings.board_nm == 18_000 + 139_000 + 35_000
    reread = commands.get_stackup({})
    assert reread["layers"][0]["thicknessMm"] == pytest.approx(0.018)
    assert reread["boardThicknessMm"] == pytest.approx(0.192)


def test_dielectric_material_is_written_by_index():
    gap = _Row(2, -1, 139_000, epsilon=4.5, loss=0.02, material="FR4")
    commands, _settings = _commands([gap], {})

    result = commands.set_stackup_layer(
        {"index": 0, "epsilonR": 3.8, "lossTangent": 0.015, "material": "Megtron 6"}
    )

    assert result["success"] is True
    assert result["layer"]["epsilonR"] == pytest.approx(3.8)
    assert result["layer"]["lossTangent"] == pytest.approx(0.015)
    assert result["layer"]["material"] == "Megtron 6"
    assert gap.thickness[0] == 139_000


def test_sublayer_thickness_changes_only_that_piece():
    gap = _Row(2, -1, {0: 100_000, 1: 39_000}, sublayers=2, epsilon=4.0, material="FR4")
    commands, settings = _commands([gap], {}, board_nm=139_000)

    result = commands.set_stackup_layer({"index": 0, "sublayer": 1, "thicknessMm": 0.05})

    assert result["success"] is True
    assert gap.thickness == {0: 100_000, 1: 50_000}
    assert result["layer"]["thicknessMm"] == pytest.approx(0.15)
    assert settings.board_nm == 150_000


def test_dielectric_fields_on_copper_are_rejected():
    top = _Row(1, 0, 35_000)
    commands, _settings = _commands([top], {0: "F.Cu"})

    result = commands.set_stackup_layer({"layer": "F.Cu", "epsilonR": 4.5})

    assert result["success"] is False
    assert "dielectric" in result["message"]
    assert top.thickness[0] == 35_000


def test_index_and_layer_must_name_the_same_row():
    top = _Row(1, 0, 35_000)
    bottom = _Row(1, 31, 35_000)
    commands, _settings = _commands([top, bottom], {0: "F.Cu", 31: "B.Cu"})

    result = commands.set_stackup_layer({"index": 0, "layer": "B.Cu", "thicknessMm": 0.018})

    assert result["success"] is False
    assert top.thickness[0] == 35_000


def test_missing_value_is_an_error():
    top = _Row(1, 0, 35_000)
    commands, _settings = _commands([top], {0: "F.Cu"})
    result = commands.set_stackup_layer({"layer": "F.Cu"})
    assert result["success"] is False
    assert result["message"] == "Nothing to change"


def test_no_board():
    result = StackupCommands(None).set_stackup_layer({"layer": "F.Cu", "thicknessMm": 0.035})
    assert result["success"] is False
    assert result["message"] == "No board is loaded"
