"""
Tests for custom property support on edit_schematic_component,
set_schematic_component_property, and remove_schematic_component_property.

Custom properties are arbitrary key/value fields attached to a placed schematic
symbol — used for BOM / sourcing metadata such as MPN, Manufacturer,
DigiKey_PN, LCSC, JLCPCB_PN, Voltage, Tolerance, Dielectric, etc.
"""

import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

# Minimal placed-symbol block embedded into the test schematic
PLACED_RESISTOR_BLOCK = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
  )
"""


def _make_test_schematic(tmp_dir: Path, extra_block: str = "") -> Path:
    """Copy empty.kicad_sch into tmp_dir, optionally appending a placed symbol block."""
    dest = tmp_dir / "test.kicad_sch"
    src_content = TEMPLATE_SCH.read_text(encoding="utf-8")
    if extra_block:
        src_content = src_content.rstrip()
        if src_content.endswith(")"):
            src_content = src_content[:-1] + "\n" + extra_block + ")\n"
    dest.write_text(src_content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Pure unit tests — exercise the static helpers in isolation.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStaticHelpers:
    """Tests for _escape_sexpr_string and _find_matching_paren."""

    def _iface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface

    def test_escape_handles_quotes(self) -> None:
        cls = self._iface()
        assert cls._escape_sexpr_string('a"b') == 'a\\"b'

    def test_escape_handles_backslashes(self) -> None:
        cls = self._iface()
        assert cls._escape_sexpr_string("a\\b") == "a\\\\b"

    def test_escape_handles_both(self) -> None:
        cls = self._iface()
        # Order matters: backslashes are doubled first, then quotes
        assert cls._escape_sexpr_string('a"b\\c') == 'a\\"b\\\\c'

    def test_escape_passes_normal_text(self) -> None:
        cls = self._iface()
        assert cls._escape_sexpr_string("RC0603FR-0710KL") == "RC0603FR-0710KL"

    def test_find_matching_paren_simple(self) -> None:
        cls = self._iface()
        s = "(abc)"
        assert cls._find_matching_paren(s, 0) == 4

    def test_find_matching_paren_nested(self) -> None:
        cls = self._iface()
        s = "(a (b (c) d) e)"
        assert cls._find_matching_paren(s, 0) == 14
        assert cls._find_matching_paren(s, 3) == 11
        assert cls._find_matching_paren(s, 6) == 8

    def test_find_matching_paren_no_match(self) -> None:
        cls = self._iface()
        s = "(abc"
        assert cls._find_matching_paren(s, 0) == -1


# ---------------------------------------------------------------------------
# Integration tests — full file I/O through the public command interface.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEditSchematicComponentProperties:
    """Tests for the new `properties` and `removeProperties` parameters."""

    @pytest.fixture
    def sch_with_r1(self, tmp_path: Any) -> Any:
        return _make_test_schematic(tmp_path, PLACED_RESISTOR_BLOCK)

    def _iface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_add_single_custom_property_string(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"MPN": "RC0603FR-0710KL"},
            },
        )
        assert result["success"] is True
        assert "MPN" in result["updated"]["propertiesAdded"]

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        assert "MPN" in get_result["fields"]
        assert get_result["fields"]["MPN"]["value"] == "RC0603FR-0710KL"

    def test_add_multiple_custom_properties(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {
                    "MPN": "RC0603FR-0710KL",
                    "Manufacturer": "Yageo",
                    "Tolerance": "1%",
                    "Power": "0.1W",
                },
            },
        )
        assert result["success"] is True
        assert set(result["updated"]["propertiesAdded"].keys()) == {
            "MPN",
            "Manufacturer",
            "Tolerance",
            "Power",
        }

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        for name, expected_value in [
            ("MPN", "RC0603FR-0710KL"),
            ("Manufacturer", "Yageo"),
            ("Tolerance", "1%"),
            ("Power", "0.1W"),
        ]:
            assert name in get_result["fields"], f"Missing property {name}"
            assert get_result["fields"][name]["value"] == expected_value

    def test_update_existing_custom_property(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        # First add
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"MPN": "OLD-PN"},
            },
        )
        # Then update
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"MPN": "RC0603FR-0710KL"},
            },
        )
        assert result["success"] is True
        assert "MPN" in result["updated"]["propertiesUpdated"]

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        assert get_result["fields"]["MPN"]["value"] == "RC0603FR-0710KL"

    def test_add_property_with_full_spec_dict(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {
                    "MPN": {
                        "value": "RC0603FR-0710KL",
                        "x": 60.0,
                        "y": 60.0,
                        "angle": 90,
                        "hide": False,
                    }
                },
            },
        )
        assert result["success"] is True

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        mpn = get_result["fields"]["MPN"]
        assert mpn["value"] == "RC0603FR-0710KL"
        assert mpn["x"] == pytest.approx(60.0)
        assert mpn["y"] == pytest.approx(60.0)
        assert mpn["angle"] == pytest.approx(90.0)

        # Verify the (hide no) flag actually made it into the file
        content = sch_with_r1.read_text(encoding="utf-8")
        m = re.search(
            r'\(property\s+"MPN"\s+"[^"]*"\s+\(at[^)]+\)\s+\(effects.*?\(hide no\)',
            content,
            re.DOTALL,
        )
        assert m is not None, "Expected (hide no) on the MPN property"

    def test_new_property_defaults_to_hidden(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"DigiKey_PN": "311-10.0KHRCT-ND"},
            },
        )
        content = sch_with_r1.read_text(encoding="utf-8")
        # Match (hide yes) inside the DigiKey_PN property block
        m = re.search(
            r'\(property\s+"DigiKey_PN"\s+"[^"]*"\s+\(at[^)]+\)\s+\(effects.*?\(hide yes\)',
            content,
            re.DOTALL,
        )
        assert m is not None, "New custom properties should default to (hide yes)"

    def test_property_added_at_component_origin_by_default(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"MPN": "RC0603FR-0710KL"},
            },
        )
        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        mpn = get_result["fields"]["MPN"]
        # Default position should equal the parent symbol's (50, 50)
        assert mpn["x"] == pytest.approx(50.0)
        assert mpn["y"] == pytest.approx(50.0)

    def test_remove_custom_property(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"MPN": "RC0603FR-0710KL"},
            },
        )
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "removeProperties": ["MPN"],
            },
        )
        assert result["success"] is True
        assert "MPN" in result["updated"]["propertiesRemoved"]

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        assert "MPN" not in get_result["fields"]

    def test_remove_protected_field_rejected(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        for name in ("Reference", "Value", "Footprint", "Datasheet"):
            result = iface.handle_command(
                "edit_schematic_component",
                {
                    "schematicPath": str(sch_with_r1),
                    "reference": "R1",
                    "removeProperties": [name],
                },
            )
            assert result["success"] is False, f"Removal of {name} should be rejected"
            assert name in result["message"]

    def test_remove_non_existent_property_is_noop(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "removeProperties": ["DoesNotExist"],
            },
        )
        assert result["success"] is True
        # No-op: the field was not present, so it should not appear in propertiesRemoved
        assert "propertiesRemoved" not in result["updated"]

    def test_batch_update_adds_and_removes_atomically(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"OldField": "drop_me"},
            },
        )
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {
                    "MPN": "RC0603FR-0710KL",
                    "Manufacturer": "Yageo",
                },
                "removeProperties": ["OldField"],
            },
        )
        assert result["success"] is True
        assert set(result["updated"]["propertiesAdded"].keys()) == {"MPN", "Manufacturer"}
        assert "OldField" in result["updated"]["propertiesRemoved"]

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        assert "OldField" not in get_result["fields"]
        assert "MPN" in get_result["fields"]
        assert "Manufacturer" in get_result["fields"]

    def test_property_with_special_chars_is_escaped(self, sch_with_r1: Any) -> None:
        """Values containing " and \\ must be backslash-escaped in the .kicad_sch file
        so the resulting S-expression is still well-formed and can be re-opened by KiCad.
        """
        iface = self._iface()
        tricky = 'Has "quotes" and \\backslash'
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"Description": tricky},
            },
        )
        assert result["success"] is True

        # Inspect the file directly: the on-disk form must contain the escaped
        # representation, NOT the raw quotes (which would corrupt the S-expression).
        content = sch_with_r1.read_text(encoding="utf-8")
        assert (
            r'(property "Description" "Has \"quotes\" and \\backslash"' in content
        ), f"Expected escaped property value in file. Got:\n{content[-1000:]}"

    def test_existing_value_field_is_unchanged_when_adding_property(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"MPN": "RC0603FR-0710KL"},
            },
        )
        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        # Built-in fields must be untouched
        assert get_result["fields"]["Value"]["value"] == "10k"
        assert get_result["fields"]["Reference"]["value"] == "R1"
        assert get_result["fields"]["Footprint"]["value"] == "Resistor_SMD:R_0603_1608Metric"

    def test_uuid_preserved_after_property_changes(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        before = sch_with_r1.read_text(encoding="utf-8")
        iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": {"MPN": "RC0603FR-0710KL", "Manufacturer": "Yageo"},
                "removeProperties": ["Datasheet"] if False else None,
            },
        )
        after = sch_with_r1.read_text(encoding="utf-8")
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in after
        # And the uuid must still be the only one (we did not duplicate the symbol)
        assert before.count("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") == after.count(
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )

    def test_unknown_reference_returns_failure(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R99",
                "properties": {"MPN": "RC0603FR-0710KL"},
            },
        )
        assert result["success"] is False

    def test_invalid_properties_type_returns_failure(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "properties": ["not", "a", "dict"],
            },
        )
        assert result["success"] is False

    def test_invalid_remove_properties_type_returns_failure(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "removeProperties": "MPN",  # should be a list
            },
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Tests for the dedicated set_/remove_ tools
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSetSchematicComponentProperty:
    """Tests for the convenience `set_schematic_component_property` tool."""

    @pytest.fixture
    def sch_with_r1(self, tmp_path: Any) -> Any:
        return _make_test_schematic(tmp_path, PLACED_RESISTOR_BLOCK)

    def _iface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_set_creates_property(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "MPN",
                "value": "RC0603FR-0710KL",
            },
        )
        assert result["success"] is True
        assert result["updated"]["propertiesAdded"]["MPN"] == "RC0603FR-0710KL"

    def test_set_updates_existing_property(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "MPN",
                "value": "OLD",
            },
        )
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "MPN",
                "value": "NEW",
            },
        )
        assert result["success"] is True
        assert result["updated"]["propertiesUpdated"]["MPN"] == "NEW"

    def test_set_with_visible_position(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "MPN",
                "value": "RC0603FR-0710KL",
                "x": 70.0,
                "y": 65.0,
                "hide": False,
                "fontSize": 0.85,
            },
        )
        assert result["success"] is True

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        mpn = get_result["fields"]["MPN"]
        assert mpn["x"] == pytest.approx(70.0)
        assert mpn["y"] == pytest.approx(65.0)

    def test_set_missing_name_fails(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "value": "RC0603FR-0710KL",
            },
        )
        assert result["success"] is False

    def test_set_missing_value_fails(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "MPN",
            },
        )
        assert result["success"] is False

    def test_set_can_modify_built_in_value_field(self, sch_with_r1: Any) -> None:
        """Built-in fields can be re-targeted via set_..._property too."""
        iface = self._iface()
        result = iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "Value",
                "value": "22k",
            },
        )
        assert result["success"] is True
        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        assert get_result["fields"]["Value"]["value"] == "22k"


@pytest.mark.integration
class TestRemoveSchematicComponentProperty:
    """Tests for the convenience `remove_schematic_component_property` tool."""

    @pytest.fixture
    def sch_with_r1(self, tmp_path: Any) -> Any:
        return _make_test_schematic(tmp_path, PLACED_RESISTOR_BLOCK)

    def _iface(self) -> Any:
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_remove_existing_custom_property(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        iface.handle_command(
            "set_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "MPN",
                "value": "RC0603FR-0710KL",
            },
        )
        result = iface.handle_command(
            "remove_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "MPN",
            },
        )
        assert result["success"] is True
        assert "MPN" in result["updated"]["propertiesRemoved"]

        get_result = iface.handle_command(
            "get_schematic_component",
            {"schematicPath": str(sch_with_r1), "reference": "R1"},
        )
        assert "MPN" not in get_result["fields"]

    def test_remove_built_in_field_rejected(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "remove_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "Reference",
            },
        )
        assert result["success"] is False

    def test_remove_missing_property_succeeds_with_no_change(self, sch_with_r1: Any) -> None:
        iface = self._iface()
        result = iface.handle_command(
            "remove_schematic_component_property",
            {
                "schematicPath": str(sch_with_r1),
                "reference": "R1",
                "name": "NeverExisted",
            },
        )
        assert result["success"] is True
        assert "propertiesRemoved" not in result["updated"]
