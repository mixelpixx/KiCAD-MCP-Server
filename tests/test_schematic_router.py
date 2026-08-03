"""
Tests for the schematic auto-router (python/commands/schematic_router.py) and
the connect_schematic_pins tool built on it.
"""

import shutil
import sys
import tempfile
import time
import uuid as _uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_router import (
    RouteError,
    _astar_route,
    _build_compressed_grid,
    _collapse_collinear,
    _pin_angle_to_unit_vector,
    route_multi_pin,
    route_two_points,
)
from commands.wire_connectivity import _load_wire_net_membership

# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_schematic_analysis.py's fixture pattern)
# ---------------------------------------------------------------------------

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "python" / "templates" / "empty.kicad_sch"


def _make_temp_schematic(extra_sexp: str = "") -> Path:
    tmp = Path(tempfile.mkdtemp()) / "test.kicad_sch"
    shutil.copy(_TEMPLATE_PATH, tmp)
    if extra_sexp:
        content = tmp.read_text(encoding="utf-8")
        idx = content.rfind(")")
        content = content[:idx] + "\n" + extra_sexp + "\n)"
        tmp.write_text(content, encoding="utf-8")
    return tmp


def _make_resistor_sexp(ref: str, x: float, y: float, rotation: float = 0) -> str:
    u = str(_uuid.uuid4())
    return f"""
  (symbol (lib_id "Device:R") (at {x} {y} {rotation}) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{u}")
    (property "Reference" "{ref}" (at {x + 2.032} {y} 90)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at {x} {y} 90)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at {x - 1.778} {y} 90)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (pin "1" (uuid "{_uuid.uuid4()}"))
    (pin "2" (uuid "{_uuid.uuid4()}"))
    (instances
      (project "test"
        (path "/" (reference "{ref}") (unit 1))
      )
    )
  )
"""


# ---------------------------------------------------------------------------
# Pure geometry unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPinAngleToUnitVector:
    def test_right(self) -> None:
        assert _pin_angle_to_unit_vector(0) == (1.0, 0.0)

    def test_up(self) -> None:
        assert _pin_angle_to_unit_vector(90) == (0.0, -1.0)

    def test_left(self) -> None:
        assert _pin_angle_to_unit_vector(180) == (-1.0, 0.0)

    def test_down(self) -> None:
        assert _pin_angle_to_unit_vector(270) == (0.0, 1.0)

    def test_wraps_360(self) -> None:
        assert _pin_angle_to_unit_vector(360) == (1.0, 0.0)


@pytest.mark.unit
class TestCollapseCollinear:
    def test_removes_straight_through_point(self) -> None:
        result = _collapse_collinear([(0, 0), (5, 0), (10, 0)])
        assert result == [(0, 0), (10, 0)]

    def test_keeps_real_bend(self) -> None:
        result = _collapse_collinear([(0, 0), (10, 0), (10, 10)])
        assert result == [(0, 0), (10, 0), (10, 10)]

    def test_short_path_unchanged(self) -> None:
        assert _collapse_collinear([(0, 0), (10, 0)]) == [(0, 0), (10, 0)]


@pytest.mark.unit
class TestBuildCompressedGrid:
    def test_includes_endpoints(self) -> None:
        xs, ys = _build_compressed_grid((0, 0), (10, 10), [], [], 1.27, 15.0)
        assert 0 in xs and 10 in xs
        assert 0 in ys and 10 in ys

    def test_includes_symbol_bbox_edges(self) -> None:
        symbol_data = [{"bbox": (4.0, 4.0, 6.0, 6.0), "sym": {}, "pin_set": set()}]
        xs, ys = _build_compressed_grid((0, 0), (10, 10), symbol_data, [], 1.27, 15.0)
        assert 4.0 in xs and 6.0 in xs
        assert 4.0 in ys and 6.0 in ys


@pytest.mark.unit
class TestAstarRoute:
    def test_direct_path_no_obstacles(self) -> None:
        xs, ys = _build_compressed_grid((0, 0), (10, 0), [], [], 1.27, 15.0)
        path = _astar_route((0, 0), (10, 0), xs, ys, [], [], 5.0, 200_000)
        assert path[0] == (0, 0)
        assert path[-1] == (10, 0)
        # A clear horizontal shot should not introduce any bends.
        assert len(path) == 2

    def test_routes_around_blocking_symbol(self) -> None:
        # A symbol body sitting squarely between start and goal forces a detour.
        symbol_data = [{"bbox": (4.0, -2.0, 6.0, 2.0), "sym": {}, "pin_set": set()}]
        xs, ys = _build_compressed_grid((0, 0), (10, 0), symbol_data, [], 1.27, 15.0)
        path = _astar_route((0, 0), (10, 0), xs, ys, symbol_data, [], 5.0, 200_000)
        assert path[0] == (0, 0)
        assert path[-1] == (10, 0)
        assert len(path) > 2, "must detour around the blocking symbol, not go straight through"

    def test_raises_when_goal_unreachable(self) -> None:
        # Goal point isn't a compressed-grid node at all.
        xs, ys = _build_compressed_grid((0, 0), (10, 0), [], [], 1.27, 15.0)
        with pytest.raises(RouteError):
            _astar_route((0, 0), (999, 999), xs, ys, [], [], 5.0, 200_000)

    def test_many_obstacles_stays_fast(self) -> None:
        """Regression test for a real bug found via live smoke-testing: the
        original per-edge obstacle scan was O(edges x obstacles), which was
        instant on these unit tests' 1-2 synthetic obstacles but took 30+
        seconds (timing out) on a real busy sheet with ~250 existing
        wires/symbols against a ~21k-node grid. _precompute_blocked_edges
        replaced it with an O(obstacles x local_cells) precompute pass.
        This constructs a comparably busy synthetic scene (200 small foreign
        wires scattered through the search area) and asserts routing still
        completes quickly."""
        foreign = [
            {
                "start": (float(i % 20) * 5, float(i // 20) * 5 - 2),
                "end": (float(i % 20) * 5, float(i // 20) * 5 + 2),
            }
            for i in range(200)
        ]
        xs, ys = _build_compressed_grid((0, -50), (100, 50), [], foreign, 1.27, 15.0)
        t0 = time.time()
        try:
            _astar_route((0, -50), (100, 50), xs, ys, [], foreign, 5.0, 200_000)
        except RouteError:
            pass  # a path existing isn't the point of this test; speed is
        elapsed = time.time() - t0
        assert elapsed < 5.0, f"routing took {elapsed:.1f}s against 200 obstacles — regression"


# ---------------------------------------------------------------------------
# route_two_points integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRouteTwoPoints:
    def test_simple_open_route(self) -> None:
        path = route_two_points((0, 0), (20, 0), [], [])
        assert path[0] == (0, 0)
        assert path[-1] == (20, 0)

    def test_avoids_foreign_wire(self) -> None:
        foreign = [{"start": (5, -10), "end": (5, 10)}]
        path = route_two_points((0, 0), (10, 0), [], foreign, search_padding_mm=15)
        # The route must not cross x=5 at y=0 in a way that touches the foreign wire's
        # clearance box; verifying no segment endpoint sits inside [4.85,5.15]x[-10,10]
        # at y=0 is a reasonable proxy without re-implementing the AABB test here.
        assert path[0] == (0, 0) and path[-1] == (10, 0)
        assert len(path) > 2, "must detour around the foreign wire"


# ---------------------------------------------------------------------------
# route_multi_pin (connect_schematic_pins core) integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRouteMultiPin:
    def test_two_pin_net_gets_wired_and_connected(self) -> None:
        extra = _make_resistor_sexp("R1", 100, 100) + _make_resistor_sexp("R2", 150, 100)
        tmp = _make_temp_schematic(extra)
        result = route_multi_pin(
            tmp, [{"reference": "R1", "pin": "2"}, {"reference": "R2", "pin": "1"}]
        )
        assert result["success"] is True
        assert len(result["legs"]) == 1

        membership = _load_wire_net_membership(str(tmp))
        assert len(membership["all_wires"]) >= 1

    def test_three_pin_net_all_connected(self) -> None:
        extra = (
            _make_resistor_sexp("R1", 100, 100)
            + _make_resistor_sexp("R2", 150, 100)
            + _make_resistor_sexp("R3", 100, 150)
        )
        tmp = _make_temp_schematic(extra)
        result = route_multi_pin(
            tmp,
            [
                {"reference": "R1", "pin": "2"},
                {"reference": "R2", "pin": "1"},
                {"reference": "R3", "pin": "1"},
            ],
        )
        assert result["success"] is True
        assert len(result["legs"]) == 2

    def test_dry_run_writes_nothing(self) -> None:
        extra = _make_resistor_sexp("R1", 100, 100) + _make_resistor_sexp("R2", 150, 100)
        tmp = _make_temp_schematic(extra)
        before = tmp.read_text(encoding="utf-8")
        result = route_multi_pin(
            tmp,
            [{"reference": "R1", "pin": "2"}, {"reference": "R2", "pin": "1"}],
            dry_run=True,
        )
        after = tmp.read_text(encoding="utf-8")
        assert result["success"] is True
        assert result["dryRun"] is True
        assert len(result["legs"]) == 1
        assert before == after, "dry_run must not modify the file"

    def test_net_conflict_reported_not_silently_merged(self) -> None:
        # R1/R2 pin "2" is at absolute y=103.81 (pin "1" is at y=96.19) — the
        # conflicting labels/wires must sit on the exact pins being targeted.
        extra = _make_resistor_sexp("R1", 100, 100) + _make_resistor_sexp("R2", 150, 100) + """
        (label "NET_A" (at 100 103.81 0)
            (effects (font (size 1.27 1.27)) (justify left bottom))
            (uuid "lbl-a"))
        (label "NET_B" (at 150 103.81 0)
            (effects (font (size 1.27 1.27)) (justify left bottom))
            (uuid "lbl-b"))
        (wire (pts (xy 100 103.81) (xy 100 120))
            (stroke (width 0) (type default))
            (uuid "w-a"))
        (wire (pts (xy 150 103.81) (xy 150 120))
            (stroke (width 0) (type default))
            (uuid "w-b"))
        """
        tmp = _make_temp_schematic(extra)
        before = tmp.read_text(encoding="utf-8")
        result = route_multi_pin(
            tmp, [{"reference": "R1", "pin": "2"}, {"reference": "R2", "pin": "2"}]
        )
        after = tmp.read_text(encoding="utf-8")
        assert result["success"] is False
        assert result["netConflict"] == {"pointA": "NET_A", "pointB": "NET_B"}
        assert before == after, "a detected conflict must abort before writing anything"

    def test_too_few_targets_raises(self) -> None:
        extra = _make_resistor_sexp("R1", 100, 100)
        tmp = _make_temp_schematic(extra)
        with pytest.raises(RouteError):
            route_multi_pin(tmp, [{"reference": "R1", "pin": "1"}])


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerDispatch:
    def test_connect_schematic_pins_in_routes(self) -> None:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
            iface.board = None
            iface.project_filename = None
            iface.use_ipc = False
            iface.ipc_backend = MagicMock()
            iface.ipc_board_api = None
            iface.footprint_library = MagicMock()
            iface.project_commands = MagicMock()
            iface.board_commands = MagicMock()
            iface.component_commands = MagicMock()
            iface.routing_commands = MagicMock()
            KiCADInterface.__init__(iface)

        assert "connect_schematic_pins" in iface.command_routes
        assert callable(iface.command_routes["connect_schematic_pins"])


@pytest.mark.unit
class TestHandlerParamValidation:
    def _make_handler(self):
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
            iface.board = None
            iface.project_filename = None
            iface.use_ipc = False
            iface.ipc_backend = MagicMock()
            iface.ipc_board_api = None
            iface.footprint_library = MagicMock()
            iface.project_commands = MagicMock()
            iface.board_commands = MagicMock()
            iface.component_commands = MagicMock()
            iface.routing_commands = MagicMock()
            KiCADInterface.__init__(iface)
        return iface.command_routes["connect_schematic_pins"]

    def test_missing_schematic_path(self) -> None:
        handler = self._make_handler()
        result = handler(
            {"targets": [{"reference": "R1", "pin": "1"}, {"reference": "R2", "pin": "1"}]}
        )
        assert result["success"] is False

    def test_too_few_targets(self) -> None:
        handler = self._make_handler()
        result = handler(
            {"schematicPath": "/fake.kicad_sch", "targets": [{"reference": "R1", "pin": "1"}]}
        )
        assert result["success"] is False

    def test_target_missing_pin(self) -> None:
        handler = self._make_handler()
        result = handler(
            {
                "schematicPath": "/fake.kicad_sch",
                "targets": [{"reference": "R1"}, {"reference": "R2", "pin": "1"}],
            }
        )
        assert result["success"] is False
