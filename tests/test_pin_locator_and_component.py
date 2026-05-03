"""
Regression tests for bugs originally fixed in PR #103 and updated for PR #145.

  1. component_schematic.py: clone() + redundant append() causes trailing "_" on reference
  2. pin_locator.py: reference comparison must tolerate trailing "_" from kicad-skip
     (this also covers WireDragger.find_symbol, used by _get_symbol_transform)

The pre-PR-145 y-axis-negation tests were removed: their assertions encoded the
correct post-PR-145 convention, but their MagicMock setup bypassed
_get_symbol_transform (which reads the .kicad_sch file directly via sexpdata).
The y-flip behaviour is now covered end-to-end against eeschema in
tests/test_pin_locator_y_flip.py — duplicating it with mocks added no value.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
TEMPLATES_DIR = PYTHON_DIR / "templates"
sys.path.insert(0, str(PYTHON_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEMPLATE_SCH = TEMPLATES_DIR / "template_with_symbols.kicad_sch"


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
# 2. pin_locator — .rstrip("_") tolerance in reference lookup
# ===========================================================================


@pytest.mark.integration
class TestPinLocatorReferenceRstrip:
    """
    kicad-skip may write 'R1_' on disk after a clone; lookups for 'R1' must
    still resolve. This must hold for *both* lookup paths inside
    get_pin_location: the kicad-skip Schematic scan AND the sexpdata-based
    _get_symbol_transform (via WireDragger.find_symbol).
    """

    def _write_sch_with_underscored_ref(self, sch_path: Path) -> None:
        """Add R1, then mangle the on-disk reference to 'R1_' to simulate the kicad-skip artifact."""
        from commands.component_schematic import ComponentManager
        from commands.schematic import SchematicManager

        shutil.copy(_TEMPLATE_SCH, sch_path)
        sch = SchematicManager.load_schematic(str(sch_path))
        ComponentManager.add_component(
            sch,
            {"type": "R", "reference": "R1", "value": "10k", "x": 100.0, "y": 100.0, "rotation": 0},
            sch_path,
        )
        SchematicManager.save_schematic(sch, str(sch_path))

        # Rewrite the saved file, replacing the Reference "R1" with "R1_"
        text = sch_path.read_text(encoding="utf-8")
        text = text.replace('(property "Reference" "R1"', '(property "Reference" "R1_"', 1)
        sch_path.write_text(text, encoding="utf-8")

    def test_get_pin_location_finds_symbol_with_trailing_underscore(self):
        from commands.pin_locator import PinLocator

        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "sch.kicad_sch"
            self._write_sch_with_underscored_ref(sch_path)

            locator = PinLocator()
            # Caller uses clean reference 'R1'; should still resolve through both
            # the kicad-skip path and the sexpdata _get_symbol_transform path.
            result = locator.get_pin_location(sch_path, "R1", "1")

        assert (
            result is not None
        ), "get_pin_location returned None for reference 'R1' when schematic stores 'R1_'"

    def test_get_pin_location_returns_none_for_genuinely_missing_symbol(self):
        from commands.component_schematic import ComponentManager
        from commands.pin_locator import PinLocator
        from commands.schematic import SchematicManager

        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "sch.kicad_sch"
            shutil.copy(_TEMPLATE_SCH, sch_path)
            sch = SchematicManager.load_schematic(str(sch_path))
            ComponentManager.add_component(
                sch,
                {
                    "type": "R",
                    "reference": "R2",
                    "value": "1k",
                    "x": 50.0,
                    "y": 50.0,
                    "rotation": 0,
                },
                sch_path,
            )
            SchematicManager.save_schematic(sch, str(sch_path))

            locator = PinLocator()
            result = locator.get_pin_location(sch_path, "R1", "1")

        assert result is None
