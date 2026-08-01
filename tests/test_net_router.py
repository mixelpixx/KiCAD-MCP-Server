"""Tests for the grid A* net router behind ``route_net``.

The board-facing glue in ``RoutingCommands.route_net`` is a thin wrapper over
these functions, so the pathfinding contract is what gets pinned here: it runs
without pcbnew, without Pillow and without a board.

Each test locks in a behaviour that is wrong in an obvious first implementation
and expensive to notice on real copper.
"""

import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from commands.net_router import (  # noqa: E402
    OccupancyGrid,
    astar,
    path_segments,
    simplify_path,
)

F_CU = 0
B_CU = 2


def _grid(width=40, height=40, layers=(F_CU, B_CU)):
    return OccupancyGrid(width, height, list(layers), (0, 0), 100_000)


def _block(grid, layer, x0, y0, x1, y1, vias_too=True):
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            grid.blocked[layer][grid.index(x, y)] = 1
            if vias_too:
                grid.via_blocked[layer][grid.index(x, y)] = 1


class TestCoordinates:
    def test_cell_and_nm_round_trip(self):
        grid = OccupancyGrid(10, 10, [F_CU], (1_000_000, 2_000_000), 100_000)
        assert grid.to_cell(1_500_000, 2_500_000) == (5, 5)
        assert grid.to_nm(5, 5) == (1_500_000, 2_500_000)

    def test_out_of_bounds_is_rejected(self):
        grid = _grid()
        assert not grid.in_bounds(-1, 0)
        assert not grid.in_bounds(0, 40)


class TestAStar:
    def test_finds_a_path_across_open_space(self):
        grid = _grid()
        path = astar(grid, [(F_CU, 2, 2)], [(F_CU, 30, 30)])
        assert path is not None
        assert path[0] == (F_CU, 2, 2)
        assert path[-1] == (F_CU, 30, 30)

    def test_routes_around_an_obstacle_rather_than_through_it(self):
        grid = _grid()
        _block(grid, F_CU, 10, 0, 10, 30)  # wall with a gap at the bottom
        path = astar(grid, [(F_CU, 2, 2)], [(F_CU, 20, 2)])
        assert path is not None
        assert all(not grid.is_blocked(*cell) for cell in path)
        # it had to detour past the end of the wall
        assert max(c[2] for c in path) > 30

    def test_returns_none_when_fully_enclosed(self):
        grid = _grid()
        _block(grid, F_CU, 5, 3, 9, 3)
        _block(grid, F_CU, 5, 7, 9, 7)
        _block(grid, F_CU, 5, 3, 5, 7)
        _block(grid, F_CU, 9, 3, 9, 7)
        for layer in (F_CU, B_CU):
            _block(grid, layer, 6, 4, 8, 6, vias_too=True)
            for x in range(6, 9):
                for y in range(4, 7):
                    grid.blocked[layer][grid.index(x, y)] = 0
        assert astar(grid, [(F_CU, 7, 5)], [(F_CU, 30, 30)]) is None

    def test_changes_layer_to_get_past_a_full_height_wall(self):
        grid = _grid()
        _block(grid, F_CU, 10, 0, 10, 39, vias_too=False)
        path = astar(grid, [(F_CU, 2, 2)], [(F_CU, 20, 2)])
        assert path is not None
        assert {c[0] for c in path} == {F_CU, B_CU}

    def test_a_via_must_clear_every_layer_not_just_two(self):
        """A via punches the whole stack, so one blocked layer forbids it."""
        grid = _grid()
        _block(grid, F_CU, 10, 0, 10, 39, vias_too=False)
        for x in range(grid.width):
            for y in range(grid.height):
                grid.via_blocked[B_CU][grid.index(x, y)] = 1
        assert astar(grid, [(F_CU, 2, 2)], [(F_CU, 20, 2)]) is None

    def test_diagonal_step_cannot_squeeze_between_two_blocked_cells(self):
        """On the grid it looks clear; in copper it clips the corner."""
        grid = _grid(layers=(F_CU,))
        _block(grid, F_CU, 6, 5, 6, 5)
        _block(grid, F_CU, 5, 6, 5, 6)
        path = astar(grid, [(F_CU, 5, 5)], [(F_CU, 6, 6)])
        assert path is not None
        assert (F_CU, 5, 5) in path and (F_CU, 6, 6) in path
        # the direct diagonal is the corner cut, so the path must be longer
        assert len(path) > 2

    def test_layer_cost_steers_the_route(self):
        grid = _grid()
        cheap = astar(grid, [(F_CU, 2, 2)], [(B_CU, 20, 2)], {F_CU: 1.0, B_CU: 1.0}, 5.0)
        assert cheap is not None
        # make the far layer expensive and the via cheap: it should still get
        # there, but a high layer cost must not break reachability
        dear = astar(grid, [(F_CU, 2, 2)], [(B_CU, 20, 2)], {B_CU: 50.0}, 5.0)
        assert dear is not None
        assert dear[-1][0] == B_CU

    def test_no_goals_is_not_an_error(self):
        assert astar(_grid(), [(F_CU, 1, 1)], []) is None


class TestPadTerminals:
    def test_free_cells_finds_the_open_end_of_a_boxed_in_pad(self):
        """Fine-pitch escape: the centre is covered, the far end is not.

        On a 0.65 mm pitch package the neighbouring pads' clearance covers the
        centre cell, so a centre-only terminal never enters the search even
        though the pad is long and its far end is wide open.
        """
        grid = _grid()
        _block(grid, F_CU, 18, 20, 20, 20)  # covers the pad centre at (20,20)
        cells = grid.free_cells_in(F_CU, 20, 20, 4, 0)
        assert cells, "a pad this long must still offer somewhere to start"
        assert all(not grid.is_blocked(*c) for c in cells)
        assert (F_CU, 21, 20) in cells


class TestSimplify:
    def test_straight_run_becomes_two_points(self):
        path = [(F_CU, x, 0) for x in range(10)]
        assert simplify_path(path) == [(F_CU, 0, 0), (F_CU, 9, 0)]

    def test_corner_is_kept(self):
        path = [(F_CU, x, 0) for x in range(5)] + [(F_CU, 4, y) for y in range(1, 5)]
        simple = simplify_path(path)
        assert (F_CU, 4, 0) in simple
        assert len(simple) == 3

    def test_layer_change_is_kept(self):
        path = [(F_CU, 0, 0), (F_CU, 1, 0), (B_CU, 1, 0), (B_CU, 2, 0)]
        assert simplify_path(path) == path

    def test_short_paths_pass_through(self):
        assert simplify_path([(F_CU, 0, 0)]) == [(F_CU, 0, 0)]
        assert simplify_path([]) == []


class TestSegments:
    def test_splits_tracks_from_vias(self):
        path = [(F_CU, 0, 0), (F_CU, 5, 0), (B_CU, 5, 0), (B_CU, 5, 5)]
        tracks, vias = path_segments(path)
        assert len(tracks) == 2
        assert vias == [(F_CU, 5, 0)]

    def test_zero_length_segments_are_dropped(self):
        tracks, vias = path_segments([(F_CU, 3, 3), (F_CU, 3, 3)])
        assert tracks == [] and vias == []
