"""
Wire Connectivity Analysis for KiCad Schematics

Traces wire networks from a point and finds connected component pins.
Uses KiCad's internal integer unit system (10,000 IU per mm) for exact
coordinate matching, mirroring KiCad's own connectivity algorithm.

Supports hierarchical (multi-sheet) schematics by recursively discovering
sub-sheet files and bridging nets via hierarchical labels / sheet pins.
"""

import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sexpdata
from commands.pin_locator import PinLocator
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

_IU_PER_MM = 10000  # KiCad schematic internal units per millimeter
_SEXP_CACHE_MAX_SIZE = 128
_SEXP_CACHE: "OrderedDict[str, Tuple[int, int, list]]" = OrderedDict()


@dataclass
class SheetConnectivity:
    """Parsed schematic data reused while answering a single net-list request."""

    schematic: Any
    schematic_path: str
    sexp: list
    all_wires: List[List[Tuple[int, int]]]
    adjacency: List[Set[int]]
    iu_to_wires: Dict[Tuple[int, int], Set[int]]
    point_to_label: Dict[Tuple[int, int], str]
    label_to_points: Dict[str, List[Tuple[int, int]]]
    hierarchical_label_to_points: Dict[str, List[Tuple[int, int]]]
    symbol_instances: List[Dict]


@dataclass
class SheetPinReference:
    """A sheet pin on a parent sheet symbol."""

    name: str
    position: Tuple[int, int]


@dataclass
class SheetReference:
    """A concrete sheet instance referenced by a parent schematic."""

    sheet_name: str
    sheet_path: str
    instance_path: str
    pins: List[SheetPinReference]


@dataclass
class SheetTraversal:
    """Prepared sheet state plus instance-local net-name mapping."""

    state: SheetConnectivity
    instance_path: str
    net_name_map: Dict[str, Set[str]]


def _to_iu(x_mm: float, y_mm: float) -> Tuple[int, int]:
    """Convert mm coordinates to KiCad internal units (integer)."""
    return (round(x_mm * _IU_PER_MM), round(y_mm * _IU_PER_MM))


def _canonical_schematic_path(schematic_path: Any) -> str:
    """Return a stable absolute path string for cache keys and de-duplication."""
    return str(Path(schematic_path).expanduser().resolve())


def _clear_sexp_cache() -> None:
    """Clear the module-level S-expression cache used by tests and long sessions."""
    _SEXP_CACHE.clear()


def _load_sexp(schematic_path: str) -> list:
    """Load and cache the raw sexpdata tree for a schematic file."""
    canonical_path = _canonical_schematic_path(schematic_path)
    path = Path(canonical_path)
    stat_result = path.stat()
    cached = _SEXP_CACHE.get(canonical_path)
    if cached and cached[0] == stat_result.st_mtime_ns and cached[1] == stat_result.st_size:
        _SEXP_CACHE.move_to_end(canonical_path)
        return cached[2]

    with open(path, "r", encoding="utf-8") as schematic_file:
        sexp = sexpdata.loads(schematic_file.read())

    _SEXP_CACHE[canonical_path] = (stat_result.st_mtime_ns, stat_result.st_size, sexp)
    _SEXP_CACHE.move_to_end(canonical_path)
    while len(_SEXP_CACHE) > _SEXP_CACHE_MAX_SIZE:
        _SEXP_CACHE.popitem(last=False)
    return sexp


def _parse_wires_sexp(sexp: list) -> List[List[Tuple[int, int]]]:
    """Extract wire endpoints from raw sexpdata as IU tuples.

    Parses ``(wire (pts (xy X Y) (xy X Y)))`` directly, bypassing
    kicad-skip which may silently drop elements.
    """
    all_wires: List[List[Tuple[int, int]]] = []
    for item in sexp:
        if not isinstance(item, list) or not item:
            continue
        if item[0] != Symbol("wire"):
            continue
        for sub in item:
            if not isinstance(sub, list) or not sub or sub[0] != Symbol("pts"):
                continue
            pts: List[Tuple[int, int]] = []
            for xy_elem in sub[1:]:
                if isinstance(xy_elem, list) and len(xy_elem) >= 3 and xy_elem[0] == Symbol("xy"):
                    pts.append(_to_iu(float(xy_elem[1]), float(xy_elem[2])))
            if len(pts) >= 2:
                all_wires.append(pts)
    return all_wires


def _parse_wires(schematic: Any) -> List[List[Tuple[int, int]]]:
    """Extract wire endpoints from a kicad-skip schematic object as IU tuples.

    Used by the single-sheet handlers (``get_wire_connections``,
    ``list_floating_labels``, ``get_net_at_point``) which receive a kicad-skip
    schematic. Multi-sheet code paths use :func:`_parse_wires_sexp` instead.
    """
    all_wires: List[List[Tuple[int, int]]] = []
    if not hasattr(schematic, "wire"):
        return all_wires
    for wire in schematic.wire:
        if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
            pts: List[Tuple[int, int]] = []
            for point in wire.pts.xy:
                if hasattr(point, "value"):
                    pts.append(_to_iu(float(point.value[0]), float(point.value[1])))
            if len(pts) >= 2:
                all_wires.append(pts)
    return all_wires


def _parse_labels_for_types_sexp(
    sexp: list,
    label_types: Set[Symbol],
) -> Tuple[Dict[Tuple[int, int], str], Dict[str, List[Tuple[int, int]]]]:
    """Parse the requested label S-expression types into IU-coordinate maps."""
    point_to_label: Dict[Tuple[int, int], str] = {}
    label_to_points: Dict[str, List[Tuple[int, int]]] = {}

    for item in sexp:
        if not isinstance(item, list) or len(item) < 2:
            continue
        if item[0] not in label_types:
            continue
        name = str(item[1]).strip('"')
        for sub in item[2:]:
            if isinstance(sub, list) and sub and sub[0] == Symbol("at") and len(sub) >= 3:
                pt = _to_iu(float(sub[1]), float(sub[2]))
                point_to_label[pt] = name
                label_to_points.setdefault(name, []).append(pt)
                logger.debug(
                    f"Parsed {item[0]} '{name}' at IU {pt} "
                    f"(mm {float(sub[1])}, {float(sub[2])})"
                )
                break

    return point_to_label, label_to_points


def _parse_labels_sexp(
    sexp: list,
) -> Tuple[Dict[Tuple[int, int], str], Dict[str, List[Tuple[int, int]]]]:
    """Parse label, global_label, and hierarchical_label from raw sexpdata.

    Returns (point_to_label, label_to_points) in IU coordinates.
    Bypasses kicad-skip which may not iterate all labels correctly.
    """
    return _parse_labels_for_types_sexp(
        sexp,
        {Symbol("label"), Symbol("global_label"), Symbol("hierarchical_label")},
    )


def _point_on_segment(px: int, py: int, ax: int, ay: int, bx: int, by: int) -> bool:
    """Check if point (px,py) lies strictly between endpoints (ax,ay)-(bx,by).

    Only handles axis-aligned (horizontal/vertical) segments, which covers
    virtually all KiCad schematic wires.
    """
    if ay == by == py:
        lo, hi = (ax, bx) if ax < bx else (bx, ax)
        return lo < px < hi
    if ax == bx == px:
        lo, hi = (ay, by) if ay < by else (by, ay)
        return lo < py < hi
    return False


def _build_adjacency(
    all_wires: List[List[Tuple[int, int]]],
) -> Tuple[List[Set[int]], Dict[Tuple[int, int], Set[int]]]:
    """Build wire adjacency using exact IU coordinate matching.

    Wires that share an endpoint are adjacent — this naturally handles
    junctions since all wires meeting at the same point get connected.

    Also detects T-junctions where a wire endpoint falls on the interior of
    another wire segment (common when KiCad doesn't split the longer wire).

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

    # Detect T-junctions: a wire endpoint landing on the interior of another
    # wire segment.  When found, register the endpoint against that segment's
    # wire index so adjacency is established through the shared point.
    all_endpoints = list(iu_to_wires.keys())
    for i, pts in enumerate(all_wires):
        if len(pts) < 2:
            continue
        ax, ay = pts[0]
        bx, by = pts[-1]
        for ep in all_endpoints:
            if ep == (ax, ay) or ep == (bx, by):
                continue
            if _point_on_segment(ep[0], ep[1], ax, ay, bx, by):
                iu_to_wires[ep].add(i)

    # Wires that share an IU endpoint (including T-junction points) are adjacent
    adjacency: List[Set[int]] = [set() for _ in range(len(all_wires))]
    for wire_set in iu_to_wires.values():
        wire_list = list(wire_set)
        for a in wire_list:
            for b in wire_list:
                if a != b:
                    adjacency[a].add(b)

    return adjacency, iu_to_wires


def _parse_virtual_connections(
    schematic: Any,
    schematic_path: Any,
    sexp: Optional[list] = None,
    locator: Optional[PinLocator] = None,
) -> Tuple[Dict[Tuple[int, int], str], Dict[str, List[Tuple[int, int]]]]:
    """Return virtual connectivity from net labels, global labels, and power symbols.

    Labels (label, global_label, hierarchical_label) are parsed directly from the
    raw sexpdata tree for reliability — kicad-skip's collection iteration can
    silently miss elements. If the sexp tree cannot be loaded (e.g. the path
    does not exist in unit tests), falls back to kicad-skip's ``schematic.label``
    so callers that pass a mock schematic still get the labels they registered.

    Power symbols are still resolved via kicad-skip's symbol collection.

    Returns a tuple of:
      - point_to_label: Dict[Tuple[int,int], str] — IU position → label name
      - label_to_points: Dict[str, List[Tuple[int,int]]] — label name → list of IU positions
    """
    point_to_label: Dict[Tuple[int, int], str] = {}
    label_to_points: Dict[str, List[Tuple[int, int]]] = {}

    if sexp is None:
        try:
            sexp = _load_sexp(schematic_path)
        except Exception as e:
            logger.debug(
                f"Could not load sexp for {schematic_path} ({e}); "
                "falling back to kicad-skip label collection"
            )
            sexp = None

    if sexp is not None:
        point_to_label, label_to_points = _parse_labels_sexp(sexp)
        logger.debug(
            f"Parsed {sum(len(v) for v in label_to_points.values())} label instances "
            f"across {len(label_to_points)} unique net names from {schematic_path}"
        )
    else:
        for attr in ("label", "global_label"):
            if not hasattr(schematic, attr):
                continue
            for label in getattr(schematic, attr):
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
        pin_locator = locator or PinLocator()
        for symbol in schematic.symbol:
            try:
                if not hasattr(symbol, "property") or not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if not (ref.startswith("#PWR") or ref.startswith("#FLG")):
                    continue
                if ref.startswith("_TEMPLATE"):
                    continue
                if not hasattr(symbol.property, "Value"):
                    continue
                name = symbol.property.Value.value
                all_pins = pin_locator.get_all_symbol_pins(Path(schematic_path), ref)
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

    First tries exact IU match on a wire endpoint, then falls back to
    checking if the point lies on the interior of any wire segment
    (handles labels placed mid-wire).
    """
    query_iu = _to_iu(x_mm, y_mm)

    # Find seed wires: exact IU match on the query endpoint
    seed_set = iu_to_wires.get(query_iu)
    if not seed_set:
        # Fallback: check if query point lies on the interior of any wire segment
        px, py = query_iu
        for i, pts in enumerate(all_wires):
            if len(pts) >= 2 and _point_on_segment(
                px, py, pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]
            ):
                seed_set = {i}
                iu_to_wires.setdefault(query_iu, set()).add(i)
                break
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


def _parse_symbol_instances_sexp(
    sexp: list,
) -> List[Dict]:
    """Parse all placed symbol instances from raw sexpdata.

    Returns a list of dicts with keys: ref, lib_id, x, y, rotation, mirror_x, mirror_y.
    Bypasses kicad-skip's symbol collection which may miss elements.
    """
    instances: List[Dict] = []
    for item in sexp:
        if not isinstance(item, list) or not item or item[0] != Symbol("symbol"):
            continue

        inst: Dict = {
            "ref": None,
            "lib_id": None,
            "x": 0.0,
            "y": 0.0,
            "rotation": 0.0,
            "mirror_x": False,
            "mirror_y": False,
        }

        for sub in item[1:]:
            if not isinstance(sub, list) or not sub:
                continue
            tag = sub[0]
            if tag == Symbol("lib_id") and len(sub) >= 2:
                inst["lib_id"] = str(sub[1]).strip('"')
            elif tag == Symbol("at") and len(sub) >= 3:
                inst["x"] = float(sub[1])
                inst["y"] = float(sub[2])
                if len(sub) >= 4:
                    inst["rotation"] = float(sub[3])
            elif tag == Symbol("mirror"):
                if len(sub) >= 2:
                    mv = str(sub[1]).strip('"')
                    if mv == "x":
                        inst["mirror_x"] = True
                    elif mv == "y":
                        inst["mirror_y"] = True
            elif tag == Symbol("property") and len(sub) >= 3:
                prop_name = str(sub[1]).strip('"')
                if prop_name == "Reference":
                    inst["ref"] = str(sub[2]).strip('"')

        if inst["ref"] and inst["lib_id"]:
            instances.append(inst)

    return instances


def _find_pins_on_net(
    net_points: Set[Tuple[int, int]],
    schematic_path: Any,
    schematic: Any,
    sexp: Optional[list] = None,
    locator: Optional[PinLocator] = None,
    symbol_instances: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Find component pins that land on net points.

    Parses symbol instances directly from sexpdata to avoid kicad-skip's
    collection iteration issues.  Uses exact IU matching first, then falls
    back to a ±1 IU tolerance for floating-point rounding edge cases.

    Returns a list of {"component": ref, "pin": pin_num} dicts.
    """

    def _on_net(px_mm: float, py_mm: float) -> bool:
        pt = _to_iu(px_mm, py_mm)
        if pt in net_points:
            return True
        ix, iy = pt
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (ix + dx, iy + dy) in net_points:
                    return True
        return False

    if sexp is None:
        sexp = _load_sexp(schematic_path)

    logger.debug(f"Searching {len(net_points)} net points for matching pins")

    pin_locator = locator or PinLocator()
    instances = (
        symbol_instances if symbol_instances is not None else _parse_symbol_instances_sexp(sexp)
    )
    logger.debug(f"Found {len(instances)} symbol instances via sexpdata")

    pins: List[Dict] = []
    seen: Set[Tuple[str, str]] = set()

    for inst in instances:
        ref = inst["ref"]
        try:
            if ref.startswith("_TEMPLATE") or ref.startswith("#"):
                continue

            lib_id = inst["lib_id"]
            pin_defs = pin_locator.get_symbol_pins(Path(schematic_path), lib_id)
            if not pin_defs:
                logger.debug(f"  {ref}: no pin definitions for lib_id={lib_id}")
                continue

            sym_x = inst["x"]
            sym_y = inst["y"]
            sym_rot = inst["rotation"]
            mirror_x = inst["mirror_x"]
            mirror_y = inst["mirror_y"]

            for pin_num, pdata in pin_defs.items():
                px, py = pdata["x"], pdata["y"]
                # y-negate: lib_symbols y-up → schematic y-down
                py = -py
                if mirror_x:
                    py = -py
                if mirror_y:
                    px = -px
                if sym_rot != 0:
                    px, py = pin_locator.rotate_point(px, py, sym_rot)
                abs_x = sym_x + px
                abs_y = sym_y + py
                if _on_net(abs_x, abs_y):
                    key = (ref, pin_num)
                    if key not in seen:
                        seen.add(key)
                        pins.append({"component": ref, "pin": pin_num})
        except Exception as e:
            logger.warning(f"Error checking pins for {ref}: {e}")

    return pins


def _build_sheet_connectivity(
    schematic: Any,
    schematic_path: str,
    locator: Optional[PinLocator] = None,
) -> Optional[SheetConnectivity]:
    """Parse a schematic sheet once and reuse the result across net queries."""
    try:
        canonical_path = _canonical_schematic_path(schematic_path)
        sexp = _load_sexp(canonical_path)
    except Exception as e:
        logger.warning(f"Could not load sexp for {schematic_path}: {e}")
        return None

    all_wires = _parse_wires_sexp(sexp)
    logger.debug(f"Parsed {len(all_wires)} wires from {canonical_path}")

    if all_wires:
        adjacency, iu_to_wires = _build_adjacency(all_wires)
    else:
        adjacency, iu_to_wires = [], {}

    point_to_label, label_to_points = _parse_virtual_connections(
        schematic,
        canonical_path,
        sexp=sexp,
        locator=locator,
    )
    _, hierarchical_label_to_points = _parse_labels_for_types_sexp(
        sexp,
        {Symbol("hierarchical_label")},
    )
    symbol_instances = _parse_symbol_instances_sexp(sexp)

    return SheetConnectivity(
        schematic=schematic,
        schematic_path=canonical_path,
        sexp=sexp,
        all_wires=all_wires,
        adjacency=adjacency,
        iu_to_wires=iu_to_wires,
        point_to_label=point_to_label,
        label_to_points=label_to_points,
        hierarchical_label_to_points=hierarchical_label_to_points,
        symbol_instances=symbol_instances,
    )


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
    return len(
        find_pin_connections_on_net(
            schematic,
            schematic_path,
            net_name,
            all_wires,
            iu_to_wires,
            adjacency,
            point_to_label,
            label_to_points,
        )
    )


def _collect_net_points_for_net(
    net_name: str,
    all_wires: List[List[Tuple[int, int]]],
    iu_to_wires: Dict[Tuple[int, int], Set[int]],
    adjacency: List[Set[int]],
    point_to_label: Dict[Tuple[int, int], str],
    label_to_points: Dict[str, List[Tuple[int, int]]],
) -> Set[Tuple[int, int]]:
    """Collect all schematic points reachable from labels for a named net."""
    all_net_points: Set[Tuple[int, int]] = set()
    for lx, ly in label_to_points.get(net_name, []):
        all_net_points.add((lx, ly))
        _visited, net_points = _find_connected_wires(
            lx / _IU_PER_MM,
            ly / _IU_PER_MM,
            all_wires,
            iu_to_wires,
            adjacency,
            point_to_label=point_to_label,
            label_to_points=label_to_points,
        )
        if net_points:
            all_net_points |= net_points
    return all_net_points


def find_pin_connections_on_net(
    schematic: Any,
    schematic_path: str,
    net_name: str,
    all_wires: List[List[Tuple[int, int]]],
    iu_to_wires: Dict[Tuple[int, int], Set[int]],
    adjacency: List[Set[int]],
    point_to_label: Dict[Tuple[int, int], str],
    label_to_points: Dict[str, List[Tuple[int, int]]],
    locator: Optional[PinLocator] = None,
) -> List[Dict]:
    """Return component-pin connections for a named net using kicad-skip objects."""
    all_net_points = _collect_net_points_for_net(
        net_name,
        all_wires,
        iu_to_wires,
        adjacency,
        point_to_label,
        label_to_points,
    )
    if not all_net_points or not hasattr(schematic, "symbol"):
        return []

    pin_locator = locator or PinLocator()
    try:
        return _find_pins_on_net(
            all_net_points,
            schematic_path,
            schematic,
            locator=pin_locator,
        )
    except Exception as e:
        logger.debug(
            f"Could not use sexp pin matching for {schematic_path}; "
            f"falling back to kicad-skip pins: {e}"
        )

    seen: Set[Tuple[str, str]] = set()
    connections: List[Dict] = []
    ref = None
    for symbol in schematic.symbol:
        try:
            if not hasattr(symbol, "property") or not hasattr(symbol.property, "Reference"):
                continue
            ref = symbol.property.Reference.value
            if ref.startswith("_TEMPLATE"):
                continue
            all_pins = pin_locator.get_all_symbol_pins(Path(schematic_path), ref)
            if not all_pins:
                continue
            for pin_num, pin_data in all_pins.items():
                pin_iu = _to_iu(float(pin_data[0]), float(pin_data[1]))
                if pin_iu in all_net_points:
                    key = (ref, pin_num)
                    if key not in seen:
                        seen.add(key)
                        connections.append({"component": ref, "pin": pin_num})
        except Exception as e:
            logger.warning(
                f"Error checking pins for {ref if ref is not None else '<unknown>'}: {e}"
            )

    return connections


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


# ---------------------------------------------------------------------------
# Multi-sheet (hierarchical) connectivity
#
# The functions below extend single-sheet net tracing to hierarchical KiCad
# projects: ``get_connections_for_net`` discovers and recurses into every
# referenced sub-sheet, processing each one with ``_process_single_sheet``
# (which uses the sexp-based parsers above for reliability across all label
# kinds, including ``hierarchical_label``).
# ---------------------------------------------------------------------------


def _sexp_text(value: Any) -> str:
    """Return a KiCad S-expression atom as plain text."""
    return str(value).strip('"')


def _join_instance_path(parent_instance_path: str, sheet_name: str, index: int) -> str:
    """Build a stable logical sheet-instance path for de-duplication."""
    token = sheet_name or f"sheet{index}"
    parent = parent_instance_path.rstrip("/")
    if not parent:
        return f"/{token}"
    return f"{parent}/{token}"


def _parse_sheet_references(
    schematic_path: str,
    instance_path: str = "/",
    sexp: Optional[list] = None,
) -> List[SheetReference]:
    """Parse concrete child sheet instances from a parent schematic."""
    canonical_path = _canonical_schematic_path(schematic_path)
    parent_dir = Path(canonical_path).parent
    if sexp is None:
        sexp = _load_sexp(canonical_path)

    result: List[SheetReference] = []
    sheet_index = 0
    for item in sexp:
        if not isinstance(item, list) or not item or item[0] != Symbol("sheet"):
            continue
        sheet_index += 1
        sheet_name = ""
        sheet_file = ""
        pins: List[SheetPinReference] = []
        for sub in item[1:]:
            if not isinstance(sub, list) or not sub:
                continue
            tag = sub[0]
            if tag == Symbol("property") and len(sub) >= 3:
                prop_name = _sexp_text(sub[1])
                if prop_name == "Sheetname":
                    sheet_name = _sexp_text(sub[2])
                elif prop_name == "Sheetfile":
                    sheet_file = _sexp_text(sub[2])
            elif tag == Symbol("pin") and len(sub) >= 2:
                pin_name = _sexp_text(sub[1])
                for pin_part in sub[2:]:
                    if (
                        isinstance(pin_part, list)
                        and len(pin_part) >= 3
                        and pin_part[0] == Symbol("at")
                    ):
                        pins.append(
                            SheetPinReference(
                                name=pin_name,
                                position=_to_iu(float(pin_part[1]), float(pin_part[2])),
                            )
                        )
                        break

        if not sheet_file:
            continue
        sheet_path = parent_dir / sheet_file
        if not sheet_path.exists():
            logger.warning(f"Sub-sheet not found: {sheet_path}")
            continue
        result.append(
            SheetReference(
                sheet_name=sheet_name,
                sheet_path=str(sheet_path.resolve()),
                instance_path=_join_instance_path(instance_path, sheet_name, sheet_index),
                pins=pins,
            )
        )
    return result


def _discover_sub_sheets(schematic_path: str, _seen: Optional[Set[str]] = None) -> List[str]:
    """Recursively discover all sub-sheet .kicad_sch files referenced by the schematic.

    Returns a list of absolute paths to sub-sheet files (does NOT include the
    top-level schematic_path itself).
    """
    canonical_path = _canonical_schematic_path(schematic_path)
    if _seen is None:
        _seen = {canonical_path}

    parent_dir = Path(canonical_path).parent
    result: List[str] = []
    try:
        sexp = _load_sexp(canonical_path)
    except Exception as e:
        logger.warning(f"Could not parse {canonical_path} for sub-sheets: {e}")
        return result

    for item in sexp:
        if not isinstance(item, list) or not item or item[0] != Symbol("sheet"):
            continue
        for sub in item:
            if not isinstance(sub, list) or len(sub) < 3:
                continue
            if sub[0] != Symbol("property"):
                continue
            prop_name = str(sub[1]).strip('"')
            if prop_name == "Sheetfile":
                sheet_file = str(sub[2]).strip('"')
                sheet_path = parent_dir / sheet_file
                if sheet_path.exists():
                    abs_path = str(sheet_path.resolve())
                    if abs_path in _seen:
                        continue
                    _seen.add(abs_path)
                    result.append(abs_path)
                    result.extend(_discover_sub_sheets(abs_path, _seen))
                else:
                    logger.warning(f"Sub-sheet not found: {sheet_path}")
    return result


def _identity_net_name_map(state: SheetConnectivity) -> Dict[str, Set[str]]:
    """Map each public net name on a sheet to the same local label name."""
    return {name: {name} for name in state.label_to_points}


def _external_names_for_local_net(
    local_net_name: str,
    net_name_map: Dict[str, Set[str]],
) -> List[str]:
    """Return public net names represented by a local sheet net."""
    external_names = [
        external_name
        for external_name, local_names in net_name_map.items()
        if local_net_name in local_names
    ]
    return external_names or [local_net_name]


def _label_point_touches_wires(
    label_point: Tuple[int, int],
    all_wires: List[List[Tuple[int, int]]],
    wire_indices: Set[int],
) -> bool:
    """Return whether a label point lies on any visited wire segment."""
    if label_point in {pt for idx in wire_indices for pt in all_wires[idx]}:
        return True
    for wire_idx in wire_indices:
        pts = all_wires[wire_idx]
        if len(pts) >= 2 and _point_on_segment(
            label_point[0],
            label_point[1],
            pts[0][0],
            pts[0][1],
            pts[-1][0],
            pts[-1][1],
        ):
            return True
    return False


def _local_net_names_at_iu_point(
    state: SheetConnectivity,
    point: Tuple[int, int],
) -> Set[str]:
    """Resolve all local label names on the net at a sheet-pin coordinate."""
    local_net_names: Set[str] = set()
    direct_label = state.point_to_label.get(point)
    if direct_label is not None:
        local_net_names.add(direct_label)

    visited, net_points = _find_connected_wires(
        point[0] / _IU_PER_MM,
        point[1] / _IU_PER_MM,
        state.all_wires,
        state.iu_to_wires,
        state.adjacency,
        point_to_label=state.point_to_label,
        label_to_points=state.label_to_points,
    )
    if not net_points or visited is None:
        return local_net_names

    for label_name, label_points in state.label_to_points.items():
        for label_point in label_points:
            if label_point in net_points or _label_point_touches_wires(
                label_point,
                state.all_wires,
                visited,
            ):
                local_net_names.add(label_name)
                break
    return local_net_names


def _local_net_names_for_label(
    state: SheetConnectivity,
    label_name: str,
) -> Set[str]:
    """Resolve every local label name electrically tied to a named label."""
    local_net_names = {label_name}
    for label_point in state.label_to_points.get(label_name, []):
        local_net_names.update(_local_net_names_at_iu_point(state, label_point))
    return local_net_names


def _build_child_net_name_map(
    parent_state: SheetConnectivity,
    parent_net_name_map: Dict[str, Set[str]],
    sheet_ref: SheetReference,
    child_state: SheetConnectivity,
) -> Dict[str, Set[str]]:
    """Map public parent net names to child-local hierarchical label names."""
    child_map = _identity_net_name_map(child_state)
    for sheet_pin in sheet_ref.pins:
        parent_local_nets = _local_net_names_at_iu_point(parent_state, sheet_pin.position)
        if not parent_local_nets:
            continue
        external_nets: Set[str] = set()
        for parent_local_net in parent_local_nets:
            external_nets.update(
                _external_names_for_local_net(parent_local_net, parent_net_name_map)
            )
        child_local_nets = _local_net_names_for_label(child_state, sheet_pin.name)
        for external_net in external_nets:
            child_map.setdefault(external_net, set()).update(child_local_nets)
            for child_local_net in child_local_nets:
                if external_net == child_local_net:
                    continue
                identity_names = child_map.get(child_local_net)
                if identity_names is not None:
                    identity_names.discard(child_local_net)
                    if not identity_names:
                        del child_map[child_local_net]
    return child_map


def collect_sheet_traversals(
    root_schematic: Any,
    schematic_path: str,
    locator: Optional[PinLocator] = None,
) -> List[SheetTraversal]:
    """Build per-instance traversal states while caching parsed data per file."""
    from skip import Schematic as SkipSchematic

    pin_locator = locator or PinLocator()
    state_cache: Dict[str, Optional[SheetConnectivity]] = {}
    schematic_cache: Dict[str, Any] = {}
    traversals: List[SheetTraversal] = []

    root_path = _canonical_schematic_path(schematic_path)
    schematic_cache[root_path] = root_schematic

    def _load_schematic(canonical_path: str) -> Any:
        cached = schematic_cache.get(canonical_path)
        if cached is not None:
            return cached
        loaded = SkipSchematic(canonical_path)
        schematic_cache[canonical_path] = loaded
        return loaded

    def _state_for(canonical_path: str, schematic: Any) -> Optional[SheetConnectivity]:
        if canonical_path not in state_cache:
            state_cache[canonical_path] = _build_sheet_connectivity(
                schematic,
                canonical_path,
                locator=pin_locator,
            )
        return state_cache[canonical_path]

    def _visit(
        state: SheetConnectivity,
        instance_path: str,
        net_name_map: Dict[str, Set[str]],
        file_stack: Set[str],
    ) -> None:
        traversals.append(
            SheetTraversal(
                state=state,
                instance_path=instance_path,
                net_name_map=net_name_map,
            )
        )
        for sheet_ref in _parse_sheet_references(
            state.schematic_path,
            instance_path=instance_path,
            sexp=state.sexp,
        ):
            child_path = _canonical_schematic_path(sheet_ref.sheet_path)
            if child_path in file_stack:
                logger.warning(f"Skipping recursive sheet reference: {child_path}")
                continue
            try:
                child_schematic = _load_schematic(child_path)
                child_state = _state_for(child_path, child_schematic)
                if child_state is None:
                    continue
                child_map = _build_child_net_name_map(
                    state,
                    net_name_map,
                    sheet_ref,
                    child_state,
                )
                _visit(
                    child_state,
                    sheet_ref.instance_path,
                    child_map,
                    {*file_stack, child_path},
                )
            except Exception as e:
                logger.warning(f"Error reading sub-sheet {sheet_ref.sheet_path}: {e}")

    root_state = _state_for(root_path, root_schematic)
    if root_state is None:
        return []

    _visit(root_state, "/", _identity_net_name_map(root_state), {root_path})
    return traversals


def pins_for_traversal_net(
    traversal: SheetTraversal,
    net_name: str,
    locator: Optional[PinLocator] = None,
) -> List[Dict]:
    """Return pins for a public net name on one concrete sheet instance."""
    pins: List[Dict] = []
    for local_net_name in sorted(traversal.net_name_map.get(net_name, set())):
        for pin in _process_single_sheet(
            traversal.state.schematic,
            traversal.state.schematic_path,
            local_net_name,
            sheet_state=traversal.state,
            locator=locator,
        ):
            annotated_pin = dict(pin)
            if traversal.instance_path != "/":
                annotated_pin.setdefault("sheet_instance", traversal.instance_path)
                annotated_pin.setdefault("sheet_path", traversal.state.schematic_path)
            pins.append(annotated_pin)
    return pins


def _parse_hierarchical_labels_sexp(
    schematic_path: str,
) -> Dict[str, List[Tuple[int, int]]]:
    """Parse hierarchical_label elements from a .kicad_sch file using sexpdata.

    kicad-skip does not expose hierarchical labels, so we parse them directly.
    Returns {label_name: [iu_position, ...]}.
    """
    result: Dict[str, List[Tuple[int, int]]] = {}
    try:
        sexp = _load_sexp(schematic_path)
    except Exception as e:
        logger.warning(f"Could not parse {schematic_path} for hierarchical labels: {e}")
        return result

    for item in sexp:
        if not isinstance(item, list) or not item:
            continue
        if item[0] != Symbol("hierarchical_label"):
            continue
        if len(item) < 2:
            continue
        name = str(item[1]).strip('"')
        for sub in item:
            if isinstance(sub, list) and sub and sub[0] == Symbol("at") and len(sub) >= 3:
                pt = _to_iu(float(sub[1]), float(sub[2]))
                result.setdefault(name, []).append(pt)
                break
    return result


def _process_single_sheet(
    schematic: Any,
    schematic_path: str,
    net_name: str,
    sheet_state: Optional[SheetConnectivity] = None,
    locator: Optional[PinLocator] = None,
) -> List[Dict]:
    """Find pins connected to *net_name* on a single schematic sheet.

    Handles label, global_label, hierarchical_label, and power symbols.
    All wire and label data is parsed directly from the raw .kicad_sch file
    via sexpdata for maximum reliability.
    """
    state = sheet_state or _build_sheet_connectivity(schematic, schematic_path, locator=locator)
    if state is None:
        return []

    seed_positions = state.label_to_points.get(net_name, [])
    if not seed_positions:
        logger.debug(f"No label positions found for net '{net_name}' in {state.schematic_path}")
        return []

    logger.debug(
        f"Net '{net_name}': {len(seed_positions)} seed position(s) — "
        f"{[f'({p[0]/10000},{p[1]/10000})' for p in seed_positions]}"
    )

    net_points: Set[Tuple[int, int]] = set()

    for seed_pt in seed_positions:
        net_points.add(seed_pt)
        if not state.all_wires:
            continue
        visited, pts = _find_connected_wires(
            seed_pt[0] / _IU_PER_MM,
            seed_pt[1] / _IU_PER_MM,
            state.all_wires,
            state.iu_to_wires,
            state.adjacency,
            point_to_label=state.point_to_label,
            label_to_points=state.label_to_points,
        )
        if pts:
            logger.debug(
                f"BFS from seed ({seed_pt[0]/10000},{seed_pt[1]/10000}) "
                f"found {len(pts)} points via {len(visited) if visited else 0} wires"
            )
            net_points.update(pts)
        else:
            logger.debug(
                f"BFS from seed ({seed_pt[0]/10000},{seed_pt[1]/10000}) "
                f"found NO connected wires"
            )

    logger.debug(f"Net '{net_name}': total {len(net_points)} IU points in net after BFS")

    return _find_pins_on_net(
        net_points,
        state.schematic_path,
        state.schematic,
        sexp=state.sexp,
        locator=locator,
        symbol_instances=state.symbol_instances,
    )


def get_connections_for_net(schematic: Any, schematic_path: str, net_name: str) -> List[Dict]:
    """Find all component pins connected to a named net across all schematic sheets.

    Recursively discovers sub-sheets, processes each sheet independently, and
    merges results. Handles label, global_label, hierarchical_label, and
    power symbol connections.

    Returns a list of {"component": ref, "pin": pin_num} dicts.
    """
    seen: Set[Tuple[str, str, str]] = set()
    all_pins: List[Dict] = []
    locator = PinLocator()

    def _collect(instance_path: str, pins: List[Dict]) -> None:
        for pin in pins:
            key = (instance_path, pin["component"], pin["pin"])
            if key not in seen:
                seen.add(key)
                all_pins.append(pin)

    for traversal in collect_sheet_traversals(schematic, schematic_path, locator=locator):
        _collect(
            traversal.instance_path,
            pins_for_traversal_net(traversal, net_name, locator=locator),
        )

    return all_pins
