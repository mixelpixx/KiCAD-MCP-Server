"""
Regression tests for delete_schematic_component.

Key regression: the handler previously used a line-by-line regex that required
`(symbol` and `(lib_id` to appear on the *same* line.  KiCAD's file writer puts
them on *separate* lines, so every real-world delete returned "not found".
"""

import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

# Inline format (single line) – matches what tests previously used
PLACED_RESISTOR_INLINE = """\
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

# Multi-line format – as KiCAD's own file writer produces it.
# (symbol and (lib_id are on separate lines, which broke the old regex.
PLACED_RESISTOR_MULTILINE = """\
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 50 50 0)
\t\t(unit 1)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(uuid "bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
\t\t(property "Reference" "R2"
\t\t\t(at 51.27 47.46 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "4.7k"
\t\t\t(at 51.27 52.54 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
"""

# Multi-line power symbol – the exact scenario that was reported as broken.
PLACED_POWER_SYMBOL_MULTILINE = """\
\t(symbol
\t\t(lib_id "power:VCC")
\t\t(at 365.6 38.1 0)
\t\t(unit 1)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(uuid "cccccccc-dddd-eeee-ffff-000000000030")
\t\t(property "Reference" "#PWR030"
\t\t\t(at 365.6 41.91 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(hide yes)
\t\t\t)
\t\t)
\t\t(property "Value" "VCC"
\t\t\t(at 365.6 35.56 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
"""


def _make_test_schematic(tmp_path: Path, extra_block: str = "") -> Path:
    dest = tmp_path / "test.kicad_sch"
    src_content = TEMPLATE_SCH.read_text(encoding="utf-8")
    if extra_block:
        src_content = src_content.rstrip()
        if src_content.endswith(")"):
            src_content = src_content[:-1] + "\n" + extra_block + ")\n"
    dest.write_text(src_content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Unit tests – regression proof for the old regex vs the new approach
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteDetectionRegex:
    """Verify that the new content-string pattern finds blocks in both formats."""

    OLD_PATTERN = re.compile(r"^\s*\(symbol\s+\(lib_id\s+\"", re.MULTILINE)
    NEW_PATTERN = re.compile(r'\(symbol\s+\(lib_id\s+"')

    def test_old_regex_fails_on_multiline_format(self) -> None:
        """Regression: old line-by-line regex must NOT match the multi-line format."""
        # The old code used re.match on individual lines; simulate that here.
        lines = PLACED_RESISTOR_MULTILINE.split("\n")
        matches = [l for l in lines if re.match(r"\s*\(symbol\s+\(lib_id\s+\"", l)]
        assert matches == [], "Old regex should not match multi-line KiCAD format"

    def test_old_regex_matches_inline_format(self) -> None:
        """Old regex did work on single-line (inline) format."""
        lines = PLACED_RESISTOR_INLINE.split("\n")
        matches = [l for l in lines if re.match(r"\s*\(symbol\s+\(lib_id\s+\"", l)]
        assert len(matches) == 1

    def test_new_pattern_matches_multiline_format(self) -> None:
        """New content-string pattern must find blocks in multi-line format."""
        assert self.NEW_PATTERN.search(PLACED_RESISTOR_MULTILINE) is not None

    def test_new_pattern_matches_inline_format(self) -> None:
        """New content-string pattern also works on inline format."""
        assert self.NEW_PATTERN.search(PLACED_RESISTOR_INLINE) is not None

    def test_new_pattern_matches_power_symbol_multiline(self) -> None:
        """New pattern must find #PWR030 power symbol in multi-line format."""
        assert self.NEW_PATTERN.search(PLACED_POWER_SYMBOL_MULTILINE) is not None

    def test_reference_extraction_from_multiline_block(self) -> None:
        """Reference property can be found inside a multi-line block."""
        ref_pattern = re.compile(r'\(property\s+"Reference"\s+"#PWR030"')
        assert ref_pattern.search(PLACED_POWER_SYMBOL_MULTILINE) is not None


# ---------------------------------------------------------------------------
# Integration tests – real file I/O using the handler
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteSchematicComponentIntegration:
    def _get_handler(self) -> Any:
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_delete_schematic_component

    def test_delete_inline_format_succeeds(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_INLINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "R1"})
        assert result["success"] is True
        assert result["deleted_count"] == 1

    def test_delete_multiline_format_succeeds(self, tmp_path: Any) -> None:
        """Regression: must succeed when KiCAD writes (symbol and (lib_id on separate lines."""
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_MULTILINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "R2"})
        assert result["success"] is True
        assert result["deleted_count"] == 1

    def test_delete_power_symbol_multiline_succeeds(self, tmp_path: Any) -> None:
        """Regression: #PWR030 multi-line power symbol must be deletable."""
        sch = _make_test_schematic(tmp_path, PLACED_POWER_SYMBOL_MULTILINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "#PWR030"})
        assert result["success"] is True
        assert result["deleted_count"] == 1

    def test_component_absent_after_delete(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_POWER_SYMBOL_MULTILINE)
        self._get_handler()({"schematicPath": str(sch), "reference": "#PWR030"})
        remaining = sch.read_text(encoding="utf-8")
        assert '"#PWR030"' not in remaining

    def test_unknown_reference_returns_failure(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_INLINE)
        result = self._get_handler()({"schematicPath": str(sch), "reference": "U99"})
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_missing_schematic_path_returns_failure(self, tmp_path: Any) -> None:
        result = self._get_handler()({"reference": "R1"})
        assert result["success"] is False

    def test_missing_reference_returns_failure(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path)
        result = self._get_handler()({"schematicPath": str(sch)})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# deleteAttachedLabels — orphan label cleanup
# ---------------------------------------------------------------------------


def _label_block(text: str, x: float, y: float, kind: str = "label") -> str:
    return (
        f'  ({kind} "{text}" (at {x} {y} 0)\n'
        "    (effects (font (size 1.27 1.27)) (justify left bottom))\n"
        '    (uuid "12121212-3434-5656-7878-909090909090")\n'
        "  )\n"
    )


def _wire_block(x1: float, y1: float, x2: float, y2: float) -> str:
    return (
        f"  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n"
        "    (stroke (width 0) (type default))\n"
        '    (uuid "abababab-cdcd-efef-0101-232323232323")\n'
        "  )\n"
    )


# A second resistor whose top pin coincides with R1's bottom pin region is
# not needed; instead place it so ONE pin coincides with a label under test.
def _placed_resistor(ref: str, x: float, y: float) -> str:
    return PLACED_RESISTOR_INLINE.replace('"R1"', f'"{ref}"').replace(
        "(at 50 50 0)", f"(at {x} {y} 0)"
    )


@pytest.mark.unit
class TestDeleteAttachedLabels:
    """R1 (Device:R at 50,50) has pins at (50, 46.19) and (50, 53.81) —
    derived from WireManager._collect_pin_positions in _pin_positions()."""

    PIN_TOP = (50.0, 46.19)
    PIN_BOT = (50.0, 53.81)

    def _get_handler(self) -> Any:
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_delete_schematic_component

    def _pin_positions(self, sch: Path) -> list:
        import sexpdata

        from commands.wire_manager import WireManager

        return WireManager._collect_pin_positions(
            sexpdata.loads(sch.read_text(encoding="utf-8"))
        )

    def test_fixture_pins_self_check(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_INLINE)
        pins = sorted(self._pin_positions(sch), key=lambda p: p[1])
        assert pins == [self.PIN_TOP, self.PIN_BOT]

    def test_labels_on_both_pins_deleted(self, tmp_path: Any) -> None:
        extra = (
            PLACED_RESISTOR_INLINE
            + _label_block("NET_A", *self.PIN_TOP)
            + _label_block("NET_B", *self.PIN_BOT)
        )
        sch = _make_test_schematic(tmp_path, extra)
        result = self._get_handler()(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "deleteAttachedLabels": True,
            }
        )
        assert result["success"] is True
        assert result["deleted_label_count"] == 2
        assert {d["text"] for d in result["deleted_labels"]} == {"NET_A", "NET_B"}
        content = sch.read_text(encoding="utf-8")
        assert "NET_A" not in content
        assert "NET_B" not in content
        assert '"R1"' not in content

    def test_default_off_keeps_labels(self, tmp_path: Any) -> None:
        extra = PLACED_RESISTOR_INLINE + _label_block("NET_A", *self.PIN_TOP)
        sch = _make_test_schematic(tmp_path, extra)
        for flag_params in ({}, {"deleteAttachedLabels": False}):
            sch_i = _make_test_schematic(tmp_path, extra)
            result = self._get_handler()(
                {"schematicPath": str(sch_i), "reference": "R1", **flag_params}
            )
            assert result["success"] is True
            assert "deleted_labels" not in result or not result["deleted_labels"]
            content = sch_i.read_text(encoding="utf-8")
            assert 'label "NET_A"' in content

    def test_label_shared_with_wire_survives(self, tmp_path: Any) -> None:
        # NET_A sits on the top pin AND is a wire endpoint -> keep.
        # NET_B sits strictly mid-wire -> keep. NET_C is only on the pin -> delete.
        extra = (
            PLACED_RESISTOR_INLINE
            + _label_block("NET_A", *self.PIN_TOP)
            + _wire_block(self.PIN_TOP[0], self.PIN_TOP[1], 70, self.PIN_TOP[1])
            + _wire_block(
                self.PIN_BOT[0] - 10, self.PIN_BOT[1], self.PIN_BOT[0] + 10, self.PIN_BOT[1]
            )
            + _label_block("NET_B", *self.PIN_BOT)
        )
        sch = _make_test_schematic(tmp_path, extra)
        result = self._get_handler()(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "deleteAttachedLabels": True,
            }
        )
        assert result["success"] is True
        content = sch.read_text(encoding="utf-8")
        assert 'label "NET_A"' in content  # wire endpoint at pin
        assert 'label "NET_B"' in content  # strictly mid-wire
        assert result["deleted_label_count"] == 0

    def test_label_shared_with_other_component_pin_survives(self, tmp_path: Any) -> None:
        # R9 placed so its top pin lands exactly on R1's bottom pin position:
        # R9 at (50, 53.81 + 3.81) has top pin at (50, 53.81).
        extra = (
            PLACED_RESISTOR_INLINE
            + _placed_resistor("R9", 50, 57.62)
            + _label_block("SHARED", *self.PIN_BOT)
            + _label_block("ONLY_R1", *self.PIN_TOP)
        )
        sch = _make_test_schematic(tmp_path, extra)
        result = self._get_handler()(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "deleteAttachedLabels": True,
            }
        )
        assert result["success"] is True
        content = sch.read_text(encoding="utf-8")
        assert 'label "SHARED"' in content
        assert "ONLY_R1" not in content
        assert result["deleted_label_count"] == 1
        assert result["deleted_labels"][0]["text"] == "ONLY_R1"

    def test_global_label_deleted_and_typed(self, tmp_path: Any) -> None:
        extra = PLACED_RESISTOR_INLINE + _label_block(
            "GNET", *self.PIN_TOP, kind="global_label"
        )
        sch = _make_test_schematic(tmp_path, extra)
        result = self._get_handler()(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "deleteAttachedLabels": True,
            }
        )
        assert result["success"] is True
        assert result["deleted_label_count"] == 1
        assert result["deleted_labels"][0]["type"] == "global_label"
        assert "GNET" not in sch.read_text(encoding="utf-8")

    def test_unknown_reference_with_flag_unchanged(self, tmp_path: Any) -> None:
        sch = _make_test_schematic(tmp_path, PLACED_RESISTOR_INLINE)
        result = self._get_handler()(
            {
                "schematicPath": str(sch),
                "reference": "U99",
                "deleteAttachedLabels": True,
            }
        )
        assert result["success"] is False
        assert "not found" in result["message"]
