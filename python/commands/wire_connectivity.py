"""
Wire Connectivity Analysis for KiCad Schematics

Traces wire networks from a point and finds connected component pins.
Uses KiCad's internal integer unit system (10,000 IU per mm) for exact
coordinate matching, mirroring KiCad's own connectivity algorithm.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from commands.pin_locator import PinLocator

logger = logging.getLogger("kicad_interface")

_IU_PER_MM = 10000  # KiCad schematic internal units per millimeter


def _to_iu(x_mm: float, y_mm: float) -> Tuple[int, int]:
    """Convert mm coordinates to KiCad internal units (integer)."""
    return (round(x_mm * _IU_PER_MM), round(y_mm * _IU_PER_MM))


def _parse_wires(schematic: Any) -> List[List[Tuple[int, int]]]:
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


def _parse_virtual_connections(
    schematic: Any, schematic_path: Any
) -> Tuple[Dict[Tuple[int, int], str], Dict[str, List[Tuple[int, int]]]]:
    """Return virtual connectivity from net labels and power symbols.

    Returns a tuple of:
      - point_to_label: Dict[Tuple[int,int], str] — IU position → label name
      - label_to_points: Dict[str, List[Tuple[int,int]]] — label name → list of IU positions
    """
    point_to_label: Dict[Tuple[int, int], str] = {}
    label_to_points: Dict[str, List[Tuple[int, int]]] = {}

    if hasattr(schematic, "label"):
        for label in schematic.label:
            try:
                if not hasattr(label, "value"):
                    continue
                name = label.value
                if not hasattr(label, "at") or not hasattr(label.at, "value"):
                    continue
                coords = label.at.value
                pt = _to_iu(float(coords[0]), float(coords[1]))
                point_to_label[pt] = name
                label_to_points.setdefault(name, []).append(pt)
            except Exception as e:
                logger.warning(f"Error parsing net label: {e}")

    if hasattr(schematic, "symbol"):
        locator = PinLocator()
        for symbol in schematic.symbol:
            try:
                if not hasattr(symbol, "property") or not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if not ref.startswith("#PWR"):
                    continue
                if ref.startswith("_TEMPLATE"):
                    continue
                if not hasattr(symbol.property, "Value"):
                    continue
                name = symbol.property.Value.value
                all_pins = locator.get_all_symbol_pins(Path(schematic_path), ref)
                if not all_pins or "1" not in all_pins:
                    continue
                pin_data = all_pins["1"]
                pt = _to_iu(float(pin_data[0]), float(pin_data[1]))
                point_to_label[pt] = name
                label_to_points.setdefault(name, []).append(pt)
            except Exception as e:
                logger.warning(f"Error parsing power symbol: {e}")

    return point_to_label, label_to_points


def _find_connected_wires(
    x_mm: float,
    y_mm: float,
    all_wires: List[List[Tuple[int, int]]],
    iu_to_wires: Dict[Tuple[int, int], Set[int]],
    adjacency: List[Set[int]],
    point_to_label: Optional[Dict[Tuple[int, int], str]] = None,
    label_to_points: Optional[Dict[str, List[Tuple[int, int]]]] = None,
) -> Tuple:
    """BFS from query point. Returns (visited wire indices, net IU points) or (None, None).

    Requires query point (x_mm, y_mm) to be exactly on a wire endpoint (exact IU match).
    """
    query_iu = _to_iu(x_mm, y_mm)

    # Find seed wires: exact IU match on the query endpoint
    seed_set = iu_to_wires.get(query_iu)
    if not seed_set:
        return (None, None)
    seed_indices: Set[int] = set(seed_set)

    # BFS flood-fill using pre-compiled adjacency
    visited: Set[int] = set(seed_indices)
    queue = list(seed_indices)
    net_points: Set[Tuple[int, int]] = set()
    for i in seed_indices:
        net_points.update(all_wires[i])

    seen_labels: Set[str] = set()
    while queue:
        wire_idx = queue.pop()
        for neighbor_idx in adjacency[wire_idx]:
            if neighbor_idx not in visited:
                visited.add(neighbor_idx)
                queue.append(neighbor_idx)
                net_points.update(all_wires[neighbor_idx])

        if point_to_label and label_to_points:
            for pt in all_wires[wire_idx]:
                label_name = point_to_label.get(pt)
                if label_name and label_name not in seen_labels:
                    seen_labels.add(label_name)
                    for other_pt in label_to_points.get(label_name, []):
                        if other_pt == pt:
                            continue
                        for idx in iu_to_wires.get(other_pt, set()):
                            if idx not in visited:
                                visited.add(idx)
                                queue.append(idx)
                                net_points.update(all_wires[idx])

    return (visited, net_points)


def _find_pins_on_net(
    net_points: Set[Tuple[int, int]],
    schematic_path: Any,
    schematic: Any,
) -> List[Dict]:
    """Find component pins that land on net points using exact IU matching.

    Returns a list of {"component": ref, "pin": pin_num} dicts.
    """

    def _on_net(px_mm: float, py_mm: float) -> bool:
        return _to_iu(px_mm, py_mm) in net_points

    locator = PinLocator()
    pins = []
    seen: Set[Tuple] = set()

    ref = None
    for symbol in schematic.symbol:
        try:
            if not hasattr(symbol, "property") or not hasattr(symbol.property, "Reference"):
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
            logger.warning(
                f"Error checking pins for {ref if ref is not None else '<unknown>'}: {e}"
            )

    return pins


def get_wire_connections(
    schematic: Any, schematic_path: str, x_mm: float, y_mm: float
) -> Optional[Dict]:
    """Find the net name and all component pins reachable from a point via connected wires.

    The query point (x_mm, y_mm) must be exactly on a wire endpoint or junction (exact IU match).
    Interior (mid-segment) points are not matched —
    use wire endpoint coordinates obtained from the schematic data.

    Net labels and power symbols are traversed: wires on the same named net are
    treated as connected even when they are not geometrically adjacent.

    Returns dict with keys:
      - "net": str or None (net label/power name, None if unnamed)
      - "pins": list of {"component": str, "pin": str}
      - "wires": list of {"start": {"x", "y"}, "end": {"x", "y"}} in mm
      - "query_point": {"x": float, "y": float}
    Or None if no wire endpoint found within tolerance of the query point.
    """
    all_wires = _parse_wires(schematic)
    query_point = {"x": x_mm, "y": y_mm}
    if not all_wires:
        return {"net": None, "pins": [], "wires": [], "query_point": query_point}

    adjacency, iu_to_wires = _build_adjacency(all_wires)

    point_to_label, label_to_points = _parse_virtual_connections(schematic, schematic_path)

    visited, net_points = _find_connected_wires(
        x_mm,
        y_mm,
        all_wires,
        iu_to_wires,
        adjacency,
        point_to_label=point_to_label,
        label_to_points=label_to_points,
    )
    if visited is None:
        return None

    # Resolve net name: first label anchor that falls on this net's IU points
    net: Optional[str] = None
    for pt in net_points:
        label = point_to_label.get(pt)
        if label is not None:
            net = label
            break

    wires_out = [
        {
            "start": {
                "x": all_wires[i][0][0] / _IU_PER_MM,
                "y": all_wires[i][0][1] / _IU_PER_MM,
            },
            "end": {
                "x": all_wires[i][-1][0] / _IU_PER_MM,
                "y": all_wires[i][-1][1] / _IU_PER_MM,
            },
        }
        for i in visited
    ]

    if not hasattr(schematic, "symbol"):
        return {"net": net, "pins": [], "wires": wires_out, "query_point": query_point}

    pins = _find_pins_on_net(net_points, schematic_path, schematic)
    return {"net": net, "pins": pins, "wires": wires_out, "query_point": query_point}


def count_pins_on_net(
    schematic: Any,
    schematic_path: str,
    net_name: str,
    all_wires: List[List[Tuple[int, int]]],
    iu_to_wires: Dict[Tuple[int, int], Set[int]],
    adjacency: List[Set[int]],
    point_to_label: Dict[Tuple[int, int], str],
    label_to_points: Dict[str, List[Tuple[int, int]]],
) -> int:
    """Count the number of component pins connected to the named net.

    A pin is counted if its IU coordinate falls on the wire-network reachable
    from any label anchor for *net_name*, or directly on a label anchor of that
    net (pin directly touching a label with no intervening wire).

    Returns the count of distinct (component, pin_num) pairs on this net.
    """
    label_positions = label_to_points.get(net_name, [])
    if not label_positions:
        return 0

    # Collect the union of all net-points across all label positions for this net
    all_net_points: Set[Tuple[int, int]] = set()
    for lx, ly in label_positions:
        # Include the label anchor itself so pins directly at the label count
        all_net_points.add((lx, ly))
        # Trace from this label position into the wire graph
        x_mm = lx / _IU_PER_MM
        y_mm = ly / _IU_PER_MM
        visited, net_points = _find_connected_wires(
            x_mm,
            y_mm,
            all_wires,
            iu_to_wires,
            adjacency,
            point_to_label=point_to_label,
            label_to_points=label_to_points,
        )
        if net_points:
            all_net_points |= net_points

    if not hasattr(schematic, "symbol"):
        return 0

    locator = PinLocator()
    seen: Set[Tuple[str, str]] = set()
    ref = None
    for symbol in schematic.symbol:
        try:
            if not hasattr(symbol, "property") or not hasattr(symbol.property, "Reference"):
                continue
            ref = symbol.property.Reference.value
            if ref.startswith("_TEMPLATE"):
                continue
            all_pins = locator.get_all_symbol_pins(Path(schematic_path), ref)
            if not all_pins:
                continue
            for pin_num, pin_data in all_pins.items():
                pin_iu = _to_iu(float(pin_data[0]), float(pin_data[1]))
                if pin_iu in all_net_points:
                    key = (ref, pin_num)
                    if key not in seen:
                        seen.add(key)
        except Exception as e:
            logger.warning(
                f"Error checking pins for {ref if ref is not None else '<unknown>'}: {e}"
            )

    return len(seen)


def list_floating_labels(schematic: Any, schematic_path: str) -> List[Dict[str, Any]]:
    """Return net labels that are not connected to any component pin.

    A label is "floating" when no component pin's IU coordinate falls on the
    wire-network reachable from the label's anchor position.  These labels are
    likely placed off-grid or incorrectly positioned and will cause ERC errors.

    Returns a list of dicts with keys:
      - "name": str   — the net label text
      - "x": float    — label X position in mm
      - "y": float    — label Y position in mm
      - "type": str   — "label" or "global_label"
    """
    all_wires = _parse_wires(schematic)
    if all_wires:
        adjacency, iu_to_wires = _build_adjacency(all_wires)
    else:
        adjacency = []
        iu_to_wires = {}

    point_to_label, label_to_points = _parse_virtual_connections(schematic, schematic_path)

    # Build a set of all pin IU positions for fast lookup
    pin_iu_set: Set[Tuple[int, int]] = set()
    if hasattr(schematic, "symbol"):
        locator = PinLocator()
        for symbol in schematic.symbol:
            try:
                if not hasattr(symbol, "property") or not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue
                all_pins = locator.get_all_symbol_pins(Path(schematic_path), ref)
                if not all_pins:
                    continue
                for pin_data in all_pins.values():
                    pin_iu_set.add(_to_iu(float(pin_data[0]), float(pin_data[1])))
            except Exception as e:
                logger.warning(f"Error reading pins for floating-label check: {e}")

    floating: List[Dict[str, Any]] = []

    if not hasattr(schematic, "label"):
        return floating

    for label in schematic.label:
        try:
            if not hasattr(label, "value"):
                continue
            name = label.value
            if not hasattr(label, "at") or not hasattr(label.at, "value"):
                continue
            coords = label.at.value
            lx_mm = float(coords[0])
            ly_mm = float(coords[1])
            label_iu = _to_iu(lx_mm, ly_mm)

            # Check if the label anchor itself is a pin position
            if label_iu in pin_iu_set:
                continue

            # Trace the wire-network from this label and check for pins
            if all_wires:
                _, net_points = _find_connected_wires(
                    lx_mm,
                    ly_mm,
                    all_wires,
                    iu_to_wires,
                    adjacency,
                    point_to_label=point_to_label,
                    label_to_points=label_to_points,
                )
            else:
                net_points = None

            if net_points is not None and net_points & pin_iu_set:
                continue  # at least one pin on this net

            floating.append({"name": name, "x": lx_mm, "y": ly_mm, "type": "label"})

        except Exception as e:
            logger.warning(f"Error checking label for floating status: {e}")

    return floating


def get_net_at_point(
    schematic: Any, schematic_path: str, x_mm: float, y_mm: float
) -> Dict[str, Any]:
    """Return the net name at the given coordinate, or null if none found.

    Checks net label positions first (exact IU match within tolerance), then
    wire endpoints. Returns a dict with keys:
      - "net_name": str or None
      - "position": {"x": float, "y": float}
      - "source": "net_label" | "wire_endpoint" | None
    """
    query_iu = _to_iu(x_mm, y_mm)
    position = {"x": x_mm, "y": y_mm}

    # Build label map from schematic
    point_to_label, _ = _parse_virtual_connections(schematic, schematic_path)

    # Check if query point is exactly on a net label / power symbol position
    label_name = point_to_label.get(query_iu)
    if label_name is not None:
        return {"net_name": label_name, "position": position, "source": "net_label"}

    # Check if query point is on a wire endpoint
    all_wires = _parse_wires(schematic) if hasattr(schematic, "wire") else []
    if all_wires:
        adjacency, iu_to_wires = _build_adjacency(all_wires)
        if query_iu in iu_to_wires:
            # Found a wire endpoint — trace the net to get the name
            visited, net_points = _find_connected_wires(
                x_mm,
                y_mm,
                all_wires,
                iu_to_wires,
                adjacency,
                point_to_label=point_to_label,
                label_to_points=None,
            )
            if visited is not None:
                net: Optional[str] = None
                if net_points:
                    for pt in net_points:
                        net = point_to_label.get(pt)
                        if net is not None:
                            break
                return {"net_name": net, "position": position, "source": "wire_endpoint"}

    return {"net_name": None, "position": position, "source": None}
