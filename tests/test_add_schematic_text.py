"""
Tests for the add_schematic_text tool.

Covers:
  - WireManager.add_text S-expression insertion
  - Correct position, angle, font options, justification
  - String escaping (double quotes in text)
  - Parameter validation in _handle_add_schematic_text
"""

import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    return iface


@pytest.fixture()
def iface():
    return _make_iface()


_MINIMAL_SCH = textwrap.dedent("""\
    (kicad_sch (version 20250114) (generator "test")
    \t(uuid aaaaaaaa-0000-0000-0000-000000000001)
    \t(paper "A4")
    \t(sheet_instances (path "/" (page "1")))
    )
    """)


# ---------------------------------------------------------------------------
# WireManager.add_text unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWireManagerAddText:
    def test_inserts_text_element(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = WireManager.add_text(sch, "Test Note", [50.0, 40.0])

        assert result is True
        content = sch.read_text(encoding="utf-8")
        assert '(text "Test Note"' in content
        assert "(at 50.0 40.0 0)" in content

    def test_inserts_before_sheet_instances(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, "Section A", [10.0, 20.0])

        content = sch.read_text(encoding="utf-8")
        text_pos = content.find('(text "Section A"')
        instances_pos = content.find("(sheet_instances")
        assert text_pos < instances_pos

    def test_rotation_angle(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, "Rotated", [20.0, 20.0], angle=90)

        content = sch.read_text(encoding="utf-8")
        assert "(at 20.0 20.0 90)" in content

    def test_bold_and_italic_flags(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, "Bold Italic", [30.0, 30.0], bold=True, italic=True)

        content = sch.read_text(encoding="utf-8")
        assert "(bold yes)" in content
        assert "(italic yes)" in content

    def test_center_justification(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, "Centered", [50.0, 50.0], justify="center")

        content = sch.read_text(encoding="utf-8")
        assert "(justify center bottom)" in content

    def test_custom_font_size(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, "Big Text", [10.0, 10.0], font_size=2.54)

        content = sch.read_text(encoding="utf-8")
        assert "(size 2.54 2.54)" in content

    def test_escapes_double_quotes_in_text(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, 'He said "hello"', [10.0, 10.0])

        content = sch.read_text(encoding="utf-8")
        assert r"He said \"hello\"" in content

    def test_result_is_valid_sexp(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, "Note", [10.0, 10.0])

        # Must parse without error
        sexpdata.loads(sch.read_text(encoding="utf-8"))

    def test_no_bold_italic_by_default(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        WireManager.add_text(sch, "Plain", [10.0, 10.0])

        content = sch.read_text(encoding="utf-8")
        assert "(bold yes)" not in content
        assert "(italic yes)" not in content


# ---------------------------------------------------------------------------
# _handle_add_schematic_text parameter-validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleAddSchematicText:
    def test_missing_schematic_path(self, iface):
        result = iface._handle_add_schematic_text({"text": "Note", "position": [10.0, 20.0]})
        assert result["success"] is False
        assert "schematicPath" in result["message"]

    def test_missing_text(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        result = iface._handle_add_schematic_text(
            {"schematicPath": str(sch), "position": [10.0, 20.0]}
        )
        assert result["success"] is False
        assert "text" in result["message"]

    def test_missing_position(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        result = iface._handle_add_schematic_text({"schematicPath": str(sch), "text": "Note"})
        assert result["success"] is False
        assert "position" in result["message"]

    def test_invalid_justify(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        result = iface._handle_add_schematic_text(
            {
                "schematicPath": str(sch),
                "text": "Note",
                "position": [10.0, 20.0],
                "justify": "top",
            }
        )
        assert result["success"] is False
        assert "justify" in result["message"]

    def test_invalid_font_size(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        result = iface._handle_add_schematic_text(
            {
                "schematicPath": str(sch),
                "text": "Note",
                "position": [10.0, 20.0],
                "fontSize": 0,
            }
        )
        assert result["success"] is False
        assert "fontSize" in result["message"]

    def test_nonexistent_file(self, iface, tmp_path):
        result = iface._handle_add_schematic_text(
            {
                "schematicPath": str(tmp_path / "nope.kicad_sch"),
                "text": "Note",
                "position": [10, 20],
            }
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_success(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        result = iface._handle_add_schematic_text(
            {
                "schematicPath": str(sch),
                "text": "Power Section",
                "position": [25.4, 50.8],
                "angle": 0,
                "fontSize": 1.5,
            }
        )
        assert result["success"] is True
        assert "position" in result
        content = sch.read_text(encoding="utf-8")
        assert '(text "Power Section"' in content

    def test_success_returns_position(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        result = iface._handle_add_schematic_text(
            {"schematicPath": str(sch), "text": "Note", "position": [12.7, 25.4]}
        )
        assert result["success"] is True
        assert result["position"] == {"x": 12.7, "y": 25.4}


# ---------------------------------------------------------------------------
# WireManager.list_texts unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWireManagerListTexts:
    def test_empty_schematic_returns_empty_list(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")

        result = WireManager.list_texts(sch)

        assert result == []

    def test_lists_added_text(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "Power Section", [10.0, 20.0])

        result = WireManager.list_texts(sch)

        assert len(result) == 1
        assert result[0]["text"] == "Power Section"
        assert result[0]["position"] == {"x": 10.0, "y": 20.0}

    def test_lists_multiple_texts(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "Alpha", [0.0, 0.0])
        WireManager.add_text(sch, "Beta", [10.0, 10.0])

        result = WireManager.list_texts(sch)

        texts = {r["text"] for r in result}
        assert texts == {"Alpha", "Beta"}

    def test_angle_is_preserved(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "Rotated", [5.0, 5.0], angle=90)

        result = WireManager.list_texts(sch)

        assert result[0]["angle"] == 90.0

    def test_bold_italic_are_preserved(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "Styled", [5.0, 5.0], bold=True, italic=True)

        result = WireManager.list_texts(sch)

        assert result[0]["bold"] is True
        assert result[0]["italic"] is True

    def test_font_size_is_preserved(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "Big", [5.0, 5.0], font_size=2.54)

        result = WireManager.list_texts(sch)

        assert result[0]["font_size"] == 2.54

    def test_nonexistent_file_returns_none(self, tmp_path):
        from commands.wire_manager import WireManager

        result = WireManager.list_texts(tmp_path / "nope.kicad_sch")

        assert result is None


# ---------------------------------------------------------------------------
# _handle_list_schematic_texts handler tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleListSchematicTexts:
    def test_missing_schematic_path(self, iface):
        result = iface._handle_list_schematic_texts({})
        assert result["success"] is False
        assert "schematicPath" in result["message"]

    def test_nonexistent_file(self, iface, tmp_path):
        result = iface._handle_list_schematic_texts(
            {"schematicPath": str(tmp_path / "nope.kicad_sch")}
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_empty_schematic(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        result = iface._handle_list_schematic_texts({"schematicPath": str(sch)})
        assert result["success"] is True
        assert result["texts"] == []
        assert result["count"] == 0

    def test_returns_all_texts(self, iface, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "Note A", [0.0, 0.0])
        WireManager.add_text(sch, "Note B", [10.0, 10.0])

        result = iface._handle_list_schematic_texts({"schematicPath": str(sch)})

        assert result["success"] is True
        assert result["count"] == 2

    def test_text_filter_substring_match(self, iface, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "Power Supply", [0.0, 0.0])
        WireManager.add_text(sch, "Ground Plane", [10.0, 10.0])

        result = iface._handle_list_schematic_texts({"schematicPath": str(sch), "text": "power"})

        assert result["success"] is True
        assert result["count"] == 1
        assert result["texts"][0]["text"] == "Power Supply"

    def test_text_filter_case_insensitive(self, iface, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_MINIMAL_SCH, encoding="utf-8")
        WireManager.add_text(sch, "SECTION HEADER", [0.0, 0.0])

        result = iface._handle_list_schematic_texts({"schematicPath": str(sch), "text": "section"})

        assert result["success"] is True
        assert result["count"] == 1
