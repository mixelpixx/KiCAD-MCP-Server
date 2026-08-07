"""Safety tests for library-footprint placement through the live IPC backend."""

from unittest.mock import MagicMock

import pytest
from kicad_api.ipc_backend import IPCBoardAPI

pytestmark = pytest.mark.unit


class ExplodingKiCad:
    """Fails if the safety path attempts any IPC or disk-discovery operation."""

    def __getattribute__(self, name):
        raise AssertionError(f"unexpected KiCad access: {name}")


def test_loaded_footprint_placement_fails_without_touching_live_board():
    notify = MagicMock()
    board_api = IPCBoardAPI(ExplodingKiCad(), notify)

    result = board_api._place_loaded_footprint(
        object(),
        reference="U1",
        x=10.0,
        y=20.0,
        rotation=90.0,
        layer="F.Cu",
        value="MCU",
    )

    assert result is False
    notify.assert_not_called()


def test_place_component_does_not_fall_back_after_refusing_loaded_footprint(monkeypatch):
    board_api = IPCBoardAPI(object(), MagicMock())
    loaded_footprint = object()
    refuse_loaded = MagicMock(return_value=False)
    place_placeholder = MagicMock(return_value=True)
    monkeypatch.setattr(
        board_api,
        "_load_footprint_from_library",
        MagicMock(return_value=loaded_footprint),
    )
    monkeypatch.setattr(board_api, "_place_loaded_footprint", refuse_loaded)
    monkeypatch.setattr(board_api, "_place_placeholder_footprint", place_placeholder)

    result = board_api.place_component(
        reference="U1",
        footprint="Package_QFP:LQFP-48_7x7mm_P0.5mm",
        x=10.0,
        y=20.0,
    )

    assert result is False
    refuse_loaded.assert_called_once_with(
        loaded_footprint,
        "U1",
        10.0,
        20.0,
        0,
        "F.Cu",
        "",
    )
    place_placeholder.assert_not_called()
