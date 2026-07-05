"""
Regression tests for issue #293:

    get_wire_connections reports phantom cross-unit pins in net membership

A multi-unit part is placed as several ``(symbol ...)`` instances that share
one reference designator but each carry their own ``(unit N)``, position and
rotation. Each instance only owns the pins defined in its unit's sub-symbol
(plus unit 0, common to all units).

The bug: ``_find_pins_on_net`` transformed *every* unit's pins against *every*
instance's position. When two units share an x-coordinate and their pins have
identical library offsets (the normal case for a dual op-amp), a sibling unit's
pin lands exactly on this instance's wire and is reported as a phantom member
of the net.

These tests place a 2-unit symbol whose two units share x and differ only in y,
wire each unit's output pin to a distinct passive, and assert that each net
contains only the pin from its own unit -- never the sibling unit's pin.
"""

import sys
import tempfile
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))


# Two-unit symbol "TEST:DualAmp":
#   unit 1 output = pin 3, unit 2 output = pin 7, both at lib offset (7.62, 0).
# Placed:
#   unit 1 at (100, 100) -> output pin 3 at (107.62, 100)
#   unit 2 at (100, 150) -> output pin 7 at (107.62, 150)
# A wire + resistor hangs off each output. Because both units share x=100 and
# both outputs are at lib-x +7.62, the pre-fix code transforms unit 2's pin 7
# against unit 1's instance -> (107.62, 100), landing on unit 1's wire, and
# vice versa. The fix must keep pin 7 off unit 1's net and pin 3 off unit 2's.
MULTI_UNIT_SCH = """\
(kicad_sch (version 20250114) (generator "test")
  (uuid 00000000-0000-0000-0000-0000000000aa)
  (paper "A4")
  (lib_symbols
    (symbol "TEST:DualAmp" (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0))
      (property "Value" "DualAmp" (at 0 0 0))
      (symbol "DualAmp_1_1"
        (pin output line (at 7.62 0 180) (length 2.54)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "3" (effects (font (size 1.27 1.27))))
        )
      )
      (symbol "DualAmp_2_1"
        (pin output line (at 7.62 0 180) (length 2.54)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "7" (effects (font (size 1.27 1.27))))
        )
      )
    )
    (symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0))
      (property "Reference" "R" (at 0 0 0))
      (property "Value" "R" (at 0 0 0))
      (symbol "R_0_1")
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin passive line (at 0 -3.81 90) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )
  (symbol (lib_id "TEST:DualAmp") (at 100 100 0) (unit 1)
    (uuid 00000000-0000-0000-0000-000000000001)
    (property "Reference" "U1" (at 100 90 0))
    (property "Value" "DualAmp" (at 100 110 0))
  )
  (symbol (lib_id "TEST:DualAmp") (at 100 150 0) (unit 2)
    (uuid 00000000-0000-0000-0000-000000000002)
    (property "Reference" "U1" (at 100 140 0))
    (property "Value" "DualAmp" (at 100 160 0))
  )
  (symbol (lib_id "Device:R") (at 120 100 90) (unit 1)
    (uuid 00000000-0000-0000-0000-000000000101)
    (property "Reference" "R1" (at 120 95 0))
    (property "Value" "1k" (at 120 105 0))
  )
  (symbol (lib_id "Device:R") (at 120 150 90) (unit 1)
    (uuid 00000000-0000-0000-0000-000000000102)
    (property "Reference" "R2" (at 120 145 0))
    (property "Value" "1k" (at 120 155 0))
  )
  (wire (pts (xy 107.62 100) (xy 116.19 100))
    (stroke (width 0) (type default)) (uuid 00000000-0000-0000-0000-000000000201))
  (wire (pts (xy 107.62 150) (xy 116.19 150))
    (stroke (width 0) (type default)) (uuid 00000000-0000-0000-0000-000000000202))
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


@pytest.fixture()
def multi_unit_sch():
    with tempfile.TemporaryDirectory() as tmp:
        sch_path = Path(tmp) / "multi_unit.kicad_sch"
        sch_path.write_text(MULTI_UNIT_SCH, encoding="utf-8")
        yield sch_path


def _pins_on_net_at(sch_path, x_mm, y_mm):
    """Return the set of "REF/PIN" strings on the net reachable from a point."""
    from commands.wire_connectivity import get_wire_connections
    from skip import Schematic

    sch = Schematic(str(sch_path))
    result = get_wire_connections(sch, str(sch_path), x_mm, y_mm)
    assert result is not None
    return {f"{p['component']}/{p['pin']}" for p in result["pins"]}


@pytest.mark.integration
class TestNoPhantomCrossUnitPins:
    """Each unit's output net must contain only that unit's pin (#293)."""

    def test_unit1_net_excludes_unit2_pin(self, multi_unit_sch):
        # Unit 1 output wire runs from (107.62, 100).
        pins = _pins_on_net_at(multi_unit_sch, 107.62, 100.0)
        assert "U1/3" in pins  # unit 1's own output
        assert "R1/2" in pins  # the passive wired to it
        assert "U1/7" not in pins  # phantom sibling-unit pin must be gone

    def test_unit2_net_excludes_unit1_pin(self, multi_unit_sch):
        # Unit 2 output wire runs from (107.62, 150).
        pins = _pins_on_net_at(multi_unit_sch, 107.62, 150.0)
        assert "U1/7" in pins  # unit 2's own output
        assert "R2/2" in pins  # the passive wired to it
        assert "U1/3" not in pins  # phantom sibling-unit pin must be gone
