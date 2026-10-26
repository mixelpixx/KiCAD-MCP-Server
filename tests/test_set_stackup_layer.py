"""Unit tests for set_stackup_layer.

pcbnew cannot write a BOARD_STACKUP, so the command rewrites the
``(stackup ...)`` section of the board file. A thickness change also updates
``(general (thickness ...))`` to the sum of the rows, which is what auto-save
used to miss (#222).
"""

from types import SimpleNamespace

import pytest
from commands.stackup import StackupCommands

pytestmark = pytest.mark.unit


_BOARD = """\
(kicad_pcb (version 20240108) (generator "pcbnew")
  (general
    (thickness 1.61)
  )
  (layers
    (0 "Top Side" signal)
    (2 "B.Cu" signal)
  )
  (setup
    (stackup
      (layer "F.Cu"
        (type "copper")
        (thickness 0.035)
      )
      (layer "dielectric 1"
        (type "core")
        (thickness 0.1)
        (material "FR4")
        (epsilon_r 4.5)
        (loss_tangent 0.02)
        (thickness 0.039)
        (material "prepreg")
        (epsilon_r 3.5)
        (loss_tangent 0.01)
      )
      (layer "B.Cu"
        (type "copper")
        (thickness 0.035)
      )
      (copper_finish "None")
      (dielectric_constraints no)
    )
  )
)
"""


def _commands(tmp_path, text=_BOARD):
    path = tmp_path / "board.kicad_pcb"
    path.write_text(text, encoding="utf-8")
    ids = {"F.Cu": 0, "B.Cu": 2, "Top Side": 0}
    user = {0: "Top Side", 2: "B.Cu"}
    standard = {0: "F.Cu", 2: "B.Cu"}

    def layer_id(name):
        return ids.get(name, -1)

    board = SimpleNamespace(
        GetFileName=lambda: str(path),
        GetLayerID=layer_id,
        GetLayerName=lambda layer_id: user[layer_id],
        GetStandardLayerName=lambda layer_id: standard[layer_id],
    )
    return StackupCommands(board), path


def test_renamed_copper_takes_a_new_thickness_and_the_board_tracks_it(tmp_path):
    """0.018 mm is half-ounce copper. The stored board thickness follows the stackup sum."""
    commands, path = _commands(tmp_path)
    result = commands.set_stackup_layer({"layer": "Top Side", "thicknessMm": 0.018})

    assert result["success"] is True
    assert result["layer"]["canonical"] == "F.Cu"
    assert result["layer"]["name"] == "Top Side"
    assert result["layer"]["thicknessMm"] == pytest.approx(0.018)
    text = path.read_text(encoding="utf-8")
    assert "(thickness 0.018)" in text
    assert "(thickness 0.035)" in text
    reread = commands.get_stackup({})
    assert reread["layers"][0]["thicknessMm"] == pytest.approx(0.018)
    assert reread["layers"][2]["thicknessMm"] == pytest.approx(0.035)
    assert reread["boardThicknessMm"] == pytest.approx(0.018 + 0.139 + 0.035)


def test_dielectric_material_is_written_by_index(tmp_path):
    commands, path = _commands(tmp_path)
    result = commands.set_stackup_layer(
        {"index": 1, "epsilonR": 3.8, "lossTangent": 0.015, "material": "Megtron 6"}
    )

    assert result["success"] is True
    assert result["layer"]["epsilonR"] == pytest.approx(3.8)
    assert result["layer"]["lossTangent"] == pytest.approx(0.015)
    assert result["layer"]["material"] == "Megtron 6"
    assert result["layer"]["thicknessMm"] == pytest.approx(0.139)
    text = path.read_text(encoding="utf-8")
    assert '(material "Megtron 6")' in text
    assert "(thickness 1.61)" in text


def test_sublayer_thickness_changes_only_that_piece(tmp_path):
    commands, _path = _commands(tmp_path)
    result = commands.set_stackup_layer({"index": 1, "sublayer": 1, "thicknessMm": 0.05})

    assert result["success"] is True
    assert result["layer"]["thicknessMm"] == pytest.approx(0.15)
    assert result["layer"]["sublayers"][0]["thicknessMm"] == pytest.approx(0.1)
    assert result["layer"]["sublayers"][1]["thicknessMm"] == pytest.approx(0.05)
    reread = commands.get_stackup({})
    assert reread["boardThicknessMm"] == pytest.approx(0.035 + 0.15 + 0.035)


def test_dielectric_fields_on_copper_are_rejected(tmp_path):
    commands, path = _commands(tmp_path)
    before = path.read_text(encoding="utf-8")
    result = commands.set_stackup_layer({"layer": "F.Cu", "epsilonR": 4.5})

    assert result["success"] is False
    assert "dielectric" in result["message"]
    assert path.read_text(encoding="utf-8") == before


def test_index_and_layer_must_name_the_same_row(tmp_path):
    commands, path = _commands(tmp_path)
    before = path.read_text(encoding="utf-8")
    result = commands.set_stackup_layer({"index": 0, "layer": "B.Cu", "thicknessMm": 0.018})

    assert result["success"] is False
    assert path.read_text(encoding="utf-8") == before


def test_missing_value_is_an_error(tmp_path):
    commands, _path = _commands(tmp_path)
    result = commands.set_stackup_layer({"layer": "F.Cu"})
    assert result["success"] is False
    assert result["message"] == "Nothing to change"


def test_no_board():
    result = StackupCommands(None).set_stackup_layer({"layer": "F.Cu", "thicknessMm": 0.035})
    assert result["success"] is False
    assert result["message"] == "No board is loaded"


def test_set_stackup_layer_auto_saves():
    """Without this, the edit reports success and the next save can drop it (#222)."""
    from kicad_interface import KiCADInterface

    assert "set_stackup_layer" in KiCADInterface._BOARD_MUTATING_COMMANDS
