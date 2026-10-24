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


def _tolerance(
    params: Dict[str, Any], key: str, default: float
) -> Tuple[float, Optional[Dict[str, Any]]]:
    if key not in params or params[key] is None:
        return default, None
    value = as_float(params[key])
    if value is None or value < 0:
        return 0.0, _failure(f"{key} must be zero or greater", key)
    return value, None


def _difference(
    index: Any, layer: Any, field: str, actual: Any, expected: Any, delta: Any
) -> Dict[str, Any]:
    return {
        "index": index,
        "layer": layer,
        "field": field,
        "actual": actual,
        "expected": expected,
        "delta": delta,
    }


class StackupCommands:
    """Read-only stackup query and recipe check. Holds the board the interface last loaded."""

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

    def check_stackup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Compare the board stackup with a recipe supplied by the caller.

        Each entry in ``expected`` names a row by ``index`` or ``layer`` and
        may give ``type``, ``thicknessMm``, and ``epsilonR``. Thickness uses
        ``thicknessToleranceMm`` (default 0.001 mm). Permittivity uses
        ``epsilonTolerance`` (default 0.01). A difference inside the tolerance
        is not a mismatch.
        """
        if not self.board:
            return no_board()
        try:
            return self._check(params)
        except Exception as exc:
            logger.error(f"check_stackup failed: {exc}")
            return {
                "success": False,
                "message": "Failed to check stackup",
                "errorDetails": str(exc),
            }

    def _check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        expected = params.get("expected")
        if not isinstance(expected, list) or not expected:
            return _failure(
                "expected must list at least one row",
                "expected",
            )
        thickness_tol, error = _tolerance(params, "thicknessToleranceMm", 0.001)
        if error is not None:
            return error
        epsilon_tol, error = _tolerance(params, "epsilonTolerance", 0.01)
        if error is not None:
            return error

        current = self._read()
        if not current.get("success"):
            return current

        mismatches: List[Dict[str, Any]] = []
        for row in expected:
            if not isinstance(row, dict):
                return _failure("each expected row must be an object", "expected")
            entry, error, missing = self._locate(current["layers"], row)
            if error is not None:
                return error
            if missing or entry is None:
                mismatches.append(
                    _difference(
                        row.get("index"),
                        row.get("layer"),
                        "layer",
                        None,
                        row.get("layer", row.get("index")),
                        None,
                    )
                )
                continue
            row_diffs, error = self._differences(entry, row, thickness_tol, epsilon_tol)
            if error is not None:
                return error
            mismatches.extend(row_diffs)

        return {
            "success": True,
            "ok": not mismatches,
            "mismatchCount": len(mismatches),
            "mismatches": mismatches,
        }

    def _locate(
        self, layers: List[Dict[str, Any]], row: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
        raw_index = row.get("index")
        index = None
        if raw_index is not None:
            index = as_int(raw_index)
            if index is None:
                return None, _failure("index must be an integer", "index"), False
        layer = row.get("layer")
        if layer is not None and (not isinstance(layer, str) or not layer):
            return None, _failure("layer must be a string", "layer"), False
        if index is None and layer is None:
            return (
                None,
                _failure(
                    "each expected row needs an index or a layer",
                    "index or layer",
                ),
                False,
            )

        chosen: Optional[Dict[str, Any]] = None
        if index is not None:
            if index < 0 or index >= len(layers):
                return None, None, True
            chosen = layers[index]
        if isinstance(layer, str):
            hits = [
                entry
                for entry in layers
                if entry.get("canonical") == layer or entry.get("name") == layer
            ]
            if len(hits) > 1:
                return (
                    None,
                    _failure(
                        f"More than one stackup row is named {layer}",
                        "layer",
                    ),
                    False,
                )
            if not hits:
                return None, None, True
            if chosen is not None and hits[0]["index"] != chosen["index"]:
                return (
                    None,
                    _failure(
                        "index and layer name different rows",
                        "pass the index of that layer, or the layer on its own",
                    ),
                    False,
                )
            chosen = hits[0]
        return chosen, None, False

    def _differences(
        self,
        entry: Dict[str, Any],
        row: Dict[str, Any],
        thickness_tol: float,
        epsilon_tol: float,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        found: List[Dict[str, Any]] = []
        label = entry.get("canonical") or entry.get("name")
        if "type" in row and row["type"] is not None:
            if not isinstance(row["type"], str):
                return [], _failure("type must be a string", "type")
            if row["type"] != entry.get("type"):
                found.append(
                    _difference(entry["index"], label, "type", entry.get("type"), row["type"], None)
                )
        if "thicknessMm" in row and row["thicknessMm"] is not None:
            expected = as_float(row["thicknessMm"])
            if expected is None:
                return [], _failure("thicknessMm must be a number", "thicknessMm")
            actual = entry.get("thicknessMm")
            if actual is None or abs(actual - expected) > thickness_tol:
                delta = None if actual is None else actual - expected
                found.append(
                    _difference(entry["index"], label, "thicknessMm", actual, expected, delta)
                )
        if "epsilonR" in row and row["epsilonR"] is not None:
            expected_eps = as_float(row["epsilonR"])
            if expected_eps is None:
                return [], _failure("epsilonR must be a number", "epsilonR")
            actual_eps = entry.get("epsilonR")
            if actual_eps is None or abs(actual_eps - expected_eps) > epsilon_tol:
                delta = None if actual_eps is None else actual_eps - expected_eps
                found.append(
                    _difference(entry["index"], label, "epsilonR", actual_eps, expected_eps, delta)
                )
        return found, None

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
