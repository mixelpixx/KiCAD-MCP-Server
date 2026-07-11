"""
Regression test for the symbol-to-schematic Y-axis flip in PinLocator.

Before the fix, pin_locator.py's get_pin_location() negated pin_data["y"]
twice in sequence (two identical blocks, one commented "Negate y here before
rotation" and a second commented "lib_symbols uses y-up; schematic uses y-down"
doing the exact same flip). The double-negation cancelled out, leaving pin
Y-coordinates mirrored about the symbol placement Y. For symmetric passives
(pin 1 and pin 2 electrically equivalent) the bug was invisible; for ICs with
non-equivalent pins it caused misrouted connections.

This test places a stock Device:R at a known absolute position and verifies
that pin 1 (symbol y=+3.81) resolves to an absolute Y *above* the placement
centre (i.e. placement_y - 3.81), matching KiCad's actual render and its
kicad-cli net extraction. The pre-fix code put pin 1 below the centre.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from kicad_mcp.commands.component_schematic import ComponentManager  # noqa: E402
from kicad_mcp.commands.pin_locator import PinLocator  # noqa: E402
from kicad_mcp.commands.schematic import SchematicManager  # noqa: E402


@pytest.mark.unit
def test_stock_resistor_pin_y_matches_render_convention():
    """Stock Device:R pin 1 must resolve to placement_y - 3.81 (above centre)."""
    template = (
        Path(__file__).resolve().parent.parent
        / "python"
        / "templates"
        / "template_with_symbols.kicad_sch"
    )
    if not template.exists():
        pytest.skip(f"Test template not found at {template}")

    with tempfile.TemporaryDirectory() as tmp:
        sch_path = Path(tmp) / "regression.kicad_sch"
        shutil.copy(template, sch_path)

        sch = SchematicManager.load_schematic(str(sch_path))
        ComponentManager.add_component(
            sch,
            {"type": "R", "reference": "R1", "value": "10k", "x": 100.0, "y": 100.0, "rotation": 0},
            sch_path,
        )
        SchematicManager.save_schematic(sch, str(sch_path))

        locator = PinLocator()
        p1 = locator.get_pin_location(sch_path, "R1", "1")
        p2 = locator.get_pin_location(sch_path, "R1", "2")

        assert p1 is not None and p2 is not None, "PinLocator returned None"

        # Device:R defines pin 1 at symbol (0, +3.81) and pin 2 at (0, -3.81).
        # KiCad symbol space is +Y up; schematic space is +Y down. After the
        # correct single negation, pin 1 lands at placement_y - 3.81 and pin 2
        # at placement_y + 3.81.
        assert p1[0] == pytest.approx(100.0), f"pin 1 X wrong: {p1[0]}"
        assert p1[1] == pytest.approx(96.19), f"pin 1 Y wrong: {p1[1]} (expected 96.19)"
        assert p2[0] == pytest.approx(100.0), f"pin 2 X wrong: {p2[0]}"
        assert p2[1] == pytest.approx(103.81), f"pin 2 Y wrong: {p2[1]} (expected 103.81)"


@pytest.mark.unit
def test_rotated_capacitor_pin_x_matches_render_convention():
    """Device:C rotated 90 CCW: pin 1 (was at +Y) should land on -X of placement."""
    template = (
        Path(__file__).resolve().parent.parent
        / "python"
        / "templates"
        / "template_with_symbols.kicad_sch"
    )
    if not template.exists():
        pytest.skip(f"Test template not found at {template}")

    with tempfile.TemporaryDirectory() as tmp:
        sch_path = Path(tmp) / "rot_regression.kicad_sch"
        shutil.copy(template, sch_path)

        sch = SchematicManager.load_schematic(str(sch_path))
        ComponentManager.add_component(
            sch,
            {
                "type": "C",
                "reference": "C1",
                "value": "100nF",
                "x": 150.0,
                "y": 100.0,
                "rotation": 90,
            },
            sch_path,
        )
        SchematicManager.save_schematic(sch, str(sch_path))

        locator = PinLocator()
        p1 = locator.get_pin_location(sch_path, "C1", "1")
        assert p1 is not None

        # Device:C pin 1 lib (0, +3.81). parseXY(invertY=true) → internal (0, -3.81).
        # Rotation 90 in eeschema is CCW in screen Y-down: TRANSFORM(0,1,-1,0).
        # Apply: (0*0 + 1*(-3.81), -1*0 + 0*(-3.81)) = (-3.81, 0).
        # World: (150-3.81, 100) = (146.19, 100). Verified vs kicad-cli netlist.
        assert p1[0] == pytest.approx(146.19), f"rotated pin 1 X wrong: {p1[0]}"
        assert p1[1] == pytest.approx(100.0), f"rotated pin 1 Y wrong: {p1[1]}"


# ---------------------------------------------------------------------------
# Asymmetric multi-pin regression (the case where the original bug hit hardest)
# ---------------------------------------------------------------------------
#
# The symmetric-symbol tests above pass even with the pre-fix code because
# Device:R and Device:C are pin-equivalent — swap pin 1 and pin 2 in the
# netlist and the circuit still works. The bug only became visible on
# asymmetric, multi-pin ICs like RF_Module:ESP32-WROOM-32, where pin 3 (EN)
# and pin 35 (TXD0/IO1) are not interchangeable. With the original code,
# pins at library y=+30.48 (top of the symbol) were reported at world
# y=symbol_y+30.48 (bottom of the schematic), so labels meant for EN landed
# on TXD0, and ERC reported either a dangling label or a wrong connection.
#
# Issue #135 specifically asked for an asymmetric-symbol regression. Rather
# than depend on system libraries (RF_Module is not bundled with the repo),
# this fixture builds a minimal 6-pin asymmetric symbol inline and asserts
# every pin lands at the formula-predicted absolute position.

_ASYMMETRIC_FIXTURE = """(kicad_sch
    (version 20231120) (generator "test_pin_locator_y_flip")
    (uuid "00000000-0000-0000-0000-000000000001")
    (paper "A4")
    (lib_symbols
        (symbol "Test:Asym6"
            (pin_numbers hide) (pin_names (offset 0.508))
            (in_bom yes) (on_board yes)
            (property "Reference" "U" (at 0 15.24 0)
                (effects (font (size 1.27 1.27))))
            (property "Value" "Asym6" (at 0 -15.24 0)
                (effects (font (size 1.27 1.27))))
            (property "Footprint" "" (at 0 0 0)
                (effects (font (size 1.27 1.27)) hide))
            (property "Datasheet" "" (at 0 0 0)
                (effects (font (size 1.27 1.27)) hide))
            (symbol "Asym6_0_1"
                (rectangle (start -7.62 12.7) (end 7.62 -12.7)
                    (stroke (width 0.254) (type default))
                    (fill (type none))))
            (symbol "Asym6_1_1"
                (pin input line (at -10.16 10.16 0) (length 2.54)
                    (name "TOP_LEFT" (effects (font (size 1.27 1.27))))
                    (number "1" (effects (font (size 1.27 1.27)))))
                (pin input line (at -10.16 5.08 0) (length 2.54)
                    (name "MID_HIGH_L" (effects (font (size 1.27 1.27))))
                    (number "2" (effects (font (size 1.27 1.27)))))
                (pin input line (at -10.16 -5.08 0) (length 2.54)
                    (name "MID_LOW_L" (effects (font (size 1.27 1.27))))
                    (number "3" (effects (font (size 1.27 1.27)))))
                (pin input line (at -10.16 -10.16 0) (length 2.54)
                    (name "BOT_LEFT" (effects (font (size 1.27 1.27))))
                    (number "4" (effects (font (size 1.27 1.27)))))
                (pin output line (at 10.16 10.16 180) (length 2.54)
                    (name "TOP_RIGHT" (effects (font (size 1.27 1.27))))
                    (number "5" (effects (font (size 1.27 1.27)))))
                (pin output line (at 10.16 -10.16 180) (length 2.54)
                    (name "BOT_RIGHT" (effects (font (size 1.27 1.27))))
                    (number "6" (effects (font (size 1.27 1.27))))))))
    (symbol
        (lib_id "Test:Asym6") (at 100 100 0) (unit 1)
        (in_bom yes) (on_board yes) (dnp no)
        (uuid "11111111-1111-1111-1111-111111111111")
        (property "Reference" "U1" (at 100 84.76 0)
            (effects (font (size 1.27 1.27))))
        (property "Value" "Asym6" (at 100 115.24 0)
            (effects (font (size 1.27 1.27))))
        (property "Footprint" "" (at 100 100 0)
            (effects (font (size 1.27 1.27)) hide))
        (property "Datasheet" "" (at 100 100 0)
            (effects (font (size 1.27 1.27)) hide))
        (instances
            (project "test"
                (path "/00000000-0000-0000-0000-000000000001"
                    (reference "U1") (unit 1))))))
"""


@pytest.mark.unit
def test_asymmetric_multi_pin_symbol_y_flip():
    """A 6-pin asymmetric IC must report every pin at the correct side of centre.

    Pre-#135 fix, library y=+10.16 pins were reported at schematic y=+110.16
    (below the placement centre at y=100). The render-correct answer is
    schematic y=89.84 (above the centre, smaller numerical y in Y-down).

    Each side (left at lib x=-10.16, right at lib x=+10.16) carries pins at
    both positive and negative library Y — so a Y-flip bug or a left/right
    swap would visibly mis-place at least one pin. This is the asymmetric
    multi-pin regression requested in issue #135 (originally hit on
    RF_Module:ESP32-WROOM-32 in the wild; same arithmetic, smaller fixture).
    """
    with tempfile.TemporaryDirectory() as tmp:
        sch_path = Path(tmp) / "asym6_regression.kicad_sch"
        sch_path.write_text(_ASYMMETRIC_FIXTURE, encoding="utf-8")

        locator = PinLocator()
        # Placement: U1 at (100, 100) rotation 0, no mirror.
        # Formula in screen Y-down (after the Y-flip fix):
        #   world_x = symbol_x + lib_px
        #   world_y = symbol_y + (-lib_py)
        # so the lib +Y pins (top of symbol) end up at smaller world_y, i.e.
        # *above* the placement centre.
        expected = {
            "1": (100 - 10.16, 100 - 10.16),  # 89.84, 89.84
            "2": (100 - 10.16, 100 - 5.08),   # 89.84, 94.92
            "3": (100 - 10.16, 100 + 5.08),   # 89.84, 105.08
            "4": (100 - 10.16, 100 + 10.16),  # 89.84, 110.16
            "5": (100 + 10.16, 100 - 10.16),  # 110.16, 89.84
            "6": (100 + 10.16, 100 + 10.16),  # 110.16, 110.16
        }

        for pin_num, (exp_x, exp_y) in expected.items():
            loc = locator.get_pin_location(sch_path, "U1", pin_num)
            assert loc is not None, f"PinLocator returned None for pin {pin_num}"
            assert loc[0] == pytest.approx(exp_x), (
                f"pin {pin_num} X wrong: got {loc[0]}, expected {exp_x}"
            )
            assert loc[1] == pytest.approx(exp_y), (
                f"pin {pin_num} Y wrong: got {loc[1]}, expected {exp_y}"
            )

        # Cross-check the side-asymmetry directly: top-left (lib y=+10.16) must
        # be ABOVE centre, bottom-left (lib y=-10.16) BELOW centre. Pre-fix
        # these would be swapped because of the double-Y-flip.
        p1 = locator.get_pin_location(sch_path, "U1", "1")
        p4 = locator.get_pin_location(sch_path, "U1", "4")
        assert p1[1] < 100, f"top pin must be above centre, got y={p1[1]}"
        assert p4[1] > 100, f"bottom pin must be below centre, got y={p4[1]}"
