"""
Unit + integration tests for schematic field-placement/layout commands.

The text S-expression helpers and the set/batch property writers are exercised against a
real minimal .kicad_sch written to a temp file (pure text manipulation — no KiCad needed).
autoplace_schematic_fields is tested for parameter validation; the geometry helpers are
unit-tested directly.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_field_layout import (  # noqa: E402
    SchematicFieldLayoutCommands,
    _bbox_overlaps,
    _gather_labels,
)
from commands.schematic_legibility import block_box, check_legibility, field_box  # noqa: E402
from commands.schematic_text_metrics import text_height, text_width  # noqa: E402
from commands.schematic_text_utils import (  # noqa: E402
    _extract_component_properties,
    _extract_property_justify,
    _extract_property_position,
    _extract_property_visible,
    _extract_symbol_transform,
    _find_matching_paren,
    _find_placed_symbol_block,
    _get_sheet_usable_area,
    _move_property_in_block,
    effective_field_justification,
    is_multiple_of_90,
    sheet_angle_to_stored_angle,
    stored_angle_to_drawn_angle,
)

MINIMAL_SCH = """(kicad_sch (version 20230121) (paper "A4")
  (lib_symbols
    (symbol "Device:R" (property "Reference" "R" (at 0 0 0)))
  )
  (symbol (lib_id "Device:R") (at 100 100 0) (uuid "11111111")
    (property "Reference" "R1" (at 102.0 98.0 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 102.0 102.0 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:C") (at 150 100 0) (uuid "22222222")
    (property "Reference" "C1" (at 152.0 98.0 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "100nF" (at 152.0 102.0 0)
      (effects (font (size 1.27 1.27))))
  )
)
"""


class TestTextHelpers:
    def test_find_matching_paren(self):
        s = "(a (b) c)"
        assert _find_matching_paren(s, 0) == len(s) - 1
        assert _find_matching_paren(s, 3) == 5

    def test_find_placed_symbol_block_skips_lib_symbols(self):
        block, start, end = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        assert block is not None
        # Must be the placed instance (has lib_id + (at 100 100 0)), not the lib_symbols def
        assert '(lib_id "Device:R")' in block and "(at 100 100 0)" in block

    def test_find_placed_symbol_block_missing(self):
        assert _find_placed_symbol_block(MINIMAL_SCH, "R99") == (None, -1, -1)

    def test_extract_property_position(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        assert _extract_property_position(block, "Reference") == {
            "x": 102.0,
            "y": 98.0,
            "angle": 0.0,
        }

    def test_extract_property_visible(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        assert _extract_property_visible(block, "Reference") is True

    def test_extract_component_properties(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        props = _extract_component_properties(block)
        assert props["Reference"] == "R1" and props["Value"] == "10k"

    def test_move_property_in_block_and_hide(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        new_block, n = _move_property_in_block(block, "Reference", 105, 95, 0, visible=False)
        assert n == 1
        assert "(at 105 95 0)" in new_block
        assert "(hide yes)" in new_block
        # Re-show it
        reshown, _ = _move_property_in_block(new_block, "Reference", 105, 95, 0, visible=True)
        assert "(hide yes)" not in reshown

    def test_move_property_missing(self):
        block, _, _ = _find_placed_symbol_block(MINIMAL_SCH, "R1")
        _, n = _move_property_in_block(block, "Footprint", 1, 2, 0, True)
        assert n == 0


class TestGeometryHelpers:
    def test_bbox_overlaps(self):
        a = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        b = {"x_min": 5, "y_min": 5, "x_max": 15, "y_max": 15}
        c = {"x_min": 20, "y_min": 20, "x_max": 30, "y_max": 30}
        assert _bbox_overlaps(a, b)
        assert not _bbox_overlaps(a, c)
        assert _bbox_overlaps(a, c, margin=11)  # margin bridges the gap

    def test_get_sheet_usable_area_default_a4(self, tmp_path):
        f = tmp_path / "a4.kicad_sch"
        f.write_text('(kicad_sch (paper "A4")')
        left, top, right, bottom = _get_sheet_usable_area(str(f))
        assert (left, top) == (12.7, 12.7)
        assert right == pytest.approx(297.0 - 12.7)
        assert bottom == pytest.approx(210.0 - 12.7)

    def test_get_sheet_usable_area_a3(self, tmp_path):
        f = tmp_path / "a3.kicad_sch"
        f.write_text('(kicad_sch (paper "A3")')
        _, _, right, _ = _get_sheet_usable_area(str(f))
        assert right == pytest.approx(420.0 - 12.7)

    def test_gather_labels(self):
        def lbl(v, at):
            return types.SimpleNamespace(value=v, at=types.SimpleNamespace(value=at))

        sch = types.SimpleNamespace(
            label=[lbl("SDA", [1, 2, 0])], global_label=[lbl("VBUS", [3, 4, 90])]
        )
        labels = _gather_labels(sch)
        assert {x["name"] for x in labels} == {"SDA", "VBUS"}
        vbus = next(x for x in labels if x["name"] == "VBUS")
        assert vbus["type"] == "global" and vbus["angle"] == 90.0


class TestSetPropertyPosition:
    def _sch(self, tmp_path):
        f = tmp_path / "x.kicad_sch"
        f.write_text(MINIMAL_SCH)
        return f

    def test_missing_params(self):
        c = SchematicFieldLayoutCommands()
        assert (
            c.set_schematic_property_position({"schematicPath": "/x", "reference": "R1"})["success"]
            is False
        )

    def test_rejects_non_ref_value(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {"schematicPath": str(f), "reference": "R1", "property": "Footprint", "x": 1, "y": 2}
        )
        assert r["success"] is False

    def test_moves_field(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {"schematicPath": str(f), "reference": "R1", "property": "Reference", "x": 105, "y": 95}
        )
        assert r["success"] is True
        content = f.read_text()
        assert '(property "Reference" "R1" (at 105 95 0)' in content
        # C1 left untouched
        assert '(property "Reference" "C1" (at 152.0 98.0 0)' in content

    def test_component_not_found(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {"schematicPath": str(f), "reference": "R99", "property": "Value", "x": 1, "y": 2}
        )
        assert r["success"] is False


class TestBatchSetPropertyPositions:
    def test_batch_applies_and_reports(self, tmp_path):
        f = tmp_path / "x.kicad_sch"
        f.write_text(MINIMAL_SCH)
        c = SchematicFieldLayoutCommands()
        r = c.batch_set_schematic_property_positions(
            {
                "schematicPath": str(f),
                "updates": [
                    {"reference": "R1", "property": "Reference", "x": 90, "y": 90},
                    {"reference": "C1", "property": "Value", "x": 160, "y": 110},
                    {"reference": "R99", "property": "Value", "x": 0, "y": 0},  # should fail
                ],
            }
        )
        assert r["applied_count"] == 2
        assert r["failed_count"] == 1
        assert r["success"] is False  # because one failed
        content = f.read_text()
        assert '(property "Reference" "R1" (at 90 90 0)' in content
        assert '(property "Value" "100nF" (at 160 110 0)' in content

    def test_requires_updates(self, tmp_path):
        f = tmp_path / "x.kicad_sch"
        f.write_text(MINIMAL_SCH)
        c = SchematicFieldLayoutCommands()
        assert (
            c.batch_set_schematic_property_positions({"schematicPath": str(f)})["success"] is False
        )


class TestAutoplaceValidation:
    def test_autoplace_requires_path(self):
        assert SchematicFieldLayoutCommands().autoplace_schematic_fields({})["success"] is False


ROTATED_AND_MIRRORED_SCH = """(kicad_sch (version 20250114) (paper "A4")
  (lib_symbols
    (symbol "Device:R"
      (symbol "R_0_1"
        (rectangle (start -1.016 -2.54) (end 1.016 2.54)))
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
        (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))
  )
  (symbol (lib_id "Device:R") (at 60 60 0) (unit 1) (uuid "00000001")
    (property "Reference" "R1" (at 62.54 58.73 0)
      (effects (font (size 1.27 1.27)) (justify left)))
    (property "Value" "10k" (at 62.54 61.27 90)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:R") (at 100 60 90) (unit 1) (uuid "00000002")
    (property "Reference" "R2" (at 100 57.46 90)
      (effects (font (size 1.27 1.27)) (justify left bottom)))
    (property "Value" "4.7k" (at 100 62.54 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:R") (at 140 60 180) (unit 1) (uuid "00000003")
    (property "Reference" "R3" (at 137.46 58.73 0)
      (effects (font (size 1.27 1.27)) (justify left bottom)))
    (property "Value" "1k" (at 137.46 61.27 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:R") (at 180 60 270) (unit 1) (uuid "00000004")
    (property "Reference" "R4" (at 180 57.46 90)
      (effects (font (size 1.27 1.27)) (justify right)))
    (property "Value" "22k" (at 180 62.54 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:R") (at 100 120 270) (mirror y) (unit 1) (uuid "00000005")
    (property "Reference" "Q1" (at 100 117.46 90)
      (effects (font (size 1.27 1.27)) (justify right)))
    (property "Value" "Q_DPAK" (at 100 122.54 90)
      (effects (font (size 1.27 1.27)) (justify left top)))
  )
  (symbol (lib_id "Device:R") (at 150 120 90) (mirror x) (unit 1) (uuid "00000006")
    (property "Reference" "R6" (at 150 117.46 0)
      (effects (font (size 1.27 1.27)) (justify left top)))
    (property "Value" "100R" (at 150 122.54 90)
      (effects (font (size 1.27 1.27))))
  )
)
"""


class TestFieldOrientationMath:
    def test_sheet_angle_to_stored_angle_all_rotations(self):
        # Horizontal text on the sheet (angle=0):
        # 0°/180° symbols store 0; 90°/270° symbols store 90.
        assert sheet_angle_to_stored_angle(0, 0) == 0
        assert sheet_angle_to_stored_angle(0, 90) == 90
        assert sheet_angle_to_stored_angle(0, 180) == 0
        assert sheet_angle_to_stored_angle(0, 270) == 90
        assert sheet_angle_to_stored_angle(0, -90) == 90

        # Vertical text on the sheet (angle=90):
        # 0°/180° symbols store 90; 90°/270° symbols store 0.
        assert sheet_angle_to_stored_angle(90, 0) == 90
        assert sheet_angle_to_stored_angle(90, 90) == 0
        assert sheet_angle_to_stored_angle(90, 180) == 90
        assert sheet_angle_to_stored_angle(90, 270) == 0

        # 180/270 normalise to upright canonical stored angles (never 180).
        assert sheet_angle_to_stored_angle(180, 0) == 0
        assert sheet_angle_to_stored_angle(180, 180) == 0
        assert sheet_angle_to_stored_angle(270, 90) == 0
        assert sheet_angle_to_stored_angle(270, 0) == 90

    def test_stored_angle_to_drawn_angle_roundtrip(self):
        for target in (0, 90):
            for rot in (0, 90, 180, 270):
                for mirror in (None, "x", "y"):
                    stored = sheet_angle_to_stored_angle(target, rot, mirror)
                    assert stored in (0, 90)
                    assert stored_angle_to_drawn_angle(stored, rot, mirror) == target

    def test_effective_justify_matches_legibility_field_box_exhaustively(self):
        """Verify all 432 (stored_angle, sym_rot, mirror, h_just, v_just) combinations
        against the KiCad-render-calibrated schematic_legibility.field_box."""
        w = text_width("10K", 1.27)
        h_sz = text_height(1.27)
        checked = 0
        for stored in (0, 90, 180, 270):
            for rot in (0, 90, 180, 270):
                for mirror in (None, "x", "y"):
                    for hj in ("left", "center", "right"):
                        for vj in ("top", "center", "bottom"):
                            stored_set = {t for t in (hj, vj) if t != "center"}
                            expected_box = field_box(
                                100.0, 100.0, stored, "10K", (1.27, 1.27), stored_set, rot, mirror
                            )
                            drawn = stored_angle_to_drawn_angle(stored, rot, mirror)
                            eff = effective_field_justification(hj, vj, stored, rot, mirror)
                            eff_set = {
                                t for t in (eff["horizontal"], eff["vertical"]) if t != "center"
                            }
                            actual_box = block_box(100.0, 100.0, drawn, w, h_sz, eff_set)
                            for a, b in zip(actual_box, expected_box):
                                assert a == pytest.approx(b, abs=1e-9), (
                                    f"stored={stored} rot={rot} mirror={mirror} "
                                    f"just=({hj},{vj}) -> drawn={drawn} eff={eff}"
                                )
                            checked += 1
        assert checked == 432

    def test_extract_symbol_transform_and_justify(self):
        for ref, exp_rot, exp_mirror, exp_ref_j, exp_val_j in (
            ("R1", 0.0, None, ("left", "center"), ("center", "center")),
            ("R2", 90.0, None, ("left", "bottom"), ("center", "center")),
            ("R3", 180.0, None, ("left", "bottom"), ("center", "center")),
            ("R4", 270.0, None, ("right", "center"), ("center", "center")),
            ("Q1", 270.0, "y", ("right", "center"), ("left", "top")),
            ("R6", 90.0, "x", ("left", "top"), ("center", "center")),
        ):
            block, _, _ = _find_placed_symbol_block(ROTATED_AND_MIRRORED_SCH, ref)
            assert block is not None
            assert _extract_symbol_transform(block) == (exp_rot, exp_mirror)
            assert _extract_property_justify(block, "Reference") == exp_ref_j
            assert _extract_property_justify(block, "Value") == exp_val_j


class TestSetPropertyPositionRotationAndMirror:
    def _sch(self, tmp_path):
        f = tmp_path / "rot.kicad_sch"
        f.write_text(ROTATED_AND_MIRRORED_SCH, encoding="utf-8")
        return f

    @pytest.mark.parametrize(
        "ref,sym_rot,expected_stored",
        [("R1", 0, 0), ("R2", 90, 90), ("R3", 180, 0), ("R4", 270, 90)],
    )
    def test_sheet_absolute_horizontal_converts_to_symbol_frame(
        self, tmp_path, ref, sym_rot, expected_stored
    ):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": ref,
                "property": "Value",
                "x": 111,
                "y": 77,
                "angle": 0,
            }
        )
        assert r["success"] is True
        assert r["stored_angle"] == expected_stored
        assert r["drawn_angle"] == 0
        assert r["symbol_rotation"] == sym_rot
        assert r["symbol_mirror"] is None
        block, _, _ = _find_placed_symbol_block(f.read_text(encoding="utf-8"), ref)
        pos = _extract_property_position(block, "Value")
        assert pos == {"x": 111.0, "y": 77.0, "angle": float(expected_stored)}

    @pytest.mark.parametrize(
        "ref,expected_stored",
        [("R1", 90), ("R2", 0), ("R3", 90), ("R4", 0)],
    )
    def test_sheet_absolute_vertical_converts_to_symbol_frame(self, tmp_path, ref, expected_stored):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": ref,
                "property": "Value",
                "x": 111,
                "y": 77,
                "angle": 90,
            }
        )
        assert r["success"] is True
        assert r["stored_angle"] == expected_stored
        assert r["drawn_angle"] == 90
        block, _, _ = _find_placed_symbol_block(f.read_text(encoding="utf-8"), ref)
        pos = _extract_property_position(block, "Value")
        assert pos == {"x": 111.0, "y": 77.0, "angle": float(expected_stored)}

    def test_omitting_angle_preserves_existing_stored_angle_on_rotated_part(self, tmp_path):
        """Leaving angle out must NOT reset a 90-degree stored angle on a rotated part to 0."""
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        # R2 is rotated 90° and its Reference is already stored at 90° (horizontal as drawn).
        r = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "R2",
                "property": "Reference",
                "x": 105,
                "y": 55,
            }
        )
        assert r["success"] is True
        assert r["stored_angle"] == 90
        assert r["drawn_angle"] == 0
        block, _, _ = _find_placed_symbol_block(f.read_text(encoding="utf-8"), "R2")
        assert "(at 105 55 90)" in block

        # R1 is rotated 0° and its Value is stored at 90° (vertical as drawn).
        r_val = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "R1",
                "property": "Value",
                "x": 65,
                "y": 65,
            }
        )
        assert r_val["success"] is True
        assert r_val["stored_angle"] == 90
        assert r_val["drawn_angle"] == 90
        block_r1, _, _ = _find_placed_symbol_block(f.read_text(encoding="utf-8"), "R1")
        assert "(at 65 65 90)" in block_r1

    def test_effective_justification_for_rotation_and_mirror(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()

        # R3: rot=180, stored justify left+bottom, angle=0 -> stored=0, drawn=0, eff right+top
        r3 = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "R3",
                "property": "Reference",
                "x": 140,
                "y": 55,
                "angle": 0,
            }
        )
        assert r3["stored_angle"] == 0
        assert r3["drawn_angle"] == 0
        assert r3["stored_justify"] == {"horizontal": "left", "vertical": "bottom"}
        assert r3["effective_justify"] == {"horizontal": "right", "vertical": "top"}

        # R2: rot=90, stored justify left+bottom, angle=0 -> stored=90 (theta=180), eff right+top
        r2 = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "R2",
                "property": "Reference",
                "x": 100,
                "y": 55,
                "angle": 0,
            }
        )
        assert r2["stored_angle"] == 90
        assert r2["drawn_angle"] == 0
        assert r2["effective_justify"] == {"horizontal": "right", "vertical": "top"}

        # Q1: rot=270 + mirror y, stored justify right, angle=0 -> stored=90, drawn=0, eff left
        q1 = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "Q1",
                "property": "Reference",
                "x": 100,
                "y": 115,
                "angle": 0,
            }
        )
        assert q1["stored_angle"] == 90
        assert q1["drawn_angle"] == 0
        assert q1["symbol_mirror"] == "y"
        assert q1["effective_justify"] == {"horizontal": "left", "vertical": "center"}

        # R6: rot=90 + mirror x, stored justify left+top, angle=90 -> stored=0, drawn=90, eff right+top
        r6 = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "R6",
                "property": "Reference",
                "x": 150,
                "y": 115,
                "angle": 90,
            }
        )
        assert r6["stored_angle"] == 0
        assert r6["drawn_angle"] == 90
        assert r6["symbol_mirror"] == "x"
        assert r6["effective_justify"] == {"horizontal": "right", "vertical": "top"}

    def test_180_sheet_angle_never_writes_upside_down_field(self, tmp_path):
        f = self._sch(tmp_path)
        c = SchematicFieldLayoutCommands()
        r = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "R3",
                "property": "Value",
                "x": 140,
                "y": 70,
                "angle": 180,
            }
        )
        assert r["success"] is True
        assert r["stored_angle"] == 0
        assert r["drawn_angle"] == 0
        leg = check_legibility(f)
        assert "upside down" not in leg["counts"]


class TestBatchSetPropertyPositionsRotation:
    def test_batch_converts_explicit_and_preserves_omitted_angles(self, tmp_path):
        f = tmp_path / "rot_batch.kicad_sch"
        f.write_text(ROTATED_AND_MIRRORED_SCH, encoding="utf-8")
        c = SchematicFieldLayoutCommands()
        r = c.batch_set_schematic_property_positions(
            {
                "schematicPath": str(f),
                "updates": [
                    # R2 (rot=90): omit angle -> preserve stored 90 (drawn 0)
                    {"reference": "R2", "property": "Reference", "x": 100, "y": 54},
                    # R2 (rot=90): explicit angle=0 -> convert to stored 90 (drawn 0)
                    {"reference": "R2", "property": "Value", "x": 100, "y": 66, "angle": 0},
                    # R4 (rot=270): explicit angle=90 -> convert to stored 0 (drawn 90)
                    {"reference": "R4", "property": "Reference", "x": 185, "y": 60, "angle": 90},
                    # Q1 (rot=270, mirror y): explicit angle=0 -> stored 90, eff left
                    {"reference": "Q1", "property": "Reference", "x": 102, "y": 115, "angle": 0},
                ],
            }
        )
        assert r["success"] is True
        assert r["applied_count"] == 4
        assert r["failed_count"] == 0

        by_key = {(item["reference"], item["property"]): item for item in r["applied"]}
        assert by_key[("R2", "Reference")]["stored_angle"] == 90
        assert by_key[("R2", "Reference")]["drawn_angle"] == 0
        assert by_key[("R2", "Reference")]["effective_justify"] == {
            "horizontal": "right",
            "vertical": "top",
        }
        assert by_key[("R2", "Value")]["stored_angle"] == 90
        assert by_key[("R2", "Value")]["drawn_angle"] == 0
        assert by_key[("R4", "Reference")]["stored_angle"] == 0
        assert by_key[("R4", "Reference")]["drawn_angle"] == 90
        assert by_key[("Q1", "Reference")]["stored_angle"] == 90
        assert by_key[("Q1", "Reference")]["drawn_angle"] == 0
        assert by_key[("Q1", "Reference")]["effective_justify"] == {
            "horizontal": "left",
            "vertical": "center",
        }

        content = f.read_text(encoding="utf-8")
        r2_block, _, _ = _find_placed_symbol_block(content, "R2")
        assert _extract_property_position(r2_block, "Reference")["angle"] == 90.0
        assert _extract_property_position(r2_block, "Value")["angle"] == 90.0
        r4_block, _, _ = _find_placed_symbol_block(content, "R4")
        assert _extract_property_position(r4_block, "Reference")["angle"] == 0.0


AUTOPLACE_ROTATED_SCH = """(kicad_sch (version 20250114) (paper "A4")
  (lib_symbols
    (symbol "Device:R"
      (symbol "R_0_1"
        (rectangle (start -1.016 -2.54) (end 1.016 2.54)))
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
        (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))
  )
  (symbol (lib_id "Device:R") (at 50.8 50.8 0) (unit 1) (uuid "10000001")
    (property "Reference" "R1" (at 50.8 50.8 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at 50.8 50.8 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:R") (at 101.6 50.8 90) (unit 1) (uuid "10000002")
    (property "Reference" "R2" (at 101.6 50.8 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "4.7k" (at 101.6 50.8 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:R") (at 152.4 50.8 180) (unit 1) (uuid "10000003")
    (property "Reference" "R3" (at 152.4 50.8 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "1k" (at 152.4 50.8 0)
      (effects (font (size 1.27 1.27))))
  )
  (symbol (lib_id "Device:R") (at 203.2 50.8 270) (unit 1) (uuid "10000004")
    (property "Reference" "R4" (at 203.2 50.8 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "22k" (at 203.2 50.8 0)
      (effects (font (size 1.27 1.27))))
  )
)
"""


class TestAutoplaceRotatedSymbols:
    def test_autoplace_orients_fields_horizontally_on_all_rotations(self, tmp_path):
        f = tmp_path / "autoplace_rot.kicad_sch"
        f.write_text(AUTOPLACE_ROTATED_SCH, encoding="utf-8")
        c = SchematicFieldLayoutCommands()
        r = c.autoplace_schematic_fields({"schematicPath": str(f)})
        assert r["success"] is True, r
        assert r["updated_count"] == 8
        assert r["failed_count"] == 0

        content = f.read_text(encoding="utf-8")
        for ref, sym_rot, expected_stored in (
            ("R1", 0, 0),
            ("R2", 90, 90),
            ("R3", 180, 0),
            ("R4", 270, 90),
        ):
            block, _, _ = _find_placed_symbol_block(content, ref)
            assert block is not None
            for prop in ("Reference", "Value"):
                pos = _extract_property_position(block, prop)
                assert pos is not None
                assert pos["angle"] == float(expected_stored), (
                    f"{ref}.{prop} on {sym_rot}° symbol stored {pos['angle']} instead of "
                    f"{expected_stored}"
                )
                assert stored_angle_to_drawn_angle(pos["angle"], sym_rot) == 0

        # Independent check via schematic_legibility: all fields must be legible and horizontal.
        leg = check_legibility(f)
        assert leg["total"] == 0, leg


class TestAngleValidation:
    """Tests for field angle multiple-of-90 validation."""

    def test_is_multiple_of_90(self):
        for valid in (0, 90, 180, 270, 360, -90, -180, -270, 90.0, 0.0):
            assert is_multiple_of_90(valid) is True, f"Expected {valid} to be valid multiple of 90"

        for invalid in (
            45,
            30,
            12.5,
            -45,
            89.0,
            91.0,
            False,
            True,
            float("inf"),
            float("-inf"),
            float("nan"),
            "abc",
            None,
            object(),
        ):
            assert is_multiple_of_90(invalid) is False, f"Expected {invalid} to be rejected"

    def test_set_schematic_property_position_rejects_non_multiple_of_90(self, tmp_path):
        f = tmp_path / "test_angle.kicad_sch"
        f.write_text(MINIMAL_SCH, encoding="utf-8")
        c = SchematicFieldLayoutCommands()
        res = c.set_schematic_property_position(
            {
                "schematicPath": str(f),
                "reference": "R1",
                "property": "Reference",
                "x": 100.0,
                "y": 50.0,
                "angle": 45,
            }
        )
        assert res["success"] is False
        assert "multiple of 90 degrees" in res["message"]

    def test_batch_set_schematic_property_positions_rejects_non_multiple_of_90(self, tmp_path):
        f = tmp_path / "test_batch_angle.kicad_sch"
        f.write_text(MINIMAL_SCH, encoding="utf-8")
        c = SchematicFieldLayoutCommands()
        res = c.batch_set_schematic_property_positions(
            {
                "schematicPath": str(f),
                "updates": [
                    {
                        "reference": "R1",
                        "property": "Reference",
                        "x": 100.0,
                        "y": 50.0,
                        "angle": 45,
                    }
                ],
            }
        )
        assert res["success"] is False
        assert res["failed_count"] == 1
        assert "multiple of 90 degrees" in res["failed"][0]["reason"]
