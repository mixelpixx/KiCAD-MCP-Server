"""Regression test: IPC zone creation must set fill_mode through the proto.

kipy's ``Zone.fill_mode`` is a read-only property — its getter reads
``_proto.copper_settings.fill_mode`` and there is no setter — so
``zone.fill_mode = ...`` raises ``AttributeError`` the moment a user creates a
zone over the IPC backend. mypy catches it as
``Property "fill_mode" defined in "Zone" is read-only``, but only when kipy is
actually installed; with kipy absent it is silently typed ``Any``, which is why
this survived until CI began installing requirements.txt.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

kipy_board_types = pytest.importorskip(
    "kipy.board_types", reason="kipy (kicad-python) not installed"
)
kipy_pb2 = pytest.importorskip("kipy.proto.board.board_types_pb2")

Zone = kipy_board_types.Zone
ZoneFillMode = kipy_pb2.ZoneFillMode


def test_fill_mode_has_no_setter() -> None:
    """Pin the upstream contract this fix exists for. If kipy ever adds a
    setter, the workaround can be simplified — this test is the tripwire."""
    prop = Zone.fill_mode
    assert isinstance(prop, property)
    assert prop.fset is None, "kipy added a fill_mode setter; simplify create_zone"

    with pytest.raises(AttributeError):
        Zone().fill_mode = ZoneFillMode.ZFM_SOLID


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("hatched", ZoneFillMode.ZFM_HATCHED), ("solid", ZoneFillMode.ZFM_SOLID)],
)
def test_proto_write_round_trips(requested: str, expected: int) -> None:
    """The assignment form used by create_zone must be readable back off the
    public property — i.e. the proto path is the correct channel."""
    zone = Zone()
    zone._proto.copper_settings.fill_mode = (
        ZoneFillMode.ZFM_HATCHED if requested == "hatched" else ZoneFillMode.ZFM_SOLID
    )
    assert zone.fill_mode == expected


def test_create_zone_source_does_not_assign_the_property() -> None:
    """Guard the specific line that regressed: create_zone must not contain a
    bare ``zone.fill_mode =`` assignment."""
    source = (Path(__file__).parent.parent / "python" / "kicad_api" / "ipc_backend.py").read_text(
        encoding="utf-8"
    )
    assert "zone.fill_mode =" not in source, (
        "create_zone assigns the read-only Zone.fill_mode property; "
        "write through zone._proto.copper_settings.fill_mode instead"
    )
