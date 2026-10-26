"""Read the board stackup for a PDN or EMC solve.

``get_board_info`` only returns layer names. Copper thickness and the
dielectric gap live in the ``(stackup ...)`` section of the ``.kicad_pcb``
file. KiCad 10's pcbnew bindings do not expose that data: ``GetStackup`` is
missing, and ``GetStackupDescriptor()`` returns an opaque object. This command
reads the file instead, which is how the rest of the server handles data SWIG
does not surface.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.sexpr_format import iter_child_offsets, match_paren, unescape_sexpr_string

logger = logging.getLogger("kicad_interface")

_VALUE = re.compile(
    r"\(\s*[A-Za-z0-9_]+\s+"
    r"(?:\"((?:[^\"\\]|\\.)*)\"|([-+0-9.eE]+)|([A-Za-z_][A-Za-z0-9_]*))"
    r"\s*\)",
    re.DOTALL,
)
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
    """The single atom of ``(thickness 0.035)`` or ``(material "FR4")``."""
    match = _VALUE.match(block)
    if not match:
        return None
    quoted, number, symbol = match.group(1), match.group(2), match.group(3)
    if quoted is not None:
        return unescape_sexpr_string(quoted)
    return number if number is not None else symbol


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


class StackupCommands:
    """Read-only stackup query. Holds the board the interface last loaded."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def get_stackup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return copper and dielectric thicknesses and the board's layer names.

        ``params`` is unused. The name is part of the command-handler signature
        the dispatcher always passes.
        """
        del params
        if not self.board:
            return _no_board()
        try:
            return self._read()
        except Exception as exc:
            logger.error(f"get_stackup failed: {exc}")
            return _failure("Failed to read stackup", str(exc))

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
