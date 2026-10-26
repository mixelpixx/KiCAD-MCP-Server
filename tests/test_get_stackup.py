"""Unit tests for get_stackup.

KiCad 10's pcbnew bindings cannot read a BOARD_STACKUP, so the command reads
the ``(stackup ...)`` section of the ``.kicad_pcb`` file. These tests use a
file snippet and a board that has no GetStackup method.
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
  (paper "A4")
  (layers
    (0 "Top Side" signal)
    (2 "Bottom Side" signal)
  )
  (setup
    (stackup
      (layer "F.SilkS"
        (type "Top Silk Screen")
      )
      (layer "F.Cu"
        (type "copper")
        (thickness 0.035)
      )
      (layer "dielectric 1"
        (type "core")
        (thickness 0.1)
        (material "FR4 (170)")
        (epsilon_r 4.0)
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


def _board(path, *, with_names=True):
    """A loaded board whose only stackup access is the file on disk."""
    ids = {"F.Cu": 0, "B.Cu": 2, "Top Side": 0, "Bottom Side": 2}
    user = {0: "Top Side", 2: "Bottom Side"}
    standard = {0: "F.Cu", 2: "B.Cu"}

    def layer_id(name):
        return ids.get(name, -1)

    board = SimpleNamespace(GetFileName=lambda: path, GetLayerID=layer_id)
    if with_names:
        board.GetLayerName = lambda layer_id: user[layer_id]
        board.GetStandardLayerName = lambda layer_id: standard[layer_id]
    return board


def test_file_stackup_keeps_custom_names_and_sums_sublayers(tmp_path):
    """A renamed outer layer stays beside F.Cu, and 0.1 + 0.039 mm is 0.139 mm."""
    path = tmp_path / "board.kicad_pcb"
    path.write_text(_BOARD, encoding="utf-8")
    result = StackupCommands(_board(str(path))).get_stackup({})

    assert result["success"] is True
    assert result["copperCount"] == 2
    assert result["boardThicknessMm"] == pytest.approx(1.61)
    silk, top, gap, bottom = result["layers"]
    assert silk["type"] == "silkscreen"
    assert silk["canonical"] == "F.SilkS"
    assert "thicknessMm" not in silk
    assert top["type"] == "copper"
    assert top["name"] == "Top Side"
    assert top["canonical"] == "F.Cu"
    assert top["layerId"] == 0
    assert top["thicknessMm"] == pytest.approx(0.035)
    assert gap["type"] == "dielectric"
    assert gap["thicknessMm"] == pytest.approx(0.139)
    assert gap["epsilonR"] == pytest.approx(4.0)
    assert gap["lossTangent"] == pytest.approx(0.02)
    assert gap["material"] == "FR4 (170)"
    assert "name" not in gap
    assert gap["sublayers"][1]["material"] == "prepreg"
    assert gap["sublayers"][1]["epsilonR"] == pytest.approx(3.5)
    assert bottom["canonical"] == "B.Cu"
    assert bottom["name"] == "Bottom Side"
    assert bottom["layerId"] == 2


def test_missing_stackup_section_is_an_error(tmp_path):
    path = tmp_path / "empty.kicad_pcb"
    path.write_text("(kicad_pcb (version 20240108) (general (thickness 1.6)))\n", encoding="utf-8")
    result = StackupCommands(_board(str(path))).get_stackup({})
    assert result["success"] is False
    assert result["message"] == "Board has no stackup"


def test_missing_file_is_an_error(tmp_path):
    result = StackupCommands(_board(str(tmp_path / "gone.kicad_pcb"))).get_stackup({})
    assert result["success"] is False
    assert result["message"] == "Board file is missing"


def test_no_board():
    result = StackupCommands(None).get_stackup({})
    assert result["success"] is False
    assert result["message"] == "No board is loaded"
