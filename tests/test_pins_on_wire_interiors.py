"""find_pins_on_wire_interiors: a pin drawn on the middle of a wire (#522).

KiCad joins a pin to a wire only where the wire ends, or where a junction sits on
the pin. A wire drawn straight through a pin leaves the pin unconnected while the
drawing suggests otherwise. The maintainers checked this with kicad-cli 10.0.7 netlists (#522):

| On R1 pin 2, mid-wire | Netlist                                   |
|-----------------------|-------------------------------------------|
| nothing               | R1.2 and R2.2 on separate nets            |
| a junction            | R1.2 and R2.2 on one net                  |
| a label `N`           | R1.2 alone on /N; R2.2 still on its own net |
| a second wire's end   | R1.2 with that wire only; R2.2 on its own |
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_analysis import find_pins_on_wire_interiors  # noqa: E402

from tests.test_junction_wire_tee import (  # noqa: E402
    FONT,
    LIB,
    ROOT,
    _junction,
    _kicad_joins_r1_r2,
    _sym,
    _wire,
)

# LIB plus a one-pin power symbol, so a power pin can sit on a wire too.
GND_LIB = (
    LIB.rstrip()[: -len(")")]
    + f"""    (symbol "T:GND" (power) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "#PWR" (at 0 -6.35 0) {FONT})
      (property "Value" "GND" (at 0 -3.81 0) {FONT})
      (symbol "GND_1_1"
        (pin power_in line (at 0 0 270) (length 0) (name "GND" {FONT}) (number "1" {FONT}))
      )
    )
  )
"""
)

R1 = _sym("R1", "33333333-3333-3333-3333-333333330000", 100, 100)  # pin 2 at (101.27, 100)
R2 = _sym("R2", "44444444-4444-4444-4444-444444440000", 100, 130)  # pin 2 at (101.27, 130)

# The case from the issue: one wire runs vertically through R1 pin 2 and ends on R2 pin 2.
THROUGH_R1 = _wire(1, 101.27, 90, 101.27, 130)
SECOND_ENDS_ON_R1 = _wire(2, 101.27, 100, 120, 100)  # ends on R1 pin 2


def _gnd(ref, x, y):
    return f"""  (symbol (lib_id "T:GND") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes) (dnp no)
    (uuid "66666666-6666-6666-6666-666666660000")
    (property "Reference" "{ref}" (at {x} {y + 6} 0) (effects (font (size 1.27 1.27)) hide))
    (property "Value" "GND" (at {x} {y + 4} 0) {FONT})
    (pin "1" (uuid "66666666-6666-6666-6666-666666660001"))
    (instances (project "p" (path "/{ROOT}" (reference "{ref}") (unit 1))))
  )
"""


def _label(name, x, y):
    return (
        f'  (label "{name}" (at {x} {y} 0) {FONT} (uuid "77777777-7777-7777-7777-777777770000"))\n'
    )


def _no_connect(x, y):
    return f'  (no_connect (at {x} {y}) (uuid "88888888-8888-8888-8888-888888880000"))\n'


def _write(tmp_path, body, symbols=R1 + R2, lib=None):
    sch = tmp_path / "p.kicad_sch"
    sch.write_text(
        '(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n'
        f'  (uuid "{ROOT}")\n  (paper "A4")\n'
        + (lib or GND_LIB)
        + body
        + symbols
        + '  (sheet_instances (path "/" (page "1")))\n)\n',
        encoding="utf-8",
    )
    return sch


def _pins(found):
    return [(f["component"]["reference"], f["pin"]) for f in found]


def test_pin_on_a_wire_interior_is_reported(tmp_path):
    found = find_pins_on_wire_interiors(_write(tmp_path, THROUGH_R1))
    assert _pins(found) == [("R1", "2")]
    hit = found[0]
    assert hit["component"]["libId"] == "T:R"
    assert hit["pinPosition"] == {"x": pytest.approx(101.27), "y": pytest.approx(100)}
    assert hit["wire"] == {"start": {"x": 101.27, "y": 90.0}, "end": {"x": 101.27, "y": 130.0}}


def test_wire_ending_on_the_pin_is_fine(tmp_path):
    body = _wire(1, 101.27, 90, 101.27, 100) + _wire(2, 101.27, 100, 101.27, 130)
    assert find_pins_on_wire_interiors(_write(tmp_path, body)) == []


def test_second_wire_ending_on_the_pin_does_not_connect_the_through_wire(tmp_path):
    # Wire 2 ends on R1 pin 2 and joins it, but wire 1 is not split there: KiCad
    # puts R1.2 with wire 2 only, not with R2.2 (20 of 20 cases in #533's review).
    found = find_pins_on_wire_interiors(_write(tmp_path, THROUGH_R1 + SECOND_ENDS_ON_R1))
    assert _pins(found) == [("R1", "2")]
    assert found[0]["wire"]["start"] == {"x": 101.27, "y": 90.0}


def test_junction_on_the_pin_connects_it(tmp_path):
    assert find_pins_on_wire_interiors(_write(tmp_path, THROUGH_R1 + _junction(101.27, 100))) == []


def test_label_on_the_pin_is_still_reported(tmp_path):
    # The label joins the pin, not the unsplit wire, so the drawing still misleads.
    found = find_pins_on_wire_interiors(_write(tmp_path, THROUGH_R1 + _label("N", 101.27, 100)))
    assert _pins(found) == [("R1", "2")]


def test_no_connect_on_the_pin_is_still_reported(tmp_path):
    found = find_pins_on_wire_interiors(_write(tmp_path, THROUGH_R1 + _no_connect(101.27, 100)))
    assert _pins(found) == [("R1", "2")]


def test_power_pins_are_included(tmp_path):
    body = _wire(1, 90, 120, 110, 120)
    found = find_pins_on_wire_interiors(_write(tmp_path, body, R1 + _gnd("#PWR01", 100, 120)))
    assert _pins(found) == [("#PWR01", "1")]


def test_pin_off_the_wire_line_is_not_reported(tmp_path):
    # The wire passes 0.01 mm beside the pin, not through it.
    body = _wire(1, 101.28, 90, 101.28, 130)
    assert find_pins_on_wire_interiors(_write(tmp_path, body)) == []


def test_pin_just_beyond_the_wire_end_is_not_reported(tmp_path):
    body = _wire(1, 101.27, 80, 101.27, 99)
    assert find_pins_on_wire_interiors(_write(tmp_path, body)) == []


def test_each_wire_through_the_pin_is_reported(tmp_path):
    # A second, horizontal wire from x=100 also runs through pin 2 (but not pin 1 at x=98.73).
    body = THROUGH_R1 + _wire(2, 100, 100, 110, 100)
    found = find_pins_on_wire_interiors(_write(tmp_path, body))
    assert _pins(found) == [("R1", "2"), ("R1", "2")]
    assert {f["wire"]["start"]["x"] for f in found} == {101.27, 100.0}


def test_template_symbols_are_ignored(tmp_path):
    template = _sym("_TEMPLATE_R", "99999999-9999-9999-9999-999999990000", 100, 100)
    assert find_pins_on_wire_interiors(_write(tmp_path, THROUGH_R1, template)) == []


DUAL_LIB = f"""    (symbol "T:DUAL" (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 2.54 0) {FONT})
      (symbol "DUAL_0_1"
        (pin power_in line (at 0 -2.54 90) (length 0) (name "V-" {FONT}) (number "8" {FONT}))
      )
      (symbol "DUAL_1_1"
        (pin input line (at -2.54 0 0) (length 0) (name "A" {FONT}) (number "1" {FONT}))
      )
      (symbol "DUAL_2_1"
        (pin input line (at 2.54 0 180) (length 0) (name "B" {FONT}) (number "2" {FONT}))
      )
    )
  )
"""


def _dual(unit, x, y):
    return f"""  (symbol (lib_id "T:DUAL") (at {x} {y} 0) (unit {unit}) (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa000{unit}")
    (property "Reference" "U1" (at {x} {y - 3} 0) {FONT})
    (instances (project "p" (path "/{ROOT}" (reference "U1") (unit {unit}))))
  )
"""


@pytest.mark.parametrize("unit,expected", [(1, [("U1", "8")]), (2, [("U1", "2"), ("U1", "8")])])
def test_only_the_placed_units_pins_count(tmp_path, unit, expected):
    # Unit 2's pin 2 would sit at (102.54, 100); placed as unit 1 there is no pin there.
    # Pin 8 is common to all units (unit 0), at (100, 102.54).
    body = _wire(1, 102.54, 90, 102.54, 110) + _wire(2, 90, 102.54, 110, 102.54)
    lib = GND_LIB.rstrip()[: -len(")")] + DUAL_LIB
    found = find_pins_on_wire_interiors(_write(tmp_path, body, _dual(unit, 100, 100), lib))
    assert sorted(_pins(found)) == expected


@pytest.mark.integration
def test_matches_kicad_netlist(tmp_path):
    if not shutil.which("kicad-cli"):
        pytest.skip("needs kicad-cli")
    for extra, joined in [
        ("", False),
        (_junction(101.27, 100), True),
        (SECOND_ENDS_ON_R1, False),
    ]:
        sch = _write(tmp_path, THROUGH_R1 + extra)
        reported = bool(find_pins_on_wire_interiors(sch))
        assert _kicad_joins_r1_r2(sch) is joined
        assert reported is not joined


def test_tool_reply_adds_the_new_key_next_to_collisions(tmp_path):
    from types import SimpleNamespace

    from commands.schematic_handlers import SchematicHandlersMixin

    sch = _write(tmp_path, THROUGH_R1)
    reply = SchematicHandlersMixin._handle_find_wires_crossing_symbols(
        SimpleNamespace(), {"schematicPath": str(sch)}
    )
    assert reply["success"] is True
    # The existing keys keep their meaning: the wire runs past R1's body, not through it.
    assert (reply["collisions"], reply["count"]) == ([], 0)
    assert _pins(reply["pinsOnWireInterior"]) == [("R1", "2")]
    assert reply["pinsOnWireInteriorCount"] == 1
    assert "1 pin(s)" in reply["message"]
