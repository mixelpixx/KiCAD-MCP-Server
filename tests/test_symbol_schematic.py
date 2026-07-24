"""Tests for SymbolSchematicCommands.replace_instance_lib_ids."""

import sys
from pathlib import Path

# Ensure python/ is on the path when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.symbol_schematic import SymbolSchematicCommands

SAMPLE_SCH = """(kicad_sch
  (version 20260101)
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

# The single-line header layout this repo's own dynamic loader writes.
SINGLE_LINE_SCH = """(kicad_sch
  (version 20260101)
  (generator "eeschema")
  (lib_symbols
    (symbol "eagle_import:R"
      (pin passive line (at -5.08 0 0) (length 2.54))
    )
  )
  (symbol (lib_id "eagle_import:R") (at 127 63.5 0) (unit 1)
    (property "Reference" "R1" (at 127 60 0))
  )
)
"""


def _write_sch(tmp_path: Path, content: str = SAMPLE_SCH) -> Path:
    p = tmp_path / "test.kicad_sch"
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return p


def test_basic_replacement(tmp_path):
    """Plain lib_id swap without mirror suffix."""
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids(
        {
            "schematicPath": str(sch),
            "mapping": {"eagle_import:C": "project_lib:C_100nF_0402"},
        }
    )
    assert result["success"] is True
    assert result["replaced"] == 1
    content = sch.read_text(encoding="utf-8")
    assert "project_lib:C_100nF_0402" in content
    assert 'eagle_import:C")' not in content  # only in lib_symbols, not instances


def test_mirror_variant_angle(tmp_path):
    """__m90 suffix should add 90 degrees to the original angle."""
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids(
        {
            "schematicPath": str(sch),
            "mapping": {
                "eagle_import:C": "project_lib:C_100nF_0402",
                "eagle_import:C__m90": "project_lib:C_10nF_0402",
            },
        }
    )
    assert result["success"] is True
    assert result["replaced"] == 2
    content = sch.read_text(encoding="utf-8")
    # __m90 instance: original angle 90 + offset 90 = 180
    assert "(at 200 200 180)" in content
    assert "project_lib:C_10nF_0402" in content


def test_mapping_values_used_verbatim_across_libraries(tmp_path):
    """Each mapping value's own library prefix is honored — one migration may
    target several libraries (e.g. passives to Device, connectors to a
    project library)."""
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids(
        {
            "schematicPath": str(sch),
            "mapping": {
                "eagle_import:C": "Device:C",
                "eagle_import:C__m90": "project_lib:C_10nF_0402",
            },
        }
    )
    assert result["success"] is True
    assert result["replaced"] == 2
    content = sch.read_text(encoding="utf-8")
    assert '(lib_id "Device:C")' in content
    assert '(lib_id "project_lib:C_10nF_0402")' in content


def test_single_line_instance_header(tmp_path):
    """Instances written by this repo's dynamic loader put the whole header on
    one line — they must be migratable too."""
    sch = _write_sch(tmp_path, SINGLE_LINE_SCH)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids(
        {
            "schematicPath": str(sch),
            "mapping": {"eagle_import:R": "Device:R"},
        }
    )
    assert result["success"] is True
    assert result["replaced"] == 1
    content = sch.read_text(encoding="utf-8")
    assert '(symbol (lib_id "Device:R") (at 127 63.5 0) (unit 1)' in content


def test_missing_file():
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids(
        {
            "schematicPath": "/nonexistent/file.kicad_sch",
            "mapping": {"eagle_import:C": "project_lib:C_100nF_0402"},
        }
    )
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_empty_mapping(tmp_path):
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids(
        {
            "schematicPath": str(sch),
            "mapping": {},
        }
    )
    assert result["success"] is False
    assert "mapping" in result["error"].lower()


def test_no_remaining_after_full_replacement(tmp_path):
    """After replacing every instance, remaining should be 0."""
    sch = _write_sch(tmp_path)
    cmd = SymbolSchematicCommands()
    result = cmd.replace_instance_lib_ids(
        {
            "schematicPath": str(sch),
            "mapping": {
                "eagle_import:C": "project_lib:C_100nF_0402",
                "eagle_import:C__m90": "project_lib:C_10nF_0402",
            },
        }
    )
    assert result["remaining"] == 0


def _lib_symbols_block(text: str) -> str:
    start = text.find("(lib_symbols")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError("unterminated lib_symbols block")


def test_lib_symbols_preserved(tmp_path):
    """lib_symbols section must not be modified."""
    sch = _write_sch(tmp_path)
    original_block = _lib_symbols_block(sch.read_text(encoding="utf-8"))
    cmd = SymbolSchematicCommands()
    cmd.replace_instance_lib_ids(
        {
            "schematicPath": str(sch),
            "mapping": {"eagle_import:C": "project_lib:C_100nF_0402"},
        }
    )
    assert _lib_symbols_block(sch.read_text(encoding="utf-8")) == original_block
