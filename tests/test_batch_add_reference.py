"""The batch placement tools resolve references like add_schematic_component (#524).

add_schematic_component gives a power symbol placed without a reference, or
with "#PWR?", the next free #PWRnn (PWR_FLAG: #FLGnn), and refuses any other
symbol without a reference. batch_add_components still placed such a symbol
silently as "X?" and wrote "#PWR?" literally, so the two tools disagreed.
Both now resolve the reference through utils.power_reference.
"""

import re
import shutil
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_batch import SchematicBatchCommands  # noqa: E402

pytestmark = pytest.mark.unit

EMPTY_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

# The power:GND definition is already in lib_symbols, so placement does not
# need KiCad's symbol libraries installed.
_POWER_SCH = """(kicad_sch (version 20250114) (generator "test")
  (uuid "aaaaaaaa-0000-0000-0000-0000000005a1")
  (paper "A4")
  (lib_symbols
    (symbol "power:GND" (power) (in_bom no) (on_board yes)
      (property "Reference" "#PWR" (at 0 -6.35 0)
        (effects (font (size 1.27 1.27)) (hide yes))
      )
      (property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (symbol "GND_0_1"
        (polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27))
          (stroke (width 0) (type default)) (fill (type none))
        )
      )
      (symbol "GND_1_1"
        (pin power_in line (at 0 0 270) (length 0) (hide yes)
          (name "GND" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )
  (sheet_instances (path "/" (page "1")))
)
"""


def _commands() -> SchematicBatchCommands:
    return SchematicBatchCommands(types.SimpleNamespace())


def _references(text: str) -> List[str]:
    return re.findall(r'\(property "Reference" "([^"]*)"', text)


def test_power_symbols_in_one_batch_get_distinct_numbers(tmp_path: Path) -> None:
    sch = tmp_path / "power.kicad_sch"
    sch.write_text(_POWER_SCH, encoding="utf-8", newline="")

    result = _commands().batch_add_components(
        {
            "schematicPath": str(sch),
            "components": [
                {"symbol": "power:GND", "position": {"x": 50.8, "y": 50.8}},
                {"symbol": "power:GND", "reference": "#PWR?", "position": {"x": 76.2, "y": 50.8}},
                {"symbol": "power:GND", "reference": "", "position": {"x": 101.6, "y": 50.8}},
            ],
        }
    )

    assert result["success"] is True, result
    assert [e["reference"] for e in result["added"]] == ["#PWR01", "#PWR02", "#PWR03"]
    assert [e["index"] for e in result["added"]] == [0, 1, 2]
    placed = _references(sch.read_text(encoding="utf-8"))
    assert {"#PWR01", "#PWR02", "#PWR03"} <= set(placed)
    assert "#PWR?" not in placed and "X?" not in placed


def test_an_explicit_power_reference_is_kept(tmp_path: Path) -> None:
    sch = tmp_path / "power.kicad_sch"
    sch.write_text(_POWER_SCH, encoding="utf-8", newline="")

    result = _commands().batch_add_components(
        {
            "schematicPath": str(sch),
            "components": [{"symbol": "power:GND", "reference": "#PWR42"}],
        }
    )

    assert [e["reference"] for e in result["added"]] == ["#PWR42"]


@pytest.mark.parametrize("missing", [{}, {"reference": ""}, {"reference": "X?"}])
def test_a_non_power_symbol_without_a_reference_is_refused(
    tmp_path: Path, missing: Dict[str, Any]
) -> None:
    sch = tmp_path / "test.kicad_sch"
    shutil.copy(EMPTY_SCH, sch)
    before = sch.read_text(encoding="utf-8")

    result = _commands().batch_add_components(
        {
            "schematicPath": str(sch),
            "components": [{"symbol": "Device:R", "value": "1k", **missing}],
        }
    )

    assert result["success"] is False
    assert result["added_count"] == 0
    [error] = result["errors"]
    assert error["index"] == 0
    assert "Reference is required for Device:R" in error["error"]
    assert sch.read_text(encoding="utf-8") == before


# --- batch_add_and_connect --------------------------------------------------


def _orchestrate(components: List[Dict[str, Any]], added: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run batch_add_and_connect with placement and wiring stubbed; return the wiring call."""
    c = _commands()
    connect_args: Dict[str, Any] = {}

    def fake_add(params: Dict[str, Any]) -> Dict[str, Any]:
        return {"added_count": len(added), "added": added, "errors": [], "placement_bbox": None}

    def fake_connect(params: Dict[str, Any]) -> Dict[str, Any]:
        connect_args.update(params)
        return {"placed": [], "failed": []}

    c.batch_add_components = fake_add  # type: ignore[method-assign]
    c.batch_connect = fake_connect  # type: ignore[method-assign]
    c.batch_add_and_connect({"schematicPath": "/x.kicad_sch", "components": components})
    return connect_args


def test_nets_follow_the_reference_each_component_was_placed_as() -> None:
    # Two power symbols both sent as "#PWR?": keyed by the sent reference they
    # collided, and neither matched the #PWRnn actually placed.
    connect_args = _orchestrate(
        [
            {"symbol": "power:GND", "reference": "#PWR?", "nets": {"1": "GND"}},
            {"symbol": "power:+3V3", "reference": "#PWR?", "nets": {"1": "+3V3"}},
            {"symbol": "Device:R", "reference": "R1", "nets": {"1": "+3V3", "2": "GND"}},
        ],
        [
            {"index": 0, "reference": "#PWR01"},
            {"index": 1, "reference": "#PWR02"},
            {"index": 2, "reference": "R1"},
        ],
    )

    assert connect_args["connections"] == {
        "#PWR01": {"1": "GND"},
        "#PWR02": {"1": "+3V3"},
        "R1": {"1": "+3V3", "2": "GND"},
    }


def test_a_component_that_failed_to_place_gets_no_nets() -> None:
    connect_args = _orchestrate(
        [
            {"symbol": "Device:R", "nets": {"1": "VCC"}},  # refused: no reference
            {"symbol": "Device:R", "reference": "R2", "nets": {"1": "VCC"}},
        ],
        [{"index": 1, "reference": "R2"}],
    )

    assert connect_args["connections"] == {"R2": {"1": "VCC"}}


def test_units_of_one_part_merge_their_nets() -> None:
    # Each unit is its own entry under one reference; the last one no longer
    # replaces the nets of the others.
    connect_args = _orchestrate(
        [
            {"symbol": "Amp:Dual", "reference": "U1", "unit": 1, "nets": {"1": "OUTA"}},
            {"symbol": "Amp:Dual", "reference": "U1", "unit": 2, "nets": {"7": "OUTB"}},
        ],
        [{"index": 0, "reference": "U1"}, {"index": 1, "reference": "U1"}],
    )

    assert connect_args["connections"] == {"U1": {"1": "OUTA", "7": "OUTB"}}
