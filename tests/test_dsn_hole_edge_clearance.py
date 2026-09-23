"""Regression tests: autoroute ignored the copper-to-edge clearance around board holes.

KiCad exports internal Edge.Cuts circles (mounting holes, cut-outs) to the Specctra DSN
as plain structure keepouts. Freerouting keeps routes away from those by the ordinary
track clearance only (0.2 mm by default), not by the board's copper-to-edge clearance
(0.5 mm by default), so autorouted tracks landed ~0.2 mm from mounting holes and DRC
flagged every one. Freerouting's own ``router.copper_to_edge_clearance_um`` setting
does not change this (identical SES output). The exported DSN now grows circular
keepouts by the difference.
"""

import math
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.freerouting import FreeroutingCommands, _grow_hole_keepouts  # noqa: E402


def _circle(cx: float, cy: float, r: float, n: int = 16) -> str:
    pts = [
        (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    pts.append(pts[0])  # KiCad closes the ring
    return "  ".join(f"{x:.1f} {y:.1f}" for x, y in pts)


def _keepout(coords: str) -> str:
    return f'    (keepout "" (polygon signal 0  {coords}))\n'


def _dsn(*keepouts: str, unit: str = "um") -> str:
    return (
        "(pcb board\n  (parser)\n  (resolution um 10)\n"
        f"  (unit {unit})\n  (structure\n"
        + "".join(keepouts)
        + "    (rule\n      (width 300)\n      (clearance 200)\n    )\n  )\n)\n"
    )


def _min_edge_distance(text: str, cx: float, cy: float) -> float:
    nums = [float(v) for v in text.split("polygon signal 0")[1].split(")")[0].split()]
    pts = list(zip(nums[0::2], nums[1::2]))
    dist = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2  # edge midpoints are the closest points
        dist.append(math.hypot(mx - cx, my - cy))
    return min(dist)


def test_hole_keepout_edges_clear_the_grown_radius() -> None:
    out = _grow_hole_keepouts(_dsn(_keepout(_circle(125000, -112000, 1350))), 300)
    # every polygon edge (not just the vertices) must sit at least r + grow from the centre
    assert _min_edge_distance(out, 125000, -112000) >= 1650 - 1


def test_rectangular_keepout_is_untouched() -> None:
    rect = "0 0  5000 0  5000 5000  0 5000  0 0"
    dsn = _dsn(_keepout(rect))
    assert _grow_hole_keepouts(dsn, 300) == dsn


def test_no_growth_when_edge_clearance_is_not_larger() -> None:
    dsn = _dsn(_keepout(_circle(0, 0, 1000)))
    assert _grow_hole_keepouts(dsn, 0) == dsn
    assert _grow_hole_keepouts(dsn, -50) == dsn


def _cmds(edge_clearance_nm: int) -> FreeroutingCommands:
    board = MagicMock()
    board.GetDesignSettings.return_value.m_CopperEdgeClearance = edge_clearance_nm
    return FreeroutingCommands(board=board)


def test_apply_uses_board_edge_clearance_minus_track_clearance(tmp_path: Any) -> None:
    dsn = tmp_path / "board.dsn"
    dsn.write_text(_dsn(_keepout(_circle(0, 0, 1350))))
    _cmds(500_000)._apply_edge_clearance(str(dsn))  # 0.5 mm edge, 0.2 mm track clearance
    assert _min_edge_distance(dsn.read_text(), 0, 0) >= 1650 - 1


def test_apply_leaves_non_um_dsn_alone(tmp_path: Any) -> None:
    dsn = tmp_path / "board.dsn"
    original = _dsn(_keepout(_circle(0, 0, 53)), unit="mil")
    dsn.write_text(original)
    _cmds(500_000)._apply_edge_clearance(str(dsn))
    assert dsn.read_text() == original
