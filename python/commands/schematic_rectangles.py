"""Schematic rectangles: list them, and create, edit or delete one (#525).

A rectangle drawn on a sheet is a ``(rectangle ...)`` at the top level of the
``.kicad_sch`` file. ``lib_symbols`` holds rectangles too (symbol bodies);
only top-level children of ``kicad_sch`` are read or changed here.

Edits are made in the text: only the fields asked for are rewritten, and every
other line keeps its bytes, including tokens this module does not manage
(KiCad 10's ``radius``, ``locked``, ``custom_property``) and the uuid as KiCad
wrote it (KiCad leaves a shape's uuid unquoted).

The corner radius is read but never written: KiCad 9 cannot load a schematic
that contains it, and choosing by file version belongs in a follow-up (#525).
"""

from __future__ import annotations

import logging
import uuid as uuid_lib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol
from utils.file_io import read_text_preserve_newline, write_text_atomic
from utils.sexpr_format import iter_child_offsets, match_paren

logger = logging.getLogger("kicad_interface")

STROKE_TYPES = ("default", "solid", "dash", "dot", "dash_dot", "dash_dot_dot")
# KiCad 10 adds hatch fills, which KiCad 9 cannot load; they are left out.
FILL_TYPES = ("none", "outline", "background", "color")
_DEFAULT_STROKE: Dict[str, Any] = {"width": 0, "type": "default"}
_DEFAULT_FILL: Dict[str, Any] = {"type": "none"}
_POINT_SHAPES = '[x, y] or {"x": .., "y": ..}'
_COLOR_SHAPE = "[r, g, b, a] with r, g, b from 0 to 255 and a from 0 to 1"


# --- reading ------------------------------------------------------------------


def _children(node: list) -> Dict[str, list]:
    return {str(c[0]): c for c in node[1:] if isinstance(c, list) and c}


def _color(node: Optional[list]) -> Optional[List[float]]:
    if node is None or len(node) < 5:
        return None
    r, g, b, a = node[1:5]
    return [int(r), int(g), int(b), float(a)]


def _describe(node: list) -> Dict[str, Any]:
    """The listing entry for one parsed ``(rectangle ...)``."""
    kids = _children(node)
    out: Dict[str, Any] = {"uuid": str(kids["uuid"][1]) if "uuid" in kids else ""}
    for key in ("start", "end"):
        x, y = (kids[key][1], kids[key][2]) if key in kids else (0, 0)
        out[key] = {"x": float(x), "y": float(y)}
    if "radius" in kids:
        out["radius"] = float(kids["radius"][1])
    stroke = _children(kids["stroke"]) if "stroke" in kids else {}
    out["stroke"] = {
        "width": float(stroke["width"][1]) if "width" in stroke else 0.0,
        "type": str(stroke["type"][1]) if "type" in stroke else "default",
    }
    if _color(stroke.get("color")) is not None:
        out["stroke"]["color"] = _color(stroke.get("color"))
    fill = _children(kids["fill"]) if "fill" in kids else {}
    out["fill"] = {"type": str(fill["type"][1]) if "type" in fill else "none"}
    if _color(fill.get("color")) is not None:
        out["fill"]["color"] = _color(fill.get("color"))
    if "locked" in kids:
        out["locked"] = str(kids["locked"][1]) == "yes"
    return out


def _top_level_rectangles(content: str) -> List[Tuple[int, int, Dict[str, Any]]]:
    """(start offset, end offset inclusive, description) of each sheet rectangle."""
    found = []
    for start in iter_child_offsets(content, depth=2):
        if not content.startswith("(rectangle", start):
            continue
        if content[start + len("(rectangle")] not in " \t\r\n)":
            continue
        end = match_paren(content, start)
        if end == -1:
            raise ValueError(f"unbalanced (rectangle at offset {start}")
        found.append((start, end, _describe(sexpdata.loads(content[start : end + 1]))))
    return found


# --- validating ---------------------------------------------------------------


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _point(value: Any) -> Optional[List[Any]]:
    if isinstance(value, dict):
        x, y = value.get("x"), value.get("y")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        x, y = value
    else:
        return None
    return [x, y] if _number(x) and _number(y) else None


def _check_color(value: Any, where: str) -> Optional[str]:
    if (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value[:3])
        and _number(value[3])
        and 0 <= value[3] <= 1
    ):
        return None
    return f"{where}.color must be {_COLOR_SHAPE}"


def _check_stroke(stroke: Any) -> Optional[str]:
    if not isinstance(stroke, dict):
        return "stroke must be an object with width, type and/or color"
    unknown = set(stroke) - {"width", "type", "color"}
    if unknown:
        return f"stroke has unknown keys {sorted(unknown)}; use width, type, color"
    if "width" in stroke and (not _number(stroke["width"]) or stroke["width"] < 0):
        return "stroke.width must be a number >= 0 (mm; 0 is KiCad's default width)"
    if "type" in stroke and stroke["type"] not in STROKE_TYPES:
        return f"stroke.type must be one of {', '.join(STROKE_TYPES)}"
    if "color" in stroke:
        return _check_color(stroke["color"], "stroke")
    return None


def _check_fill(fill: Any) -> Optional[str]:
    if not isinstance(fill, dict):
        return "fill must be an object with type and/or color"
    unknown = set(fill) - {"type", "color"}
    if unknown:
        return f"fill has unknown keys {sorted(unknown)}; use type, color"
    if "type" in fill and fill["type"] not in FILL_TYPES:
        return f"fill.type must be one of {', '.join(FILL_TYPES)}"
    if "color" in fill:
        return _check_color(fill["color"], "fill")
    return None


# --- writing ------------------------------------------------------------------


def _fmt(value: Any) -> str:
    """A number as KiCad writes mm: no exponent, no trailing zeros; ints unchanged."""
    if isinstance(value, int):
        return str(value)
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _color_text(color: List[Any]) -> str:
    return f"(color {color[0]} {color[1]} {color[2]} {_fmt(color[3])})"


def _stroke_text(stroke: Dict[str, Any], indent: Optional[str]) -> str:
    lines = [f"(width {_fmt(stroke['width'])})", f"(type {stroke['type']})"]
    if stroke.get("color") is not None:
        lines.append(_color_text(stroke["color"]))
    return _block("stroke", lines, indent)


def _fill_text(fill: Dict[str, Any], indent: Optional[str]) -> str:
    lines = [f"(type {fill['type']})"]
    if fill.get("color") is not None:
        lines.append(_color_text(fill["color"]))
    return _block("fill", lines, indent)


def _block(tag: str, lines: List[str], indent: Optional[str]) -> str:
    """``(tag ...)`` laid out as KiCad does when it sits on its own line."""
    if indent is None:
        return f"({tag} " + " ".join(lines) + ")"
    inner = "".join(f"\n{indent}\t{line}" for line in lines)
    return f"({tag}{inner}\n{indent})"


def _line_indent(content: str, offset: int) -> Optional[str]:
    """The whitespace before *offset* on its line, or None if text precedes it."""
    line_start = content.rfind("\n", 0, offset) + 1
    prefix = content[line_start:offset]
    return prefix if not prefix.strip() else None


def _new_rectangle_text(start, end, stroke, fill, uid: str) -> str:
    return (
        "\t(rectangle\n"
        f"\t\t(start {_fmt(start[0])} {_fmt(start[1])})\n"
        f"\t\t(end {_fmt(end[0])} {_fmt(end[1])})\n"
        f"\t\t{_stroke_text(stroke, chr(9) * 2)}\n"
        f"\t\t{_fill_text(fill, chr(9) * 2)}\n"
        f'\t\t(uuid "{uid}")\n'
        "\t)\n"
    )


def _child_spans(block: str) -> Dict[str, Tuple[int, int]]:
    """Offsets (start, end inclusive) of each direct child of *block* by tag."""
    spans: Dict[str, Tuple[int, int]] = {}
    for start in iter_child_offsets(block, depth=2):
        tag = block[start + 1 :].split(None, 1)[0].rstrip(")")
        spans.setdefault(tag, (start, match_paren(block, start)))
    return spans


def _edited_block(block: str, changes: Dict[str, Any]) -> str:
    """*block* with only the changed children rewritten, in place.

    A child the block lacks (a hand-written rectangle without ``stroke``, say)
    is added before ``uuid``, or before the closing paren.
    """
    spans = _child_spans(block)
    anchor = spans["uuid"][0] if "uuid" in spans else len(block) - 1
    replacements: List[Tuple[int, int, str]] = []
    inserted = ""
    renderers = {
        "start": lambda v, _: f"(start {_fmt(v[0])} {_fmt(v[1])})",
        "end": lambda v, _: f"(end {_fmt(v[0])} {_fmt(v[1])})",
        "stroke": _stroke_text,
        "fill": _fill_text,
    }
    for key in ("start", "end", "stroke", "fill"):
        if key not in changes:
            continue
        render = renderers[key]
        if key in spans:
            s, e = spans[key]
            replacements.append((s, e, render(changes[key], _line_indent(block, s))))
        else:
            indent = _line_indent(block, anchor)
            sep = " " if indent is None else "\n" + indent
            inserted += render(changes[key], indent) + sep
    if inserted:
        replacements.append((anchor, anchor - 1, inserted))
    # Right to left, so earlier offsets stay valid.
    for s, e, text in sorted(replacements, reverse=True):
        block = block[:s] + text + block[e + 1 :]
    return block


def _delete_span(content: str, start: int, end: int) -> Tuple[int, int]:
    """Widen [start, end] to whole lines when the block owns them."""
    line_start = content.rfind("\n", 0, start) + 1
    if content[line_start:start].strip():
        return start, end + 1
    stop = end + 1
    if content.startswith("\n", stop):
        stop += 1
    return line_start, stop


# --- commands -----------------------------------------------------------------


def _load(params: Dict[str, Any]) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
    schematic_path = params.get("schematicPath")
    if not schematic_path:
        return None, {"success": False, "message": "schematicPath is required"}
    path = Path(schematic_path)
    if not path.exists():
        return None, {"success": False, "message": f"Schematic not found: {schematic_path}"}
    return path, None


def list_schematic_rectangles(params: Dict[str, Any]) -> Dict[str, Any]:
    """List the rectangles drawn on a sheet (not those inside symbol bodies)."""
    path, error = _load(params)
    if error:
        return error
    try:
        content, _ = read_text_preserve_newline(path)  # type: ignore[arg-type]
        rectangles = [desc for _, _, desc in _top_level_rectangles(content)]
    except Exception as e:  # sexpdata and offset errors alike
        logger.error(f"Error listing schematic rectangles: {e}")
        return {"success": False, "message": f"Failed to read rectangles: {e}"}
    return {"success": True, "rectangles": rectangles, "count": len(rectangles)}


def _requested_changes(params: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    if "radius" in params:
        return {}, (
            "radius is not supported: KiCad 9 cannot load a rectangle with a corner "
            "radius. An existing radius is kept when a rectangle is edited."
        )
    changes: Dict[str, Any] = {}
    for key in ("start", "end"):
        if params.get(key) is not None:
            point = _point(params[key])
            if point is None:
                return {}, f"{key} must be {_POINT_SHAPES}"
            changes[key] = point
    if params.get("stroke") is not None:
        problem = _check_stroke(params["stroke"])
        if problem:
            return {}, problem
        changes["stroke"] = params["stroke"]
    if params.get("fill") is not None:
        problem = _check_fill(params["fill"])
        if problem:
            return {}, problem
        changes["fill"] = params["fill"]
    return changes, None


def _merged(
    current: Dict[str, Any], changes: Dict[str, Any]
) -> Tuple[Dict[str, Any], Optional[str]]:
    merged = dict(changes)
    if "stroke" in changes:
        merged["stroke"] = {**current["stroke"], **changes["stroke"]}
    if "fill" in changes:
        fill = {**current["fill"], **changes["fill"]}
        if fill["type"] != "color":
            fill.pop("color", None)
        elif fill.get("color") is None:
            return {}, 'fill.type "color" needs fill.color, ' + _COLOR_SHAPE
        merged["fill"] = fill
    return merged, None


def _create(path: Path, changes: Dict[str, Any]) -> Dict[str, Any]:
    from commands.wire_manager import _text_insert

    for key in ("start", "end"):
        if key not in changes:
            return {"success": False, "message": f"{key} is required to create a rectangle"}
    merged, problem = _merged(
        {"stroke": dict(_DEFAULT_STROKE), "fill": dict(_DEFAULT_FILL)}, changes
    )
    if problem:
        return {"success": False, "message": problem}
    stroke = merged.get("stroke", dict(_DEFAULT_STROKE))
    fill = merged.get("fill", dict(_DEFAULT_FILL))
    uid = str(uuid_lib.uuid4())
    _text_insert(path, _new_rectangle_text(changes["start"], changes["end"], stroke, fill, uid))
    content, _ = read_text_preserve_newline(path)
    rect = next(d for _, _, d in _top_level_rectangles(content) if d["uuid"] == uid)
    return {
        "success": True,
        "uuid": uid,
        "rectangle": rect,
        "message": f"Added rectangle {uid}",
    }


def _unknown_uuid(uid: str, found: List[Tuple[int, int, Dict[str, Any]]]) -> Dict[str, Any]:
    known = [d["uuid"] for _, _, d in found]
    here = ", ".join(known) if known else "none"
    return {
        "success": False,
        "message": f"No rectangle with uuid {uid} on this sheet. Rectangles here: {here}",
        "rectangles": known,
    }


def set_schematic_rectangle(params: Dict[str, Any]) -> Dict[str, Any]:
    """Create a rectangle (no uuid), edit one (uuid) or delete one (uuid + delete)."""
    path, error = _load(params)
    if error:
        return error
    uid = params.get("uuid")
    delete = params.get("delete") is True
    if uid is not None and (not isinstance(uid, str) or not uid.strip()):
        return {"success": False, "message": "uuid must be a non-empty string"}
    if delete and uid is None:
        return {"success": False, "message": "delete needs the uuid of the rectangle to remove"}
    changes, problem = _requested_changes(params)
    if problem:
        return {"success": False, "message": problem}
    if delete and changes:
        return {
            "success": False,
            "message": f"delete takes only uuid; drop {', '.join(sorted(changes))}",
        }
    try:
        if uid is None:
            return _create(path, changes)  # type: ignore[arg-type]
        if not delete and not changes:
            return {
                "success": False,
                "message": "nothing to change: give start, end, stroke and/or fill, or delete",
            }
        return _edit_or_delete(path, uid, changes, delete)  # type: ignore[arg-type]
    except Exception as e:
        logger.error(f"Error setting schematic rectangle: {e}")
        return {"success": False, "message": f"Failed to update the rectangle: {e}"}


def _edit_or_delete(path: Path, uid: str, changes: Dict[str, Any], delete: bool) -> Dict[str, Any]:
    content, newline = read_text_preserve_newline(path)
    found = _top_level_rectangles(content)
    match = next(((s, e, d) for s, e, d in found if d["uuid"] == uid), None)
    if match is None:
        return _unknown_uuid(uid, found)
    start, end, current = match
    if delete:
        s, e = _delete_span(content, start, end)
        updated = content[:s] + content[e:]
    else:
        merged, problem = _merged(current, changes)
        if problem:
            return {"success": False, "message": problem}
        block = _edited_block(content[start : end + 1], merged)
        updated = content[:start] + block + content[end + 1 :]
    sexpdata.loads(updated)  # never write a file that no longer parses
    write_text_atomic(path, updated, newline)
    if delete:
        return {
            "success": True,
            "uuid": uid,
            "deleted": True,
            "message": f"Deleted rectangle {uid}",
        }
    rect = next(d for _, _, d in _top_level_rectangles(updated) if d["uuid"] == uid)
    return {
        "success": True,
        "uuid": uid,
        "rectangle": rect,
        "changed": sorted(changes),
        "message": f"Updated {', '.join(sorted(changes))} of rectangle {uid}",
    }
