"""Placed schematic instances inherit the library symbol's Footprint.

Regression guard: create_component_instance previously wrote the Footprint
straight from its (empty-default) argument and never consulted the library
symbol, so a footprint set via create_symbol never propagated to placements —
only a later edit_schematic_component set it. KiCad inherits the field on
placement; the loader now does too.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402

# Minimal schematic whose lib_symbols entry carries a Footprint value.
_SCH = """(kicad_sch (version 20231120) (generator test)
  (lib_symbols
    (symbol "MyLib:ESP32" (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
      (property "Value" "ESP32" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "RF_Module:ESP32-C3-MINI-1" (at 0 -2.54 0) \
(effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "~" (at 0 -5 0) (effects (font (size 1.27 1.27)) (hide yes)))
    )
  )
)
"""


def _placed_footprint(schematic_text: str) -> str:
    """Return the Footprint value of the placed instance (outside lib_symbols)."""
    instance = schematic_text[schematic_text.rfind("(symbol (lib_id") :]
    m = re.search(r'\(property "Footprint" "([^"]*)"', instance)
    return m.group(1) if m else ""


@pytest.fixture()
def schematic(tmp_path: Path) -> Path:
    p = tmp_path / "t.kicad_sch"
    p.write_text(_SCH, encoding="utf-8")
    return p


def test_placement_inherits_library_footprint(schematic: Path) -> None:
    """No footprint passed -> inherit the library symbol's Footprint."""
    loader = DynamicSymbolLoader(project_path=schematic.parent)
    loader.create_component_instance(schematic, "MyLib", "ESP32", reference="U1", x=100, y=100)
    assert _placed_footprint(schematic.read_text(encoding="utf-8")) == "RF_Module:ESP32-C3-MINI-1"


def test_explicit_footprint_overrides_library(schematic: Path) -> None:
    """An explicit footprint argument still wins over the library value."""
    loader = DynamicSymbolLoader(project_path=schematic.parent)
    loader.create_component_instance(
        schematic, "MyLib", "ESP32", reference="U1", footprint="MyFP:Custom", x=100, y=100
    )
    assert _placed_footprint(schematic.read_text(encoding="utf-8")) == "MyFP:Custom"
