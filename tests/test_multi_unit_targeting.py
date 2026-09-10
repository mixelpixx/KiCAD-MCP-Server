"""move / rotate / delete can address a single unit of a multi-unit part.

Every unit of a multi-unit symbol is placed as its own (symbol ...) block under
one shared reference (U201 A-E). Addressing by reference alone therefore hit
whichever block came first in the file — which unit that was could not be
predicted from the outside, and deleting took the whole part. An optional
`unit` parameter names the placement to act on.
"""

import sys
from pathlib import Path
from typing import Any

import pytest
from sexpdata import Symbol as S

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from commands.wire_dragger import WireDragger  # noqa: E402

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"


def _placed_unit(unit: int, x: float, y: float, uid: str) -> str:
    """A placed unit of the two-unit part U1."""
    return f"""  (symbol (lib_id "Amplifier_Operational:LM358") (at {x} {y} 0) (unit {unit})
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{uid}")
    (property "Reference" "U1" (at {x} {y - 5} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "LM358" (at {x} {y + 5} 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""


def _schematic(tmp_path: Path) -> Path:
    dest = tmp_path / "multi.kicad_sch"
    content = TEMPLATE_SCH.read_text(encoding="utf-8").rstrip()
    assert content.endswith(")")
    blocks = _placed_unit(1, 50.8, 50.8, "11111111-1111-1111-1111-111111111111") + _placed_unit(
        2, 101.6, 50.8, "22222222-2222-2222-2222-222222222222"
    )
    dest.write_text(content[:-1] + "\n" + blocks + ")\n", encoding="utf-8")
    return dest


def _iface() -> Any:
    from kicad_interface import KiCADInterface

    return KiCADInterface.__new__(KiCADInterface)


def _units_and_positions(sch: Path):
    import sexpdata

    data = sexpdata.loads(sch.read_text(encoding="utf-8"))
    out = {}
    for item in data:
        if not (isinstance(item, list) and item and item[0] == S("symbol")):
            continue
        unit = WireDragger._symbol_unit(item)
        if unit is None:
            continue
        at = next(p for p in item[1:] if isinstance(p, list) and p[0] == S("at"))
        out[unit] = (float(at[1]), float(at[2]))
    return out


class TestFindSymbolUnit:
    def test_unit_selects_the_matching_placement(self, tmp_path: Path) -> None:
        import sexpdata

        data = sexpdata.loads(_schematic(tmp_path).read_text(encoding="utf-8"))
        assert WireDragger.find_symbol(data, "U1", 2)[1] == 101.6
        assert WireDragger.find_symbol(data, "U1", 1)[1] == 50.8
        assert WireDragger.find_symbol(data, "U1", 3) is None

    def test_list_symbol_units_reports_what_is_placed(self, tmp_path: Path) -> None:
        import sexpdata

        data = sexpdata.loads(_schematic(tmp_path).read_text(encoding="utf-8"))
        assert sorted(WireDragger.list_symbol_units(data, "U1")) == [1, 2]


class TestMove:
    def test_moves_only_the_named_unit(self, tmp_path: Path) -> None:
        sch = _schematic(tmp_path)
        result = _iface()._handle_move_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "U1",
                "unit": 2,
                "position": {"x": 152.4, "y": 76.2},
            }
        )
        assert result["success"] is True
        positions = _units_and_positions(sch)
        assert positions[2] == (152.4, 76.2)
        assert positions[1] == (50.8, 50.8), "unit A must not have moved"

    def test_unknown_unit_says_which_units_exist(self, tmp_path: Path) -> None:
        sch = _schematic(tmp_path)
        result = _iface()._handle_move_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "U1",
                "unit": 5,
                "position": {"x": 152.4, "y": 76.2},
            }
        )
        assert result["success"] is False
        assert "no unit 5" in result["message"]
        assert "1, 2" in result["message"]


class TestRotate:
    def test_rotates_only_the_named_unit(self, tmp_path: Path) -> None:
        sch = _schematic(tmp_path)
        result = _iface()._handle_rotate_schematic_component(
            {"schematicPath": str(sch), "reference": "U1", "unit": 2, "angle": 90}
        )
        assert result["success"] is True

        import sexpdata

        data = sexpdata.loads(sch.read_text(encoding="utf-8"))
        angles = {}
        for item in data:
            if not (isinstance(item, list) and item and item[0] == S("symbol")):
                continue
            unit = WireDragger._symbol_unit(item)
            if unit is None:
                continue
            at = next(p for p in item[1:] if isinstance(p, list) and p[0] == S("at"))
            angles[unit] = at[3]
        assert angles[2] == 90
        assert angles[1] == 0


class TestDelete:
    def test_deletes_only_the_named_unit(self, tmp_path: Path) -> None:
        sch = _schematic(tmp_path)
        result = _iface()._handle_delete_schematic_component(
            {"schematicPath": str(sch), "reference": "U1", "unit": 1}
        )
        assert result["success"] is True
        assert result["deleted_count"] == 1
        assert sorted(_units_and_positions(sch)) == [2]

    def test_without_unit_the_whole_part_goes(self, tmp_path: Path) -> None:
        sch = _schematic(tmp_path)
        result = _iface()._handle_delete_schematic_component(
            {"schematicPath": str(sch), "reference": "U1"}
        )
        assert result["success"] is True
        assert result["deleted_count"] == 2
        assert _units_and_positions(sch) == {}

    def test_missing_unit_is_reported_not_silently_ignored(self, tmp_path: Path) -> None:
        sch = _schematic(tmp_path)
        result = _iface()._handle_delete_schematic_component(
            {"schematicPath": str(sch), "reference": "U1", "unit": 4}
        )
        assert result["success"] is False
        assert "unit 4" in result["message"]
        assert sorted(_units_and_positions(sch)) == [1, 2]
