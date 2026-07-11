"""Tests for suggest_schematic_declutter's pure geometry, planner, and the
raw-text apply path (including justify injection when KiCad omitted the token).

These cover the label re-orientation logic without needing a live KiCad /
kicad-skip environment — the geometry lives in module-level pure functions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.commands.schematic_declutter import (  # noqa: E402
    _bbox_overlaps,
    _inject_justify_into_effects,
    _justify_for_angle,
    _label_bbox,
    _reorient_label_in_text,
    plan_label_declutter,
)


def test_label_bbox_orientation_flips_text_side():
    b0 = _label_bbox(10, 10, 0, "VBUS")     # text extends +x
    b180 = _label_bbox(10, 10, 180, "VBUS")  # text extends -x
    assert b0["x_min"] == 10 and b0["x_max"] > 10
    assert b180["x_max"] == 10 and b180["x_min"] < 10


def test_justify_for_angle():
    assert _justify_for_angle(0) == "left"
    assert _justify_for_angle(90) == "left"
    assert _justify_for_angle(180) == "right"
    assert _justify_for_angle(270) == "right"


def test_plan_reduces_overlap_between_piled_labels():
    labels = [
        {"name": "NET_A", "x": 50.0, "y": 30.0, "angle": 0, "type": "net"},
        {"name": "NET_B", "x": 51.0, "y": 30.0, "angle": 0, "type": "net"},
        {"name": "NET_C", "x": 50.5, "y": 30.0, "angle": 0, "type": "net"},
    ]
    props, before, after = plan_label_declutter(labels, [], margin=0.3)
    assert before > 0
    assert after < before
    assert all(p["to_angle"] in (0, 90, 180, 270) for p in props)


def test_plan_flips_label_away_from_body():
    # Label on a wire stub just left of a body; angle 0 sends text INTO the
    # body, angle 180 points it away into free space.
    lab = [{"name": "SDA", "x": 48.0, "y": 20.0, "angle": 0, "type": "net"}]
    body = [{"x_min": 50.0, "y_min": 18.0, "x_max": 58.0, "y_max": 22.0}]
    props, before, after = plan_label_declutter(lab, body, margin=0.2)
    assert before == 1 and after == 0
    assert props and props[0]["to_angle"] == 180
    assert props[0]["to_justify"] == "right"


def test_apply_rewrites_angle_and_justify_keeps_anchor():
    sch = (
        '(kicad_sch\n'
        '  (label "SDA" (at 48.0 20.0 0)\n'
        '    (effects (font (size 1.27 1.27)) (justify left))\n'
        '    (uuid "aaaa")\n'
        '  )\n'
        '  (global_label "VBUS" (at 48.0 20.0 0)\n'   # same anchor, other name
        '    (effects (font (size 1.27 1.27)) (justify left))\n'
        '    (uuid "bbbb")\n'
        '  )\n'
        ')\n'
    )
    new, changed = _reorient_label_in_text(sch, "SDA", 48.0, 20.0, 180, "right")
    assert changed
    assert "(at 48.0 20.0 180)" in new            # angle rewritten, anchor kept
    sda, _, vbus = new.partition("global_label")
    assert "(justify right)" in sda               # SDA flipped
    assert "(at 48.0 20.0 0)" in vbus              # VBUS untouched
    assert "(justify left)" in vbus               # VBUS justify untouched


def test_apply_injects_justify_when_absent():
    # KiCad omits (justify) for default-left labels. A 180 reorient must INJECT
    # one, else the text would render pointing the wrong way.
    sch = (
        '(kicad_sch\n'
        '  (label "CLK" (at 30.0 40.0 0)\n'
        '    (effects (font (size 1.27 1.27)))\n'    # <-- no justify token
        '    (uuid "cccc")\n'
        '  )\n'
        ')\n'
    )
    new, changed = _reorient_label_in_text(sch, "CLK", 30.0, 40.0, 180, "right")
    assert changed
    assert "(at 30.0 40.0 180)" in new
    assert "(justify right)" in new                # injected
    # justify must live inside the effects group
    assert "(font (size 1.27 1.27)) (justify right)" in new


def test_inject_justify_into_effects_paren_matched():
    block = '(label "X" (at 0 0 0) (effects (font (size 1.27 1.27))) (uuid "z"))'
    out = _inject_justify_into_effects(block, "right")
    assert out == '(label "X" (at 0 0 0) (effects (font (size 1.27 1.27)) (justify right)) (uuid "z"))'


def test_inject_justify_noop_without_effects():
    block = '(label "X" (at 0 0 0) (uuid "z"))'
    assert _inject_justify_into_effects(block, "right") == block


def test_bbox_overlaps_basic():
    a = {"x_min": 0, "y_min": 0, "x_max": 2, "y_max": 2}
    b = {"x_min": 1, "y_min": 1, "x_max": 3, "y_max": 3}
    c = {"x_min": 5, "y_min": 5, "x_max": 6, "y_max": 6}
    assert _bbox_overlaps(a, b)
    assert not _bbox_overlaps(a, c)
