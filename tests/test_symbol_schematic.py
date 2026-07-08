"""Tests for SymbolSchematicCommands.replace_instance_lib_ids."""

import sys
from pathlib import Path

# Ensure python/ is on the path when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.symbol_schematic import SymbolSchematicCommands


SAMPLE_SCH = """(kicad_sch
  (version 20260306)
  (generator "eeschema")
  (lib_symbols
    (symbol "eagle_import:C"
      (pin bidirectional line (at -5.08 0 0) (length 2.54))
    )
  )
  (symbol
    (lib_id "eagle_import:C")
    (at 100 100 0)
    (unit 1)
    (property "Reference" "C1" (at 100 95 0))
    (property "Value" "100nF" (at 100 105 0))
  )
  (symbol
    (lib_id "eagle_import:C__m90")
    (at 200 200 90)
    (unit 1)
    (property "Reference" "C2" (at 200 195 0))
    (property "Value" "10nF" (at 200 205 0))
  )
)
"""


def _write_sch(tmp_path: Path) -> Path:
    p = tmp_path / "test.kicad_sch"
    p.write_text(SAMPLE_SCH, encoding="utf-8", newline="\n")
    return p


def test_basic_replacement(tmp_path):
    """Plain lib_id swap without mirror suffix."""
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids({
        "schematic_path": str(sch),
        "mapping": {"eagle_import:C": "FOG_components:C_100nF_0402"},
    })
    assert result["success"] is True
    assert result["replaced"] == 1
    content = sch.read_text(encoding="utf-8")
    assert "FOG_components:C_100nF_0402" in content
    assert 'eagle_import:C")' not in content  # only in lib_symbols, not instances


def test_mirror_variant_angle(tmp_path):
    """__m90 suffix should add 90° to the original angle."""
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids({
        "schematic_path": str(sch),
        "mapping": {
            "eagle_import:C": "FOG_components:C_100nF_0402",
            "eagle_import:C__m90": "FOG_components:C_10nF_0402",
        },
    })
    assert result["success"] is True
    assert result["replaced"] == 2
    content = sch.read_text(encoding="utf-8")
    # __m90 instance: original angle 90 + offset 90 = 180
    assert "(at 200 200 180)" in content
    assert "FOG_components:C_10nF_0402" in content


def test_missing_file():
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids({
        "schematic_path": "/nonexistent/file.kicad_sch",
        "mapping": {"eagle_import:C": "FOG_components:C_100nF_0402"},
    })
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_empty_mapping(tmp_path):
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids({
        "schematic_path": str(sch),
        "mapping": {},
    })
    assert result["success"] is False
    assert "mapping" in result["error"].lower()


def test_no_remaining_eagle(tmp_path):
    """After replacement, remaining_eagle should be 0 in instances."""
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids({
        "schematic_path": str(sch),
        "mapping": {
            "eagle_import:C": "FOG_components:C_100nF_0402",
            "eagle_import:C__m90": "FOG_components:C_10nF_0402",
        },
    })
    assert result["remaining_eagle"] == 0


def test_lib_symbols_preserved(tmp_path):
    """lib_symbols section must not be modified."""
    sch = _write_sch(tmp_path)
    original = sch.read_text(encoding="utf-8")
    # Extract lib_symbols block by parenthesis depth
    ls = original.find("(lib_symbols")
    d = 0
    le = None
    for i in range(ls, len(original)):
        if original[i] == "(":
            d += 1
        elif original[i] == ")":
            d -= 1
            if d == 0:
                le = i
                break
    lib_section = original[ls : le + 1]
    cmd = SymbolSchematicCommands()
    cmd.replace_instance_lib_ids({
        "schematic_path": str(sch),
        "mapping": {"eagle_import:C": "FOG_components:C_100nF_0402"},
    })
    new = sch.read_text(encoding="utf-8")
    ls2 = new.find("(lib_symbols")
    d = 0
    le2 = None
    for i in range(ls2, len(new)):
        if new[i] == "(":
            d += 1
        elif new[i] == ")":
            d -= 1
            if d == 0:
                le2 = i
                break
    new_lib = new[ls2 : le2 + 1]
    assert lib_section == new_lib
