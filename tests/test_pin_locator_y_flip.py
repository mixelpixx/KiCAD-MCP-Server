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

from commands.component_schematic import ComponentManager  # noqa: E402
from commands.pin_locator import PinLocator  # noqa: E402
from commands.schematic import SchematicManager  # noqa: E402


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

        # Device:C pin 1 is at symbol (0, +3.81). After y-negate → (0, -3.81).
        # Rotated 90° CCW in screen coords: (0, -3.81) → (3.81, 0).
        # Absolute: (150+3.81, 100+0) = (153.81, 100).
        assert p1[0] == pytest.approx(153.81), f"rotated pin 1 X wrong: {p1[0]}"
        assert p1[1] == pytest.approx(100.0), f"rotated pin 1 Y wrong: {p1[1]}"
