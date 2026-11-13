"""find_orphaned_wires counts sheet pins, hierarchical labels and junction T's as connections.

On a real 3-sheet design whose ERC reports no dangling wire, the root sheet
came back with 38 "orphaned" wires: every wire to a sheet pin. Pruning those
deleted live wires back through whole nets (93 on that sheet before the loop
ran out of things to remove).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_analysis import find_orphaned_wires  # noqa: E402

HEAD = '(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n  (uuid "11111111-1111-1111-1111-111111111111")\n  (paper "A4")\n  (lib_symbols)\n'


def _wire(x1, y1, x2, y2, n):
    return f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid "55555555-5555-5555-5555-5555555555{n:02d}"))\n'


def _write(tmp_path, body):
    f = tmp_path / "s.kicad_sch"
    f.write_text(HEAD + body + '  (sheet_instances (path "/" (page "1")))\n)\n')
    return f


def test_wire_to_a_sheet_pin_is_connected(tmp_path):
    body = (
        _wire(100, 100, 120, 100, 1)
        + '  (label "A" (at 100 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666601"))\n'
        + '  (sheet (at 120 90) (size 20 20) (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000)) (uuid "22222222-2222-2222-2222-222222222222")\n'
        + '    (property "Sheetname" "Sub" (at 120 89 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
        + '    (property "Sheetfile" "sub.kicad_sch" (at 120 111 0) (effects (font (size 1.27 1.27)) (justify left top)))\n'
        + '    (pin "A" input (at 120 100 180) (effects (font (size 1.27 1.27)) (justify left)) (uuid "66666666-6666-6666-6666-666666666602"))\n'
        + "  )\n"
    )
    assert find_orphaned_wires(_write(tmp_path, body))["count"] == 0


def test_wire_to_a_hierarchical_label_is_connected(tmp_path):
    body = (
        _wire(100, 100, 120, 100, 1)
        + '  (label "A" (at 100 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666601"))\n'
        + '  (hierarchical_label "A" (shape input) (at 120 100 0) (effects (font (size 1.27 1.27)) (justify left)) (uuid "66666666-6666-6666-6666-666666666603"))\n'
    )
    assert find_orphaned_wires(_write(tmp_path, body))["count"] == 0


def test_unsplit_tee_at_a_junction_is_connected(tmp_path):
    # Wire 2 ends on wire 1's interior at a junction: KiCad connects it.
    body = (
        _wire(100, 100, 120, 100, 1)
        + _wire(110, 100, 110, 120, 2)
        + '  (label "A" (at 100 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666601"))\n'
        + '  (label "A" (at 120 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666604"))\n'
        + '  (label "B" (at 110 120 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666605"))\n'
        + '  (junction (at 110 100) (diameter 0) (color 0 0 0 0) (uuid "66666666-6666-6666-6666-666666666606"))\n'
    )
    assert find_orphaned_wires(_write(tmp_path, body))["count"] == 0


def test_unsplit_tee_without_a_junction_is_still_dangling(tmp_path):
    # Without the junction KiCad leaves the T open, so the end really dangles.
    body = (
        _wire(100, 100, 120, 100, 1)
        + _wire(110, 100, 110, 120, 2)
        + '  (label "A" (at 100 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666601"))\n'
        + '  (label "A" (at 120 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666604"))\n'
        + '  (label "B" (at 110 120 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666605"))\n'
    )
    r = find_orphaned_wires(_write(tmp_path, body))
    assert r["count"] == 1
    assert r["orphaned_wires"][0]["dangling_ends"] == [{"x": 110.0, "y": 100.0}]


def test_a_truly_dangling_wire_is_still_reported(tmp_path):
    body = _wire(100, 100, 120, 100, 1)
    assert find_orphaned_wires(_write(tmp_path, body))["count"] == 1


def test_wire_to_a_bus_entry_is_connected(tmp_path):
    # A wire ending on a bus_entry endpoint connects to the bus and is not orphaned.
    body = (
        _wire(100, 100, 120, 100, 1)
        + '  (label "A" (at 100 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666601"))\n'
        + '  (bus_entry (at 120 100) (size 2.54 2.54) (stroke (width 0.1524) (type solid)) (uuid "66666666-6666-6666-6666-666666666607"))\n'
    )
    assert find_orphaned_wires(_write(tmp_path, body))["count"] == 0


def test_wire_with_interior_label_is_connected(tmp_path):
    # When a net label is placed along a wire lead extending from an anchored
    # endpoint (pin or label), the wire serves as the connection and is not orphaned.
    body = (
        _wire(100, 100, 120, 100, 1)
        + '  (label "PIN" (at 100 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666601"))\n'
        + '  (label "NET" (at 110 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666608"))\n'
    )
    assert find_orphaned_wires(_write(tmp_path, body))["count"] == 0


def test_floating_wire_with_interior_label_is_still_reported(tmp_path):
    # A floating wire where neither endpoint connects to anything is still orphaned,
    # even if a label sits on its interior.
    body = (
        _wire(100, 100, 120, 100, 1)
        + '  (label "NET" (at 110 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "66666666-6666-6666-6666-666666666609"))\n'
    )
    r = find_orphaned_wires(_write(tmp_path, body))
    assert r["count"] == 1
    assert len(r["orphaned_wires"][0]["dangling_ends"]) == 2
