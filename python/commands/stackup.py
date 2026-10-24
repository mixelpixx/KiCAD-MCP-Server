"""Read the board stackup for a PDN or EMC solve.

padne and openEMS both need the copper thickness and the dielectric gap.
``get_board_info`` only returns layer names, so a custom name such as
``Top Side`` was previously recovered by reading the ``.kicad_pcb`` text.
This command returns those names next to the canonical ``F.Cu`` name and
the thickness of every stackup entry, in millimetres.
"""

import logging
from typing import Any, Dict, List, Optional

from commands.analysis_geom import (
    as_float,
    as_int,
    layer_fields,
    nm_to_mm,
    no_board,
)

logger = logging.getLogger("kicad_interface")

_TYPE_BY_INT = {
    1: "copper",
    2: "dielectric",
    3: "solderpaste",
    4: "soldermask",
    5: "silkscreen",
}


def _item_type(item: Any) -> str:
    """Map a BOARD_STACKUP_ITEM type enum to a short name."""
    raw = item.GetType()
    number = as_int(raw)
    if number is not None:
        return _TYPE_BY_INT.get(number, "undefined")
    text = str(getattr(raw, "name", raw)).upper()
    for label in _TYPE_BY_INT.values():
        if label.upper() in text:
            return label
    return "undefined"


def _call_nm(item: Any, method: str, index: int) -> Optional[int]:
    """Call a thickness accessor that may or may not take a sublayer index."""
    fn = getattr(item, method, None)
    if not callable(fn):
        return None
    try:
        return as_int(fn(index))
    except TypeError:
        if index != 0:
            return None
        try:
            return as_int(fn())
        except TypeError:
            return None


def _sublayer_count(item: Any) -> int:
    """How many dielectric sublayers this stackup entry holds. Copper is one."""
    for name in ("GetSublayersCount", "GetDielectricLayerCount"):
        fn = getattr(item, name, None)
        if not callable(fn):
            continue
        try:
            count = as_int(fn())
        except TypeError:
            count = None
        if count is not None and count > 0:
            return count
    return 1


def _text(item: Any, method: str, index: int) -> Optional[str]:
    fn = getattr(item, method, None)
    if not callable(fn):
        return None
    try:
        value = fn(index)
    except TypeError:
        if index != 0:
            return None
        try:
            value = fn()
        except TypeError:
            return None
    if isinstance(value, str) and value:
        return value
    return None


class StackupCommands:
    """Read-only stackup query. Holds the board the interface last loaded."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def get_stackup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return copper and dielectric thicknesses and the board's layer names.

        ``params`` is unused: the tool takes no arguments. The name is part
        of the command-handler signature the dispatcher always passes.
        """
        del params
        if not self.board:
            return no_board()
        try:
            return self._read()
        except Exception as exc:
            logger.error(f"get_stackup failed: {exc}")
            return {
                "success": False,
                "message": "Failed to read stackup",
                "errorDetails": str(exc),
            }

    def _read(self) -> Dict[str, Any]:
        settings_fn = getattr(self.board, "GetDesignSettings", None)
        if not callable(settings_fn):
            return {
                "success": False,
                "message": "Board has no design settings",
                "errorDetails": "GetDesignSettings is not available",
            }
        settings = settings_fn()
        stack_fn = getattr(settings, "GetStackup", None)
        if not callable(stack_fn):
            return {
                "success": False,
                "message": "Board has no stackup",
                "errorDetails": "GetDesignSettings().GetStackup is not available",
            }
        stack = stack_fn()
        count = as_int(stack.GetCount())
        if count is None:
            return {
                "success": False,
                "message": "Stackup has no layer count",
                "errorDetails": "BOARD_STACKUP.GetCount did not return an integer",
            }

        layers: List[Dict[str, Any]] = []
        thickness_sum_nm = 0
        saw_thickness = False
        for index in range(count):
            item = stack.GetLayer(index)
            entry = self._entry(item, index)
            layers.append(entry)
            if entry.get("thicknessNm") is not None:
                thickness_sum_nm += entry["thicknessNm"]
                saw_thickness = True

        for entry in layers:
            entry.pop("thicknessNm", None)

        result: Dict[str, Any] = {
            "success": True,
            "copperCount": sum(1 for entry in layers if entry.get("type") == "copper"),
            "layers": layers,
        }
        board_nm = self._board_thickness_nm(settings)
        if board_nm is not None:
            result["boardThicknessMm"] = board_nm / 1_000_000
        elif saw_thickness:
            result["boardThicknessMm"] = thickness_sum_nm / 1_000_000
        return result

    def _board_thickness_nm(self, settings: Any) -> Optional[int]:
        getter = getattr(settings, "GetBoardThickness", None)
        if not callable(getter):
            return None
        try:
            return as_int(getter())
        except TypeError:
            return None

    def _entry(self, item: Any, index: int) -> Dict[str, Any]:
        kind = _item_type(item)
        layer_id = None
        layer_fn = getattr(item, "GetBrdLayerId", None)
        if callable(layer_fn):
            try:
                layer_id = as_int(layer_fn())
            except TypeError:
                layer_id = None

        sublayers = _sublayer_count(item)
        pieces: List[Dict[str, Any]] = []
        total_nm = 0
        saw = False
        for sub in range(sublayers):
            piece: Dict[str, Any] = {}
            thick = _call_nm(item, "GetThickness", sub)
            if thick is not None:
                piece["thicknessMm"] = nm_to_mm(thick)
                total_nm += thick
                saw = True
            if kind == "dielectric":
                epsilon = self._number(item, "GetEpsilonR", sub)
                loss = self._number(item, "GetLossTangent", sub)
                material = _text(item, "GetMaterial", sub)
                if epsilon is not None:
                    piece["epsilonR"] = epsilon
                if loss is not None:
                    piece["lossTangent"] = loss
                if material is not None:
                    piece["material"] = material
            if piece:
                pieces.append(piece)

        entry: Dict[str, Any] = {"index": index, "type": kind}
        entry.update(layer_fields(self.board, layer_id))
        if saw:
            entry["thicknessMm"] = total_nm / 1_000_000
            entry["thicknessNm"] = total_nm
        if kind == "dielectric" and pieces:
            first = pieces[0]
            for key in ("epsilonR", "lossTangent", "material"):
                if key in first:
                    entry[key] = first[key]
            if sublayers > 1:
                entry["sublayers"] = pieces
        return entry

    def _number(self, item: Any, method: str, index: int) -> Optional[float]:
        fn = getattr(item, method, None)
        if not callable(fn):
            return None
        try:
            return as_float(fn(index))
        except TypeError:
            if index != 0:
                return None
            try:
                return as_float(fn())
            except TypeError:
                return None
