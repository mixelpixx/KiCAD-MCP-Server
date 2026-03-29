"""
Schematic Analysis Tools for KiCad Schematics

Read-only analysis tools for detecting spatial problems, querying regions,
and checking connectivity in KiCad schematic files.
"""

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sexpdata
from commands.pin_locator import PinLocator
from sexpdata import Symbol

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
        symbols.append(
            {
                "reference": reference,
                "lib_id": lib_id,
                "x": x,
                "y": y,
                "rotation": rotation,
                "mirror_x": mirror_x,
                "mirror_y": mirror_y,
                "is_power": is_power,
            }
        )
    return symbols


def _parse_lib_symbol_graphics(symbol_def: list) -> List[Tuple[float, float]]:
    """
    Parse graphical body elements from a lib_symbol definition and return
    local-coordinate bounding points.

    Extracts points from rectangle, polyline, circle, arc, and bezier
    elements found in sub-symbols (typically the ``_0_1`` layers that
    contain body shapes).

    Returns a list of ``(x, y)`` points in local symbol coordinates.
    """
    points: List[Tuple[float, float]] = []

    def _extract_graphics_recursive(sexp: list) -> None:
        if not isinstance(sexp, list) or len(sexp) == 0:
            return

        tag = sexp[0]

        if tag == Symbol("rectangle"):
            # (rectangle (start x y) (end x y) ...)
            for sub in sexp[1:]:
                if isinstance(sub, list) and len(sub) >= 3:
                    if sub[0] in (Symbol("start"), Symbol("end")):
                        points.append((float(sub[1]), float(sub[2])))

        elif tag == Symbol("polyline"):
            # (polyline (pts (xy x y) (xy x y) ...) ...)
            for sub in sexp[1:]:
                if isinstance(sub, list) and len(sub) > 0 and sub[0] == Symbol("pts"):
                    for pt in sub[1:]:
                        if isinstance(pt, list) and len(pt) >= 3 and pt[0] == Symbol("xy"):
                            points.append((float(pt[1]), float(pt[2])))

        elif tag == Symbol("circle"):
            # (circle (center x y) (radius r) ...)
            cx, cy, r = 0.0, 0.0, 0.0
            for sub in sexp[1:]:
                if isinstance(sub, list) and len(sub) >= 3 and sub[0] == Symbol("center"):
                    cx, cy = float(sub[1]), float(sub[2])
                elif isinstance(sub, list) and len(sub) >= 2 and sub[0] == Symbol("radius"):
                    r = float(sub[1])
            if r > 0:
                points.extend(
                    [
                        (cx - r, cy - r),
                        (cx + r, cy + r),
                    ]
                )

        elif tag == Symbol("arc"):
            # (arc (start x y) (mid x y) (end x y) ...)
            for sub in sexp[1:]:
                if isinstance(sub, list) and len(sub) >= 3:
                    if sub[0] in (Symbol("start"), Symbol("mid"), Symbol("end")):
                        points.append((float(sub[1]), float(sub[2])))

        elif tag == Symbol("bezier"):
            # (bezier (pts (xy x y) ...) ...)
            for sub in sexp[1:]:
                if isinstance(sub, list) and len(sub) > 0 and sub[0] == Symbol("pts"):
                    for pt in sub[1:]:
                        if isinstance(pt, list) and len(pt) >= 3 and pt[0] == Symbol("xy"):
                            points.append((float(pt[1]), float(pt[2])))

        else:
            # Recurse into sub-symbols to find graphics in nested definitions
            for sub in sexp[1:]:
                if isinstance(sub, list):
                    _extract_graphics_recursive(sub)

    # Search the top-level symbol definition and its sub-symbols
    for item in symbol_def[1:]:
        if isinstance(item, list):
            _extract_graphics_recursive(item)

    return points


def _extract_lib_symbols(sexp_data: list) -> Dict[str, Dict]:
    """
    Walk the lib_symbols section of already-parsed sexp_data and return
    pin definitions and graphics points for every symbol definition.

    Returns:
        Dict mapping lib_id → {"pins": pin_defs, "graphics_points": [(x,y), ...]}.
    """
    lib_symbols_section = None
    for item in sexp_data:
        if isinstance(item, list) and len(item) > 0 and item[0] == Symbol("lib_symbols"):
            lib_symbols_section = item
            break

    if not lib_symbols_section:
        return {}

    result: Dict[str, Dict] = {}
    for item in lib_symbols_section[1:]:
        if isinstance(item, list) and len(item) > 1 and item[0] == Symbol("symbol"):
            symbol_name = str(item[1]).strip('"')
            result[symbol_name] = {
                "pins": PinLocator.parse_symbol_definition(item),
                "graphics_points": _parse_lib_symbol_graphics(item),
            }
    return result


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
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    box_min_x: float,
    box_min_y: float,
    box_max_x: float,
    box_max_y: float,
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
    px: float,
    py: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> bool:
    """Check if a point is within a rectangle."""
    return min_x <= px <= max_x and min_y <= py <= max_y


def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def _aabb_overlap(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> bool:
    """Check if two axis-aligned bounding boxes overlap.

    Each bbox is (min_x, min_y, max_x, max_y).
    """
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _transform_local_point(
    lx: float,
    ly: float,
    sym_x: float,
    sym_y: float,
    rotation: float,
    mirror_x: bool,
    mirror_y: bool,
) -> Tuple[float, float]:
    """
    Transform a point from local symbol coordinates to absolute schematic
    coordinates using KiCad's transform order:
    negate-y (lib y-up → schematic y-down) → mirror → rotate → translate.
    """
    # Library symbols use y-up; schematic uses y-down
    ly = -ly

    # Apply mirroring in local coords
    if mirror_x:
        ly = -ly
    if mirror_y:
        lx = -lx

    # Apply rotation
    if rotation != 0:
        lx, ly = PinLocator.rotate_point(lx, ly, rotation)

    return (sym_x + lx, sym_y + ly)


def _compute_symbol_bbox_direct(
    sym: Dict[str, Any],
    pin_defs: Dict[str, Dict],
    margin: float = 0.0,
    graphics_points: Optional[List[Tuple[float, float]]] = None,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Compute bounding box of a symbol from its graphics and pin definitions.

    When graphics_points are available (from lib_symbol body shapes), uses
    those for the bbox and unions with pin positions. Falls back to
    pin-only estimation with degenerate expansion when no graphics data
    is available.

    Args:
        sym: Parsed symbol dict with x, y, rotation, mirror_x, mirror_y.
        pin_defs: Pin definitions from PinLocator.get_symbol_pins().
        margin: Shrink bbox by this amount on each side (mm).
        graphics_points: Local-coordinate points from symbol body graphics.

    Returns (min_x, min_y, max_x, max_y) in mm, or None if no pins.
    """
    pin_positions = _compute_pin_positions_direct(sym, pin_defs)
    if not pin_positions:
        return None

    if graphics_points:
        # Transform graphics points to absolute coordinates
        sym_x, sym_y = sym["x"], sym["y"]
        rotation = sym["rotation"]
        mirror_x = sym.get("mirror_x", False)
        mirror_y = sym.get("mirror_y", False)

        abs_points = [
            _transform_local_point(lx, ly, sym_x, sym_y, rotation, mirror_x, mirror_y)
            for lx, ly in graphics_points
        ]

        # Union with pin positions so pins extending beyond body are included
        all_xs = [p[0] for p in abs_points] + [p[0] for p in pin_positions.values()]
        all_ys = [p[1] for p in abs_points] + [p[1] for p in pin_positions.values()]

        min_x, min_y = min(all_xs), min(all_ys)
        max_x, max_y = max(all_xs), max(all_ys)
    else:
        # Fallback: pin-only estimation with degenerate expansion
        xs = [p[0] for p in pin_positions.values()]
        ys = [p[1] for p in pin_positions.values()]
        min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)

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

    # Skip degenerate bboxes
    if max_x <= min_x or max_y <= min_y:
        return None

    return (min_x, min_y, max_x, max_y)


# ---------------------------------------------------------------------------
# Tool 3: find_overlapping_elements
# ---------------------------------------------------------------------------


def find_overlapping_elements(schematic_path: Path, tolerance: float = 0.5) -> Dict[str, Any]:
    """
    Detect spatially overlapping symbols, wires, and labels.

    Args:
        schematic_path: Path to .kicad_sch file
        tolerance: Distance threshold in mm for label proximity and wire collinearity checks. Symbol overlap uses bounding-box intersection.

    Returns dict: {overlappingSymbols, overlappingLabels, overlappingWires, totalOverlaps}
    """
    sexp_data = _load_sexp(schematic_path)
    symbols = _parse_symbols(sexp_data)
    wires = _parse_wires(sexp_data)
    labels = _parse_labels(sexp_data)

    overlapping_symbols = []
    overlapping_labels = []
    overlapping_wires = []

    lib_defs = _extract_lib_symbols(sexp_data)

    # --- Symbol-symbol overlap using bounding-box intersection (O(n²)) ---
    non_template_symbols = [
        s for s in symbols if not s["reference"].startswith("_TEMPLATE") and s["reference"]
    ]

    # Pre-compute bounding boxes for all non-template symbols
    symbol_bboxes = []
    for sym in non_template_symbols:
        lib_data = lib_defs.get(sym["lib_id"], {})
        pin_defs = lib_data.get("pins", {})
        graphics_points = lib_data.get("graphics_points", [])
        bbox = None
        if pin_defs:
            bbox = _compute_symbol_bbox_direct(sym, pin_defs, graphics_points=graphics_points)
        symbol_bboxes.append((sym, bbox))

    for i in range(len(symbol_bboxes)):
        s1, bbox1 = symbol_bboxes[i]
        for j in range(i + 1, len(symbol_bboxes)):
            s2, bbox2 = symbol_bboxes[j]
            dist = _distance((s1["x"], s1["y"]), (s2["x"], s2["y"]))

            overlap_detected = False
            if bbox1 is not None and bbox2 is not None:
                # Use bounding box intersection
                overlap_detected = _aabb_overlap(bbox1, bbox2)
            else:
                # Fallback to center distance when pin data is unavailable
                overlap_detected = dist < tolerance

            if overlap_detected:
                entry = {
                    "element1": {
                        "reference": s1["reference"],
                        "libId": s1["lib_id"],
                        "position": {"x": s1["x"], "y": s1["y"]},
                    },
                    "element2": {
                        "reference": s2["reference"],
                        "libId": s2["lib_id"],
                        "position": {"x": s2["x"], "y": s2["y"]},
                    },
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
                overlapping_labels.append(
                    {
                        "element1": {
                            "name": l1["name"],
                            "type": l1["type"],
                            "position": {"x": l1["x"], "y": l1["y"]},
                        },
                        "element2": {
                            "name": l2["name"],
                            "type": l2["type"],
                            "position": {"x": l2["x"], "y": l2["y"]},
                        },
                        "distance": round(dist, 4),
                    }
                )

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

    Works for horizontal, vertical, and diagonal wires. Uses direction
    vectors, cross-product parallelism, point-to-line distance for
    collinearity, and 1D projection overlap.

    Returns overlap info dict or None.
    """
    s1, e1 = w1["start"], w1["end"]
    s2, e2 = w2["start"], w2["end"]

    d1 = (e1[0] - s1[0], e1[1] - s1[1])
    d2 = (e2[0] - s2[0], e2[1] - s2[1])

    len1 = math.sqrt(d1[0] ** 2 + d1[1] ** 2)
    len2 = math.sqrt(d2[0] ** 2 + d2[1] ** 2)
    if len1 < 1e-12 or len2 < 1e-12:
        return None  # degenerate zero-length segment

    # Cross product to check parallel
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) > tolerance * max(len1, len2):
        return None  # not parallel

    # Point-to-line distance: s2 relative to line through s1 along d1
    ds = (s2[0] - s1[0], s2[1] - s1[1])
    perp_dist = abs(ds[0] * d1[1] - ds[1] * d1[0]) / len1
    if perp_dist > tolerance:
        return None  # parallel but offset

    # Project onto d1 direction for 1D overlap check
    u1 = (d1[0] / len1, d1[1] / len1)
    proj_s1 = s1[0] * u1[0] + s1[1] * u1[1]
    proj_e1 = e1[0] * u1[0] + e1[1] * u1[1]
    proj_s2 = s2[0] * u1[0] + s2[1] * u1[1]
    proj_e2 = e2[0] * u1[0] + e2[1] * u1[1]

    min1, max1 = min(proj_s1, proj_e1), max(proj_s1, proj_e1)
    min2, max2 = min(proj_s2, proj_e2), max(proj_s2, proj_e2)
    if min1 < max2 and min2 < max1:
        return {
            "wire1": {
                "start": {"x": s1[0], "y": s1[1]},
                "end": {"x": e1[0], "y": e1[1]},
            },
            "wire2": {
                "start": {"x": s2[0], "y": s2[1]},
                "end": {"x": e2[0], "y": e2[1]},
            },
            "type": "collinear_overlap",
        }

    return None


# ---------------------------------------------------------------------------
# Tool 4: get_elements_in_region
# ---------------------------------------------------------------------------


def get_elements_in_region(
    schematic_path: Path,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
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

    lib_defs = _extract_lib_symbols(sexp_data)

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
            lib_data = lib_defs.get(sym["lib_id"], {})
            pin_defs = lib_data.get("pins", {})
            if pin_defs:
                pin_positions = _compute_pin_positions_direct(sym, pin_defs)
                if pin_positions:
                    entry["pins"] = {
                        pn: {"x": round(pos[0], 4), "y": round(pos[1], 4)}
                        for pn, pos in pin_positions.items()
                    }
            region_symbols.append(entry)

    # Wires: include if any part of the wire intersects the region
    region_wires = []
    for w in wires:
        s, e = w["start"], w["end"]
        if (
            _point_in_rect(s[0], s[1], min_x, min_y, max_x, max_y)
            or _point_in_rect(e[0], e[1], min_x, min_y, max_x, max_y)
            or _line_segment_intersects_aabb(s[0], s[1], e[0], e[1], min_x, min_y, max_x, max_y)
        ):
            region_wires.append(
                {
                    "start": {"x": s[0], "y": s[1]},
                    "end": {"x": e[0], "y": e[1]},
                }
            )

    # Labels: include if position is within bounds
    region_labels = []
    for lbl in labels:
        if _point_in_rect(lbl["x"], lbl["y"], min_x, min_y, max_x, max_y):
            region_labels.append(
                {
                    "name": lbl["name"],
                    "type": lbl["type"],
                    "position": {"x": lbl["x"], "y": lbl["y"]},
                }
            )

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


def find_wires_crossing_symbols(schematic_path: Path) -> List[Dict[str, Any]]:
    """
    Find all wires that cross over component symbol bodies.

    Wires passing over symbols are unacceptable in schematics — they indicate
    routing mistakes where a wire was drawn across a component instead of
    around it.

    For each non-power, non-template symbol:
    1. Compute bounding box from pin positions (shrunk by margin).
    2. For each wire segment, test intersection with the bbox.
    3. If intersects and the wire is not simply terminating at a pin from
       outside, report it as a crossing.

    Returns list of crossing dicts.
    """
    sexp_data = _load_sexp(schematic_path)
    symbols = _parse_symbols(sexp_data)
    wires = _parse_wires(sexp_data)

    lib_defs = _extract_lib_symbols(sexp_data)
    margin = 0.5  # mm margin to shrink bbox (avoids false positives at pin tips)
    pin_tolerance = 0.05  # mm

    collisions = []

    # Pre-compute per-symbol data
    symbol_data = []
    for sym in symbols:
        ref = sym["reference"]
        if sym["is_power"] or ref.startswith("_TEMPLATE") or not ref:
            continue

        lib_data = lib_defs.get(sym["lib_id"], {})
        pin_defs = lib_data.get("pins", {})
        if not pin_defs:
            continue

        graphics_points = lib_data.get("graphics_points", [])
        bbox = _compute_symbol_bbox_direct(
            sym, pin_defs, margin=margin, graphics_points=graphics_points
        )
        if bbox is None:
            continue

        pin_positions = _compute_pin_positions_direct(sym, pin_defs)
        pin_set = set()
        for pos in pin_positions.values():
            pin_set.add((pos[0], pos[1]))

        symbol_data.append(
            {
                "sym": sym,
                "bbox": bbox,
                "pin_set": pin_set,
            }
        )

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

            # When exactly one endpoint is at a pin, check whether the wire
            # just terminates at the pin (valid connection) or continues through
            # the component body (pass-through → collision).
            # Nudge the pin endpoint slightly toward the other end; if the
            # shortened segment still intersects the bbox, the wire extends
            # into/through the body.
            if (start_at_pin or end_at_pin) and not (start_at_pin and end_at_pin):
                dx, dy = ex - sx, ey - sy
                length = math.sqrt(dx * dx + dy * dy)
                if length > 0:
                    nudge = min(0.2, length * 0.5)
                    ux, uy = dx / length, dy / length
                    if start_at_pin:
                        nsx, nsy = sx + ux * nudge, sy + uy * nudge
                        if not _line_segment_intersects_aabb(nsx, nsy, ex, ey, bx1, by1, bx2, by2):
                            continue  # Wire terminates at pin from outside
                    else:
                        nex, ney = ex - ux * nudge, ey - uy * nudge
                        if not _line_segment_intersects_aabb(sx, sy, nex, ney, bx1, by1, bx2, by2):
                            continue  # Wire terminates at pin from outside

            sym = sd["sym"]
            collisions.append(
                {
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
                }
            )

    return collisions
