"""
Tests for ExportCommands._read_components_from_schematic and
export_bom with schematicPath.

Covers:
  - Minimal block parsed to reference/value/footprint
  - LCSC property included when include_attributes=["LCSC"]
  - Power symbol #PWR01 skipped (reference starts with '#')
  - lib_symbols template content not returned in result
  - Property value containing parentheses parsed correctly
  - Multiple components all returned
  - export_bom groupByValue grouping and reference joining
  - export_bom LCSC carried through to grouped rows
  - export_bom groupByValue=False keeps individual rows
"""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

# ---------------------------------------------------------------------------
# Schematic fixture content
# ---------------------------------------------------------------------------

_SYMBOLS_TEXT = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-0000-0000-0000-000000000001")
    (property "Reference" "R1" (at 51.27 47.46 0))
    (property "Value" "10k" (at 51.27 52.54 0))
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 50 50 0))
    (property "LCSC" "C12345" (at 50 50 0))
  )
  (symbol (lib_id "Device:R") (at 60 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-0000-0000-0000-000000000002")
    (property "Reference" "R2" (at 61.27 47.46 0))
    (property "Value" "10k" (at 61.27 52.54 0))
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 60 50 0))
    (property "LCSC" "C12345" (at 60 50 0))
  )
  (symbol (lib_id "Device:C") (at 70 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-0000-0000-0000-000000000003")
    (property "Reference" "C1" (at 71.27 47.46 0))
    (property "Value" "100nF" (at 71.27 52.54 0))
    (property "Footprint" "Capacitor_SMD:C_0402_1005Metric" (at 70 50 0))
    (property "LCSC" "C19702" (at 70 50 0))
  )
  (symbol (lib_id "power:GND") (at 80 80 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-0000-0000-0000-000000000004")
    (property "Reference" "#PWR01" (at 80 80 0))
    (property "Value" "GND" (at 80 80 0))
    (property "Footprint" "" (at 80 80 0))
  )
"""

# Symbol with parens in Value property
_PAREN_VALUE_SYMBOL = """\
  (symbol (lib_id "Device:R") (at 90 90 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-0000-0000-0000-000000000005")
    (property "Reference" "TIM1" (at 91.27 87.46 0))
    (property "Value" "TIM1_CH4(N)" (at 91.27 92.54 0))
    (property "Footprint" "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm" (at 90 90 0))
  )
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_schematic_with_components(tmp_path: Path, symbols_text: str) -> Path:
    """Copy the empty template and inject symbols_text before the closing paren."""
    dest = tmp_path / "test.kicad_sch"
    shutil.copy(TEMPLATE_SCH, dest)
    content = dest.read_text(encoding="utf-8")
    idx = content.rfind(")")
    content = content[:idx] + "\n" + symbols_text + "\n)"
    dest.write_text(content, encoding="utf-8")
    return dest


def _make_export_commands(board=None):
    """Construct ExportCommands without importing pcbnew at module level."""
    from commands.export import ExportCommands

    return ExportCommands(board=board)


# ===========================================================================
# Unit tests — _read_components_from_schematic
# ===========================================================================


@pytest.mark.unit
class TestReadComponentsFromSchematic:
    def test_minimal_block_parsed_correctly(self, tmp_path):
        block = """\
  (symbol (lib_id "Device:R") (at 10 10 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "bbbbbbbb-0000-0000-0000-000000000001")
    (property "Reference" "R9" (at 11 9 0))
    (property "Value" "1k" (at 11 11 0))
    (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 10 10 0))
  )
"""
        sch = _make_schematic_with_components(tmp_path, block)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), [])
        assert len(components) == 1
        c = components[0]
        assert c["reference"] == "R9"
        assert c["value"] == "1k"
        assert c["footprint"] == "Resistor_SMD:R_0402_1005Metric"

    def test_lcsc_included_when_requested(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), ["LCSC"])
        refs = {c["reference"] for c in components}
        assert "R1" in refs
        r1 = next(c for c in components if c["reference"] == "R1")
        assert r1["LCSC"] == "C12345"

    def test_lcsc_not_in_result_when_not_requested(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), [])
        for comp in components:
            assert "LCSC" not in comp

    def test_power_symbol_skipped(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), [])
        refs = {c["reference"] for c in components}
        assert "#PWR01" not in refs

    def test_lib_symbols_block_not_returned(self, tmp_path):
        # The template's lib_symbols block contains Device:R, Device:C etc.
        # None of those should appear in the result (they have no placed UUID).
        sch = _make_schematic_with_components(tmp_path, "")
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), [])
        assert len(components) == 0

    def test_paren_in_value_parsed_correctly(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _PAREN_VALUE_SYMBOL)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), [])
        assert len(components) == 1
        assert components[0]["value"] == "TIM1_CH4(N)"

    def test_multiple_components_all_returned(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), [])
        refs = {c["reference"] for c in components}
        # #PWR01 should be excluded; R1, R2, C1 should be present
        assert refs == {"R1", "R2", "C1"}

    def test_all_lcsc_values_correct(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), ["LCSC"])
        by_ref = {c["reference"]: c for c in components}
        assert by_ref["R1"]["LCSC"] == "C12345"
        assert by_ref["R2"]["LCSC"] == "C12345"
        assert by_ref["C1"]["LCSC"] == "C19702"

    def test_missing_lcsc_returns_empty_string(self, tmp_path):
        block = """\
  (symbol (lib_id "Device:R") (at 10 10 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "cccccccc-0000-0000-0000-000000000001")
    (property "Reference" "R5" (at 11 9 0))
    (property "Value" "100" (at 11 11 0))
    (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 10 10 0))
  )
"""
        sch = _make_schematic_with_components(tmp_path, block)
        ec = _make_export_commands()
        components = ec._read_components_from_schematic(str(sch), ["LCSC"])
        assert components[0]["LCSC"] == ""


# ===========================================================================
# Unit tests — export_bom with schematicPath
# ===========================================================================


@pytest.mark.unit
class TestExportBomWithSchematicPath:
    def _bom_params(self, sch_path: Path, output_path: Path, **kwargs) -> dict:
        params = {
            "schematicPath": str(sch_path),
            "outputPath": str(output_path),
            "format": "JSON",
        }
        params.update(kwargs)
        return params

    def _load_json_rows(self, out: Path):
        import json

        data = json.loads(out.read_text())
        # export_bom_json wraps in {"components": [...]}
        if isinstance(data, dict) and "components" in data:
            return data["components"]
        return data

    def test_returns_lcsc_when_include_attributes_set(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        out = tmp_path / "bom.json"
        ec = _make_export_commands()
        result = ec.export_bom(
            self._bom_params(sch, out, includeAttributes=["LCSC"], groupByValue=False)
        )
        assert result["success"] is True
        rows = self._load_json_rows(out)
        by_ref = {r["reference"]: r for r in rows}
        assert by_ref["R1"]["LCSC"] == "C12345"
        assert by_ref["C1"]["LCSC"] == "C19702"

    def test_group_by_value_groups_r1_and_r2(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        out = tmp_path / "bom.json"
        ec = _make_export_commands()
        result = ec.export_bom(
            self._bom_params(sch, out, groupByValue=True)
        )
        assert result["success"] is True
        rows = self._load_json_rows(out)
        # R1 and R2 share value=10k and footprint → should be grouped
        r_rows = [r for r in rows if "10k" in r.get("value", "")]
        assert len(r_rows) == 1
        assert r_rows[0]["quantity"] == 2

    def test_group_by_value_references_semicolon_separated(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        out = tmp_path / "bom.json"
        ec = _make_export_commands()
        result = ec.export_bom(
            self._bom_params(sch, out, groupByValue=True)
        )
        rows = self._load_json_rows(out)
        r_rows = [r for r in rows if "10k" in r.get("value", "")]
        refs_str = r_rows[0]["references"]
        # Both R1 and R2 should appear, separated by semicolon
        assert "R1" in refs_str
        assert "R2" in refs_str
        assert ";" in refs_str

    def test_group_by_value_carries_lcsc_through(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        out = tmp_path / "bom.json"
        ec = _make_export_commands()
        result = ec.export_bom(
            self._bom_params(sch, out, groupByValue=True, includeAttributes=["LCSC"])
        )
        rows = self._load_json_rows(out)
        r_rows = [r for r in rows if "10k" in r.get("value", "")]
        assert r_rows[0]["LCSC"] == "C12345"

    def test_group_by_value_false_keeps_individual_rows(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        out = tmp_path / "bom.json"
        ec = _make_export_commands()
        result = ec.export_bom(
            self._bom_params(sch, out, groupByValue=False)
        )
        rows = self._load_json_rows(out)
        refs = {r["reference"] for r in rows}
        assert "R1" in refs
        assert "R2" in refs
        assert "C1" in refs

    def test_power_symbols_excluded_from_bom(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        out = tmp_path / "bom.json"
        ec = _make_export_commands()
        result = ec.export_bom(
            self._bom_params(sch, out, groupByValue=False)
        )
        rows = self._load_json_rows(out)
        refs = {r["reference"] for r in rows}
        assert "#PWR01" not in refs

    def test_missing_output_path_returns_failure(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        ec = _make_export_commands()
        result = ec.export_bom({"schematicPath": str(sch)})
        assert result["success"] is False

    def test_component_count_in_result(self, tmp_path):
        sch = _make_schematic_with_components(tmp_path, _SYMBOLS_TEXT)
        out = tmp_path / "bom.json"
        ec = _make_export_commands()
        result = ec.export_bom(
            self._bom_params(sch, out, groupByValue=False)
        )
        assert result["success"] is True
        # R1, R2, C1 = 3 components (#PWR01 excluded)
        assert result["file"]["componentCount"] == 3
