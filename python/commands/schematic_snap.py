"""
Snap-to-grid tool for KiCAD schematics.

Snaps wire endpoints, junction positions, net labels, and optionally component
positions to the nearest grid point. Modifies the schematic file in place.

The standard KiCAD schematic grid is 50 mil (1.27 mm). Component pins are
placed at multiples of 1.27 mm relative to the symbol origin, so absolute pin
coordinates end up as odd multiples of 1.27 mm (e.g. 26.67 mm = 21 × 1.27 mm).
These are valid on-grid positions that must not be moved.

The coarser 2.54 mm (100-mil) grid is a common mistake: exactly half of all
valid 1.27 mm positions are not multiples of 2.54 mm and would be displaced by
1.27 mm — moving labels or wire endpoints off their pins and breaking
connectivity.

Off-grid coordinates cause wires that appear visually connected to fail ERC
connectivity checks because KiCAD uses exact integer (IU) matching internally.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

_DEFAULT_GRID_MM: float = 1.27

# Element type names exposed in the public API
_VALID_ELEMENTS = frozenset({"wires", "junctions", "labels", "components"})

# Tags treated as net labels (all have (at x y angle) structure)
_LABEL_TAGS = frozenset(
    {
        Symbol("label"),
        Symbol("global_label"),
        Symbol("hierarchical_label"),
        Symbol("net_tie"),
        Symbol("no_connect"),
    }
)


def _snap_mm(value: float, grid_mm: float) -> float:
    """Snap a single coordinate to the nearest grid multiple."""
    return round(value / grid_mm) * grid_mm


def _is_on_grid(value: float, grid_mm: float, eps: float = 1e-9) -> bool:
    """Return True if *value* is already within *eps* of a grid point."""
    snapped = _snap_mm(value, grid_mm)
    return abs(value - snapped) < eps


def _snap_xy_pair(item: list, grid_mm: float) -> int:
    """
    Snap a ``(xy x y)`` S-expression item in place.
    Returns 1 if at least one coordinate changed, 0 otherwise.
    """
    if not (isinstance(item, list) and len(item) >= 3 and item[0] == Symbol("xy")):
        return 0
    x_orig, y_orig = float(item[1]), float(item[2])
    x_new = _snap_mm(x_orig, grid_mm)
    y_new = _snap_mm(y_orig, grid_mm)
    changed = not (_is_on_grid(x_orig, grid_mm) and _is_on_grid(y_orig, grid_mm))
    item[1] = x_new
    item[2] = y_new
    return 1 if changed else 0


def _snap_at_xy(item: list, grid_mm: float) -> int:
    """
    Snap an ``(at x y ...)`` S-expression item in place (indices 1 and 2 only).
    Preserves rotation / angle at index 3+ unchanged.
    Returns 1 if at least one coordinate changed, 0 otherwise.
    """
    if not (isinstance(item, list) and len(item) >= 3 and item[0] == Symbol("at")):
        return 0
    x_orig, y_orig = float(item[1]), float(item[2])
    x_new = _snap_mm(x_orig, grid_mm)
    y_new = _snap_mm(y_orig, grid_mm)
    changed = not (_is_on_grid(x_orig, grid_mm) and _is_on_grid(y_orig, grid_mm))
    item[1] = x_new
    item[2] = y_new
    return 1 if changed else 0


def snap_to_grid(
    schematic_path: Path,
    grid_size: float = _DEFAULT_GRID_MM,
    elements: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Snap element coordinates in a ``.kicad_sch`` file to the nearest grid point.

    Modifies the file in place and returns statistics.

    Args:
        schematic_path: Path to the ``.kicad_sch`` file.
        grid_size:      Grid spacing in mm (default 1.27 mm = 50 mil).
                        Do NOT use 2.54 mm — half of all valid KiCAD pin
                        positions fall between 2.54 mm grid lines and would
                        be displaced 1.27 mm, breaking connectivity.
        elements:       List of element types to snap.  Valid values:
                        ``"wires"``, ``"junctions"``, ``"labels"``,
                        ``"components"``.  Defaults to
                        ``["wires", "junctions", "labels"]`` when ``None``.

    Returns:
        ``{"snapped": int, "already_on_grid": int, "grid_size": float}``
        where *snapped* is the number of elements that had at least one
        coordinate moved.
    """
    if grid_size <= 0:
        raise ValueError(f"grid_size must be positive, got {grid_size}")

    if elements is None:
        active: frozenset = frozenset({"wires", "junctions", "labels"})
    else:
        unknown = set(elements) - _VALID_ELEMENTS
        if unknown:
            raise ValueError(
                f"Unknown element type(s): {sorted(unknown)}. "
                f"Valid types: {sorted(_VALID_ELEMENTS)}"
            )
        active = frozenset(elements)

    with open(schematic_path, "r", encoding="utf-8") as fh:
        sch_data = sexpdata.loads(fh.read())

    snapped = 0
    already_on_grid = 0

    snap_wires = "wires" in active
    snap_junctions = "junctions" in active
    snap_labels = "labels" in active
    snap_components = "components" in active

    for item in sch_data:
        if not isinstance(item, list) or not item:
            continue
        tag = item[0]

        # -----------------------------------------------------------------
        # Wires: (wire (pts (xy x y) (xy x y)) ...)
        # -----------------------------------------------------------------
        if snap_wires and tag == Symbol("wire"):
            changed = 0
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == Symbol("pts"):
                    for pt in sub[1:]:
                        changed += _snap_xy_pair(pt, grid_size)
            if changed:
                snapped += 1
            else:
                already_on_grid += 1
            continue

        # -----------------------------------------------------------------
        # Junctions: (junction (at x y) ...)
        # -----------------------------------------------------------------
        if snap_junctions and tag == Symbol("junction"):
            changed = 0
            for sub in item[1:]:
                changed += _snap_at_xy(sub, grid_size)
            if changed:
                snapped += 1
            else:
                already_on_grid += 1
            continue

        # -----------------------------------------------------------------
        # Labels: (label|global_label|hierarchical_label|no_connect … (at x y angle) …)
        # -----------------------------------------------------------------
        if snap_labels and tag in _LABEL_TAGS:
            changed = 0
            for sub in item[1:]:
                changed += _snap_at_xy(sub, grid_size)
            if changed:
                snapped += 1
            else:
                already_on_grid += 1
            continue

        # -----------------------------------------------------------------
        # Components: (symbol (lib_id …) (at x y rotation) …)
        # Snap only the top-level (at …) — not property sub-positions.
        # -----------------------------------------------------------------
        if snap_components and tag == Symbol("symbol"):
            changed = 0
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == Symbol("at"):
                    changed += _snap_at_xy(sub, grid_size)
                    break  # only the first (at …) belongs to the symbol itself
            if changed:
                snapped += 1
            else:
                already_on_grid += 1
            continue

    with open(schematic_path, "w", encoding="utf-8") as fh:
        fh.write(sexpdata.dumps(sch_data))

    return {
        "snapped": snapped,
        "already_on_grid": already_on_grid,
        "grid_size": grid_size,
    }
