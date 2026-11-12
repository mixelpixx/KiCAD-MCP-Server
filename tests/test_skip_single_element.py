"""kicad-skip returns a bare element, not a collection, when a schematic holds exactly one item of a
kind it has no dedicated collection for (hierarchical labels, no-connects, ...).

``bool()`` on that element raises "__bool__ should return bool, returned str", and iterating it
walks the element's own children. A sheet with a single hierarchical label made
create_board_from_schematic and sync_schematic_to_board fail. These tests load real files with
kicad-skip (the other pad-net-map tests mock it with plain lists, which hides the problem).
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from tests.test_hierarchical_pad_net_map import _build_sch_with_instances  # noqa: E402

HLABEL = (
    '  (hierarchical_label "{name}" (shape input) (at {x} {y} 0)\n'
    "    (effects (font (size 1.27 1.27)) (justify left))\n"
    '    (uuid "00000000-0000-0000-0000-0000000{i:05d}"))\n'
)
NOCONNECT = '  (no_connect (at {x} {y}) (uuid "00000000-0000-0000-0000-0000001{i:05d}"))\n'


def _sheet(tmp_path: Path, labels, no_connects=()) -> Path:
    # R1 at (10, 10): pin 1 at (8.73, 10), pin 2 at (11.27, 10). R2 at (30, 10).
    text = _build_sch_with_instances(
        [("R1", "TestLib:R", 10.0, 10.0, 0), ("R2", "TestLib:R", 30.0, 10.0, 0)]
    )
    extra = "".join(HLABEL.format(name=n, x=x, y=y, i=i) for i, (n, x, y) in enumerate(labels))
    extra += "".join(NOCONNECT.format(x=x, y=y, i=i) for i, (x, y) in enumerate(no_connects))
    body = text.rstrip().rstrip(")") + "\n" + extra + ")\n"
    path = tmp_path / "sub.kicad_sch"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        return KiCADInterface.__new__(KiCADInterface)


@pytest.mark.unit
@pytest.mark.parametrize("kind, template", [("hierarchical_label", HLABEL), ("no_connect", None)])
@pytest.mark.parametrize("count", [0, 1, 2])
def test_skip_items_always_returns_a_list_of_elements(tmp_path, kind, template, count) -> None:
    import skip
    from utils.skip_items import skip_items

    labels = [(f"N{i}", 8.73 + 20 * i, 10.0) for i in range(count)] if template else []
    ncs = [(11.27 + 20 * i, 10.0) for i in range(count)] if not template else []
    sch = skip.Schematic(str(_sheet(tmp_path, labels, ncs)))

    items = skip_items(sch, kind)
    assert isinstance(items, list)
    assert len(items) == count
    for item in items:
        assert hasattr(item, "at"), f"{kind}: got a child of the element, not the element"


@pytest.mark.unit
def test_skip_items_missing_attribute_is_empty() -> None:
    from utils.skip_items import skip_items

    assert skip_items(object(), "hierarchical_label") == []


@pytest.mark.unit
def test_pad_net_map_with_one_hierarchical_label(iface, tmp_path) -> None:
    """Used to raise TypeError: __bool__ should return bool, returned str."""
    sub = _sheet(tmp_path, [("SDA", 8.73, 10.0)])
    pad_net_map, net_names = iface._build_hierarchical_pad_net_map(str(sub))
    assert pad_net_map.get(("R1", "1")) == "SDA"
    assert "SDA" in net_names


@pytest.mark.unit
def test_pad_net_map_with_two_hierarchical_labels(iface, tmp_path) -> None:
    sub = _sheet(tmp_path, [("SDA", 8.73, 10.0), ("SCL", 28.73, 10.0)])
    pad_net_map, _ = iface._build_hierarchical_pad_net_map(str(sub))
    assert pad_net_map.get(("R1", "1")) == "SDA"
    assert pad_net_map.get(("R2", "1")) == "SCL"
