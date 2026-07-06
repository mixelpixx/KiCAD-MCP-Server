"""Off-grid geometry lint for .kicad_sch files (lint_offgrid tool).

KiCad's schematic connection grid is fixed at 50 mil (1.27 mm) and junction
placement uses exact coordinate matching: a single off-grid wire endpoint or
symbol origin can poison junction placement for an entire sheet.

This module reports every off-grid connection-relevant coordinate — wire/bus
endpoints, symbol origins, label/junction/no_connect/bus_entry anchors — and
optionally snaps offenders to the nearest grid point via byte-exact text
surgery that preserves the file's formatting (unlike snap_to_grid's
whole-file sexpdata rewrite). Anything inside the (lib_symbols) block (local
pin definitions — snapping deforms symbols) or under a (property ...)
(cosmetic field text positions) is deliberately excluded, which the
stack-based scanner gives for free.

Offenders more than ``needs_human_mm`` (default 0.5 mm) off-grid are
reported as needsHuman and never auto-snapped: sub-half-grid offsets round
coincident points to the SAME grid node, preserving connectivity, while
larger offsets need a human decision.
"""

import bisect
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import sexpdata

logger = logging.getLogger("kicad_interface")

# stack suffixes (under the kicad_sch root) -> offender type
_WIRE_CONTEXTS = {
    ("wire", "pts", "xy"): "wire_endpoint",
    ("bus", "pts", "xy"): "wire_endpoint",
}
_ANCHOR_CONTEXTS = {
    ("symbol", "at"): "symbol_origin",
    ("label", "at"): "label",
    ("global_label", "at"): "label",
    ("hierarchical_label", "at"): "label",
    ("junction", "at"): "junction",
    ("no_connect", "at"): "no_connect",
    ("bus_entry", "at"): "wire_endpoint",
}


def _scan_coordinate_nodes(text: str) -> List[Dict[str, Any]]:
    """Single-pass, string-aware scan yielding every (at ...)/(xy ...) node.

    Each node record: {"stack": tuple of tags from the root, "tokens":
    [(token_text, start, end), ...] for the node's direct atom children}.
    """
    nodes: List[Dict[str, Any]] = []
    stack: List[str] = []
    open_captures: List[Dict[str, Any]] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
            i += 1
            continue
        if c == "(":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            k = j
            while k < n and (text[k].isalnum() or text[k] == "_"):
                k += 1
            tag = text[j:k]
            stack.append(tag)
            if tag in ("at", "xy"):
                capture = {"stack": tuple(stack), "tokens": [], "depth": len(stack)}
                open_captures.append(capture)
                nodes.append(capture)
            i = k
            continue
        if c == ")":
            if open_captures and len(stack) == open_captures[-1]["depth"]:
                open_captures.pop()
            if stack:
                stack.pop()
            i += 1
            continue
        if c in " \t\r\n":
            i += 1
            continue
        j = i
        while j < n and text[j] not in ' \t\r\n()"':
            j += 1
        if open_captures and len(stack) == open_captures[-1]["depth"]:
            open_captures[-1]["tokens"].append((text[i:j], i, j))
        i = j
    return nodes


def _classify(stack: Tuple[str, ...]) -> Optional[str]:
    """Return the offender type for a coordinate node, or None to skip."""
    if len(stack) < 2 or stack[0] != "kicad_sch":
        return None
    if "lib_symbols" in stack or "property" in stack:
        return None  # symbol-local pin defs / cosmetic field positions
    if len(stack) >= 4 and stack[-3:] in _WIRE_CONTEXTS and len(stack) == 4:
        return _WIRE_CONTEXTS[stack[-3:]]
    if len(stack) == 3 and stack[-2:] in _ANCHOR_CONTEXTS:
        return _ANCHOR_CONTEXTS[stack[-2:]]
    return None


def _snap_value(v: float, grid: float) -> float:
    return round(round(v / grid) * grid, 6)


def _format_number(v: float) -> str:
    """Format a coordinate the way KiCad does (no trailing zeros)."""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def lint_offgrid(
    path: str,
    grid_mm: float = 1.27,
    tolerance_mm: float = 1e-4,
    needs_human_mm: float = 0.5,
    fix: bool = False,
) -> Dict[str, Any]:
    """Report (and with fix=True, snap) off-grid connection geometry.

    Returns {"offenders": [...], "counts": {...}, "fixed": n,
    "needsHuman": n}. Raises on unreadable/unparseable input.
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    newline_offsets = [idx for idx, ch in enumerate(text) if ch == "\n"]

    def _line_of(offset: int) -> int:
        return bisect.bisect_right(newline_offsets, offset) + 1

    offenders: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for node in _scan_coordinate_nodes(text):
        offender_type = _classify(node["stack"])
        if offender_type is None:
            continue
        tokens = node["tokens"][:2]  # x, y (ignore trailing angle)
        if len(tokens) < 2:
            continue
        try:
            x = float(tokens[0][0])
            y = float(tokens[1][0])
        except ValueError:
            continue
        sx = _snap_value(x, grid_mm)
        sy = _snap_value(y, grid_mm)
        offset_mm = max(abs(sx - x), abs(sy - y))
        if offset_mm <= tolerance_mm:
            continue
        offenders.append(
            {
                "type": offender_type,
                "x": x,
                "y": y,
                "snappedX": sx,
                "snappedY": sy,
                "offsetMm": round(offset_mm, 6),
                "needsHuman": offset_mm > needs_human_mm,
                "line": _line_of(tokens[0][1]),
                "_spans": [
                    (tokens[0][1], tokens[0][2], sx),
                    (tokens[1][1], tokens[1][2], sy),
                ],
            }
        )
        counts[offender_type] = counts.get(offender_type, 0) + 1

    fixed = 0
    if fix and offenders:
        splices: List[Tuple[int, int, float]] = []
        for offender in offenders:
            if offender["needsHuman"]:
                continue
            splices.extend(offender["_spans"])
            fixed += 1
        if splices:
            new_text = text
            for start, end, value in sorted(splices, reverse=True):
                # Guard: the span must still parse as the original float.
                float(new_text[start:end])
                new_text = new_text[:start] + _format_number(value) + new_text[end:]
            # Post-fix sanity: the file must still parse before we write it.
            sexpdata.loads(new_text)
            directory = os.path.dirname(path) or "."
            fd, tmp_path = tempfile.mkstemp(
                dir=directory, prefix=".lintgrid-", suffix=".kicad_sch"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(new_text)
                os.replace(tmp_path, path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
            logger.info("lint_offgrid: snapped %d offender(s) in %s", fixed, path)
        else:
            fixed = 0

    for offender in offenders:
        del offender["_spans"]

    return {
        "offenders": offenders,
        "counts": counts,
        "fixed": fixed if fix else 0,
        "needsHuman": sum(1 for o in offenders if o["needsHuman"]),
    }
