"""Shared geometry helpers for the read-only PDN and EMC board queries.

The helpers stay free of command routing so each query can be tested with a
mocked pcbnew board. Thickness and coordinates coming out of pcbnew are
nanometres (KiCad 6+ internal units).
"""

from typing import Any, Dict, Optional, Tuple

import pcbnew

NM_PER_MM = 1_000_000

# KiCad PCB_LAYER_ID. F_Cu is 0 and B_Cu is 31 on every KiCad 6+ build;
# inner copper fills 1..30. The technical layers used by a stackup follow.
_CANONICAL_LAYERS: Dict[int, str] = {
    0: "F.Cu",
    **{index: f"In{index}.Cu" for index in range(1, 31)},
    31: "B.Cu",
    32: "B.Adhes",
    33: "F.Adhes",
    34: "B.Paste",
    35: "F.Paste",
    36: "B.SilkS",
    37: "F.SilkS",
    38: "B.Mask",
    39: "F.Mask",
    44: "Edge.Cuts",
}

_UNIT_TO_MM = {"mm": 1.0, "mil": 0.0254, "inch": 25.4}


def no_board() -> Dict[str, Any]:
    """The same failure the other board commands return when nothing is loaded."""
    return {
        "success": False,
        "message": "No board is loaded",
        "errorDetails": "Load or create a board first",
    }


def as_int(value: Any) -> Optional[int]:
    """Return ``value`` when it is a real integer, never a bool or a mock."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def as_float(value: Any) -> Optional[float]:
    """Return ``value`` when it is a real number, never a bool or a mock."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def nm_to_mm(value: Any) -> Optional[float]:
    """Convert a pcbnew nanometre integer to millimetres."""
    nm = as_int(value)
    if nm is None:
        return None
    return nm / NM_PER_MM


def pcb_const(name: str, default: int) -> int:
    """Read a pcbnew integer constant, falling back when the stub returns a mock."""
    value = getattr(pcbnew, name, default)
    parsed = as_int(value)
    return default if parsed is None else parsed


def front_copper_id() -> int:
    """Layer id of the front copper (F.Cu)."""
    return pcb_const("F_Cu", 0)


def back_copper_id() -> int:
    """Layer id of the back copper (B.Cu)."""
    return pcb_const("B_Cu", 31)


def canonical_layer_name(layer_id: Optional[int]) -> Optional[str]:
    """KiCad's standard layer name for ``layer_id``, such as ``F.Cu``."""
    if layer_id is None or layer_id < 0:
        return None
    return _CANONICAL_LAYERS.get(layer_id)


def user_layer_name(board: Any, layer_id: Optional[int]) -> Optional[str]:
    """The layer name stored on this board, which may differ from the canonical one."""
    if board is None or layer_id is None or layer_id < 0:
        return None
    getter = getattr(board, "GetLayerName", None)
    if not callable(getter):
        return None
    try:
        text = getter(layer_id)
    except Exception:
        return None
    if isinstance(text, str) and text:
        return text
    return None


def layer_fields(board: Any, layer_id: Optional[int]) -> Dict[str, Any]:
    """Name fields for one layer id: board name, canonical name, and the id."""
    fields: Dict[str, Any] = {}
    if layer_id is None or layer_id < 0:
        return fields
    fields["layerId"] = layer_id
    user = user_layer_name(board, layer_id)
    canonical = canonical_layer_name(layer_id)
    if user is not None:
        fields["name"] = user
    if canonical is not None:
        fields["canonical"] = canonical
    return fields


def layer_matches(wanted: Optional[str], board: Any, layer_id: Optional[int]) -> bool:
    """True when ``wanted`` is empty or equals the board name or the canonical name."""
    if not wanted:
        return True
    if wanted == user_layer_name(board, layer_id):
        return True
    return wanted == canonical_layer_name(layer_id)


def bbox_mm(bbox: Any) -> Tuple[Optional[Tuple[float, float, float, float]], Optional[str]]:
    """Parse a ``boundingBox`` object into inclusive millimetre limits.

    Returns ``((x1, y1, x2, y2), None)`` or ``(None, error message)``.
    Reversed corners are normalised. ``unit`` defaults to millimetres.
    """
    if not isinstance(bbox, dict):
        return None, "boundingBox must be an object with x1, y1, x2, y2"
    unit = bbox.get("unit") or "mm"
    scale = _UNIT_TO_MM.get(unit)
    if scale is None:
        return None, f"Unsupported boundingBox unit '{unit}'"
    try:
        x1 = float(bbox["x1"]) * scale
        y1 = float(bbox["y1"]) * scale
        x2 = float(bbox["x2"]) * scale
        y2 = float(bbox["y2"]) * scale
    except (KeyError, TypeError, ValueError):
        return None, "boundingBox requires numeric x1, y1, x2, y2"
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)), None


def point_in(x: float, y: float, box: Tuple[float, float, float, float]) -> bool:
    """True when ``(x, y)`` lies inside an inclusive rectangle."""
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def xy_mm(position: Any) -> Optional[Tuple[float, float]]:
    """Convert a pcbnew VECTOR2I (nanometres) to millimetres."""
    if position is None:
        return None
    x = as_int(getattr(position, "x", None))
    y = as_int(getattr(position, "y", None))
    if x is None or y is None:
        return None
    return x / NM_PER_MM, y / NM_PER_MM


def is_via(item: Any) -> bool:
    """True when ``item`` is a pcbnew via rather than a track segment."""
    marker = getattr(pcbnew, "PCB_VIA_T", None)
    try:
        return item.Type() == marker
    except Exception:
        return False


def iter_board_items(board: Any, accessor: str) -> list:
    """Return ``board.Tracks()`` or ``board.Zones()`` as a list, or an empty list."""
    getter = getattr(board, accessor, None)
    if not callable(getter):
        return []
    try:
        return list(getter())
    except TypeError:
        return []
