"""
Schematic Analysis Tools for KiCad Schematics

Read-only analysis tools for detecting spatial problems, querying regions,
and checking connectivity in KiCad schematic files.
"""

import logging
import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set

import sexpdata
from sexpdata import Symbol

from commands.pin_locator import PinLocator

logger = logging.getLogger("kicad_interface")


# ---------------------------------------------------------------------------
# S-expression parsing helpers
# ---------------------------------------------------------------------------

def _load_sexp(schematic_path: Path) -> list:
    """Load schematic file and return parsed S-expression data."""
    with open(schematic_path, "r", encoding="utf-8") as f:
        return sexpdata.loads(f.read())


def _parse_wires(sexp_data: list) -> List[Dict[str, Any]]:
    """
    Parse all wire segments from the schematic S-expression.

    Returns list of dicts: {start: (x_mm, y_mm), end: (x_mm, y_mm)}
    """
    wires = []
    for item in sexp_data:
        if not isinstance(item, list) or len(item) < 2:
            continue
        if item[0] != Symbol("wire"):
            continue
        pts = None
        for sub in item:
            if isinstance(sub, list) and len(sub) > 0 and sub[0] == Symbol("pts"):
                pts = sub
                break
        if not pts:
            continue
        coords = []
        for sub in pts:
            if isinstance(sub, list) and len(sub) >= 3 and sub[0] == Symbol("xy"):
                coords.append((float(sub[1]), float(sub[2])))
        if len(coords) >= 2:
            wires.append({"start": coords[0], "end": coords[1]})
    return wires


def _parse_labels(sexp_data: list) -> List[Dict[str, Any]]:
    """
    Parse all labels (label and global_label) from the schematic S-expression.

    Returns list of dicts: {name, type ('label'|'global_label'), x, y}
    """
    labels = []
    for item in sexp_data:
        if not isinstance(item, list) or len(item) < 2:
            continue
        tag = item[0]
        if tag not in (Symbol("label"), Symbol("global_label")):
            continue
        name = str(item[1]).strip('"')
        label_type = str(tag)
        x, y = 0.0, 0.0
        for sub in item:
            if isinstance(sub, list) and len(sub) >= 3 and sub[0] == Symbol("at"):
                x = float(sub[1])
                y = float(sub[2])
                break
        labels.append({"name": name, "type": label_type, "x": x, "y": y})
    return labels


def _parse_symbols(sexp_data: list) -> List[Dict[str, Any]]:
    """
    Parse all placed symbol instances from the schematic S-expression.

    Returns list of dicts: {reference, lib_id, x, y, rotation, mirror_x, mirror_y, is_power}
    """
    symbols = []
    for item in sexp_data:
        if not isinstance(item, list) or len(item) < 2:
            continue
        if item[0] != Symbol("symbol"):
            continue

        lib_id = ""
        x, y, rotation = 0.0, 0.0, 0.0
        reference = ""
        is_power = False
        mirror_x = False
        mirror_y = False

        for sub in item:
            if isinstance(sub, list) and len(sub) >= 2:
                if sub[0] == Symbol("lib_id"):
                    lib_id = str(sub[1]).strip('"')
                elif sub[0] == Symbol("at") and len(sub) >= 3:
                    x = float(sub[1])
                    y = float(sub[2])
                    if len(sub) >= 4:
                        rotation = float(sub[3])
                elif sub[0] == Symbol("mirror"):
                    m = str(sub[1])
                    if m == "x":
                        mirror_x = True
                    elif m == "y":
                        mirror_y = True
                elif sub[0] == Symbol("property") and len(sub) >= 3:
                    prop_name = str(sub[1]).strip('"')
                    if prop_name == "Reference":
                        reference = str(sub[2]).strip('"')

        is_power = reference.startswith("#PWR") or reference.startswith("#FLG")
        symbols.append({
            "reference": reference,
            "lib_id": lib_id,
            "x": x,
            "y": y,
            "rotation": rotation,
            "mirror_x": mirror_x,
            "mirror_y": mirror_y,
            "is_power": is_power,
        })
    return symbols


def _parse_no_connects(sexp_data: list) -> Set[Tuple[float, float]]:
    """Parse all no_connect elements and return their positions as (x, y) tuples in mm."""
    positions: Set[Tuple[float, float]] = set()
    for item in sexp_data:
        if not isinstance(item, list) or len(item) < 2:
            continue
        if item[0] != Symbol("no_connect"):
            continue
        for sub in item:
            if isinstance(sub, list) and len(sub) >= 3 and sub[0] == Symbol("at"):
                positions.add((float(sub[1]), float(sub[2])))
                break
    return positions


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def compute_symbol_bbox(
    schematic_path: Path,
    reference: str,
    locator: PinLocator,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Compute bounding box of a symbol from its pin positions.

    Returns (min_x, min_y, max_x, max_y) in mm, or None if no pins found.
    """
    pins = locator.get_all_symbol_pins(schematic_path, reference)
    if not pins:
        return None
    xs = [p[0] for p in pins.values()]
    ys = [p[1] for p in pins.values()]
    return (min(xs), min(ys), max(xs), max(ys))


def _line_segment_intersects_aabb(
    x1: float, y1: float, x2: float, y2: float,
    box_min_x: float, box_min_y: float, box_max_x: float, box_max_y: float,
) -> bool:
    """
    Test whether line segment (x1,y1)→(x2,y2) intersects an axis-aligned bounding box.

    Uses the Liang-Barsky clipping algorithm.
    """
    dx = x2 - x1
    dy = y2 - y1

    p = [-dx, dx, -dy, dy]
    q = [x1 - box_min_x, box_max_x - x1, y1 - box_min_y, box_max_y - y1]

    t_min = 0.0
    t_max = 1.0

    for i in range(4):
        if abs(p[i]) < 1e-12:
            # Parallel to this edge
            if q[i] < 0:
                return False
        else:
            t = q[i] / p[i]
            if p[i] < 0:
                t_min = max(t_min, t)
            else:
                t_max = min(t_max, t)
            if t_min > t_max:
                return False

    return True


def _point_in_rect(
    px: float, py: float,
    min_x: float, min_y: float, max_x: float, max_y: float,
) -> bool:
    """Check if a point is within a rectangle."""
    return min_x <= px <= max_x and min_y <= py <= max_y


def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


# ---------------------------------------------------------------------------
# Tool 2: find_unconnected_pins
# ---------------------------------------------------------------------------

def find_unconnected_pins(schematic_path: Path) -> List[Dict[str, Any]]:
    """
    Find all component pins with no wire, label, or power symbol touching them.

    Returns list of dicts: {reference, libId, pinNumber, pinName, position: {x, y}}
    """
    sexp_data = _load_sexp(schematic_path)
    symbols = _parse_symbols(sexp_data)
    wires = _parse_wires(sexp_data)
    labels = _parse_labels(sexp_data)
    no_connects = _parse_no_connects(sexp_data)

    # Build set of "connected" positions in mm
    connected: Set[Tuple[float, float]] = set()

    # Wire endpoints
    for w in wires:
        connected.add(w["start"])
        connected.add(w["end"])

    # Label positions
    for lbl in labels:
        connected.add((lbl["x"], lbl["y"]))

    # Power symbol positions (they implicitly connect)
    for sym in symbols:
        if sym["is_power"]:
            connected.add((sym["x"], sym["y"]))

    tolerance = 0.05  # mm

    def _snap(v: float) -> int:
        """Snap coordinate to grid for O(1) set lookup."""
        return round(v / tolerance)

    connected_grid: set = set()
    for pos in connected:
        connected_grid.add((_snap(pos[0]), _snap(pos[1])))

    no_connect_grid: set = set()
    for pos in no_connects:
        no_connect_grid.add((_snap(pos[0]), _snap(pos[1])))

    def is_connected(px: float, py: float) -> bool:
        sx, sy = _snap(px), _snap(py)
        # Check the snapped cell and immediate neighbors to handle edge cases
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (sx + dx, sy + dy) in connected_grid:
                    return True
        return False

    def is_no_connect(px: float, py: float) -> bool:
        sx, sy = _snap(px), _snap(py)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (sx + dx, sy + dy) in no_connect_grid:
                    return True
        return False

    locator = PinLocator()
    unconnected = []

    for sym in symbols:
        ref = sym["reference"]
        # Skip power symbols, templates, and empty references
        if sym["is_power"] or ref.startswith("_TEMPLATE") or not ref:
            continue

        pin_defs = locator.get_symbol_pins(schematic_path, sym["lib_id"])
        if not pin_defs:
            continue

        pin_positions = _compute_pin_positions_direct(sym, pin_defs)
        if not pin_positions:
            continue

        for pin_num, pos in pin_positions.items():
            px, py = pos[0], pos[1]

            if is_no_connect(px, py):
                continue
            if is_connected(px, py):
                continue

            pin_name = pin_defs.get(pin_num, {}).get("name", pin_num)
            unconnected.append({
                "reference": ref,
                "libId": sym["lib_id"],
                "pinNumber": pin_num,
                "pinName": pin_name,
                "position": {"x": round(px, 4), "y": round(py, 4)},
            })

    return unconnected


# ---------------------------------------------------------------------------
# Tool 3: find_overlapping_elements
# ---------------------------------------------------------------------------

def find_overlapping_elements(
    schematic_path: Path, tolerance: float = 0.5
) -> Dict[str, Any]:
    """
    Detect spatially overlapping symbols, wires, and labels.

    Args:
        schematic_path: Path to .kicad_sch file
        tolerance: Distance in mm below which elements are considered overlapping

    Returns dict: {overlappingSymbols, overlappingLabels, overlappingWires, totalOverlaps}
    """
    sexp_data = _load_sexp(schematic_path)
    symbols = _parse_symbols(sexp_data)
    wires = _parse_wires(sexp_data)
    labels = _parse_labels(sexp_data)

    overlapping_symbols = []
    overlapping_labels = []
    overlapping_wires = []

    # --- Symbol-symbol overlap (O(n²)) ---
    non_template_symbols = [s for s in symbols if not s["reference"].startswith("_TEMPLATE") and s["reference"]]
    for i in range(len(non_template_symbols)):
        for j in range(i + 1, len(non_template_symbols)):
            s1 = non_template_symbols[i]
            s2 = non_template_symbols[j]
            dist = _distance((s1["x"], s1["y"]), (s2["x"], s2["y"]))
            if dist < tolerance:
                entry = {
                    "element1": {"reference": s1["reference"], "libId": s1["lib_id"],
                                 "position": {"x": s1["x"], "y": s1["y"]}},
                    "element2": {"reference": s2["reference"], "libId": s2["lib_id"],
                                 "position": {"x": s2["x"], "y": s2["y"]}},
                    "distance": round(dist, 4),
                }
                # Flag power symbol pairs specifically
                if s1["is_power"] and s2["is_power"]:
                    entry["type"] = "power_symbol_overlap"
                else:
                    entry["type"] = "symbol_overlap"
                overlapping_symbols.append(entry)

    # --- Label-label overlap ---
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            l1 = labels[i]
            l2 = labels[j]
            dist = _distance((l1["x"], l1["y"]), (l2["x"], l2["y"]))
            if dist < tolerance:
                overlapping_labels.append({
                    "element1": {"name": l1["name"], "type": l1["type"],
                                 "position": {"x": l1["x"], "y": l1["y"]}},
                    "element2": {"name": l2["name"], "type": l2["type"],
                                 "position": {"x": l2["x"], "y": l2["y"]}},
                    "distance": round(dist, 4),
                })

    # --- Wire-wire collinear overlap ---
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            w1 = wires[i]
            w2 = wires[j]
            overlap = _check_wire_overlap(w1, w2, tolerance)
            if overlap:
                overlapping_wires.append(overlap)

    total = len(overlapping_symbols) + len(overlapping_labels) + len(overlapping_wires)

    return {
        "overlappingSymbols": overlapping_symbols,
        "overlappingLabels": overlapping_labels,
        "overlappingWires": overlapping_wires,
        "totalOverlaps": total,
    }


def _check_wire_overlap(
    w1: Dict[str, Any], w2: Dict[str, Any], tolerance: float
) -> Optional[Dict[str, Any]]:
    """
    Check if two wire segments are collinear and overlapping.

    Returns overlap info dict or None.
    """
    s1, e1 = w1["start"], w1["end"]
    s2, e2 = w2["start"], w2["end"]

    # Check horizontal collinearity
    if abs(s1[1] - e1[1]) < tolerance and abs(s2[1] - e2[1]) < tolerance:
        if abs(s1[1] - s2[1]) < tolerance:
            # Both horizontal, same Y
            min1, max1 = min(s1[0], e1[0]), max(s1[0], e1[0])
            min2, max2 = min(s2[0], e2[0]), max(s2[0], e2[0])
            if min1 < max2 and min2 < max1:
                return {
                    "wire1": {"start": {"x": s1[0], "y": s1[1]}, "end": {"x": e1[0], "y": e1[1]}},
                    "wire2": {"start": {"x": s2[0], "y": s2[1]}, "end": {"x": e2[0], "y": e2[1]}},
                    "type": "collinear_overlap",
                }

    # Check vertical collinearity
    if abs(s1[0] - e1[0]) < tolerance and abs(s2[0] - e2[0]) < tolerance:
        if abs(s1[0] - s2[0]) < tolerance:
            # Both vertical, same X
            min1, max1 = min(s1[1], e1[1]), max(s1[1], e1[1])
            min2, max2 = min(s2[1], e2[1]), max(s2[1], e2[1])
            if min1 < max2 and min2 < max1:
                return {
                    "wire1": {"start": {"x": s1[0], "y": s1[1]}, "end": {"x": e1[0], "y": e1[1]}},
                    "wire2": {"start": {"x": s2[0], "y": s2[1]}, "end": {"x": e2[0], "y": e2[1]}},
                    "type": "collinear_overlap",
                }

    return None


# ---------------------------------------------------------------------------
# Tool 4: get_elements_in_region
# ---------------------------------------------------------------------------

def get_elements_in_region(
    schematic_path: Path,
    x1: float, y1: float, x2: float, y2: float,
) -> Dict[str, Any]:
    """
    List all wires, labels, and symbols within a rectangular region.

    Args:
        schematic_path: Path to .kicad_sch file
        x1, y1, x2, y2: Bounding box corners in schematic mm

    Returns dict: {symbols, wires, labels, counts}
    """
    min_x, max_x = min(x1, x2), max(x1, x2)
    min_y, max_y = min(y1, y2), max(y1, y2)

    sexp_data = _load_sexp(schematic_path)
    symbols = _parse_symbols(sexp_data)
    wires = _parse_wires(sexp_data)
    labels = _parse_labels(sexp_data)

    locator = PinLocator()

    # Symbols: include if position is within bounds
    region_symbols = []
    for sym in symbols:
        if not sym["reference"] or sym["reference"].startswith("_TEMPLATE"):
            continue
        if _point_in_rect(sym["x"], sym["y"], min_x, min_y, max_x, max_y):
            entry = {
                "reference": sym["reference"],
                "libId": sym["lib_id"],
                "position": {"x": sym["x"], "y": sym["y"]},
                "isPower": sym["is_power"],
            }
            # Include pin positions (compute directly to handle unannotated duplicates)
            pin_defs = locator.get_symbol_pins(schematic_path, sym["lib_id"])
            if pin_defs:
                pin_positions = _compute_pin_positions_direct(sym, pin_defs)
                if pin_positions:
                    entry["pins"] = {
                        pn: {"x": round(pos[0], 4), "y": round(pos[1], 4)}
                        for pn, pos in pin_positions.items()
                    }
            region_symbols.append(entry)

    # Wires: include if ANY endpoint is within bounds
    region_wires = []
    for w in wires:
        s, e = w["start"], w["end"]
        if (_point_in_rect(s[0], s[1], min_x, min_y, max_x, max_y) or
                _point_in_rect(e[0], e[1], min_x, min_y, max_x, max_y)):
            region_wires.append({
                "start": {"x": s[0], "y": s[1]},
                "end": {"x": e[0], "y": e[1]},
            })

    # Labels: include if position is within bounds
    region_labels = []
    for lbl in labels:
        if _point_in_rect(lbl["x"], lbl["y"], min_x, min_y, max_x, max_y):
            region_labels.append({
                "name": lbl["name"],
                "type": lbl["type"],
                "position": {"x": lbl["x"], "y": lbl["y"]},
            })

    return {
        "symbols": region_symbols,
        "wires": region_wires,
        "labels": region_labels,
        "counts": {
            "symbols": len(region_symbols),
            "wires": len(region_wires),
            "labels": len(region_labels),
        },
    }


# ---------------------------------------------------------------------------
# Tool 5: check_wire_collisions
# ---------------------------------------------------------------------------

def _compute_pin_positions_direct(
    sym: Dict[str, Any], pin_defs: Dict[str, Dict]
) -> Dict[str, List[float]]:
    """
    Compute absolute schematic pin positions for a symbol instance directly from
    its parsed position/rotation/mirror data and pin definitions in local coords.

    Unlike PinLocator.get_all_symbol_pins, this does NOT do a reference-name
    lookup in the schematic, so it works correctly when multiple symbols share
    the same reference designator (e.g. unannotated "Q?").

    KiCad transform order: mirror (in local coords) → rotate → translate.
    """
    sym_x = sym["x"]
    sym_y = sym["y"]
    rotation = sym["rotation"]
    mirror_x = sym.get("mirror_x", False)
    mirror_y = sym.get("mirror_y", False)

    result: Dict[str, List[float]] = {}
    for pin_num, pin_data in pin_defs.items():
        rel_x = float(pin_data["x"])
        rel_y = float(pin_data["y"])

        # Apply mirroring in local symbol coordinates
        if mirror_x:
            rel_y = -rel_y
        if mirror_y:
            rel_x = -rel_x

        # Apply symbol rotation
        if rotation != 0:
            rel_x, rel_y = PinLocator.rotate_point(rel_x, rel_y, rotation)

        result[pin_num] = [sym_x + rel_x, sym_y + rel_y]
    return result


def check_wire_collisions(schematic_path: Path) -> List[Dict[str, Any]]:
    """
    Detect wires passing through component bodies without connecting to their pins.

    For each non-power, non-template symbol:
    1. Compute bounding box from pin positions (shrunk by margin).
    2. For each wire segment, test intersection with the bbox.
    3. If intersects but no wire endpoint matches a pin → collision.

    Returns list of collision dicts.
    """
    sexp_data = _load_sexp(schematic_path)
    symbols = _parse_symbols(sexp_data)
    wires = _parse_wires(sexp_data)

    locator = PinLocator()
    margin = 0.5  # mm margin to shrink bbox (avoids false positives at pin tips)
    pin_tolerance = 0.05  # mm

    collisions = []

    # Pre-compute per-symbol data
    symbol_data = []
    for sym in symbols:
        ref = sym["reference"]
        if sym["is_power"] or ref.startswith("_TEMPLATE") or not ref:
            continue

        # Get pin definitions by lib_id (works regardless of reference designator,
        # so unannotated components with duplicate "Q?" references are handled correctly).
        pin_defs = locator.get_symbol_pins(schematic_path, sym["lib_id"])
        if not pin_defs:
            continue

        # Compute absolute pin positions directly from this symbol's own position/rotation,
        # bypassing the reference-name lookup in PinLocator (which always finds the first
        # symbol with a given reference, breaking for unannotated duplicates like "Q?").
        pin_positions = _compute_pin_positions_direct(sym, pin_defs)
        if not pin_positions:
            continue

        xs = [p[0] for p in pin_positions.values()]
        ys = [p[1] for p in pin_positions.values()]
        min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)

        # Expand degenerate dimensions (pins in a line) to approximate body size
        min_body = 1.5  # mm minimum half-extent for component body
        if max_x - min_x < 2 * min_body:
            cx = (min_x + max_x) / 2
            min_x = cx - min_body
            max_x = cx + min_body
        if max_y - min_y < 2 * min_body:
            cy = (min_y + max_y) / 2
            min_y = cy - min_body
            max_y = cy + min_body

        # Shrink bbox by margin
        min_x += margin
        min_y += margin
        max_x -= margin
        max_y -= margin

        # Skip degenerate bboxes (single-pin or very small after shrink)
        if max_x <= min_x or max_y <= min_y:
            continue

        pin_set = set()
        for pos in pin_positions.values():
            pin_set.add((pos[0], pos[1]))

        symbol_data.append({
            "sym": sym,
            "bbox": (min_x, min_y, max_x, max_y),
            "pin_set": pin_set,
        })

    # Test each wire against each symbol bbox
    for w in wires:
        sx, sy = w["start"]
        ex, ey = w["end"]

        for sd in symbol_data:
            bx1, by1, bx2, by2 = sd["bbox"]

            if not _line_segment_intersects_aabb(sx, sy, ex, ey, bx1, by1, bx2, by2):
                continue

            # Check which endpoints land on a pin of this symbol
            start_at_pin = any(
                abs(sx - px) < pin_tolerance and abs(sy - py) < pin_tolerance
                for px, py in sd["pin_set"]
            )
            end_at_pin = any(
                abs(ex - px) < pin_tolerance and abs(ey - py) < pin_tolerance
                for px, py in sd["pin_set"]
            )

            # Suppress only when exactly ONE endpoint is at a pin: the wire arrives
            # from elsewhere and terminates at this component (a valid connection).
            # If BOTH endpoints match pins of this same component, the wire shorts
            # two pins while traversing the body — that IS a collision.
            if (start_at_pin or end_at_pin) and not (start_at_pin and end_at_pin):
                continue

            sym = sd["sym"]
            collisions.append({
                    "wire": {
                        "start": {"x": sx, "y": sy},
                        "end": {"x": ex, "y": ey},
                    },
                    "component": {
                        "reference": sym["reference"],
                        "libId": sym["lib_id"],
                        "position": {"x": sym["x"], "y": sym["y"]},
                    },
                    "intersectionType": "passes_through",
                })

    return collisions
