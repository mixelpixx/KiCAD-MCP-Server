"""
Regression tests for reference-based schematic lookups when lib_symbols
contains an unescaped parenthesis inside a quoted string.

Bug: get/edit/delete_schematic_component used a hand-rolled paren matcher
(`_find_matching_paren`) that counted parens *inside* quoted strings. KiCAD does
NOT backslash-escape bare parens in quoted strings — MCU pin names like
"PA13(JTMS" (STM32 alternate-function names) and descriptions like "Vin(fwd) 40V"
appear raw. One unbalanced in-string "(" inside the (lib_symbols ...) block made
the matcher run to EOF, so `lib_sym_end` swallowed every placed symbol (they all
follow lib_symbols), and every reference lookup returned "not found" for the
whole schematic.

The kicad-skip/sexpdata-based tools (list_schematic_components,
get_schematic_pin_locations) parse strings correctly and were unaffected — which
is why a reference resolved in one code path but not the other.
"""

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# A schematic whose lib_symbols embeds a symbol with an unbalanced paren inside a
# quoted pin-name token ("PA13(JTMS"), exactly as KiCAD's own STM32 libs write it.
# The placed symbol U3 follows lib_symbols, so the old matcher skipped it.
SCH_WITH_PAREN_IN_LIB_STRING = """\
(kicad_sch (version 20250114) (generator "test")
  (uuid b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e)
  (paper "A4")
  (lib_symbols
    (symbol "MCU_ST:STM32"
      (property "ki_description" "MCU, alt-func Vin(fwd) tolerant")
      (symbol "STM32_0_1"
        (pin bidirectional line (at 0 0 0) (length 2.54)
          (name "PA13(JTMS" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))
      )
    )
  )
  (symbol
    (lib_id "MCU_ST:STM32")
    (at 100 100 0)
    (unit 1)
    (uuid "11111111-1111-1111-1111-111111111111")
    (property "Reference" "U3" (at 100 95 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "STM32" (at 100 105 0)
      (effects (font (size 1.27 1.27))))
  )
)
"""


def _write_sch(tmp_path: Path) -> Path:
    dest = tmp_path / "paren.kicad_sch"
    dest.write_text(SCH_WITH_PAREN_IN_LIB_STRING, encoding="utf-8")
    return dest


def _iface() -> Any:
    from kicad_interface import KiCADInterface

    return KiCADInterface.__new__(KiCADInterface)


@pytest.mark.unit
def test_find_matching_paren_is_string_aware() -> None:
    """The matcher must ignore parens inside quoted strings."""
    from kicad_interface import KiCADInterface

    # Outer parens balance; the lone "(" lives inside a quoted string and must
    # not be counted. The true close is the final char.
    s = '(a "PA13(JTMS" (b "x") )'
    assert KiCADInterface._find_matching_paren(s, 0) == len(s) - 1

    # Escaped quote inside a string must not prematurely end the string.
    s2 = r'(a "he said \"hi(\"" )'
    assert KiCADInterface._find_matching_paren(s2, 0) == len(s2) - 1


@pytest.mark.integration
def test_get_finds_reference_despite_paren_in_lib_string(tmp_path: Any) -> None:
    sch = _write_sch(tmp_path)
    result = _iface()._handle_get_schematic_component(
        {"schematicPath": str(sch), "reference": "U3"}
    )
    assert result["success"] is True, result.get("message")


@pytest.mark.integration
def test_edit_finds_reference_despite_paren_in_lib_string(tmp_path: Any) -> None:
    sch = _write_sch(tmp_path)
    result = _iface()._handle_edit_schematic_component(
        {"schematicPath": str(sch), "reference": "U3", "value": "STM32F1"}
    )
    assert result["success"] is True, result.get("message")
    assert '(property "Value" "STM32F1"' in sch.read_text(encoding="utf-8")


@pytest.mark.integration
def test_delete_finds_reference_despite_paren_in_lib_string(tmp_path: Any) -> None:
    sch = _write_sch(tmp_path)
    result = _iface()._handle_delete_schematic_component(
        {"schematicPath": str(sch), "reference": "U3"}
    )
    assert result["success"] is True, result.get("message")
    assert result["deleted_count"] == 1
    remaining = sch.read_text(encoding="utf-8")
    # The placed instance is gone, but the library definition is preserved.
    assert '(property "Reference" "U3"' not in remaining
    assert '(symbol "MCU_ST:STM32"' in remaining


@pytest.mark.integration
def test_absent_reference_still_reports_not_found(tmp_path: Any) -> None:
    """Guard against the fix over-matching: a missing ref must still fail."""
    sch = _write_sch(tmp_path)
    result = _iface()._handle_get_schematic_component(
        {"schematicPath": str(sch), "reference": "ZZ99"}
    )
    assert result["success"] is False
