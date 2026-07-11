"""
Regression tests for issue #239:

    get_schematic_pin_locations returns wrong coordinates for multi-unit components

A multi-unit part (e.g. a dual op-amp) is placed as several ``(symbol ...)``
instances that share one reference designator but each carry their own
``(unit N)``, position and rotation. The pins for unit N live in the
``<name>_N_<body>`` sub-symbol inside ``lib_symbols``.

The bug: every pin was located against whichever instance appeared first in
file order, so all pins collapsed onto that one unit's position. These tests
place a 2-unit symbol at two distinct positions and assert each pin resolves
against the instance for its own unit.
"""

import sys
import tempfile
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))


# A minimal but valid schematic with one 2-unit symbol "TEST:DualAmp":
#   unit 1 (pins 1,2,3) placed at (100, 100)
#   unit 2 (pins 5,6,7) placed at (100, 150)
# Pin library Y offsets are distinct per pin so a mislocated pin is obvious.
MULTI_UNIT_SCH = """\
(kicad_sch (version 20250114) (generator "test")
  (uuid 00000000-0000-0000-0000-0000000000aa)
  (paper "A4")
  (lib_symbols
    (symbol "TEST:DualAmp" (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0))
      (property "Value" "DualAmp" (at 0 0 0))
      (symbol "DualAmp_1_1"
        (pin input line (at 0 5.08 270) (length 2.54)
          (name "+" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin input line (at 0 -5.08 90) (length 2.54)
          (name "-" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
        (pin output line (at 7.62 0 180) (length 2.54)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "3" (effects (font (size 1.27 1.27))))
        )
      )
      (symbol "DualAmp_2_1"
        (pin input line (at 0 5.08 270) (length 2.54)
          (name "+" (effects (font (size 1.27 1.27))))
          (number "5" (effects (font (size 1.27 1.27))))
        )
        (pin input line (at 0 -5.08 90) (length 2.54)
          (name "-" (effects (font (size 1.27 1.27))))
          (number "6" (effects (font (size 1.27 1.27))))
        )
        (pin output line (at 7.62 0 180) (length 2.54)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "7" (effects (font (size 1.27 1.27))))
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


@pytest.mark.integration
class TestParseSymbolDefinitionUnits:
    """parse_symbol_definition must tag each pin with its owning unit."""

    def test_pins_carry_their_unit(self):
        import sexpdata
        from kicad_mcp.commands.pin_locator import PinLocator
        from sexpdata import Symbol

        sch_data = sexpdata.loads(MULTI_UNIT_SCH)
        lib_symbols = next(
            item
            for item in sch_data
            if isinstance(item, list) and item and item[0] == Symbol("lib_symbols")
        )
        sym_def = next(
            item
            for item in lib_symbols[1:]
            if isinstance(item, list) and str(item[1]).strip('"') == "TEST:DualAmp"
        )

        pins = PinLocator.parse_symbol_definition(sym_def)

        assert pins["1"]["unit"] == 1
        assert pins["2"]["unit"] == 1
        assert pins["3"]["unit"] == 1
        assert pins["5"]["unit"] == 2
        assert pins["6"]["unit"] == 2
        assert pins["7"]["unit"] == 2


@pytest.mark.integration
class TestMultiUnitPinLocations:
    """Each pin resolves against the placed instance for its own unit (#239)."""

    def test_unit1_pin_uses_unit1_position(self, multi_unit_sch):
        from kicad_mcp.commands.pin_locator import PinLocator

        loc = PinLocator().get_pin_location(multi_unit_sch, "U1", "1")

        assert loc is not None
        # Unit 1 sits at y=100; pin lib-y +5.08 flips to screen -> 100 - 5.08.
        assert loc[0] == pytest.approx(100.0)
        assert loc[1] == pytest.approx(94.92)

    def test_unit2_pin_uses_unit2_position_not_first_instance(self, multi_unit_sch):
        from kicad_mcp.commands.pin_locator import PinLocator

        loc = PinLocator().get_pin_location(multi_unit_sch, "U1", "5")

        assert loc is not None
        # Unit 2 sits at y=150. The bug reported it near unit 1 (~94.92); it must
        # now track unit 2's instance: 150 - 5.08 = 144.92.
        assert loc[1] == pytest.approx(144.92)
        assert loc[1] != pytest.approx(94.92)

    def test_all_pins_split_across_the_two_units(self, multi_unit_sch):
        from kicad_mcp.commands.pin_locator import PinLocator

        pins = PinLocator().get_all_symbol_pins(multi_unit_sch, "U1")

        # Unit 1 pins cluster around y=100, unit 2 pins around y=150.
        assert pins["1"][1] == pytest.approx(94.92)
        assert pins["2"][1] == pytest.approx(105.08)
        assert pins["5"][1] == pytest.approx(144.92)
        assert pins["6"][1] == pytest.approx(155.08)
        # The output pins (pin lib-y 0) sit exactly at each unit's center y.
        assert pins["3"][1] == pytest.approx(100.0)
        assert pins["7"][1] == pytest.approx(150.0)
