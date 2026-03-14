"""
Wire Connectivity Analysis for KiCad Schematics

Traces wire networks from a point and finds connected component pins.
Uses KiCad's internal integer unit system (10,000 IU per mm) for exact
coordinate matching, mirroring KiCad's own connectivity algorithm.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from commands.pin_locator import PinLocator

logger = logging.getLogger('kicad_interface')

_IU_PER_MM = 10000  # KiCad schematic internal units per millimeter
_QUERY_TOLERANCE_IU = 5000  # 0.5 mm in IU — for user-supplied query points


def _to_iu(x_mm: float, y_mm: float) -> Tuple[int, int]:
    """Convert mm coordinates to KiCad internal units (integer)."""
    return (round(x_mm * _IU_PER_MM), round(y_mm * _IU_PER_MM))


def _parse_wires(schematic) -> List[List[Tuple[int, int]]]:
    """Extract wire endpoints from a schematic object as IU tuples."""
    all_wires = []
    for wire in schematic.wire:
        if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
            pts = []
            for point in wire.pts.xy:
                if hasattr(point, "value"):
                    pts.append(_to_iu(float(point.value[0]), float(point.value[1])))
            if len(pts) >= 2:
                all_wires.append(pts)
    return all_wires


def _build_adjacency(
    all_wires: List[List[Tuple[int, int]]],
) -> Tuple[List[Set[int]], Dict[Tuple[int, int], Set[int]]]:
    """Build wire adjacency using exact IU coordinate matching.

    Wires that share an endpoint are adjacent — this naturally handles
    junctions since all wires meeting at the same point get connected.

    Returns a tuple of:
      - adjacency: list of sets, one per wire, containing adjacent wire indices
      - iu_to_wires: dict mapping each IU endpoint to the set of wire indices
        that have an endpoint at that exact coordinate (used for seed queries)
    """
    # Map each IU endpoint to all wire indices that touch it
    iu_to_wires: Dict[Tuple[int, int], Set[int]] = {}
    for i, pts in enumerate(all_wires):
        for pt in pts:
            iu_to_wires.setdefault(pt, set()).add(i)

    # Wires that share an IU endpoint are adjacent
    adjacency: List[Set[int]] = [set() for _ in range(len(all_wires))]
    for wire_set in iu_to_wires.values():
        wire_list = list(wire_set)
        for a in wire_list:
            for b in wire_list:
                if a != b:
                    adjacency[a].add(b)

    return adjacency, iu_to_wires


def _find_connected_wires(
    x_mm: float,
    y_mm: float,
    all_wires: List[List[Tuple[int, int]]],
    iu_to_wires: Dict[Tuple[int, int], Set[int]],
    adjacency: List[Set[int]],
) -> Tuple:
    """BFS from query point. Returns (visited wire indices, net IU points) or (None, None).

    Uses _QUERY_TOLERANCE_IU for the seed step because user-supplied coordinates
    may be imprecise. Wire-to-wire matching inside _build_adjacency is exact.
    """
    query_iu = _to_iu(x_mm, y_mm)

    # Find seed wires: any wire whose endpoint is within _QUERY_TOLERANCE_IU of the query
    seed_indices: Set[int] = set()
    for iu_pt, wire_indices in iu_to_wires.items():
        if (abs(iu_pt[0] - query_iu[0]) <= _QUERY_TOLERANCE_IU and
                abs(iu_pt[1] - query_iu[1]) <= _QUERY_TOLERANCE_IU):
            seed_indices.update(wire_indices)

    if not seed_indices:
        return (None, None)

    # BFS flood-fill using pre-compiled adjacency
    visited: Set[int] = set(seed_indices)
    queue = list(seed_indices)
    net_points: Set[Tuple[int, int]] = set()
    for i in seed_indices:
        net_points.update(all_wires[i])

    while queue:
        wire_idx = queue.pop()
        for neighbor_idx in adjacency[wire_idx]:
            if neighbor_idx not in visited:
                visited.add(neighbor_idx)
                queue.append(neighbor_idx)
                net_points.update(all_wires[neighbor_idx])

    return (visited, net_points)


def _find_pins_on_net(
    net_points: Set[Tuple[int, int]],
    schematic_path,
    schematic,
) -> List[Dict]:
    """Find component pins that land on net points.

    Uses exact IU matching with a ±_PIN_TOLERANCE_IU neighbourhood to guard
    against floating-point round-trip differences between wire and pin coordinates.

    Returns a list of {"component": ref, "pin": pin_num} dicts.
    """

    def _on_net(px_mm: float, py_mm: float) -> bool:
        pin_iu = _to_iu(px_mm, py_mm)
        if pin_iu in net_points:
            return True
        x, y = pin_iu
        return ((x+1, y) in net_points or (x-1, y) in net_points or
                (x, y+1) in net_points or (x, y-1) in net_points)

    locator = PinLocator()
    pins = []
    seen: Set[Tuple] = set()

    ref = None
    for symbol in schematic.symbol:
        try:
            if not hasattr(symbol, 'property') or not hasattr(symbol.property, "Reference"):
                continue
            ref = symbol.property.Reference.value
            if ref.startswith("_TEMPLATE"):
                continue
            all_pins = locator.get_all_symbol_pins(Path(schematic_path), ref)
            if not all_pins:
                continue
            for pin_num, pin_data in all_pins.items():
                if _on_net(pin_data[0], pin_data[1]):
                    key = (ref, pin_num)
                    if key not in seen:
                        seen.add(key)
                        pins.append({"component": ref, "pin": pin_num})
        except Exception as e:
            logger.warning(f"Error checking pins for {ref if ref is not None else '<unknown>'}: {e}")

    return pins


def get_wire_connections(schematic, schematic_path: str, x_mm: float, y_mm: float) -> Optional[Dict]:
    """Find all component pins reachable from a point via connected wires.

    Returns dict with keys:
      - "pins": list of {"component": str, "pin": str}
      - "wires": list of {"start": {"x", "y"}, "end": {"x", "y"}} in mm
    Or None if no wire found at the query point.
    """
    all_wires = _parse_wires(schematic)
    if not all_wires:
        return {"pins": [], "wires": []}

    adjacency, iu_to_wires = _build_adjacency(all_wires)

    visited, net_points = _find_connected_wires(x_mm, y_mm, all_wires, iu_to_wires, adjacency)
    if visited is None:
        return None

    wires_out = [
        {"start": {"x": all_wires[i][0][0] / _IU_PER_MM, "y": all_wires[i][0][1] / _IU_PER_MM},
         "end": {"x": all_wires[i][-1][0] / _IU_PER_MM, "y": all_wires[i][-1][1] / _IU_PER_MM}}
        for i in visited
    ]

    if not hasattr(schematic, "symbol"):
        return {"pins": [], "wires": wires_out}

    pins = _find_pins_on_net(net_points, schematic_path, schematic)
    return {"pins": pins, "wires": wires_out}
