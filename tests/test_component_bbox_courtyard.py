"""Tests for bounding-box / courtyard data in component queries (SWIG path).

``get_component_properties`` and ``get_component_list`` now include a
``boundingBox`` field built from ``module.GetBoundingBox()`` and (for the
single-component query) a ``courtyard`` field built from
``module.GetCourtyard()`` against ``F_CrtYd``/``B_CrtYd``.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _bbox(left_nm, top_nm, right_nm, bottom_nm):
    bb = MagicMock()
    bb.GetLeft.return_value = left_nm
    bb.GetTop.return_value = top_nm
    bb.GetRight.return_value = right_nm
    bb.GetBottom.return_value = bottom_nm
    return bb


def _make_module(*, ref="U1", value="LM317", with_courtyard=False):
    pos = MagicMock()
    pos.x = 10_000_000  # 10 mm
    pos.y = 20_000_000  # 20 mm

    module = MagicMock()
    module.GetPosition.return_value = pos
    module.GetReference.return_value = ref
    module.GetValue.return_value = value
    module.GetFPIDAsString.return_value = "Lib:Footprint"
    orientation = MagicMock()
    orientation.AsDegrees.return_value = 0
    module.GetOrientation.return_value = orientation
    module.GetLayer.return_value = 0
    module.GetAttributes.return_value = 0
    module.GetBoundingBox.return_value = _bbox(0, 0, 5_000_000, 3_000_000)  # 5 x 3 mm

    courtyard_outline = MagicMock()
    if with_courtyard:
        courtyard_outline.OutlineCount.return_value = 1
        courtyard_outline.BBox.return_value = _bbox(-500_000, -500_000, 5_500_000, 3_500_000)
    else:
        courtyard_outline.OutlineCount.return_value = 0
    module.GetCourtyard.return_value = courtyard_outline

    return module


def _make_board(modules):
    board = MagicMock()
    board.GetLayerName.return_value = "F.Cu"
    board.GetFootprints.return_value = list(modules)
    if modules:
        board.FindFootprintByReference.return_value = modules[0]
    else:
        board.FindFootprintByReference.return_value = None
    return board


def test_get_component_properties_returns_bounding_box():
    from commands.component import ComponentCommands

    module = _make_module()
    cmd = ComponentCommands(board=_make_board([module]))
    result = cmd.get_component_properties({"reference": "U1"})

    assert result["success"] is True
    bb = result["component"]["boundingBox"]
    assert bb["min_x"] == 0.0
    assert bb["min_y"] == 0.0
    assert bb["max_x"] == 5.0
    assert bb["max_y"] == 3.0
    assert bb["width"] == 5.0
    assert bb["height"] == 3.0
    assert bb["unit"] == "mm"


def test_get_component_properties_returns_courtyard_when_present():
    from commands.component import ComponentCommands

    module = _make_module(with_courtyard=True)
    cmd = ComponentCommands(board=_make_board([module]))
    result = cmd.get_component_properties({"reference": "U1"})

    courtyard = result["component"]["courtyard"]
    assert courtyard is not None
    assert courtyard["min_x"] == -0.5
    assert courtyard["max_x"] == 5.5
    assert courtyard["unit"] == "mm"


def test_get_component_properties_courtyard_none_when_absent():
    from commands.component import ComponentCommands

    module = _make_module(with_courtyard=False)
    cmd = ComponentCommands(board=_make_board([module]))
    result = cmd.get_component_properties({"reference": "U1"})

    assert result["component"]["courtyard"] is None


def test_get_component_list_includes_bounding_box():
    from commands.component import ComponentCommands

    modules = [_make_module(ref="R1"), _make_module(ref="R2")]
    cmd = ComponentCommands(board=_make_board(modules))
    result = cmd.get_component_list({})

    assert result["success"] is True
    assert len(result["components"]) == 2
    for comp in result["components"]:
        assert "boundingBox" in comp
        assert comp["boundingBox"]["unit"] == "mm"
