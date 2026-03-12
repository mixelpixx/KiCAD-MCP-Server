"""Regression test for IPC rotate_component absolute-angle behavior.

Bug: ``_ipc_rotate_component`` accumulated the supplied angle on top of the
current rotation, but the tool schema documents ``rotation`` as the absolute
target angle. Two consecutive ``rotate_component(angle=90)`` calls would land
the part at 180° instead of leaving it at 90°.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_iface(current_rotation: float) -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", True):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)

    iface.use_ipc = True
    iface.board = None
    iface.ipc_board_api = MagicMock()
    iface.ipc_board_api.list_components.return_value = [
        {
            "reference": "R1",
            "position": {"x": 10.0, "y": 20.0, "unit": "mm"},
            "rotation": current_rotation,
        }
    ]
    iface.ipc_board_api.move_component.return_value = True
    return iface


def test_rotation_is_absolute_not_additive():
    """angle=90 sets rotation to 90° regardless of current rotation."""
    iface = _make_iface(current_rotation=270)
    result = iface._ipc_rotate_component({"reference": "R1", "angle": 90})

    assert result["success"] is True
    assert result["newRotation"] == 90
    _, kwargs = iface.ipc_board_api.move_component.call_args
    assert kwargs["rotation"] == 90


def test_rotation_is_absolute_when_current_is_zero():
    iface = _make_iface(current_rotation=0)
    result = iface._ipc_rotate_component({"reference": "R1", "angle": 180})
    assert result["newRotation"] == 180


def test_rotation_normalized_to_modulo_360():
    """Values >= 360 are normalized."""
    iface = _make_iface(current_rotation=0)
    result = iface._ipc_rotate_component({"reference": "R1", "angle": 450})
    assert result["newRotation"] == 90


def test_position_preserved_during_rotate():
    """Rotating must not move the part."""
    iface = _make_iface(current_rotation=0)
    iface._ipc_rotate_component({"reference": "R1", "angle": 90})
    _, kwargs = iface.ipc_board_api.move_component.call_args
    assert kwargs["x"] == 10.0
    assert kwargs["y"] == 20.0


def test_unknown_reference_returns_failure():
    iface = _make_iface(current_rotation=0)
    result = iface._ipc_rotate_component({"reference": "DOES_NOT_EXIST", "angle": 90})
    assert result["success"] is False
    iface.ipc_board_api.move_component.assert_not_called()
