"""
Regression tests for three bugs fixed in PR #103:

  1. component_schematic.py: clone() + redundant append() causes trailing "_" on reference
  2. pin_locator.py: pin_rel_y must be negated (lib y-up → schematic y-down)
  3. pin_locator.py: reference comparison must tolerate trailing "_" from kicad-skip
"""

import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
TEMPLATES_DIR = PYTHON_DIR / "templates"
sys.path.insert(0, str(PYTHON_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEMPLATE_SCH = TEMPLATES_DIR / "template_with_symbols.kicad_sch"


def _stub_symbol(ref: str, at: list, lib_id: str = "Device:R") -> MagicMock:
    """Build a minimal kicad-skip symbol stub."""
    sym = MagicMock()
    sym.property.Reference.value = ref
    sym.at.value = at
    sym.lib_id.value = lib_id
    return sym


# ===========================================================================
# 1. component_schematic — no trailing underscore after clone()
# ===========================================================================


@pytest.mark.integration
class TestAddComponentNoTrailingUnderscore:
    """clone() already inserts the symbol; a second append() renamed the ref to 'R1_'."""

    def test_added_component_reference_has_no_trailing_underscore(self):
        from skip import Schematic

        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "test.kicad_sch"
            shutil.copy(_TEMPLATE_SCH, sch_path)

            from commands.component_schematic import ComponentManager

            schematic = Schematic(str(sch_path))
            component_def = {
                "type": "R",
                "reference": "R1",
                "value": "10k",
                "x": 100,
                "y": 100,
                "rotation": 0,
            }
            new_sym = ComponentManager.add_component(schematic, component_def, sch_path)
            ref = new_sym.property.Reference.value
            assert not ref.endswith(
                "_"
            ), f"Reference '{ref}' has trailing underscore — redundant append() was re-introduced"
            assert ref == "R1", f"Expected 'R1', got '{ref}'"


# ===========================================================================
# 2. pin_locator — y-axis sign (lib y-up → schematic y-down)
# ===========================================================================


@pytest.mark.unit
class TestPinLocatorYAxisNegation:
    """
    Device:R pin 1 is at library y=+3.81 (y-up).
    For a symbol centred at (100, 100) with rotation=0, the schematic absolute y
    must be 100 - 3.81 = 96.19, NOT 100 + 3.81 = 103.81.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        # Stub sexpdata and skip so the module can be imported without them installed
        for mod_name in ("sexpdata", "skip"):
            sys.modules.setdefault(mod_name, types.ModuleType(mod_name))
        from commands.pin_locator import PinLocator

        self.locator = PinLocator()

    def test_pin1_y_above_center_for_rotation_0(self):
        """Pin at lib y=+3.81 should appear *above* the symbol centre (lower y value)."""
        sym = _stub_symbol("R1", at=[100.0, 100.0, 0.0])
        self.locator._schematic_cache["test.kicad_sch"] = MagicMock(symbol=[sym])
        # Patch get_symbol_pins to return a Device:R-like pin definition
        with patch.object(
            self.locator,
            "get_symbol_pins",
            return_value={"1": {"x": 0.0, "y": 3.81, "angle": 270, "name": "~"}},
        ):
            result = self.locator.get_pin_location(Path("test.kicad_sch"), "R1", "1")

        assert result is not None
        x, y = result
        assert abs(x - 100.0) < 1e-6, f"x should be 100.0, got {x}"
        assert abs(y - 96.19) < 1e-4, (
            f"y should be ~96.19 (above centre), got {y}. "
            "y was not negated — library y-up convention mismatch."
        )

    def test_pin2_y_below_center_for_rotation_0(self):
        """Pin at lib y=-3.81 should appear *below* the symbol centre (higher y value)."""
        sym = _stub_symbol("R1", at=[100.0, 100.0, 0.0])
        self.locator._schematic_cache["test.kicad_sch"] = MagicMock(symbol=[sym])
        with patch.object(
            self.locator,
            "get_symbol_pins",
            return_value={"2": {"x": 0.0, "y": -3.81, "angle": 90, "name": "~"}},
        ):
            result = self.locator.get_pin_location(Path("test.kicad_sch"), "R1", "2")

        assert result is not None
        _, y = result
        assert abs(y - 103.81) < 1e-4, f"y should be ~103.81 (below centre), got {y}."

    def test_pin1_rotated_90(self):
        """
        Symbol rotated 90°. Pin at lib (x=0, y=+3.81).
        After y-negation: (0, -3.81). After 90° CCW rotation: (x=3.81, y=0).
        Absolute: (100+3.81, 100+0) = (103.81, 100).
        """
        sym = _stub_symbol("C1", at=[100.0, 100.0, 90.0])
        self.locator._schematic_cache["test.kicad_sch"] = MagicMock(symbol=[sym])
        with patch.object(
            self.locator,
            "get_symbol_pins",
            return_value={"1": {"x": 0.0, "y": 3.81, "angle": 270, "name": "~"}},
        ):
            result = self.locator.get_pin_location(Path("test.kicad_sch"), "C1", "1")

        assert result is not None
        x, y = result
        assert abs(x - 103.81) < 1e-4, f"x should be ~103.81, got {x}"
        assert abs(y - 100.0) < 1e-4, f"y should be ~100.0, got {y}"


# ===========================================================================
# 3. pin_locator — .rstrip("_") tolerance in reference lookup
# ===========================================================================


@pytest.mark.unit
class TestPinLocatorReferenceRstrip:
    """kicad-skip may write 'R1_' — lookups must still find 'R1'."""

    @pytest.fixture(autouse=True)
    def setup(self):
        for mod_name in ("sexpdata", "skip"):
            sys.modules.setdefault(mod_name, types.ModuleType(mod_name))
        from commands.pin_locator import PinLocator

        self.locator = PinLocator()

    def test_get_pin_location_finds_symbol_with_trailing_underscore(self):
        # Symbol stored in schematic with reference 'R1_' (kicad-skip artifact)
        sym = _stub_symbol("R1_", at=[50.0, 50.0, 0.0])
        self.locator._schematic_cache["sch.kicad_sch"] = MagicMock(symbol=[sym])
        with patch.object(
            self.locator,
            "get_symbol_pins",
            return_value={"1": {"x": 0.0, "y": 3.81, "angle": 270, "name": "~"}},
        ):
            # Caller uses clean reference 'R1'; should still resolve
            result = self.locator.get_pin_location(Path("sch.kicad_sch"), "R1", "1")

        assert (
            result is not None
        ), "get_pin_location returned None for reference 'R1' when schematic stores 'R1_'"

    def test_get_pin_location_returns_none_for_genuinely_missing_symbol(self):
        sym = _stub_symbol("R2", at=[50.0, 50.0, 0.0])
        self.locator._schematic_cache["sch.kicad_sch"] = MagicMock(symbol=[sym])
        result = self.locator.get_pin_location(Path("sch.kicad_sch"), "R1", "1")
        assert result is None
