"""Recipe comparison is an optional argument of get_stackup.

A separate check_stackup tool would spend a slot against client tool limits.
The same comparison rides along when the caller passes ``expected``.
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
  (setup
    (stackup
      (layer "F.Cu"
        (type "copper")
        (thickness 0.035)
      )
      (layer "dielectric 1"
        (type "core")
        (thickness 0.139)
        (material "FR4")
        (epsilon_r 4.5)
        (loss_tangent 0.02)
      )
      (layer "B.Cu"
        (type "copper")
        (thickness 0.035)
      )
    )
  )
)
"""


def _commands(tmp_path):
    path = tmp_path / "board.kicad_pcb"
    path.write_text(_BOARD, encoding="utf-8")
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
    return StackupCommands(board)


def test_reading_without_a_recipe_has_no_comparison(tmp_path):
    result = _commands(tmp_path).get_stackup({})
    assert result["success"] is True
    assert result["copperCount"] == 2
    assert "ok" not in result
    assert "mismatches" not in result


def test_matching_recipe_is_ok(tmp_path):
    result = _commands(tmp_path).get_stackup(
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
    assert result["mismatchCount"] == 0
    assert result["mismatches"] == []
    assert result["layers"][0]["name"] == "Top Side"


def test_thickness_and_epsilon_outside_tolerance(tmp_path):
    result = _commands(tmp_path).get_stackup(
        {"expected": [{"layer": "F.Cu", "thicknessMm": 0.018}, {"index": 1, "epsilonR": 4.2}]}
    )
    assert result["success"] is True
    assert result["ok"] is False
    by_field = {item["field"]: item for item in result["mismatches"]}
    assert by_field["thicknessMm"]["layer"] == "F.Cu"
    assert by_field["thicknessMm"]["actual"] == pytest.approx(0.035)
    assert by_field["thicknessMm"]["expected"] == pytest.approx(0.018)
    assert by_field["thicknessMm"]["delta"] == pytest.approx(0.017)
    assert by_field["epsilonR"]["delta"] == pytest.approx(0.3)


def test_one_micron_is_inside_the_default_tolerance(tmp_path):
    result = _commands(tmp_path).get_stackup(
        {"expected": [{"layer": "Top Side", "thicknessMm": 0.0355}]}
    )
    assert result["ok"] is True


def test_wider_tolerance_accepts_a_copper_weight_step(tmp_path):
    commands = _commands(tmp_path)
    strict = commands.get_stackup({"expected": [{"layer": "F.Cu", "thicknessMm": 0.018}]})
    loose = commands.get_stackup(
        {"expected": [{"layer": "F.Cu", "thicknessMm": 0.018}], "thicknessToleranceMm": 0.02}
    )
    assert strict["ok"] is False
    assert loose["ok"] is True


def test_wrong_type_and_a_missing_layer(tmp_path):
    result = _commands(tmp_path).get_stackup(
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


def test_empty_recipe_is_an_error(tmp_path):
    result = _commands(tmp_path).get_stackup({"expected": []})
    assert result["success"] is False
    assert result["message"] == "expected must list at least one row"


def test_no_board():
    result = StackupCommands(None).get_stackup(
        {"expected": [{"layer": "F.Cu", "thicknessMm": 0.035}]}
    )
    assert result["success"] is False
    assert result["message"] == "No board is loaded"
