"""Regression tests for creating IPC copper zones with an explicit fill mode."""

import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

kipy_board_types = pytest.importorskip(
    "kipy.board_types", reason="kipy (kicad-python) not installed"
)

from kicad_api.ipc_backend import IPCBoardAPI  # noqa: E402

Zone = kipy_board_types.Zone
ZoneFillMode = kipy_board_types.ZoneFillMode


class _Board:
    def __init__(self) -> None:
        self.created = None

    @staticmethod
    def get_nets():
        return []

    @staticmethod
    def begin_commit():
        return object()

    def create_items(self, item) -> None:
        self.created = item

    @staticmethod
    def push_commit(commit, message) -> None:
        return None


def test_fill_mode_has_no_setter() -> None:
    """Pin the upstream contract that requires writing through the zone proto."""
    prop = Zone.fill_mode
    assert isinstance(prop, property)
    assert prop.fset is None, "kipy added a fill_mode setter; simplify add_zone"

    with pytest.raises(AttributeError):
        Zone().fill_mode = ZoneFillMode.ZFM_SOLID


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("solid", ZoneFillMode.ZFM_SOLID),
        ("hatched", ZoneFillMode.ZFM_HATCHED),
    ],
)
def test_proto_write_round_trips(requested: str, expected: int) -> None:
    """The public proto property is the supported write channel for fill mode."""
    zone = Zone()
    zone.proto.copper_settings.fill_mode = (
        ZoneFillMode.ZFM_HATCHED if requested == "hatched" else ZoneFillMode.ZFM_SOLID
    )
    assert zone.fill_mode == expected


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("solid", ZoneFillMode.ZFM_SOLID),
        ("hatched", ZoneFillMode.ZFM_HATCHED),
    ],
)
def test_add_zone_writes_fill_mode_to_created_proto(requested: str, expected: int) -> None:
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


def test_create_zone_source_does_not_assign_the_read_only_property() -> None:
    source = (PYTHON_DIR / "kicad_api" / "ipc_backend.py").read_text(encoding="utf-8")
    assert "zone.fill_mode =" not in source
    assert "zone.proto.copper_settings.fill_mode =" in source
