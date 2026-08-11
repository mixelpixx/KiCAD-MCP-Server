"""Tests for python/utils/kicad_dru.py — the pure text-transform and
persistence layer behind the ``set_layer_constraints`` tool.

``.kicad_dru`` custom-rules files have no pcbnew SWIG API at all (confirmed:
no ``DRC_RULE``/rules-parsing class in the bindings), so this is pure text
manipulation, verified headless. The rule syntax itself (constraint types,
layer selector quoting) was separately verified against real KiCad 10 via
``kicad-cli pcb drc`` against a real demo board with a deliberately strict
rule — violations correctly cited the rule by name
(``rule 'mcp_layer_constraint_F.Cu' clearance 5.0000 mm; actual ...``) for
all four constraint types (track_width, clearance, via_diameter, hole_size).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from utils.kicad_dru import (  # noqa: E402
    apply_layer_constraint_rule,
    build_layer_constraint_rule,
    persist_layer_constraint_rule,
    resolve_dru_path,
    rule_name_for_layer,
)

# --- resolve_dru_path -------------------------------------------------------


def test_resolve_dru_path_from_kicad_pcb():
    assert resolve_dru_path("/proj/board.kicad_pcb") == str(Path("/proj/board.kicad_dru"))


def test_resolve_dru_path_none_when_no_board_path():
    assert resolve_dru_path(None) is None
    assert resolve_dru_path("") is None


def test_resolve_dru_path_none_for_non_pcb_extension():
    assert resolve_dru_path("/proj/board.kicad_sch") is None


# --- rule_name_for_layer ----------------------------------------------------


def test_rule_name_is_deterministic_per_layer():
    assert rule_name_for_layer("F.Cu") == rule_name_for_layer("F.Cu")
    assert rule_name_for_layer("F.Cu") != rule_name_for_layer("B.Cu")


# --- build_layer_constraint_rule --------------------------------------------


def test_build_rule_includes_only_provided_constraints():
    text = build_layer_constraint_rule("F.Cu", min_track_width=0.2, min_clearance=0.15)
    assert 'rule "mcp_layer_constraint_F.Cu"' in text
    assert '(layer "F.Cu")' in text
    assert "(constraint track_width (min 0.2mm))" in text
    assert "(constraint clearance (min 0.15mm))" in text
    assert "via_diameter" not in text
    assert "hole_size" not in text


def test_build_rule_all_four_constraints():
    text = build_layer_constraint_rule(
        "B.Cu",
        min_track_width=0.25,
        min_clearance=0.2,
        min_via_diameter=0.5,
        min_via_drill=0.3,
    )
    assert "(constraint track_width (min 0.25mm))" in text
    assert "(constraint clearance (min 0.2mm))" in text
    assert "(constraint via_diameter (min 0.5mm))" in text
    assert "(constraint hole_size (min 0.3mm))" in text


def test_build_rule_is_balanced_parens():
    text = build_layer_constraint_rule("F.Cu", min_track_width=0.2)
    assert text.count("(") == text.count(")")


# --- apply_layer_constraint_rule --------------------------------------------


def test_apply_creates_version_header_when_empty():
    rule = build_layer_constraint_rule("F.Cu", min_track_width=0.2)
    result = apply_layer_constraint_rule("", "mcp_layer_constraint_F.Cu", rule)
    assert result.startswith("(version 1)")
    assert rule in result


def test_apply_appends_when_rule_absent():
    existing = '(version 1)\n\n(rule "other_rule"\n  (layer "B.Cu")\n  (constraint clearance (min 0.3mm))\n)\n'
    rule = build_layer_constraint_rule("F.Cu", min_track_width=0.2)
    result = apply_layer_constraint_rule(existing, "mcp_layer_constraint_F.Cu", rule)
    assert 'rule "other_rule"' in result  # untouched
    assert rule in result
    assert result.count("(rule ") == 2


def test_apply_replaces_existing_rule_in_place():
    old_rule = build_layer_constraint_rule("F.Cu", min_track_width=0.1)
    existing = f"(version 1)\n\n{old_rule}\n"
    new_rule = build_layer_constraint_rule("F.Cu", min_track_width=0.3)
    result = apply_layer_constraint_rule(existing, "mcp_layer_constraint_F.Cu", new_rule)
    assert "0.1mm" not in result
    assert "0.3mm" in result
    assert result.count("(rule ") == 1  # replaced, not duplicated


def test_apply_replace_preserves_unrelated_rules_before_and_after():
    before_rule = '(rule "before_rule"\n  (layer "B.Cu")\n  (constraint clearance (min 0.3mm))\n)'
    after_rule = '(rule "after_rule"\n  (layer "In1.Cu")\n  (constraint clearance (min 0.4mm))\n)'
    old_rule = build_layer_constraint_rule("F.Cu", min_track_width=0.1)
    existing = f"(version 1)\n\n{before_rule}\n\n{old_rule}\n\n{after_rule}\n"

    new_rule = build_layer_constraint_rule("F.Cu", min_track_width=0.3)
    result = apply_layer_constraint_rule(existing, "mcp_layer_constraint_F.Cu", new_rule)

    assert before_rule in result
    assert after_rule in result
    assert new_rule in result
    assert old_rule not in result
    assert result.count("(rule ") == 3


def test_apply_is_idempotent():
    rule = build_layer_constraint_rule("F.Cu", min_track_width=0.2, min_clearance=0.15)
    once = apply_layer_constraint_rule("(version 1)\n", "mcp_layer_constraint_F.Cu", rule)
    twice = apply_layer_constraint_rule(once, "mcp_layer_constraint_F.Cu", rule)
    assert once == twice
    assert twice.count("(rule ") == 1


def test_apply_different_layers_produce_separate_rules():
    rule_f = build_layer_constraint_rule("F.Cu", min_track_width=0.2)
    rule_b = build_layer_constraint_rule("B.Cu", min_track_width=0.3)
    result = apply_layer_constraint_rule("(version 1)\n", "mcp_layer_constraint_F.Cu", rule_f)
    result = apply_layer_constraint_rule(result, "mcp_layer_constraint_B.Cu", rule_b)
    assert rule_f in result
    assert rule_b in result
    assert result.count("(rule ") == 2


# --- persist_layer_constraint_rule ------------------------------------------


def test_persist_creates_file_when_absent(tmp_path):
    dru = tmp_path / "proj.kicad_dru"
    rule = build_layer_constraint_rule("F.Cu", min_track_width=0.2)
    result = persist_layer_constraint_rule(str(dru), "mcp_layer_constraint_F.Cu", rule)
    assert result["persisted"] is True
    assert result["druFile"] == str(dru)
    assert dru.exists()
    assert rule in dru.read_text(encoding="utf-8")


def test_persist_updates_existing_file_preserving_other_content(tmp_path):
    dru = tmp_path / "proj.kicad_dru"
    dru.write_text(
        '(version 1)\n\n(rule "keep_me"\n  (layer "B.Cu")\n  (constraint clearance (min 0.3mm))\n)\n'
    )
    rule = build_layer_constraint_rule("F.Cu", min_track_width=0.2)
    result = persist_layer_constraint_rule(str(dru), "mcp_layer_constraint_F.Cu", rule)
    assert result["persisted"] is True
    content = dru.read_text(encoding="utf-8")
    assert 'rule "keep_me"' in content
    assert rule in content


def test_persist_writes_atomically_leaving_no_temp_file(tmp_path):
    dru = tmp_path / "proj.kicad_dru"
    rule = build_layer_constraint_rule("F.Cu", min_track_width=0.2)
    persist_layer_constraint_rule(str(dru), "mcp_layer_constraint_F.Cu", rule)
    assert [p.name for p in tmp_path.iterdir()] == ["proj.kicad_dru"]


def test_persist_warns_when_no_path():
    result = persist_layer_constraint_rule(None, "mcp_layer_constraint_F.Cu", "(rule ...)")
    assert result["persisted"] is False
    assert "warning" in result


def test_persist_warns_when_path_is_a_directory(tmp_path):
    result = persist_layer_constraint_rule(str(tmp_path), "mcp_layer_constraint_F.Cu", "(rule ...)")
    assert result["persisted"] is False
    assert str(tmp_path) in result["warning"]
