"""Regression test for inch-unit conversion in IPC place/move handlers.

Bug: ``_ipc_place_component`` and ``_ipc_move_component`` ignored the
``unit`` field in ``position`` and forwarded the values directly to the IPC
backend, which expects mm. Calling with ``unit="inch"`` placed the part at
1/25.4 of the intended position. The fix reads ``unit`` and converts inches
→ mm before invoking ``self.ipc_board_api.*``.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_iface() -> Any:
    """Build a stripped-down KiCADInterface with a mock ipc_board_api."""
    with patch("kicad_interface.USE_IPC_BACKEND", True):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)

    iface.use_ipc = True
    iface.board = None
    iface.ipc_board_api = MagicMock()
    iface.ipc_board_api.place_component.return_value = True
    iface.ipc_board_api.move_component.return_value = True
    return iface


def test_place_component_converts_inches_to_mm():
    iface = _make_iface()
    iface._ipc_place_component(
        {
            "reference": "R1",
            "footprint": "Resistor_SMD:R_0805",
            "position": {"x": 1, "y": 2, "unit": "inch"},
            "rotation": 0,
            "layer": "F.Cu",
            "value": "220",
        }
    )

    args, kwargs = iface.ipc_board_api.place_component.call_args
    assert kwargs["x"] == pytest.approx(25.4)
    assert kwargs["y"] == pytest.approx(50.8)


def test_place_component_passes_mm_unchanged():
    iface = _make_iface()
    iface._ipc_place_component(
        {
            "reference": "R1",
            "footprint": "Resistor_SMD:R_0805",
            "position": {"x": 25.4, "y": 50.8, "unit": "mm"},
            "rotation": 0,
            "layer": "F.Cu",
            "value": "220",
        }
    )
    args, kwargs = iface.ipc_board_api.place_component.call_args
    assert kwargs["x"] == 25.4
    assert kwargs["y"] == 50.8


def test_move_component_converts_inches_to_mm():
    iface = _make_iface()
    iface._ipc_move_component(
        {
            "reference": "R1",
            "position": {"x": 1, "y": 0.5, "unit": "inch"},
        }
    )
    args, kwargs = iface.ipc_board_api.move_component.call_args
    assert kwargs["x"] == pytest.approx(25.4)
    assert kwargs["y"] == pytest.approx(12.7)


def test_default_unit_is_mm():
    """Omitting unit defaults to mm — values pass through unchanged."""
    iface = _make_iface()
    iface._ipc_move_component({"reference": "R1", "position": {"x": 10, "y": 20}})
    args, kwargs = iface.ipc_board_api.move_component.call_args
    assert kwargs["x"] == 10
    assert kwargs["y"] == 20
