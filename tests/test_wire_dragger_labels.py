"""Tests for WireDragger dragging net labels along with a moved/rotated pin.

Regression guard: when a symbol is moved or rotated with wire-dragging enabled,
a net label sitting exactly on one of its pins used to be left behind while the
pin's wiring moved away.  The label would then detach from the pin's net and, if
another net's wire happened to occupy that coordinate, silently merge onto it
(e.g. a test-point label ending up on an adjacent power rail).  drag_wires must
now carry coincident net labels along so they stay attached.
"""

import sys
from pathlib import Path

from sexpdata import Symbol as S

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from kicad_mcp.commands.wire_dragger import WireDragger  # noqa: E402


def _sch_with_label_on_pin(label_token="label"):
    """A wire from (100,100)->(100,90) plus a net label at the (100,100) pin."""
    return [
        S("kicad_sch"),
        [S("wire"), [S("pts"), [S("xy"), 100.0, 100.0], [S("xy"), 100.0, 90.0]]],
        [S(label_token), "DRAIN_TP", [S("at"), 100.0, 100.0, 0]],
    ]


class TestLabelDragOnRotate:
    def test_label_follows_moved_pin(self):
        sch = _sch_with_label_on_pin()
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})
        assert summary["labels_moved"] == 1
        label = next(i for i in sch if isinstance(i, list) and str(i[0]) == "label")
        at = next(p for p in label if isinstance(p, list) and str(p[0]) == "at")
        assert (at[1], at[2]) == (110.0, 100.0)

    def test_global_and_hierarchical_labels_also_move(self):
        for token in ("global_label", "hierarchical_label"):
            sch = _sch_with_label_on_pin(token)
            summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})
            assert summary["labels_moved"] == 1, token

    def test_label_not_on_pin_is_untouched(self):
        sch = [
            S("kicad_sch"),
            [S("wire"), [S("pts"), [S("xy"), 100.0, 100.0], [S("xy"), 100.0, 90.0]]],
            [S("label"), "OTHER", [S("at"), 50.0, 50.0, 0]],
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})
        assert summary["labels_moved"] == 0
        label = next(i for i in sch if isinstance(i, list) and str(i[0]) == "label")
        at = next(p for p in label if isinstance(p, list) and str(p[0]) == "at")
        assert (at[1], at[2]) == (50.0, 50.0)

    def test_no_labels_reported_when_none_present(self):
        sch = [
            S("kicad_sch"),
            [S("wire"), [S("pts"), [S("xy"), 100.0, 100.0], [S("xy"), 100.0, 90.0]]],
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})
        assert summary["labels_moved"] == 0
