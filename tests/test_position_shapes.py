"""Every handler that takes a position accepts [x, y] and {"x": .., "y": ..}.

add_schematic_text took only a list (a dict passed its length check and then
failed with "Failed to add text annotation"); delete_schematic_net_label took
only a dict (a list raised on .get). Found driving the tools from a script.
"""

import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

_SCH = textwrap.dedent("""\
    (kicad_sch (version 20250114) (generator "test")
    \t(uuid aaaaaaaa-0000-0000-0000-000000000001)
    \t(paper "A4")
    \t(sheet_instances (path "/" (page "1")))
    )
    """)


def _iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        return KiCADInterface.__new__(KiCADInterface)


@pytest.fixture()
def sch(tmp_path):
    f = tmp_path / "s.kicad_sch"
    f.write_text(_SCH, encoding="utf-8")
    return f


@pytest.mark.unit
def test_xy_normaliser():
    from commands.schematic_handlers import _xy

    assert _xy([1, 2]) == [1, 2]
    assert _xy((1.5, 2)) == [1.5, 2]
    assert _xy({"x": 3, "y": 4}) == [3, 4]
    assert _xy({"x": "3", "y": 4}) is None
    assert _xy({"x": 3}) is None
    assert _xy([1, 2, 3]) is None
    assert _xy(None) is None


@pytest.mark.unit
@pytest.mark.parametrize("pos", [[50.8, 25.4], {"x": 50.8, "y": 25.4}])
def test_add_schematic_text_takes_either_shape(sch, pos):
    r = _iface()._handle_add_schematic_text(
        {"schematicPath": str(sch), "text": "NOTE", "position": pos}
    )
    assert r["success"], r
    assert '(text "NOTE"' in sch.read_text() and "(at 50.8 25.4 0)" in sch.read_text()


@pytest.mark.unit
def test_add_schematic_text_bad_position_says_what_it_wants(sch):
    r = _iface()._handle_add_schematic_text(
        {"schematicPath": str(sch), "text": "NOTE", "position": {"x": 1}}
    )
    assert not r["success"] and "[x, y]" in r["message"] and '"x"' in r["message"]


@pytest.mark.unit
@pytest.mark.parametrize("pos", [[50.8, 25.4], {"x": 50.8, "y": 25.4}])
def test_delete_net_label_takes_either_shape(sch, pos):
    from commands.wire_manager import WireManager

    assert WireManager.add_label(sch, "VBUS", [50.8, 25.4])
    assert '(label "VBUS"' in sch.read_text()
    r = _iface()._handle_delete_schematic_net_label(
        {"schematicPath": str(sch), "netName": "VBUS", "position": pos}
    )
    assert r["success"], r
    assert '(label "VBUS"' not in sch.read_text()


@pytest.mark.unit
@pytest.mark.parametrize("pos", [{"x": 50.8}, [50.8], "50.8, 25.4", {"x": "50.8", "y": 25.4}])
def test_delete_net_label_refuses_a_malformed_position(sch, pos):
    """A position that is present but malformed is an error, not "no position".

    Treating it as absent would delete the only label of that name, which is
    the wrong label whenever the caller passed coordinates to pick one.
    """
    from commands.wire_manager import WireManager

    assert WireManager.add_label(sch, "VBUS", [50.8, 25.4])
    before = sch.read_text()
    r = _iface()._handle_delete_schematic_net_label(
        {"schematicPath": str(sch), "netName": "VBUS", "position": pos}
    )
    assert not r["success"], r
    assert "[x, y]" in r["message"] and '"x"' in r["message"]
    assert sch.read_text() == before


@pytest.mark.unit
@pytest.mark.parametrize("pos", [[50.8, 25.4], {"x": 50.8, "y": 25.4}])
def test_hierarchical_label_takes_either_shape(sch, pos):
    r = _iface()._handle_add_schematic_hierarchical_label(
        {"schematicPath": str(sch), "text": "SDA", "position": pos, "shape": "bidirectional"}
    )
    assert r["success"], r
    assert '(hierarchical_label "SDA"' in sch.read_text()
