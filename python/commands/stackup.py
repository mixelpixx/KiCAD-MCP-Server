"""Read the board stackup for a PDN or EMC solve.

padne and openEMS both need the copper thickness and the dielectric gap.
``get_board_info`` only returns layer names, so a custom name such as
``Top Side`` was previously recovered by reading the ``.kicad_pcb`` text.
This command returns those names next to the canonical ``F.Cu`` name and
the thickness of every stackup entry, in millimetres.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

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


def _failure(message: str, details: str) -> Dict[str, Any]:
    return {"success": False, "message": message, "errorDetails": details}


def _optional_int(
    params: Dict[str, Any], key: str
) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    if key not in params or params[key] is None:
        return None, None
    value = as_int(params[key])
    if value is None:
        return None, _failure(f"{key} must be an integer", key)
    return value, None


def _optional_float(
    params: Dict[str, Any], key: str
) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    if key not in params or params[key] is None:
        return None, None
    value = as_float(params[key])
    if value is None:
        return None, _failure(f"{key} must be a number", key)
    return value, None


def _call_set(item: Any, method: str, value: Any, sublayer: int) -> bool:
    """Call a BOARD_STACKUP_ITEM setter. Older builds omit the sublayer argument."""
    fn = getattr(item, method, None)
    if not callable(fn):
        return False
    try:
        fn(value, sublayer)
    except TypeError:
        if sublayer != 0:
            return False
        try:
            fn(value)
        except TypeError:
            return False
    return True


class StackupCommands:
    """Stackup query and edit. Holds the board the interface last loaded."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def get_stackup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return copper and dielectric thicknesses and the board's layer names.

        ``params`` is unused: the tool takes no arguments. The name is part
        of the command-handler signature the dispatcher always passes.
        """
        del params
        try:
            return self._read()
        except Exception as exc:
            logger.error(f"get_stackup failed: {exc}")
            return {
                "success": False,
                "message": "Failed to read stackup",
                "errorDetails": str(exc),
            }

    def set_stackup_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Write thickness, and on a dielectric the material and loss, of one row.

        The row is ``index`` from ``get_stackup`` or ``layer`` (``F.Cu`` or the
        name stored on the board). ``sublayer`` selects a dielectric piece and
        defaults to 0. Fields absent from ``params`` stay as they are.
        """
        try:
            return self._set(params)
        except Exception as exc:
            logger.error(f"set_stackup_layer failed: {exc}")
            return {
                "success": False,
                "message": "Failed to set stackup layer",
                "errorDetails": str(exc),
            }

    def _set(self, params: Dict[str, Any]) -> Dict[str, Any]:
        stack, settings, count, error = self._open()
        if error is not None:
            return error
        selected, error = self._select(stack, count, params)
        if error is not None or selected is None:
            return error or _failure("Stackup row was not found", "index or layer")
        item, entry = selected
        sublayer, error = self._sublayer_index(params, item)
        if error is not None:
            return error

        thickness, error = _optional_float(params, "thicknessMm")
        if error is not None:
            return error
        epsilon, error = _optional_float(params, "epsilonR")
        if error is not None:
            return error
        loss, error = _optional_float(params, "lossTangent")
        if error is not None:
            return error
        material = params.get("material")
        if material is not None and not isinstance(material, str):
            return _failure("material must be a string", "material")
        if isinstance(material, str) and not material:
            return _failure("material must be a string", "material is empty")

        if thickness is None and epsilon is None and loss is None and material is None:
            return _failure(
                "Nothing to change",
                "pass thicknessMm, or for a dielectric epsilonR, lossTangent, or material",
            )
        if entry.get("type") != "dielectric" and (
            epsilon is not None or loss is not None or material is not None
        ):
            return _failure(
                "epsilonR, lossTangent, and material apply only to a dielectric row",
                f"row {entry.get('index')} is {entry.get('type')}",
            )
        if thickness is not None and thickness <= 0:
            return _failure("thicknessMm must be greater than zero", "thicknessMm")
        if epsilon is not None and epsilon <= 0:
            return _failure("epsilonR must be greater than zero", "epsilonR")
        if loss is not None and loss < 0:
            return _failure("lossTangent must be zero or greater", "lossTangent")

        if thickness is not None:
            nm = int(round(thickness * 1_000_000))
            if not _call_set(item, "SetThickness", nm, sublayer):
                return _failure(
                    "This stackup row cannot store a thickness",
                    "SetThickness is not available",
                )
        if epsilon is not None and not _call_set(item, "SetEpsilonR", epsilon, sublayer):
            return _failure(
                "This stackup row cannot store epsilonR",
                "SetEpsilonR is not available",
            )
        if loss is not None and not _call_set(item, "SetLossTangent", loss, sublayer):
            return _failure(
                "This stackup row cannot store lossTangent",
                "SetLossTangent is not available",
            )
        if material is not None and not _call_set(item, "SetMaterial", material, sublayer):
            return _failure(
                "This stackup row cannot store material",
                "SetMaterial is not available",
            )
        if thickness is not None:
            self._sync_board_thickness(stack, settings, count)

        updated = self._entry(item, entry["index"])
        updated.pop("thicknessNm", None)
        return {"success": True, "message": "Updated stackup layer", "layer": updated}

    def _open(self) -> Tuple[Any, Any, int, Optional[Dict[str, Any]]]:
        """Return the stackup, or an error dict in the last position."""
        if not self.board:
            return None, None, 0, no_board()
        settings_fn = getattr(self.board, "GetDesignSettings", None)
        if not callable(settings_fn):
            return (
                None,
                None,
                0,
                {
                    "success": False,
                    "message": "Board has no design settings",
                    "errorDetails": "GetDesignSettings is not available",
                },
            )
        settings = settings_fn()
        stack_fn = getattr(settings, "GetStackup", None)
        if not callable(stack_fn):
            return (
                None,
                None,
                0,
                {
                    "success": False,
                    "message": "Board has no stackup",
                    "errorDetails": "GetDesignSettings().GetStackup is not available",
                },
            )
        stack = stack_fn()
        count = as_int(stack.GetCount())
        if count is None:
            return (
                None,
                None,
                0,
                {
                    "success": False,
                    "message": "Stackup has no layer count",
                    "errorDetails": "BOARD_STACKUP.GetCount did not return an integer",
                },
            )
        return stack, settings, count, None

    def _select(
        self, stack: Any, count: int, params: Dict[str, Any]
    ) -> Tuple[Optional[Tuple[Any, Dict[str, Any]]], Optional[Dict[str, Any]]]:
        index, error = _optional_int(params, "index")
        if error is not None:
            return None, error
        layer = params.get("layer")
        if layer is not None and (not isinstance(layer, str) or not layer):
            return None, _failure("layer must be a string", "layer")
        if index is None and layer is None:
            return None, _failure(
                "index or layer is required",
                "name the stackup row by index or by layer",
            )

        rows = [(stack.GetLayer(i), self._entry(stack.GetLayer(i), i)) for i in range(count)]
        chosen: Optional[Tuple[Any, Dict[str, Any]]] = None
        if index is not None:
            if index < 0 or index >= count:
                return None, _failure(
                    "index is outside the stackup",
                    f"index {index} but the stackup has {count} rows",
                )
            chosen = rows[index]
        if isinstance(layer, str):
            hits = [
                row
                for row in rows
                if row[1].get("canonical") == layer or row[1].get("name") == layer
            ]
            if not hits:
                return None, _failure(
                    f"No stackup row named {layer}",
                    "layer did not match a canonical name or a board layer name",
                )
            if len(hits) > 1:
                return None, _failure(
                    f"More than one stackup row is named {layer}",
                    "layer",
                )
            if chosen is not None and hits[0][1]["index"] != chosen[1]["index"]:
                return None, _failure(
                    "index and layer name different rows",
                    "pass the index of that layer, or the layer on its own",
                )
            chosen = hits[0]
        return chosen, None

    def _sublayer_index(
        self, params: Dict[str, Any], item: Any
    ) -> Tuple[int, Optional[Dict[str, Any]]]:
        sublayer, error = _optional_int(params, "sublayer")
        if error is not None:
            return 0, error
        if sublayer is None:
            sublayer = 0
        count = _sublayer_count(item)
        if sublayer < 0 or sublayer >= count:
            return 0, _failure(
                "sublayer is outside this row",
                f"sublayer {sublayer} but the row has {count}",
            )
        return sublayer, None

    def _sync_board_thickness(self, stack: Any, settings: Any, count: int) -> None:
        """Keep the stored board thickness equal to the sum of the stackup rows."""
        total = 0
        saw = False
        for index in range(count):
            item = stack.GetLayer(index)
            for sub in range(_sublayer_count(item)):
                thick = _call_nm(item, "GetThickness", sub)
                if thick is None:
                    continue
                total += thick
                saw = True
        if not saw:
            return
        setter = getattr(settings, "SetBoardThickness", None)
        if not callable(setter):
            setter = getattr(self.board, "SetBoardThickness", None)
        if not callable(setter):
            return
        try:
            setter(total)
        except TypeError:
            return

    def _read(self) -> Dict[str, Any]:
        stack, settings, count, error = self._open()
        if error is not None:
            return error

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
