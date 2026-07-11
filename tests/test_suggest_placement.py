"""Tests for suggest_placement (connectivity-driven placement optimizer).

The optimizer's geometry is exercised with lightweight fakes for KiCad's
footprint/pad/board objects, plus numeric stubs for the handful of pcbnew
helpers it calls (ToMM / FromMM / VECTOR2I). conftest.py already installs a
MagicMock `pcbnew`; here we give those three helpers real numeric behaviour.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import pcbnew  # noqa: E402  (MagicMock module from conftest)

pcbnew.ToMM = lambda nm: nm / 1_000_000.0
pcbnew.FromMM = lambda mm: int(round(mm * 1_000_000.0))


class _V2I:
    def __init__(self, x, y):
        self.x, self.y = x, y


pcbnew.VECTOR2I = _V2I

from kicad_mcp.commands.placement_optimizer import PlacementOptimizerCommands as PO  # noqa: E402


# ── Fakes ────────────────────────────────────────────────────────────────
class Pad:
    def __init__(self, code, lx_mm, ly_mm):
        self._code, self._lx, self._ly, self._fp = code, lx_mm, ly_mm, None

    def GetNetCode(self):
        return self._code

    def GetPosition(self):
        a = math.radians(self._fp._angle)
        c, s = math.cos(a), math.sin(a)
        wx = self._lx * c - self._ly * s
        wy = self._lx * s + self._ly * c
        return _V2I(int((self._fp._x + wx) * 1e6), int((self._fp._y + wy) * 1e6))


class FP:
    def __init__(self, ref, x, y, pads, hw=1.0, hh=0.5, locked=False, angle=0.0):
        self.ref, self._x, self._y = ref, x, y
        self._pads, self.hw, self.hh = pads, hw, hh
        self._locked, self._angle = locked, angle
        for p in pads:
            p._fp = self

    def GetReference(self):
        return self.ref

    def GetPosition(self):
        return _V2I(int(self._x * 1e6), int(self._y * 1e6))

    def SetPosition(self, v):
        self._x, self._y = v.x / 1e6, v.y / 1e6

    def GetOrientationDegrees(self):
        return self._angle

    def SetOrientationDegrees(self, a):
        self._angle = a

    def Pads(self):
        return self._pads

    def GetPadCount(self):
        return len(self._pads)

    def IsLocked(self):
        return self._locked


class _Net:
    def __init__(self, n):
        self._n = n

    def GetNetname(self):
        return self._n


class _NetInfo:
    def __init__(self, m):
        self._m = m

    def NetsByNetcode(self):
        return self._m


class Board:
    def __init__(self, fps, nets):
        self._fps = fps
        self._ni = _NetInfo({c: _Net(n) for c, n in nets.items()})

    def GetFootprints(self):
        return self._fps

    def GetNetInfo(self):
        return self._ni

    def GetBoardEdgesBoundingBox(self):
        class B:
            GetWidth = lambda s: 1  # noqa: E731
            GetHeight = lambda s: 1  # noqa: E731
            GetLeft = lambda s: 0  # noqa: E731
            GetTop = lambda s: 0  # noqa: E731
            GetRight = lambda s: int(60e6)  # noqa: E731
            GetBottom = lambda s: int(40e6)  # noqa: E731

        return B()


class Host(PO):
    def __init__(self, board):
        self.board = board

    def _footprint_courtyard_bbox(self, fp, override):
        return (fp._x - fp.hw, fp._y - fp.hh, fp._x + fp.hw, fp._y + fp.hh)


def _two_converters_board():
    fps = [
        FP("U1", 10, 20, [Pad(1, -1, 0), Pad(10, 1, 0), Pad(99, 0, 0.5)], hw=2, hh=2),
        FP("U2", 50, 20, [Pad(1, -1, 0), Pad(11, 1, 0), Pad(99, 0, 0.5)], hw=2, hh=2),
        FP("R1", 48, 5, [Pad(10, -0.5, 0), Pad(99, 0.5, 0)]),
        FP("C1", 52, 5, [Pad(1, -0.5, 0), Pad(99, 0.5, 0)]),
        FP("R2", 12, 35, [Pad(11, -0.5, 0), Pad(99, 0.5, 0)]),
        FP("C2", 8, 35, [Pad(1, -0.5, 0), Pad(99, 0.5, 0)]),
    ]
    nets = {1: "VBAT", 10: "U1_FB", 11: "U2_FB", 99: "GND"}
    return Host(Board(fps, nets))


# ── Tests ────────────────────────────────────────────────────────────────
def test_no_board_returns_error():
    res = Host(None).suggest_placement({})
    assert res["success"] is False
    assert "No board" in res["message"]


def test_fewer_than_two_movable_returns_error():
    fps = [FP("U1", 10, 20, [Pad(99, 0, 0.5)], hw=2, hh=2)]
    res = Host(Board(fps, {99: "GND"})).suggest_placement({})
    assert res["success"] is False
    assert "optimize" in res["message"].lower()


def test_optimize_shortens_wire_length_without_overlaps():
    res = _two_converters_board().suggest_placement({"iterations": 300, "apply": False})
    assert res["success"] is True
    s = res["score"]
    assert s["hpwl_after_mm"] < s["hpwl_before_mm"]
    assert s["overlaps_after"] == 0
    # passives migrate next to their IC
    u1 = res["proposals"].get("U1", [10, 20, 0])
    r1 = res["proposals"]["R1"]
    assert math.hypot(r1[0] - u1[0], r1[1] - u1[1]) < 20


def test_dry_run_does_not_move_parts():
    host = _two_converters_board()
    before = host.board.GetFootprints()[2]._x  # R1 x
    host.suggest_placement({"iterations": 100, "apply": False})
    assert host.board.GetFootprints()[2]._x == before


def test_scoped_bounds_limits_movers_and_stays_in_box():
    host = _two_converters_board()
    res = host.suggest_placement({
        "refs": ["R1", "C1"],
        "bounds": {"x1": 13, "y1": 15, "x2": 20, "y2": 25, "unit": "mm"},
        "iterations": 300,
    })
    assert set(res["proposals"]) == {"R1", "C1"}
    for r in ("R1", "C1"):
        x, y, _ = res["proposals"][r]
        assert 12 <= x <= 21 and 14 <= y <= 26


def test_deterministic_across_runs():
    a = _two_converters_board().suggest_placement({"iterations": 200})
    b = _two_converters_board().suggest_placement({"iterations": 200})
    assert a["proposals"] == b["proposals"]


def test_cluster_snap_aligns_rows_and_columns():
    def mk(x, y):
        return {"x": x, "y": y, "cox": 0.0, "coy": 0.0, "locked": False}

    parts = [mk(5.0, 10.3), mk(9.8, 9.7), mk(15.1, 10.1),
             mk(5.2, 20.2), mk(10.1, 19.8), mk(14.9, 20.3)]
    PO._opt_cluster_snap(parts, "y", 1.5)
    assert len(set(round(p["y"], 3) for p in parts)) == 2   # two row lines
    PO._opt_cluster_snap(parts, "x", 1.5)
    assert len(set(round(p["x"], 3) for p in parts)) == 3   # three column lines


def test_resolve_outline_unit_conversion_includes_mil():
    host = Host(None)
    mm = host._opt_resolve_outline({"x1": 0, "y1": 0, "x2": 10, "y2": 10, "unit": "mm"})
    mil = host._opt_resolve_outline({"x1": 0, "y1": 0, "x2": 1000, "y2": 1000, "unit": "mil"})
    inch = host._opt_resolve_outline({"x1": 0, "y1": 0, "x2": 1, "y2": 1, "unit": "inch"})
    assert mm == (0, 0, 10, 10)
    assert mil == (0, 0, 25.4, 25.4)       # 1000 mil = 25.4 mm
    assert inch == (0, 0, 25.4, 25.4)      # 1 inch = 25.4 mm
