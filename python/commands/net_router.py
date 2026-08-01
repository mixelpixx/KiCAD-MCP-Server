"""Grid A* net router — the pathfinding layer under ``route_net``.

``route_trace`` and ``route_pad_to_pad`` draw a trace where you tell them to.
They do not look at what is already on the board, so the caller has to know a
legal path before asking. For an LLM driving the board that is the hard part:
it can see the netlist and the DRC report, but not the free space.

This module supplies the missing piece — an occupancy model of the board and an
A* search over it — with no dependency beyond Pillow, which is already required.
Grids are ``bytearray`` rather than numpy arrays deliberately: a 100 x 80 mm
board at 0.1 mm is ~800k cells per layer, which indexes fast enough in CPython
and costs the project nothing new.

Nothing here imports pcbnew. The board-facing glue lives in
``commands.routing.RoutingCommands.route_net``; everything below is plain
geometry so it can be tested without KiCad installed.
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Cell = Tuple[int, int, int]  # (layer_id, x, y)

DIAG = math.sqrt(2.0)

# 8-way movement. Diagonals cost sqrt(2) so the search does not prefer a
# staircase of orthogonal steps over the 45-degree run a PCB actually wants.
_NEIGHBOURS: Sequence[Tuple[int, int, float]] = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, DIAG),
    (1, -1, DIAG),
    (-1, 1, DIAG),
    (-1, -1, DIAG),
)


class OccupancyGrid:
    """Per-layer maps of where a new trace on one net may and may not go.

    Three maps per copper layer:

    ``blocked``      cells a trace of this net cannot occupy — every other
                     net's copper, grown by (clearance + trace_width / 2), plus
                     rule areas that bar tracks and everything off-board.
    ``via_blocked``  the same for vias, grown by (clearance + via_diameter / 2).
                     A via is fatter than a trace; checking a layer change
                     against the trace map is how a via ends up sitting a tenth
                     of a millimetre from somebody else's copper.
    ``target``       this net's existing copper. Reaching any of it is what
                     "connected" means, so it is a goal, never an obstacle.
    """

    __slots__ = ("width", "height", "layers", "origin", "pitch", "blocked", "via_blocked", "target")

    def __init__(
        self,
        width: int,
        height: int,
        layers: Sequence[int],
        origin: Tuple[int, int],
        pitch: int,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.layers = list(layers)
        self.origin = origin
        self.pitch = int(pitch)
        size = self.width * self.height
        self.blocked: Dict[int, bytearray] = {L: bytearray(size) for L in self.layers}
        self.via_blocked: Dict[int, bytearray] = {L: bytearray(size) for L in self.layers}
        self.target: Dict[int, bytearray] = {L: bytearray(size) for L in self.layers}

    # -- coordinates ------------------------------------------------------
    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def to_cell(self, x_nm: int, y_nm: int) -> Tuple[int, int]:
        return (
            int(round((x_nm - self.origin[0]) / self.pitch)),
            int(round((y_nm - self.origin[1]) / self.pitch)),
        )

    def to_nm(self, x: int, y: int) -> Tuple[int, int]:
        return (self.origin[0] + x * self.pitch, self.origin[1] + y * self.pitch)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_blocked(self, layer: int, x: int, y: int) -> bool:
        return bool(self.blocked[layer][self.index(x, y)])

    def is_target(self, layer: int, x: int, y: int) -> bool:
        return bool(self.target[layer][self.index(x, y)])

    def via_fits(self, x: int, y: int) -> bool:
        """A via punches every layer, so it must clear all of them."""
        i = self.index(x, y)
        return not any(self.via_blocked[L][i] for L in self.layers)

    def free_cells_in(self, layer: int, cx: int, cy: int, rx: int, ry: int) -> List[Cell]:
        """Unblocked cells in a rectangle — used to find where a pad can start.

        Taking the pad centre alone fails on fine-pitch parts: on a 0.65 mm
        pitch package the neighbouring pads' clearance covers the centre cell
        entirely, so a centre-only terminal never enters the search even though
        the pad is 1.5 mm long and its far end is wide open.
        """
        out: List[Cell] = []
        for x in range(cx - rx, cx + rx + 1):
            for y in range(cy - ry, cy + ry + 1):
                if self.in_bounds(x, y) and not self.blocked[layer][self.index(x, y)]:
                    out.append((layer, x, y))
        return out


def _octile(x: int, y: int, goals_xy: Sequence[Tuple[int, int]]) -> float:
    """Admissible heuristic for 8-way movement: nearest goal, octile distance."""
    best = float("inf")
    for gx, gy in goals_xy:
        dx = abs(gx - x)
        dy = abs(gy - y)
        lo, hi = (dx, dy) if dx < dy else (dy, dx)
        d = (hi - lo) + lo * DIAG
        if d < best:
            best = d
    return best


def astar(
    grid: OccupancyGrid,
    starts: Iterable[Cell],
    goals: Iterable[Cell],
    layer_costs: Optional[Dict[int, float]] = None,
    via_cost: float = 40.0,
) -> Optional[List[Cell]]:
    """Cheapest legal path from any start cell to any goal cell.

    ``layer_costs`` is where board intent lives: make 2 oz outer copper dear and
    an empty inner signal layer cheap and the router stops carving through the
    power planes to save a via. ``via_cost`` is in grid steps — layer changes
    are not free, they cost area and inductance.
    """
    layer_costs = layer_costs or {}
    goal_set = set(goals)
    if not goal_set:
        return None
    goals_xy = list({(g[1], g[2]) for g in goal_set})

    open_heap: List[Tuple[float, float, Cell]] = []
    best_g: Dict[Cell, float] = {}
    came: Dict[Cell, Optional[Cell]] = {}

    for s in starts:
        if s[0] not in grid.blocked or not grid.in_bounds(s[1], s[2]):
            continue
        best_g[s] = 0.0
        heapq.heappush(open_heap, (_octile(s[1], s[2], goals_xy), 0.0, s))
        came[s] = None
    if not open_heap:
        return None

    closed: set = set()
    while open_heap:
        _, g, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)
        if cur in goal_set:
            path: List[Cell] = []
            node: Optional[Cell] = cur
            while node is not None:
                path.append(node)
                node = came[node]
            path.reverse()
            return path

        layer, x, y = cur
        step_cost = layer_costs.get(layer, 1.0)
        blocked = grid.blocked[layer]

        for dx, dy, dist in _NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if not grid.in_bounds(nx, ny):
                continue
            if blocked[grid.index(nx, ny)]:
                continue
            # A diagonal step must not squeeze between two blocked cells: on the
            # grid it looks clear, in copper it clips the corner.
            if dx and dy:
                if blocked[grid.index(x + dx, y)] or blocked[grid.index(x, y + dy)]:
                    continue
            nxt = (layer, nx, ny)
            if nxt in closed:
                continue
            ng = g + dist * step_cost
            if ng < best_g.get(nxt, float("inf")):
                best_g[nxt] = ng
                came[nxt] = cur
                heapq.heappush(open_heap, (ng + _octile(nx, ny, goals_xy), ng, nxt))

        if grid.via_fits(x, y):
            for other in grid.layers:
                if other == layer:
                    continue
                nxt = (other, x, y)
                if nxt in closed:
                    continue
                ng = g + via_cost
                if ng < best_g.get(nxt, float("inf")):
                    best_g[nxt] = ng
                    came[nxt] = cur
                    heapq.heappush(open_heap, (ng + _octile(x, y, goals_xy), ng, nxt))

    return None


def simplify_path(path: Sequence[Cell]) -> List[Cell]:
    """Collapse a cell-by-cell path into corner points.

    Keeps every layer change and every change of direction and drops everything
    in between, so a straight run becomes one segment instead of a hundred.
    """
    if len(path) < 2:
        return list(path)
    out: List[Cell] = [path[0]]
    for i in range(1, len(path) - 1):
        pl, px, py = out[-1]
        cl, cx, cy = path[i]
        nl, nx, ny = path[i + 1]
        if cl != pl or nl != cl:
            out.append(path[i])
            continue
        d1 = ((cx > px) - (cx < px), (cy > py) - (cy < py))
        d2 = ((nx > cx) - (nx < cx), (ny > cy) - (ny < cy))
        if d1 != d2:
            out.append(path[i])
    out.append(path[-1])
    return out


def path_segments(path: Sequence[Cell]) -> Tuple[List[Tuple[Cell, Cell]], List[Cell]]:
    """Split a simplified path into (track segments, via locations)."""
    tracks: List[Tuple[Cell, Cell]] = []
    vias: List[Cell] = []
    for a, b in zip(path, path[1:]):
        if a[0] == b[0]:
            if a[1:] != b[1:]:
                tracks.append((a, b))
        else:
            vias.append(a)
    return tracks, vias
