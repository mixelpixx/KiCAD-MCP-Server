"""
Regression test for #239: get_schematic_pin_locations returned wrong coordinates
for multi-unit components.

Each unit of a multi-unit symbol is placed as a SEPARATE (symbol ...) instance
that shares the reference but carries its own (unit N) and (at ...).  The pin
locator used to compute every pin from whichever instance appeared first in file
order, so a pin belonging to unit 2 (placed lower on the sheet) was reported at
unit 1's position.  The fix maps each pin to its unit (via the lib_symbols
sub-symbol name <name>_<unit>_<style>) and reads that unit's placement.

The schematic below is fully self-contained (baked lib_symbols), so the test
needs no installed KiCad symbol library.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# A two-unit symbol "Test:DUAL": unit 1 has pin "1", unit 2 has pin "2", each a
# vertical pin whose connection point sits 2.54 mm above the symbol origin.
# U1 unit 1 is placed at y=100, unit 2 at y=150.
DUAL_SCH = """(kicad_sch (version 20250114) (generator "test")
  (uuid b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d60)
  (paper "A4")
  (lib_symbols
    (symbol "Test:DUAL" (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Value" "DUAL" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (symbol "DUAL_1_1"
        (pin passive line (at 0 2.54 270) (length 2.54)
          (name "A" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))
      )
      (symbol "DUAL_2_1"
        (pin passive line (at 0 2.54 270) (length 2.54)
          (name "B" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27)))))
      )
    )
  )
  (symbol (lib_id "Test:DUAL") (at 100 100 0) (unit 1)
    (uuid 11111111-1111-1111-1111-111111111111)
    (property "Reference" "U1" (at 100 96 0) (effects (font (size 1.27 1.27))))
    (property "Value" "DUAL" (at 100 104 0) (effects (font (size 1.27 1.27))))
    (pin "1" (uuid aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa))
    (instances (project "p" (path "/" (reference "U1") (unit 1))))
  )
  (symbol (lib_id "Test:DUAL") (at 100 150 0) (unit 2)
    (uuid 22222222-2222-2222-2222-222222222222)
    (property "Reference" "U1" (at 100 146 0) (effects (font (size 1.27 1.27))))
    (property "Value" "DUAL" (at 100 154 0) (effects (font (size 1.27 1.27))))
    (pin "2" (uuid bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb))
    (instances (project "p" (path "/" (reference "U1") (unit 2))))
  )
  (sheet_instances (path "/" (page "1")))
)
"""


@pytest.fixture
def dual_sch() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".kicad_sch", delete=False, mode="w", encoding="utf-8")
    tmp.write(DUAL_SCH)
    tmp.close()
    return Path(tmp.name)


@pytest.mark.unit
class TestMultiUnitPinLocation:
    def _locator(self):
        from commands.pin_locator import PinLocator

        return PinLocator()

    def test_pin_unit_map(self, dual_sch: Path) -> None:
        """Pins are mapped to the correct unit from the lib_symbols sub-symbols."""
        umap = self._locator().get_pin_unit_map(dual_sch, "Test:DUAL")
        assert umap == {"1": 1, "2": 2}

    def test_find_symbol_selects_instance_by_unit(self, dual_sch: Path) -> None:
        import sexpdata
        from commands.wire_dragger import WireDragger

        data = sexpdata.loads(dual_sch.read_text())
        _, x1, y1, *_ = WireDragger.find_symbol(data, "U1", unit=1)
        _, x2, y2, *_ = WireDragger.find_symbol(data, "U1", unit=2)
        assert (x1, y1) == (100.0, 100.0)
        assert (x2, y2) == (100.0, 150.0)

    def test_pins_located_from_their_own_unit(self, dual_sch: Path) -> None:
        """Pin 1 (unit 1 @y=100) and pin 2 (unit 2 @y=150) resolve to distinct
        y positions — the pre-fix bug reported both at unit 1's position."""
        loc = self._locator()
        p1 = loc.get_pin_location(dual_sch, "U1", "1")
        p2 = loc.get_pin_location(dual_sch, "U1", "2")
        assert p1 is not None and p2 is not None
        # unit 1 origin y=100, unit 2 origin y=150; pins sit ~2.54 mm off origin
        assert abs(p1[1] - 100) < 5, p1
        assert abs(p2[1] - 150) < 5, p2
        # The two pins must NOT collapse onto the same unit's position.
        assert abs(p1[1] - p2[1]) > 40, (p1, p2)
