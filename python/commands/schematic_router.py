"""
Schematic auto-router for KiCad Schematics

Automatically computes and draws an orthogonal wire path connecting 2+
component pins, avoiding symbol bodies and wires belonging to a different
net — the tool behind ``connect_schematic_pins``.

First version, deliberately scoped:
  - Manhattan/orthogonal routing only (no diagonal wires).
  - 2-point connections use a coordinate-compressed *local* grid (not a
    fixed global grid) + A* search with a bend penalty.
  - 3+ pin nets use sequential nearest-insertion (greedy), not a full
    Steiner-tree optimization.

See python/commands/schematic_analysis.py (_load_obstacle_model,
_line_segment_intersects_aabb) and python/commands/wire_connectivity.py
(_load_wire_net_membership) for the obstacle-model / net-membership
primitives this module builds on — no new geometry or connectivity
algorithms are introduced here, only routing on top of them.
"""

import heapq
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from commands.pin_locator import PinLocator
from commands.schematic_analysis import (
    _line_segment_intersects_aabb,
    _load_obstacle_model,
)
from commands.wire_connectivity import _load_wire_net_membership, _to_iu
from commands.wire_manager import WireManager

logger = logging.getLogger("kicad_interface")

DEFAULT_ROUTING_GRID_MM = 1.27
DEFAULT_SEARCH_PADDING_MM = 15.0
DEFAULT_BEND_PENALTY_MM = 5.0
DEFAULT_CLEARANCE_MM = 0.15
MAX_ASTAR_STATES = 200_000

# Direction index -> (dx, dy) unit step. 0=East, 1=North, 2=West, 3=South.
_DIRS: List[Tuple[int, int]] = [(1, 0), (0, -1), (-1, 0), (0, 1)]


class RouteError(Exception):
    """Raised when a route cannot be found (search budget, blocked pin, etc.)."""


def _round_grid(v: float) -> float:
    return round(v, 6)


def _pin_angle_to_unit_vector(angle_deg: float) -> Tuple[float, float]:
    """Snap a pin's outward angle (0=right,90=up,180=left,270=down) to a unit vector.

    KiCad pin angles are axis-aligned by convention; rounding to the nearest
    quadrant handles the rare non-cardinal angle defensively rather than
    crashing on it.
    """
    quadrant = round(angle_deg / 90.0) % 4
    return {0: (1.0, 0.0), 1: (0.0, -1.0), 2: (-1.0, 0.0), 3: (0.0, 1.0)}[quadrant]


def _resolve_pin(schematic_path: Path, reference: str, pin: str) -> Dict[str, Any]:
    """Resolve a (reference, pin) target to its absolute pin coordinate and a
    one-grid-step outward stub point (clears the owning symbol's body before
    the graph search begins, avoiding the ambiguous "pin sits exactly on its
    own bbox boundary" edge case)."""
    locator = PinLocator()
    coords = locator.get_pin_location(schematic_path, reference, str(pin))
    if not coords:
        raise RouteError(f"No pin location found for {reference}/{pin}")
    angle = locator.get_pin_angle(schematic_path, reference, str(pin))
    dx, dy = _pin_angle_to_unit_vector(angle if angle is not None else 0.0)
    stub = (
        _round_grid(coords[0] + dx * DEFAULT_ROUTING_GRID_MM),
        _round_grid(coords[1] + dy * DEFAULT_ROUTING_GRID_MM),
    )
    return {
        "reference": reference,
        "pin": str(pin),
        "pin_xy": (float(coords[0]), float(coords[1])),
        "stub_xy": stub,
    }


def _resolve_own_net(
    schematic_path: str, points: List[Tuple[float, float]]
) -> Tuple[Optional[str], Set[int], Optional[Dict[str, str]], Dict[str, Any]]:
    """Resolve which existing wire-net-membership component(s) each target
    point already belongs to (exact-IU wire endpoint match against the
    file's pre-existing state — the candidate route doesn't exist on disk
    yet, so there's no exclude-my-own-future-wire problem).

    Component *identity* (an integer id from ``_load_wire_net_membership``),
    not net *name*, is the source of truth for "is this wire mine" — an
    unnamed (unlabelled) net still has a real component id, and comparing by
    name alone would wrongly treat every unnamed net as foreign (None never
    equals None-with-intent-to-exclude here, since two *different* unnamed
    nets must NOT be treated as the same "own net" either).

    Returns (own_net_name, own_component_ids, conflict, membership).
    ``conflict`` is set when two different existing *named* nets are already
    present among the targets — the only case surfaced as an error, since an
    unnamed net has no name to conflict over.
    """
    membership = _load_wire_net_membership(schematic_path)

    def _resolve_id(pt: Tuple[float, float]) -> Optional[int]:
        iu = _to_iu(pt[0], pt[1])
        for wi, pts in enumerate(membership["all_wires"]):
            if pts[0] == iu or pts[-1] == iu:
                return membership["wire_net_id"][wi]
        return None

    ids = [_resolve_id(p) for p in points]
    own_ids = {i for i in ids if i is not None}
    named = [membership["net_names"].get(i) for i in own_ids]
    named = [n for n in named if n is not None]
    distinct = sorted(set(named))
    if len(distinct) > 1:
        first = next(n for n in named)
        second = next(n for n in named if n != first)
        return None, own_ids, {"pointA": first, "pointB": second}, membership
    return (distinct[0] if distinct else None), own_ids, None, membership


def _foreign_wires_mm(
    membership: Dict[str, Any], own_component_ids: Set[int]
) -> List[Dict[str, Any]]:
    """Existing wires (mm coords) belonging to a component *other* than the
    target's own — the obstacle set a router leg must avoid touching.

    Compares by component id (see ``_resolve_own_net``), not net name, so
    unnamed nets are excluded/included correctly too.
    """
    result: List[Dict[str, Any]] = []
    for wi, w in enumerate(membership["wires_mm"]):
        net_id = membership["wire_net_id"][wi]
        if net_id in own_component_ids:
            continue
        result.append(
            {"start": (w["start"]["x"], w["start"]["y"]), "end": (w["end"]["x"], w["end"]["y"])}
        )
    return result


def _precompute_blocked_edges(
    xs: List[float],
    ys: List[float],
    obstacle_symbols: List[Dict[str, Any]],
    foreign_wires: List[Dict[str, Any]],
) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
    """
    Precompute which grid edges are blocked, once, by iterating each obstacle
    and marking only the (typically few) local grid cells it actually
    overlaps — the inverse of testing every edge against every obstacle
    during A* expansion, which is O(edges x obstacles) and becomes the
    dominant cost on a busy real sheet (hundreds of existing wires each
    contributing an obstacle): a ~21k-node grid against ~250 obstacles was
    observed to take 30+ seconds with the naive per-edge scan, entirely in
    this check, despite grid construction itself being sub-millisecond.

    This is O(obstacles x cells_each_spans) instead — normally tiny, since a
    single symbol or wire-clearance box only touches a handful of grid cells
    relative to the whole padded search area. Uses the same exact
    ``_line_segment_intersects_aabb`` test as before per candidate edge, just
    restricted to each obstacle's own local window instead of the full grid,
    so results are identical, not an approximation.

    Returns (blocked_h, blocked_v):
      blocked_h: set of (xi, yi) — the horizontal edge from xs[xi] to
        xs[xi+1] at ys[yi] is blocked.
      blocked_v: set of (xi, yi) — the vertical edge from ys[yi] to
        ys[yi+1] at xs[xi] is blocked.
    """
    import bisect

    blocked_h: Set[Tuple[int, int]] = set()
    blocked_v: Set[Tuple[int, int]] = set()
    n_xs, n_ys = len(xs), len(ys)

    def _mark(box_min_x: float, box_min_y: float, box_max_x: float, box_max_y: float) -> None:
        xi_lo = max(0, bisect.bisect_left(xs, box_min_x) - 1)
        xi_hi = min(n_xs - 1, bisect.bisect_right(xs, box_max_x))
        yi_lo = max(0, bisect.bisect_left(ys, box_min_y) - 1)
        yi_hi = min(n_ys - 1, bisect.bisect_right(ys, box_max_y))

        for yi in range(yi_lo, yi_hi + 1):
            if yi >= n_ys:
                continue
            for xi in range(xi_lo, xi_hi):
                if xi + 1 >= n_xs or (xi, yi) in blocked_h:
                    continue
                if _line_segment_intersects_aabb(
                    xs[xi], ys[yi], xs[xi + 1], ys[yi], box_min_x, box_min_y, box_max_x, box_max_y
                ):
                    blocked_h.add((xi, yi))

        for xi in range(xi_lo, xi_hi + 1):
            if xi >= n_xs:
                continue
            for yi in range(yi_lo, yi_hi):
                if yi + 1 >= n_ys or (xi, yi) in blocked_v:
                    continue
                if _line_segment_intersects_aabb(
                    xs[xi], ys[yi], xs[xi], ys[yi + 1], box_min_x, box_min_y, box_max_x, box_max_y
                ):
                    blocked_v.add((xi, yi))

    for sd in obstacle_symbols:
        _mark(*sd["bbox"])

    for w in foreign_wires:
        wx1, wy1 = w["start"]
        wx2, wy2 = w["end"]
        _mark(
            min(wx1, wx2) - DEFAULT_CLEARANCE_MM,
            min(wy1, wy2) - DEFAULT_CLEARANCE_MM,
            max(wx1, wx2) + DEFAULT_CLEARANCE_MM,
            max(wy1, wy2) + DEFAULT_CLEARANCE_MM,
        )

    return blocked_h, blocked_v


def _build_compressed_grid(
    p_a: Tuple[float, float],
    p_b: Tuple[float, float],
    obstacle_symbols: List[Dict[str, Any]],
    foreign_wires: List[Dict[str, Any]],
    routing_grid_mm: float,
    search_padding_mm: float,
) -> Tuple[List[float], List[float]]:
    """Build sparse, coordinate-compressed x/y grid lines for the local A*
    search space around a pin pair — not a fixed global grid, which would
    either miss off-grid pins or waste cells on a sheet-spanning connection
    between two pins that are actually close together.

    Grid lines = the two target points, every symbol-bbox edge (+clearance),
    every foreign-net-wire edge (+clearance) that falls within the padded
    bounding box, plus uniform fill wherever a gap between compressed lines
    exceeds routing_grid_mm (so most output lands on KiCad's default grid).
    """
    manhattan = abs(p_a[0] - p_b[0]) + abs(p_a[1] - p_b[1])
    padding = max(search_padding_mm, 0.25 * manhattan)

    min_x = min(p_a[0], p_b[0]) - padding
    max_x = max(p_a[0], p_b[0]) + padding
    min_y = min(p_a[1], p_b[1]) - padding
    max_y = max(p_a[1], p_b[1]) + padding

    xs: Set[float] = {p_a[0], p_b[0], min_x, max_x}
    ys: Set[float] = {p_a[1], p_b[1], min_y, max_y}

    for sd in obstacle_symbols:
        bx1, by1, bx2, by2 = sd["bbox"]
        if bx2 < min_x or bx1 > max_x or by2 < min_y or by1 > max_y:
            continue
        xs.update((bx1, bx2))
        ys.update((by1, by2))

    for w in foreign_wires:
        wx1, wy1 = w["start"]
        wx2, wy2 = w["end"]
        wminx = min(wx1, wx2) - DEFAULT_CLEARANCE_MM
        wmaxx = max(wx1, wx2) + DEFAULT_CLEARANCE_MM
        wminy = min(wy1, wy2) - DEFAULT_CLEARANCE_MM
        wmaxy = max(wy1, wy2) + DEFAULT_CLEARANCE_MM
        if wmaxx < min_x or wminx > max_x or wmaxy < min_y or wminy > max_y:
            continue
        xs.update((wminx, wmaxx))
        ys.update((wminy, wmaxy))

    def _fill(vals: Set[float], lo: float, hi: float) -> List[float]:
        sorted_vals = sorted(v for v in vals if lo - 1e-6 <= v <= hi + 1e-6)
        if not sorted_vals:
            return [lo, hi]
        result = [sorted_vals[0]]
        for v in sorted_vals[1:]:
            while v - result[-1] > routing_grid_mm * 1.5:
                result.append(_round_grid(result[-1] + routing_grid_mm))
            if v - result[-1] > 1e-6:
                result.append(v)
        return result

    return _fill(xs, min_x, max_x), _fill(ys, min_y, max_y)


def _astar_route(
    start: Tuple[float, float],
    goal: Tuple[float, float],
    xs: List[float],
    ys: List[float],
    obstacle_symbols: List[Dict[str, Any]],
    foreign_wires: List[Dict[str, Any]],
    bend_penalty_mm: float,
    max_states: int,
) -> List[Tuple[float, float]]:
    """Grid-constrained A* between two exact grid nodes.

    State = (x_index, y_index, incoming_direction) — direction is part of the
    state so a bend penalty can be applied on direction change; the Manhattan
    distance heuristic stays admissible since it never exceeds true remaining
    cost (edge_length + non-negative bend penalty >= edge_length).

    Blocked-edge lookups are precomputed once via ``_precompute_blocked_edges``
    rather than re-tested per obstacle on every edge expansion — see that
    function's docstring for why (naive per-edge scanning is the dominant
    cost on a busy real sheet with hundreds of existing wires).

    Returns a waypoint list with collinear intermediate points collapsed to
    bends only (a clean list suitable for WireManager.add_polyline_wire).
    """
    blocked_h, blocked_v = _precompute_blocked_edges(xs, ys, obstacle_symbols, foreign_wires)
    x_idx = {v: i for i, v in enumerate(xs)}
    y_idx = {v: i for i, v in enumerate(ys)}
    if start[0] not in x_idx or start[1] not in y_idx:
        raise RouteError(f"Start point {start} is not a grid node")
    if goal[0] not in x_idx or goal[1] not in y_idx:
        raise RouteError(f"Goal point {goal} is not a grid node")

    def h(x: float, y: float) -> float:
        return abs(x - goal[0]) + abs(y - goal[1])

    start_state = (x_idx[start[0]], y_idx[start[1]], -1)
    goal_cell = (x_idx[goal[0]], y_idx[goal[1]])

    open_heap: List[Tuple[float, float, Tuple[int, int, int]]] = [(h(*start), 0.0, start_state)]
    came_from: Dict[Tuple[int, int, int], Tuple[Tuple[int, int, int], Tuple[float, float]]] = {}
    best_g: Dict[Tuple[int, int, int], float] = {start_state: 0.0}
    expanded = 0

    while open_heap:
        _, g, state = heapq.heappop(open_heap)
        if g > best_g.get(state, math.inf):
            continue
        xi, yi, direction = state
        if (xi, yi) == goal_cell:
            path_states = [state]
            cur = state
            while cur in came_from:
                cur, _ = came_from[cur]
                path_states.append(cur)
            path_states.reverse()
            waypoints = [(xs[s[0]], ys[s[1]]) for s in path_states]
            return _collapse_collinear(waypoints)

        expanded += 1
        if expanded > max_states:
            raise RouteError("A* search budget exceeded")

        for new_dir, (dxu, dyu) in enumerate(_DIRS):
            nxi, nyi = xi + dxu, yi + dyu
            if not (0 <= nxi < len(xs) and 0 <= nyi < len(ys)):
                continue
            if dyu == 0:
                if (min(xi, nxi), yi) in blocked_h:
                    continue
            else:
                if (xi, min(yi, nyi)) in blocked_v:
                    continue
            x1, y1 = xs[xi], ys[yi]
            x2, y2 = xs[nxi], ys[nyi]
            edge_len = math.hypot(x2 - x1, y2 - y1)
            bend = bend_penalty_mm if (direction != -1 and direction != new_dir) else 0.0
            new_g = g + edge_len + bend
            new_state = (nxi, nyi, new_dir)
            if new_g < best_g.get(new_state, math.inf):
                best_g[new_state] = new_g
                came_from[new_state] = (state, (x2, y2))
                heapq.heappush(open_heap, (new_g + h(x2, y2), new_g, new_state))

    raise RouteError(f"No path found from {start} to {goal}")


def _collapse_collinear(waypoints: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Drop intermediate points that don't represent an actual bend."""
    if len(waypoints) <= 2:
        return waypoints
    collapsed = [waypoints[0]]
    for i in range(1, len(waypoints) - 1):
        px, py = collapsed[-1]
        cx, cy = waypoints[i]
        nx, ny = waypoints[i + 1]
        # Cross product of (cur-prev) and (next-cur); zero means collinear.
        if (cx - px) * (ny - cy) - (cy - py) * (nx - cx) != 0:
            collapsed.append((cx, cy))
    collapsed.append(waypoints[-1])
    return collapsed


def route_two_points(
    p_a: Tuple[float, float],
    p_b: Tuple[float, float],
    obstacle_symbols: List[Dict[str, Any]],
    foreign_wires: List[Dict[str, Any]],
    routing_grid_mm: float = DEFAULT_ROUTING_GRID_MM,
    search_padding_mm: float = DEFAULT_SEARCH_PADDING_MM,
    bend_penalty_mm: float = DEFAULT_BEND_PENALTY_MM,
) -> List[Tuple[float, float]]:
    """Route an orthogonal path between two points. Retries once with doubled
    padding if the initial local search budget is exceeded (handles a direct
    corridor being blocked and a detour needing room outside the first box),
    then fails cleanly rather than searching the whole sheet unbounded."""
    xs, ys = _build_compressed_grid(
        p_a, p_b, obstacle_symbols, foreign_wires, routing_grid_mm, search_padding_mm
    )
    try:
        return _astar_route(
            p_a, p_b, xs, ys, obstacle_symbols, foreign_wires, bend_penalty_mm, MAX_ASTAR_STATES
        )
    except RouteError:
        xs, ys = _build_compressed_grid(
            p_a, p_b, obstacle_symbols, foreign_wires, routing_grid_mm, search_padding_mm * 2
        )
        return _astar_route(
            p_a, p_b, xs, ys, obstacle_symbols, foreign_wires, bend_penalty_mm, MAX_ASTAR_STATES
        )


def route_multi_pin(
    schematic_path: Path,
    targets: List[Dict[str, str]],
    net_name: Optional[str] = None,
    routing_grid_mm: float = DEFAULT_ROUTING_GRID_MM,
    search_padding_mm: float = DEFAULT_SEARCH_PADDING_MM,
    bend_penalty_mm: float = DEFAULT_BEND_PENALTY_MM,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Route and (unless dry_run) commit wires connecting 2+ pins.

    3+ pin nets use sequential nearest-insertion: start with the first
    target routed, then repeatedly route the not-yet-routed target closest
    (by Manhattan distance between pin coordinates) to any already-routed
    target, growing the tree one leg at a time.

    Each committed leg goes through the real WireManager (so its existing
    T-junction splitting fires correctly for any leg that lands on an
    existing same-net wire), and the obstacle/net-membership model is
    reloaded from disk before the next leg — safer than hand-simulating
    WireManager's side effects in memory. For dry_run, legs are computed but
    never written; their segments are instead added to an in-memory-only
    obstacle extension so later legs in the same preview route sensibly.
    """
    if len(targets) < 2:
        raise RouteError("At least 2 targets are required")

    schematic_path = Path(schematic_path)
    resolved = [_resolve_pin(schematic_path, t["reference"], t["pin"]) for t in targets]

    own_net, own_ids, conflict, membership = _resolve_own_net(
        str(schematic_path), [r["pin_xy"] for r in resolved]
    )
    if conflict:
        return {
            "success": False,
            "message": "Targets already sit on two different existing nets",
            "netConflict": conflict,
        }
    if net_name and own_net and own_net != net_name:
        return {
            "success": False,
            "message": (
                f"Targets already belong to net '{own_net}', which does not match "
                f"the expected netName '{net_name}'"
            ),
        }

    obstacle = _load_obstacle_model(schematic_path)
    foreign_wires = _foreign_wires_mm(membership, own_ids)

    routed_indices = [0]
    remaining = list(range(1, len(resolved)))
    legs: List[Dict[str, Any]] = []

    def _manhattan(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    while remaining:
        best_pair = None
        best_dist = math.inf
        for ri in remaining:
            for routed_i in routed_indices:
                d = _manhattan(resolved[ri]["pin_xy"], resolved[routed_i]["pin_xy"])
                if d < best_dist:
                    best_dist = d
                    best_pair = (ri, routed_i)
        new_i, anchor_i = best_pair
        new_pin = resolved[new_i]
        anchor_pin = resolved[anchor_i]

        try:
            path = route_two_points(
                new_pin["stub_xy"],
                anchor_pin["stub_xy"],
                obstacle["symbol_data"],
                foreign_wires,
                routing_grid_mm=routing_grid_mm,
                search_padding_mm=search_padding_mm,
                bend_penalty_mm=bend_penalty_mm,
            )
        except RouteError as e:
            return {
                "success": False,
                "message": f"Failed to route {new_pin['reference']}/{new_pin['pin']} "
                f"to {anchor_pin['reference']}/{anchor_pin['pin']}: {e}",
                "legsCompleted": legs,
            }

        waypoints = [new_pin["pin_xy"], *path, anchor_pin["pin_xy"]]
        # Collapse again in case the pin/stub join is collinear with the route.
        waypoints = _collapse_collinear(waypoints)

        if not dry_run:
            points_list = [[p[0], p[1]] for p in waypoints]
            if len(points_list) == 2:
                ok = WireManager.add_wire(schematic_path, points_list[0], points_list[1])
            else:
                ok = WireManager.add_polyline_wire(schematic_path, points_list)
            if not ok:
                return {
                    "success": False,
                    "message": f"WireManager failed to write leg "
                    f"{new_pin['reference']}/{new_pin['pin']} -> "
                    f"{anchor_pin['reference']}/{anchor_pin['pin']}",
                    "legsCompleted": legs,
                }
            # Reload from disk before the next leg — see docstring.
            obstacle = _load_obstacle_model(schematic_path)
            own_net, own_ids, _, membership = _resolve_own_net(
                str(schematic_path), [r["pin_xy"] for r in resolved]
            )
            foreign_wires = _foreign_wires_mm(membership, own_ids)

        legs.append(
            {
                "from": {"reference": new_pin["reference"], "pin": new_pin["pin"]},
                "to": {"reference": anchor_pin["reference"], "pin": anchor_pin["pin"]},
                "waypoints": [{"x": p[0], "y": p[1]} for p in waypoints],
            }
        )
        routed_indices.append(new_i)
        remaining.remove(new_i)

    return {"success": True, "dryRun": dry_run, "legs": legs, "ownNet": own_net}
