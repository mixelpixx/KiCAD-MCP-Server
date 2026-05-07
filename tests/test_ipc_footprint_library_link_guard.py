"""Regression test for IPCBoardAPI.list_components — footprint field guard.

KiCad 9 IPC sometimes returns Footprint objects whose ``definition`` lacks the
``library_link`` attribute, which used to raise ``AttributeError`` and drop
every component from ``list_components``. The fix guards the access and falls
back to ``definition.id`` when present, or an empty string.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# Stub kipy.util.units.to_mm so the module-level import inside list_components
# succeeds without a real kipy installation.
_kipy = sys.modules.setdefault("kipy", MagicMock(name="kipy"))
_kipy_util = sys.modules.setdefault("kipy.util", MagicMock(name="kipy.util"))
_kipy_units = sys.modules.setdefault("kipy.util.units", MagicMock(name="kipy.util.units"))
_kipy_units.to_mm = lambda v: v / 1_000_000


def _make_fp(*, library_link=None, fp_id=None):
    """Build a minimal mock Footprint with the requested definition shape."""
    if library_link is not None and fp_id is not None:
        definition = SimpleNamespace(library_link=library_link, id=fp_id)
    elif library_link is not None:
        definition = SimpleNamespace(library_link=library_link)
    elif fp_id is not None:
        definition = SimpleNamespace(id=fp_id)
    else:
        definition = SimpleNamespace()  # neither attribute

    fp = SimpleNamespace(
        position=SimpleNamespace(x=1_000_000, y=2_000_000),
        reference_field=SimpleNamespace(text=SimpleNamespace(value="R1")),
        value_field=SimpleNamespace(text=SimpleNamespace(value="220")),
        definition=definition,
        orientation=SimpleNamespace(degrees=0),
        layer="F.Cu",
        id="fp-uuid-1",
    )
    return fp


def _list_components_with(fps):
    """Run IPCBoardAPI.list_components against a list of mock footprints."""
    from kicad_api.ipc_backend import IPCBoardAPI

    api = IPCBoardAPI.__new__(IPCBoardAPI)
    fake_board = MagicMock()
    fake_board.get_footprints.return_value = fps
    with patch.object(api, "_get_board", return_value=fake_board, create=True):
        return api.list_components()


def test_definition_with_library_link_returned_as_footprint():
    fp = _make_fp(library_link="Library:Footprint")
    [comp] = _list_components_with([fp])
    assert comp["footprint"] == "Library:Footprint"


def test_definition_without_library_link_falls_back_to_id():
    """Regression: the bug we are guarding against."""
    fp = _make_fp(fp_id="some-fp-id")
    [comp] = _list_components_with([fp])
    # Old code raised AttributeError and dropped the component entirely.
    assert comp["footprint"] == "some-fp-id"
    assert comp["reference"] == "R1"


def test_definition_without_either_attribute_returns_empty_string():
    fp = _make_fp()
    [comp] = _list_components_with([fp])
    assert comp["footprint"] == ""
    # And the component is still emitted (not silently dropped)
    assert comp["reference"] == "R1"
