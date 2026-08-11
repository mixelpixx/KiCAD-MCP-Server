"""Regression tests for creating IPC copper zones with an explicit fill mode."""

import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from kicad_api.ipc_backend import IPCBoardAPI  # noqa: E402
from kipy.board_types import ZoneFillMode  # noqa: E402


class _Board:
    def __init__(self):
        self.created = None

    @staticmethod
    def get_nets():
        return []

    @staticmethod
    def begin_commit():
        return object()

    def create_items(self, item):
        self.created = item

    @staticmethod
    def push_commit(commit, message):
        return None


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("solid", ZoneFillMode.ZFM_SOLID),
        ("hatched", ZoneFillMode.ZFM_HATCHED),
    ],
)
def test_add_zone_writes_fill_mode_to_created_proto(requested, expected):
    board = _Board()
    api = IPCBoardAPI(object(), lambda *args: None)
    api._board = board

    success = api.add_zone(
        [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 0, "y": 10}],
        fill_mode=requested,
    )

    assert success is True
    assert board.created is not None
    assert board.created.proto.copper_settings.fill_mode == expected
