"""Tests for keeping dragged routing orthogonal and no-connect flags attached.

Dragging a symbol used to move only the wire endpoint that touched a pin. A
trace routed pin -> corner -> corner -> pin is a chain of separate two-point
segments, so the first segment came out diagonal and its bend landed off-grid —
eeschema then reported endpoint_off_grid on a trace the user never touched.
A no-connect flag on a moved pin stayed behind the same way, turning into a
dangling flag plus an "unconnected pin" on the symbol's new location.

drag_wires must now carry the neighbouring bend along with the pin and move
no-connect flags with it, while refusing to disturb corners that something else
holds in place.
"""

import sys
from pathlib import Path

from sexpdata import Symbol as S

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from commands.wire_dragger import WireDragger  # noqa: E402


def _wire(x1, y1, x2, y2):
    return [S("wire"), [S("pts"), [S("xy"), x1, y1], [S("xy"), x2, y2]]]


def _coords(sch):
    """All wire segments as ((x1,y1),(x2,y2)) tuples, in file order."""
    return [
        WireDragger._wire_endpoints(item)
        for item in sch
        if WireDragger._wire_endpoints(item) is not None
    ]


class TestNoConnectFlags:
    def test_no_connect_follows_moved_pin(self):
        sch = [
            S("kicad_sch"),
            [S("no_connect"), [S("at"), 100.0, 100.0]],
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (100.0, 90.0)})
        assert summary["no_connects_moved"] == 1
        nc = next(i for i in sch if isinstance(i, list) and str(i[0]) == "no_connect")
        at = next(p for p in nc if isinstance(p, list) and str(p[0]) == "at")
        assert (at[1], at[2]) == (100.0, 90.0)

    def test_no_connect_elsewhere_is_untouched(self):
        sch = [
            S("kicad_sch"),
            [S("no_connect"), [S("at"), 50.0, 50.0]],
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (100.0, 90.0)})
        assert summary["no_connects_moved"] == 0
        nc = next(i for i in sch if isinstance(i, list) and str(i[0]) == "no_connect")
        at = next(p for p in nc if isinstance(p, list) and str(p[0]) == "at")
        assert (at[1], at[2]) == (50.0, 50.0)


class TestOrthogonality:
    def test_corner_follows_the_pin(self):
        # Pin at (100,100) -> corner (100,80) -> away to (140,80).
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 100.0, 80.0),
            _wire(100.0, 80.0, 140.0, 80.0),
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})

        first, second = _coords(sch)
        # The vertical segment stays vertical: its corner moved to x=110.
        assert first == ((110.0, 100.0), (110.0, 80.0))
        # ...and the horizontal segment it feeds keeps its own axis.
        assert second == ((110.0, 80.0), (140.0, 80.0))
        assert summary["wires_straightened"] == 1
        assert summary["wires_left_diagonal"] == 0

    def test_cascade_through_two_corners(self):
        # Pin -> corner -> corner -> far end. Moving the pin diagonally has to
        # settle both bends, not just the first.
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 100.0, 80.0),
            _wire(100.0, 80.0, 140.0, 80.0),
            _wire(140.0, 80.0, 140.0, 60.0),
        ]
        WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 90.0)})

        for (x1, y1), (x2, y2) in _coords(sch):
            assert abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6, "segment left diagonal"

    def test_corner_held_by_a_junction_is_left_alone(self):
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 100.0, 80.0),
            _wire(100.0, 80.0, 140.0, 80.0),
            [S("junction"), [S("at"), 100.0, 80.0]],
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})

        first, second = _coords(sch)
        assert first == ((110.0, 100.0), (100.0, 80.0))  # left diagonal on purpose
        assert second == ((100.0, 80.0), (140.0, 80.0))  # junction untouched
        assert summary["wires_straightened"] == 0
        assert summary["wires_left_diagonal"] == 1

    def test_corner_held_by_a_stationary_pin_is_left_alone(self):
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 100.0, 80.0),
        ]
        summary = WireDragger.drag_wires(
            sch,
            {(100.0, 100.0): (110.0, 100.0)},
            anchor_points={(100.0, 80.0)},
        )
        assert summary["wires_straightened"] == 0
        assert summary["wires_left_diagonal"] == 1
        assert _coords(sch) == [((110.0, 100.0), (100.0, 80.0))]

    def test_fork_of_three_segments_is_left_alone(self):
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 100.0, 80.0),
            _wire(100.0, 80.0, 140.0, 80.0),
            _wire(100.0, 80.0, 60.0, 80.0),
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})
        assert summary["wires_straightened"] == 0
        assert summary["wires_left_diagonal"] == 1

    def test_label_at_the_corner_travels_with_it(self):
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 100.0, 80.0),
            [S("label"), "SDA", [S("at"), 100.0, 80.0, 0]],
        ]
        WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})
        label = next(i for i in sch if isinstance(i, list) and str(i[0]) == "label")
        at = next(p for p in label if isinstance(p, list) and str(p[0]) == "at")
        assert (at[1], at[2]) == (110.0, 80.0)

    def test_deliberately_diagonal_segment_is_preserved(self):
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 130.0, 70.0),
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)})
        assert summary["wires_straightened"] == 0
        assert _coords(sch) == [((110.0, 100.0), (130.0, 70.0))]

    def test_straighten_can_be_switched_off(self):
        sch = [
            S("kicad_sch"),
            _wire(100.0, 100.0, 100.0, 80.0),
        ]
        summary = WireDragger.drag_wires(sch, {(100.0, 100.0): (110.0, 100.0)}, straighten=False)
        assert summary["wires_straightened"] == 0
        assert _coords(sch) == [((110.0, 100.0), (100.0, 80.0))]
