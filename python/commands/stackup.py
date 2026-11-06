"""Read the board stackup for a PDN or EMC solve.

``get_board_info`` only returns layer names. Copper thickness and the
dielectric gap live in the ``(stackup ...)`` section of the ``.kicad_pcb``
file. KiCad 10's pcbnew bindings do not expose that data: ``GetStackup`` is
missing, and ``GetStackupDescriptor()`` returns an opaque object. This command
reads the file instead, which is how the rest of the server handles data SWIG
does not surface.
"""

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.sexpr_format import (
    escape_sexpr_string,
    iter_child_offsets,
    match_paren,
    unescape_sexpr_string,
)

logger = logging.getLogger("kicad_interface")

# The first atom is the value. KiCad may follow a thickness with ``locked``
# when that row is locked in the stackup editor: ``(thickness 1.51 locked)``.
_VALUE = re.compile(
    r"\(\s*[A-Za-z0-9_]+\s+"
    r"(?:\"((?:[^\"\\]|\\.)*)\"|([-+0-9.eE]+)|([A-Za-z_][A-Za-z0-9_]*))"
    r"(?P<rest>.*?)\s*\)",
    re.DOTALL,
)
_LOCKED = re.compile(r"(?<![A-Za-z0-9_])locked(?![A-Za-z0-9_])")
_LAYER_TOKEN = re.compile(r"\(\s*layer\s+\"((?:[^\"\\]|\\.)*)\"")
_LIST_HEAD = re.compile(r"\(\s*([A-Za-z0-9_]+)")


def _failure(message: str, details: str) -> Dict[str, Any]:
    return {"success": False, "message": message, "errorDetails": details}


def _no_board() -> Dict[str, Any]:
    return _failure("No board is loaded", "Load or create a board first")


def _as_int(value: Any) -> Optional[int]:
    """Return ``value`` when it is a real integer, never a bool or a mock."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_float(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _kind(type_text: Optional[str]) -> str:
    """Map a stackup ``(type ...)`` string onto the short name callers expect."""
    if not type_text:
        return "undefined"
    text = type_text.lower()
    if text == "copper":
        return "copper"
    if text in ("core", "prepreg") or "dielectric" in text:
        return "dielectric"
    if "mask" in text:
        return "soldermask"
    if "paste" in text:
        return "solderpaste"
    if "silk" in text:
        return "silkscreen"
    return "undefined"


def _find_list(text: str, head: str, start: int = 0) -> Optional[Tuple[int, int]]:
    """Return the inclusive span of the first ``(head ...)`` list."""
    token = "(" + head
    in_string = False
    i = start
    limit = len(text)
    while i < limit:
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if text.startswith(token, i):
            after = i + len(token)
            if after >= limit or text[after] in " \t\r\n)":
                close = match_paren(text, i)
                if close < 0:
                    return None
                return i, close
        i += 1
    return None


def _child_lists(block: str) -> List[str]:
    """Text of each list nested directly inside ``block``."""
    found: List[str] = []
    for offset in iter_child_offsets(block):
        close = match_paren(block, offset)
        if close < 0:
            continue
        found.append(block[offset : close + 1])
    return found


def _list_head(block: str) -> str:
    match = _LIST_HEAD.match(block)
    return match.group(1) if match else ""


def _list_value(block: str) -> Optional[str]:
    """The first atom of ``(thickness 0.035)`` or ``(material "FR4")``.

    A trailing ``locked`` flag is ignored here and reported by
    ``_thickness_locked``.
    """
    match = _VALUE.match(block)
    if not match:
        return None
    quoted, number, symbol = match.group(1), match.group(2), match.group(3)
    if quoted is not None:
        return unescape_sexpr_string(quoted)
    return number if number is not None else symbol


def _thickness_locked(block: str) -> bool:
    """True when KiCad saved ``(thickness <mm> locked)`` for this row."""
    match = _VALUE.match(block)
    if not match:
        return False
    return _LOCKED.search(match.group("rest") or "") is not None


def _parse_layer(block: str) -> Optional[Dict[str, Any]]:
    """One ``(layer ...)`` row. Dielectric sublayers repeat thickness and loss."""
    match = _LAYER_TOKEN.match(block)
    if not match:
        return None
    token = unescape_sexpr_string(match.group(1))
    type_text: Optional[str] = None
    sublayers: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for child in _child_lists(block):
        head = _list_head(child)
        value = _list_value(child)
        if head == "type":
            type_text = value
            continue
        if head == "thickness":
            current = {}
            thickness = _as_float(value)
            if thickness is not None:
                current["thicknessMm"] = thickness
            if _thickness_locked(child):
                current["thicknessLocked"] = True
            sublayers.append(current)
            continue
        if current is None or value is None:
            continue
        if head == "material":
            current["material"] = value
        elif head == "epsilon_r":
            epsilon = _as_float(value)
            if epsilon is not None:
                current["epsilonR"] = epsilon
        elif head == "loss_tangent":
            loss = _as_float(value)
            if loss is not None:
                current["lossTangent"] = loss
    return {"token": token, "typeText": type_text, "sublayers": sublayers}


def _board_thickness_mm(text: str) -> Optional[float]:
    """``(general (thickness ...))`` is the board thickness KiCad stores, in mm."""
    found = _find_list(text, "general")
    if found is None:
        return None
    block = text[found[0] : found[1] + 1]
    for child in _child_lists(block):
        if _list_head(child) == "thickness":
            return _as_float(_list_value(child))
    return None


def _call_str(board: Any, method: str, argument: Any) -> Optional[str]:
    fn = getattr(board, method, None)
    if not callable(fn):
        return None
    try:
        value = fn(argument)
    except Exception:
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _layer_id(board: Any, token: str) -> Optional[int]:
    """Resolve a canonical stackup name such as ``F.Cu`` through the board."""
    fn = getattr(board, "GetLayerID", None)
    if not callable(fn):
        return None
    try:
        parsed = _as_int(fn(token))
    except Exception:
        return None
    # UNDEFINED_LAYER comes back negative, or as a huge unsigned value.
    if parsed is None or parsed < 0 or parsed > 128:
        return None
    return parsed


def _name_fields(board: Any, token: str) -> Dict[str, Any]:
    """Board name beside the canonical name. A dielectric row has neither."""
    if token.lower().startswith("dielectric"):
        return {}
    layer_id = _layer_id(board, token)
    if layer_id is None:
        return {"canonical": token}
    fields: Dict[str, Any] = {"layerId": layer_id, "canonical": token}
    standard = _call_str(board, "GetStandardLayerName", layer_id)
    user = _call_str(board, "GetLayerName", layer_id)
    if standard:
        fields["canonical"] = standard
    if user:
        fields["name"] = user
    return fields


def _entry(board: Any, index: int, row: Dict[str, Any]) -> Dict[str, Any]:
    kind = _kind(row.get("typeText"))
    pieces: List[Dict[str, Any]] = [piece for piece in row["sublayers"] if piece]
    entry: Dict[str, Any] = {"index": index, "type": kind}
    entry.update(_name_fields(board, row["token"]))
    total = 0.0
    saw = False
    for piece in pieces:
        thickness = piece.get("thicknessMm")
        if isinstance(thickness, (int, float)):
            total += float(thickness)
            saw = True
    if saw:
        entry["thicknessMm"] = total
    if any(piece.get("thicknessLocked") for piece in pieces):
        entry["thicknessLocked"] = True
    if kind == "dielectric" and pieces:
        first = pieces[0]
        for key in ("epsilonR", "lossTangent", "material"):
            if key in first:
                entry[key] = first[key]
        if len(pieces) > 1:
            entry["sublayers"] = pieces
    return entry


def read_stackup_text(board: Any, text: str) -> Dict[str, Any]:
    """Parse a ``.kicad_pcb`` document and return the get_stackup payload."""
    found = _find_list(text, "stackup")
    if found is None:
        return _failure(
            "Board has no stackup",
            "The board file has no (stackup ...) section",
        )
    block = text[found[0] : found[1] + 1]
    layers: List[Dict[str, Any]] = []
    for child in _child_lists(block):
        if _list_head(child) != "layer":
            continue
        row = _parse_layer(child)
        if row is None:
            continue
        layers.append(_entry(board, len(layers), row))

    result: Dict[str, Any] = {
        "success": True,
        "copperCount": sum(1 for entry in layers if entry.get("type") == "copper"),
        "layers": layers,
    }
    stored = _board_thickness_mm(text)
    if stored is not None:
        result["boardThicknessMm"] = stored
    else:
        total = sum(entry["thicknessMm"] for entry in layers if "thicknessMm" in entry)
        if total:
            result["boardThicknessMm"] = total
    return result


def _param_number(
    params: Dict[str, Any], key: str
) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    if key not in params or params[key] is None:
        return None, None
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, _failure(f"{key} must be a number", key)
    return float(value), None


def _param_int(params: Dict[str, Any], key: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    if key not in params or params[key] is None:
        return None, None
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        return None, _failure(f"{key} must be an integer", key)
    return value, None


def _tolerance(
    params: Dict[str, Any], key: str, default: float
) -> Tuple[float, Optional[Dict[str, Any]]]:
    if key not in params or params[key] is None:
        return default, None
    value, error = _param_number(params, key)
    if error is not None or value is None:
        return 0.0, error
    if value < 0:
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


def _locate(
    layers: List[Dict[str, Any]], row: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
    index, error = _param_int(row, "index")
    if error is not None:
        return None, error, False
    layer = row.get("layer")
    if layer is not None and (not isinstance(layer, str) or not layer):
        return None, _failure("layer must be a string", "layer"), False
    if index is None and layer is None:
        return (
            None,
            _failure("each expected row needs an index or a layer", "index or layer"),
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
            return None, _failure(f"More than one stackup row is named {layer}", "layer"), False
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


def _row_differences(
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
        expected, error = _param_number(row, "thicknessMm")
        if error is not None:
            return [], error
        actual = entry.get("thicknessMm")
        if actual is None or abs(actual - expected) > thickness_tol:
            delta = None if actual is None else actual - expected
            found.append(_difference(entry["index"], label, "thicknessMm", actual, expected, delta))
    if "epsilonR" in row and row["epsilonR"] is not None:
        expected_eps, error = _param_number(row, "epsilonR")
        if error is not None:
            return [], error
        pieces = entry.get("sublayers") or [{"epsilonR": entry.get("epsilonR")}]
        for sublayer, piece in enumerate(pieces):
            actual_eps = piece.get("epsilonR") if isinstance(piece, dict) else None
            if actual_eps is None or abs(actual_eps - expected_eps) > epsilon_tol:
                delta = None if actual_eps is None else actual_eps - expected_eps
                difference = _difference(
                    entry["index"], label, "epsilonR", actual_eps, expected_eps, delta
                )
                if len(pieces) > 1:
                    difference["sublayer"] = sublayer
                found.append(difference)
    return found, None


def compare_stackup(current: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a recipe comparison to a successful get_stackup result."""
    expected = params.get("expected")
    if not isinstance(expected, list) or not expected:
        return _failure("expected must list at least one row", "expected")
    thickness_tol, error = _tolerance(params, "thicknessToleranceMm", 0.001)
    if error is not None:
        return error
    epsilon_tol, error = _tolerance(params, "epsilonTolerance", 0.01)
    if error is not None:
        return error
    mismatches: List[Dict[str, Any]] = []
    for row in expected:
        if not isinstance(row, dict):
            return _failure("each expected row must be an object", "expected")
        entry, error, missing = _locate(current["layers"], row)
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
        row_diffs, error = _row_differences(entry, row, thickness_tol, epsilon_tol)
        if error is not None:
            return error
        mismatches.extend(row_diffs)
    compared = dict(current)
    compared["ok"] = not mismatches
    compared["mismatchCount"] = len(mismatches)
    compared["mismatches"] = mismatches
    return compared


def _fmt_mm(value: float) -> str:
    """A short decimal KiCad will read back as the same millimetre value."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    if "." not in text:
        return text + ".0"
    return text


def _indent_at(block: str, index: int) -> str:
    line = block.rfind("\n", 0, index) + 1
    return block[line:index]


def _apply_edits(block: str, edits: List[Tuple[int, int, str]]) -> str:
    """Apply ``(start, end, text)`` replacements. ``end`` is exclusive."""
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        block = block[:start] + replacement + block[end:]
    return block


def _layer_records(
    text: str, board: Any
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    found = _find_list(text, "stackup")
    if found is None:
        return None, _failure(
            "Board has no stackup",
            "The board file has no (stackup ...) section",
        )
    block_open = found[0]
    block = text[block_open : found[1] + 1]
    records: List[Dict[str, Any]] = []
    for offset in iter_child_offsets(block):
        close = match_paren(block, offset)
        if close < 0:
            continue
        child = block[offset : close + 1]
        if _list_head(child) != "layer":
            continue
        row = _parse_layer(child)
        if row is None:
            continue
        records.append(
            {
                "open": block_open + offset,
                "close": block_open + close,
                "text": child,
                "token": row["token"],
                "entry": _entry(board, len(records), row),
            }
        )
    return records, None


def _select_record(
    records: List[Dict[str, Any]], params: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    index, error = _param_int(params, "index")
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
    chosen: Optional[Dict[str, Any]] = None
    if index is not None:
        if index < 0 or index >= len(records):
            return None, _failure(
                "index is outside the stackup",
                f"index {index} but the stackup has {len(records)} rows",
            )
        chosen = records[index]
    if isinstance(layer, str):
        hits = [
            record
            for record in records
            if layer
            in (
                record["entry"].get("canonical"),
                record["entry"].get("name"),
                record.get("token"),
            )
        ]
        if not hits:
            return None, _failure(
                f"No stackup row named {layer}",
                "layer did not match the file token, a canonical name, or a board layer name",
            )
        if len(hits) > 1:
            return None, _failure(f"More than one stackup row is named {layer}", "layer")
        if chosen is not None and hits[0]["entry"]["index"] != chosen["entry"]["index"]:
            return None, _failure(
                "index and layer name different rows",
                "pass the index of that layer, or the layer on its own",
            )
        chosen = hits[0]
    return chosen, None


def _edit_layer_block(
    block: str,
    sublayer: int,
    thickness: Optional[float],
    epsilon: Optional[float],
    loss: Optional[float],
    material: Optional[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Replace one sublayer's fields inside a ``(layer ...)`` list."""
    children: List[Tuple[int, int, str]] = []
    for offset in iter_child_offsets(block):
        close = match_paren(block, offset)
        if close < 0:
            continue
        children.append((offset, close, block[offset : close + 1]))
    groups: List[Dict[str, Tuple[int, int]]] = []
    current: Optional[Dict[str, Tuple[int, int]]] = None
    for offset, close, child in children:
        head = _list_head(child)
        if head == "thickness":
            current = {"thickness": (offset, close)}
            groups.append(current)
        elif current is not None and head in ("material", "epsilon_r", "loss_tangent"):
            current[head] = (offset, close)
    if sublayer < 0 or (groups and sublayer >= len(groups)) or (not groups and sublayer != 0):
        count = len(groups) if groups else 1
        return None, _failure(
            "sublayer is outside this row",
            f"sublayer {sublayer} but the row has {count}",
        )
    edits: List[Tuple[int, int, str]] = []
    if not groups:
        if thickness is None:
            return None, _failure(
                "This stackup row cannot store a thickness",
                "the layer has no thickness",
            )
        insert_at = len(block) - 1
        indent = "  "
        blob = f"\n{indent}(thickness {_fmt_mm(thickness)})"
        edits.append((insert_at, insert_at, blob))
        return _apply_edits(block, edits), None

    group = groups[sublayer]
    thick_open, thick_close = group["thickness"]
    if thickness is not None:
        locked = " locked" if _thickness_locked(block[thick_open : thick_close + 1]) else ""
        edits.append((thick_open, thick_close + 1, f"(thickness {_fmt_mm(thickness)}{locked})"))
    extras: List[str] = []
    indent = _indent_at(block, thick_open)
    if material is not None:
        token = f'(material "{escape_sexpr_string(material)}")'
        if "material" in group:
            open_at, close_at = group["material"]
            edits.append((open_at, close_at + 1, token))
        else:
            extras.append(token)
    if epsilon is not None:
        token = f"(epsilon_r {_fmt_mm(epsilon)})"
        if "epsilon_r" in group:
            open_at, close_at = group["epsilon_r"]
            edits.append((open_at, close_at + 1, token))
        else:
            extras.append(token)
    if loss is not None:
        token = f"(loss_tangent {_fmt_mm(loss)})"
        if "loss_tangent" in group:
            open_at, close_at = group["loss_tangent"]
            edits.append((open_at, close_at + 1, token))
        else:
            extras.append(token)
    if extras:
        blob = "".join(f"\n{indent}{token}" for token in extras)
        edits.append((thick_close + 1, thick_close + 1, blob))
    return _apply_edits(block, edits), None


def _set_general_thickness(text: str, mm: float) -> str:
    found = _find_list(text, "general")
    if found is None:
        return text
    block_open = found[0]
    block = text[block_open : found[1] + 1]
    for offset in iter_child_offsets(block):
        close = match_paren(block, offset)
        if close < 0:
            continue
        child = block[offset : close + 1]
        if _list_head(child) != "thickness":
            continue
        replacement = f"(thickness {_fmt_mm(mm)})"
        start = block_open + offset
        end = block_open + close + 1
        return text[:start] + replacement + text[end:]
    return text


def _structural_thickness(layers: List[Dict[str, Any]]) -> Optional[float]:
    """Sum of every row, or None when a copper or dielectric row has no thickness.

    A silk row often has no thickness. A copper or dielectric row without one
    means the parse missed a value, and rewriting ``(general (thickness))``
    from that sum would shrink the board.
    """
    for entry in layers:
        if entry.get("type") in ("copper", "dielectric") and "thicknessMm" not in entry:
            return None
    return sum(float(entry["thicknessMm"]) for entry in layers if "thicknessMm" in entry)


class StackupCommands:
    """Stackup query and one-row edit. Holds the board the interface last loaded."""

    def __init__(self, board: Any, host: Any = None) -> None:
        self.board = board
        self.host = host

    def get_stackup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return copper and dielectric thicknesses and the board's layer names.

        Pass ``expected`` to compare the stackup with a recipe in the same call.
        Each row names a layer by ``index`` or ``layer`` and may give ``type``,
        ``thicknessMm``, and ``epsilonR``. Thickness uses ``thicknessToleranceMm``
        (default 0.001 mm). Permittivity uses ``epsilonTolerance`` (default 0.01).
        """
        if not self.board:
            return _no_board()
        try:
            current = self._read()
        except Exception as exc:
            logger.error(f"get_stackup failed: {exc}")
            return _failure("Failed to read stackup", str(exc))
        if not current.get("success") or "expected" not in params or params.get("expected") is None:
            return current
        return compare_stackup(current, params)

    def set_stackup_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Write thickness, and on a dielectric the material and loss, of one row.

        The row is ``index`` from ``get_stackup`` or ``layer`` (``F.Cu`` or the
        name stored on the board). ``sublayer`` selects a dielectric piece and
        defaults to 0. Fields absent from ``params`` stay as they are. The
        change is written into the ``(stackup ...)`` section of the board file,
        because pcbnew does not expose a stackup setter.
        """
        if not self.board:
            return _no_board()
        try:
            return self._set(params)
        except Exception as exc:
            logger.error(f"set_stackup_layer failed: {exc}")
            return _failure("Failed to set stackup layer", str(exc))

    def _set(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = self._board_path()
        if path is None:
            return _failure(
                "Board has no file",
                "The loaded board has no .kicad_pcb path to write the stackup to",
            )
        file_path = Path(path)
        if not file_path.is_file():
            return _failure("Board file is missing", f"Cannot write stackup to {path}")
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            return _failure("Failed to read board file", str(exc))

        records, error = _layer_records(text, self.board)
        if error is not None or records is None:
            return error or _failure("Board has no stackup", "stackup")
        chosen, error = _select_record(records, params)
        if error is not None or chosen is None:
            return error or _failure("Stackup row was not found", "index or layer")

        sublayer, error = _param_int(params, "sublayer")
        if error is not None:
            return error
        if sublayer is None:
            sublayer = 0
        thickness, error = _param_number(params, "thicknessMm")
        if error is not None:
            return error
        epsilon, error = _param_number(params, "epsilonR")
        if error is not None:
            return error
        loss, error = _param_number(params, "lossTangent")
        if error is not None:
            return error
        material = params.get("material")
        if material is not None and (not isinstance(material, str) or not material):
            return _failure("material must be a string", "material")

        if thickness is None and epsilon is None and loss is None and material is None:
            return _failure(
                "Nothing to change",
                "pass thicknessMm, or for a dielectric epsilonR, lossTangent, or material",
            )
        if chosen["entry"].get("type") != "dielectric" and (
            epsilon is not None or loss is not None or material is not None
        ):
            return _failure(
                "epsilonR, lossTangent, and material apply only to a dielectric row",
                f"row {chosen['entry'].get('index')} is {chosen['entry'].get('type')}",
            )
        if thickness is not None and thickness <= 0:
            return _failure("thicknessMm must be greater than zero", "thicknessMm")
        if epsilon is not None and epsilon <= 0:
            return _failure("epsilonR must be greater than zero", "epsilonR")
        if loss is not None and loss < 0:
            return _failure("lossTangent must be zero or greater", "lossTangent")

        revised, error = _edit_layer_block(
            chosen["text"], sublayer, thickness, epsilon, loss, material
        )
        if error is not None or revised is None:
            return error or _failure("Failed to edit stackup layer", "layer")
        updated = text[: chosen["open"]] + revised + text[chosen["close"] + 1 :]
        if thickness is not None:
            reread = read_stackup_text(self.board, updated)
            if reread.get("success"):
                total = _structural_thickness(reread["layers"])
                if total is not None:
                    updated = _set_general_thickness(updated, total)
        refused = self._refuse_direct_write()
        if refused is not None:
            return refused
        try:
            self._backup_board(file_path)
            self._write_board(file_path, updated)
        except OSError as exc:
            return _failure("Failed to write board file", str(exc))

        reread = read_stackup_text(self.board, updated)
        if not reread.get("success"):
            return reread
        layer = reread["layers"][chosen["entry"]["index"]]
        return {"success": True, "message": "Updated stackup layer", "layer": layer}

    def _refuse_direct_write(self) -> Optional[Dict[str, Any]]:
        """Block a file edit that would drop unsaved work or fight KiCad.

        Unit tests build the command without a host, and those writes stay
        allowed. A live session has the interface as ``host``.
        """
        host = self.host
        if host is None:
            return None
        if getattr(host, "session_backend", None) == "ipc":
            return _failure(
                "Refusing to edit the stackup in an IPC session",
                "The board file is open in KiCad, and KiCad's next save would overwrite this edit",
            )
        state_fn = getattr(host, "_dirty_state", None)
        if not callable(state_fn):
            return _failure(
                "Refusing to edit the stackup file",
                "The session cannot tell whether the board file is safe to overwrite",
            )
        state = state_fn(self._board_path())
        if state.get("dirty") is not False or state.get("diskChangedExternally"):
            return _failure(
                "Refusing to edit the stackup file",
                state.get("dirtyReason")
                or "The board file or the in-memory board has changes this edit would drop",
            )
        return None

    def _backup_board(self, file_path: Path) -> None:
        backup_dir = file_path.parent / ".mcp-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        shutil.copy2(file_path, backup_dir / f"{file_path.name}.{stamp}")
        host = self.host
        prune = getattr(host, "_prune_auto_save_backups", None)
        if callable(prune):
            prune(str(backup_dir), file_path.name)

    def _write_board(self, file_path: Path, text: str) -> None:
        """Replace the board file without turning LF into CRLF on Windows."""
        temporary = file_path.with_name(file_path.name + ".mcp-tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.replace(temporary, file_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _read(self) -> Dict[str, Any]:
        path = self._board_path()
        if path is None:
            return _failure(
                "Board has no file",
                "The loaded board has no .kicad_pcb path to read the stackup from",
            )
        file_path = Path(path)
        if not file_path.is_file():
            return _failure(
                "Board file is missing",
                f"Cannot read stackup from {path}",
            )
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            return _failure("Failed to read board file", str(exc))
        return read_stackup_text(self.board, text)

    def _board_path(self) -> Optional[str]:
        getter = getattr(self.board, "GetFileName", None)
        if not callable(getter):
            return None
        try:
            path = getter()
        except Exception:
            return None
        if isinstance(path, str) and path:
            return path
        return None
