"""
Tests for _handle_set_schematic_component_properties (plural batch tool)
and schema registration.

Covers:
  - Schema: set_schematic_component_properties in TOOL_SCHEMAS
  - Schema has 'components' as required property
  - Schema has 'hideNewProperties' as optional boolean
  - Handler: missing schematicPath → success=False
  - Handler: missing components → success=False
  - Handler: empty components map → success with 0 items set
  - Handler: sets properties per-component via _handle_set_schematic_component_property
  - Handler: response contains 'set' and 'failed' keys
  - Integration: real schematic file, set LCSC on R1 and MPN on C1, verify file content
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

# ---------------------------------------------------------------------------
# Placed-component blocks for the test schematic
# ---------------------------------------------------------------------------

_PLACED_COMPONENTS = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "cccccccc-0000-0000-0000-000000000001")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
  )
  (symbol (lib_id "Device:C") (at 70 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "cccccccc-0000-0000-0000-000000000002")
    (property "Reference" "C1" (at 71.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "100nF" (at 71.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at 70 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 70 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
  )
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_schematic(tmp_dir: Path) -> Path:
    dest = tmp_dir / "test.kicad_sch"
    shutil.copy(TEMPLATE_SCH, dest)
    content = dest.read_text(encoding="utf-8")
    idx = content.rfind(")")
    content = content[:idx] + "\n" + _PLACED_COMPONENTS + "\n)"
    dest.write_text(content, encoding="utf-8")
    return dest


def _make_iface():
    """Construct a KiCADInterface instance without calling __init__."""
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

    return KiCADInterface.__new__(KiCADInterface)


# ===========================================================================
# Schema tests
# ===========================================================================


@pytest.mark.unit
class TestBatchPropertiesSchema:
    def test_set_schematic_component_properties_in_tool_schemas(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "set_schematic_component_properties" in TOOL_SCHEMAS

    def test_components_is_required(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["set_schematic_component_properties"]
        required = schema["inputSchema"].get("required", [])
        assert "components" in required

    def test_schematic_path_is_required(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["set_schematic_component_properties"]
        required = schema["inputSchema"].get("required", [])
        assert "schematicPath" in required

    def test_hide_new_properties_is_optional_boolean(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["set_schematic_component_properties"]
        props = schema["inputSchema"]["properties"]
        assert "hideNewProperties" in props
        assert props["hideNewProperties"]["type"] == "boolean"
        required = schema["inputSchema"].get("required", [])
        assert "hideNewProperties" not in required


# ===========================================================================
# Handler unit tests (no real file I/O)
# ===========================================================================


@pytest.mark.unit
class TestBatchPropertiesHandler:
    def test_missing_schematic_path_returns_failure(self):
        iface = _make_iface()
        result = iface._handle_set_schematic_component_properties(
            {"components": {"R1": {"LCSC": "C12345"}}}
        )
        assert result["success"] is False
        assert "schematicPath" in result["message"] or "schematic" in result["message"].lower()

    def test_missing_components_returns_failure(self):
        iface = _make_iface()
        result = iface._handle_set_schematic_component_properties(
            {"schematicPath": "/fake.kicad_sch"}
        )
        assert result["success"] is False

    def test_empty_components_map_returns_failure(self):
        iface = _make_iface()
        result = iface._handle_set_schematic_component_properties(
            {"schematicPath": "/fake.kicad_sch", "components": {}}
        )
        assert result["success"] is False

    def test_response_has_set_and_failed_keys(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        # Mock the singular handler to always return success
        iface._handle_set_schematic_component_property = MagicMock(return_value={"success": True})

        result = iface._handle_set_schematic_component_properties(
            {"schematicPath": str(sch), "components": {"R1": {"LCSC": "C12345"}}}
        )

        assert "set" in result
        assert "failed" in result

    def test_sets_single_property_calls_singular_handler(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        mock_single = MagicMock(return_value={"success": True})
        iface._handle_set_schematic_component_property = mock_single

        iface._handle_set_schematic_component_properties(
            {"schematicPath": str(sch), "components": {"R1": {"LCSC": "C12345"}}}
        )

        mock_single.assert_called_once()
        call_params = mock_single.call_args[0][0]
        assert call_params["reference"] == "R1"
        assert call_params["name"] == "LCSC"
        assert call_params["value"] == "C12345"

    def test_multiple_components_calls_singular_handler_for_each_property(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        mock_single = MagicMock(return_value={"success": True})
        iface._handle_set_schematic_component_property = mock_single

        iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {
                    "R1": {"LCSC": "C12345", "MPN": "RC0603FR-0710KL"},
                    "C1": {"LCSC": "C19702"},
                },
            }
        )

        # 3 total property calls
        assert mock_single.call_count == 3

    def test_success_true_when_all_properties_set(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        iface._handle_set_schematic_component_property = MagicMock(return_value={"success": True})

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {"R1": {"LCSC": "C12345"}},
            }
        )

        assert result["success"] is True
        assert "R1.LCSC" in result["set"]
        assert len(result["failed"]) == 0

    def test_success_false_when_a_property_fails(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        iface._handle_set_schematic_component_property = MagicMock(
            return_value={"success": False, "message": "component not found"}
        )

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {"X99": {"LCSC": "C00000"}},
            }
        )

        assert result["success"] is False
        assert len(result["failed"]) == 1
        assert result["failed"][0]["ref"] == "X99"

    def test_partial_failure_mixed_set_and_failed(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        def _side_effect(params):
            if params.get("reference") == "R1":
                return {"success": True}
            return {"success": False, "message": "not found"}

        iface._handle_set_schematic_component_property = MagicMock(side_effect=_side_effect)

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {
                    "R1": {"LCSC": "C12345"},
                    "X99": {"LCSC": "C00000"},
                },
            }
        )

        assert result["success"] is False
        assert any("R1" in s for s in result["set"])
        assert any(f["ref"] == "X99" for f in result["failed"])

    def test_non_dict_props_goes_to_failed(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        iface._handle_set_schematic_component_property = MagicMock(return_value={"success": True})

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {"R1": "not-a-dict"},
            }
        )

        assert any(f["ref"] == "R1" for f in result["failed"])

    def test_hide_new_properties_forwarded_to_singular_handler(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        mock_single = MagicMock(return_value={"success": True})
        iface._handle_set_schematic_component_property = mock_single

        iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {"R1": {"LCSC": "C12345"}},
                "hideNewProperties": False,
            }
        )

        call_params = mock_single.call_args[0][0]
        assert call_params.get("hide") is False


# ===========================================================================
# Integration test — real file I/O
# ===========================================================================


@pytest.mark.integration
class TestBatchPropertiesIntegration:
    def test_sets_lcsc_on_r1_and_mpn_on_c1(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {
                    "R1": {"LCSC": "C12345"},
                    "C1": {"MPN": "GRM155R71E104KA88D"},
                },
            }
        )

        assert result["success"] is True, f"Failed: {result}"

        content = sch.read_text(encoding="utf-8")
        assert '(property "LCSC" "C12345"' in content
        assert '(property "MPN" "GRM155R71E104KA88D"' in content

    def test_sets_multiple_properties_on_same_component(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {
                    "R1": {"LCSC": "C12345", "Manufacturer": "Yageo"},
                },
            }
        )

        assert result["success"] is True, f"Failed: {result}"

        content = sch.read_text(encoding="utf-8")
        assert '(property "LCSC" "C12345"' in content
        assert '(property "Manufacturer" "Yageo"' in content

    def test_set_count_matches_properties_set(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {
                    "R1": {"LCSC": "C12345"},
                    "C1": {"LCSC": "C19702"},
                },
            }
        )

        assert result["success"] is True
        assert len(result["set"]) == 2
        assert len(result["failed"]) == 0

    def test_unknown_reference_goes_to_failed(self, tmp_path):
        sch = _make_test_schematic(tmp_path)
        iface = _make_iface()

        result = iface._handle_set_schematic_component_properties(
            {
                "schematicPath": str(sch),
                "components": {
                    "R1": {"LCSC": "C12345"},
                    "XXXX": {"LCSC": "C99999"},
                },
            }
        )

        # R1 should succeed; XXXX should fail (not in schematic)
        assert any("R1" in s for s in result["set"])
        assert any(f["ref"] == "XXXX" for f in result["failed"])
