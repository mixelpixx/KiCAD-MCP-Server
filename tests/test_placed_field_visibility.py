"""Placed instances inherit the library symbol's field visibility.

Regression guard: create_component_instance wrote Reference and Value as
visible unconditionally. Power symbols (power:GND, power:+3V3, …) hide their
Reference in the library — the #PWR101 designators say nothing to a reader —
and losing that flag printed one stray designator beside every ground symbol,
enough to make a dense sheet unreadable.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402

# A power symbol the way KiCad ships it: Reference hidden, Value shown.
_POWER_SCH = """(kicad_sch (version 20231120) (generator test)
  (lib_symbols
    (symbol "power:GND" (power) (in_bom no) (on_board yes)
      (property "Reference" "#PWR" (at 0 -6.35 0)
        (effects (font (size 1.27 1.27)) (hide yes))
      )
      (property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
    )
  )
)
"""

# An ordinary part: both Reference and Value visible.
_DEVICE_SCH = _POWER_SCH.replace('"power:GND"', '"Device:R"').replace(
    """      (property "Reference" "#PWR" (at 0 -6.35 0)
        (effects (font (size 1.27 1.27)) (hide yes))
      )""",
    '      (property "Reference" "R" (at 2.032 0 0) (effects (font (size 1.27 1.27))))',
)


def _placed_block(text: str) -> str:
    return text[text.rfind("(symbol (lib_id") :]


def _property_block(text: str, name: str) -> str:
    """The placed instance's (property "<name>" ...) block, up to the next property."""
    block = _placed_block(text)
    m = re.search(
        r'\(property "' + re.escape(name) + r'".*?(?=\n    \(property |\n    \(pin )', block, re.S
    )
    assert m is not None, f"no {name} property in placed instance"
    return m.group(0)


def _is_hidden(text: str, name: str) -> bool:
    return "(hide yes)" in _property_block(text, name)


def test_power_symbol_reference_stays_hidden(tmp_path: Path) -> None:
    p = tmp_path / "t.kicad_sch"
    p.write_text(_POWER_SCH, encoding="utf-8")
    loader = DynamicSymbolLoader(project_path=tmp_path)
    loader.create_component_instance(
        p, "power", "GND", reference="#PWR01", value="GND", x=100, y=100
    )

    text = p.read_text(encoding="utf-8")
    assert _is_hidden(text, "Reference"), "#PWR designator must not be printed on the sheet"
    assert not _is_hidden(text, "Value"), "the net name is the whole point of a power symbol"


def test_ordinary_symbol_keeps_both_fields_visible(tmp_path: Path) -> None:
    p = tmp_path / "t.kicad_sch"
    p.write_text(_DEVICE_SCH, encoding="utf-8")
    loader = DynamicSymbolLoader(project_path=tmp_path)
    loader.create_component_instance(p, "Device", "R", reference="R1", value="10k", x=100, y=100)

    text = p.read_text(encoding="utf-8")
    assert not _is_hidden(text, "Reference")
    assert not _is_hidden(text, "Value")


def test_field_value_containing_the_word_hide_is_not_treated_as_hidden(tmp_path: Path) -> None:
    """The marker is a token, not a substring of some field's text."""
    sch = _DEVICE_SCH.replace('(property "Value" "GND"', '(property "Value" "auto hide relay"')
    p = tmp_path / "t.kicad_sch"
    p.write_text(sch, encoding="utf-8")
    loader = DynamicSymbolLoader(project_path=tmp_path)
    loader.create_component_instance(p, "Device", "R", reference="R1", value="10k", x=100, y=100)

    assert not _is_hidden(p.read_text(encoding="utf-8"), "Value")
