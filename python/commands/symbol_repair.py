"""Repair "flat" vendor symbols so kicad-skip can parse them.

SnapEDA/SamacSys ``.kicad_sym`` captures often put pins and graphics directly
under the top-level ``(symbol "NAME" ...)`` with no ``(symbol "NAME_1_1")``
sub-unit. KiCad and kicad-cli tolerate that, but kicad-skip's lib_symbol
parser does ``pv.symbol`` and crashes when a lib symbol has zero sub-units —
taking down every skip-based tool for any sheet that uses (or embeds a
snapshot of) such a symbol.

The repair is pure TEXT surgery: insert ``(symbol "NAME_1_1" ...)`` around
the drawable/pin children, leaving every other byte intact. Never round-trip
through sexpdata.dumps — that collapses formatting and has been observed to
break downstream parsers. Idempotent: symbols that already have a sub-unit
(or are ``extends``-derived) are skipped.
"""

import logging
import os
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

# Child s-exprs that are unit content (must move into the sub-symbol).
DRAWABLES = (
    "pin",
    "rectangle",
    "polyline",
    "circle",
    "arc",
    "text",
    "bezier",
    "text_box",
)

_HEAD_TOKEN = re.compile(r"\(\s*([A-Za-z_]+)")


def _scan_block(text: str, start: int) -> Tuple[Optional[int], List[int]]:
    """Balanced-paren scan (string-aware) from the ``(`` at ``start``.

    Returns ``(end_index, child_open_positions)`` where ``end_index`` is the
    index of the block's closing paren (or None if unbalanced) and
    ``child_open_positions`` are the offsets of each depth-2 ``(`` — the
    block's direct children. KiCad does not backslash-escape parens inside
    quoted strings, so an in-string state machine is required.
    """
    depth = 0
    i = start
    in_str = esc = False
    child_opens: List[int] = []
    end: Optional[int] = None
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
            if depth == 2:  # a direct child of the scanned block
                child_opens.append(i)
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i  # the block's closing paren
                break
        i += 1
    return end, child_opens


def _classify(text: str, child_opens: List[int]) -> Tuple[bool, bool, Optional[int]]:
    """Classify a symbol block by its direct children.

    Returns ``(is_wrapped, is_derived, first_drawable_offset)``:
    wrapped = has a ``(symbol ...)`` sub-unit already; derived = has an
    ``(extends ...)`` child (legitimately drawable-free); first_drawable is
    the offset of the first pin/graphic child, or None.
    """
    is_wrapped = False
    is_derived = False
    first_drawable: Optional[int] = None
    for cs in child_opens:
        tok = _HEAD_TOKEN.match(text[cs : cs + 40])
        if not tok:
            continue
        head = tok.group(1)
        if head == "symbol":
            is_wrapped = True
        elif head == "extends":
            is_derived = True
        elif head in DRAWABLES and first_drawable is None:
            first_drawable = cs
    return is_wrapped, is_derived, first_drawable


def _wrap(text: str, name: str, first_drawable: int, end: int) -> str:
    """Insert a ``(symbol "<base>_1_1" ...)`` sub-unit around the drawable
    children [first_drawable, end) of the symbol named ``name``.

    Embedded schematic snapshots name symbols ``LIB:NAME`` but sub-units must
    not carry the library prefix, hence the ``split(":")``.
    """
    unit_name = name.split(":")[-1] + "_1_1"
    return (
        text[:first_drawable]
        + f'(symbol "{unit_name}"\n      '
        + text[first_drawable:end]
        + ")\n  "
        + text[end:]
    )


def _iter_symbols(text: str, container_start: int) -> List[Tuple[str, int, int, List[int]]]:
    """Yield ``(name, start, end, child_opens)`` for each direct
    ``(symbol "NAME" ...)`` child of the container block at ``container_start``."""
    container_end, child_opens = _scan_block(text, container_start)
    if container_end is None:
        raise ValueError("unbalanced s-expression")
    symbols = []
    for cs in child_opens:
        m = re.match(r'\(\s*symbol\s+"([^"]+)"', text[cs : cs + 200])
        if not m:
            continue
        end, sym_children = _scan_block(text, cs)
        if end is None:
            raise ValueError("unbalanced s-expression in symbol block")
        symbols.append((m.group(1), cs, end, sym_children))
    return symbols


def repair_text(text: str, container_start: int) -> Tuple[str, List[str], List[str]]:
    """Repair all flat symbols inside the container block at ``container_start``.

    Returns ``(new_text, flat_symbols_found, repaired)``. Wraps are applied
    back-to-front so earlier offsets stay valid.
    """
    flat: List[Tuple[str, int, int]] = []  # (name, first_drawable, end)
    names_found: List[str] = []
    for name, _start, end, child_opens in _iter_symbols(text, container_start):
        is_wrapped, is_derived, first_drawable = _classify(text, child_opens)
        if is_wrapped or is_derived:
            continue
        if first_drawable is None:
            # Properties-only symbol with no drawables: there is no unit
            # content to move, so don't fabricate an empty sub-unit
            # (matches the field-validated reference behavior).
            continue
        names_found.append(name)
        flat.append((name, first_drawable, end))

    new_text = text
    for name, first_drawable, end in sorted(flat, key=lambda t: t[1], reverse=True):
        new_text = _wrap(new_text, name, first_drawable, end)
    return new_text, names_found, list(names_found)


class SymbolRepairCommands:
    """Handler for the repair_flat_symbols MCP tool."""

    def repair_flat_symbols(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect (and with dryRun=false, repair) flat vendor symbols in a
        ``.kicad_sym`` library or the embedded ``(lib_symbols)`` block of a
        ``.kicad_sch`` schematic."""
        try:
            path = params.get("path")
            dry_run = bool(params.get("dryRun", True))

            if not path:
                return {"success": False, "message": "path is required"}
            if not os.path.isfile(path):
                return {"success": False, "message": f"File not found: {path}"}

            with open(path, "r", encoding="utf-8") as f:
                text = f.read()

            if path.endswith(".kicad_sym"):
                container_start = text.find("(kicad_symbol_lib")
                if container_start < 0:
                    return {
                        "success": False,
                        "message": "No (kicad_symbol_lib ...) block found — not a symbol library?",
                    }
            elif path.endswith(".kicad_sch"):
                container_start = text.find("(lib_symbols")
                if container_start < 0:
                    return {
                        "success": True,
                        "path": path,
                        "dryRun": dry_run,
                        "flat_symbols_found": [],
                        "repaired": [],
                        "skipped_reason": "no lib_symbols block in schematic",
                        "message": "No embedded lib_symbols block; nothing to repair",
                    }
            else:
                return {
                    "success": False,
                    "message": "path must be a .kicad_sym or .kicad_sch file",
                }

            try:
                new_text, flat_found, repaired = repair_text(text, container_start)
            except ValueError as e:
                return {
                    "success": False,
                    "message": f"Could not parse {path}: {e}",
                }

            if not flat_found:
                return {
                    "success": True,
                    "path": path,
                    "dryRun": dry_run,
                    "flat_symbols_found": [],
                    "repaired": [],
                    "skipped_reason": "no flat symbols found; all symbols already have sub-units",
                    "message": "No flat symbols found; nothing to repair",
                }

            if dry_run:
                return {
                    "success": True,
                    "path": path,
                    "dryRun": True,
                    "flat_symbols_found": flat_found,
                    "repaired": [],
                    "skipped_reason": "dryRun=true — no changes written",
                    "message": (
                        f"Found {len(flat_found)} flat symbol(s): "
                        f"{', '.join(flat_found)}. Re-run with dryRun=false to repair."
                    ),
                }

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            logger.info(
                "repair_flat_symbols: wrapped %d flat symbol(s) in %s",
                len(repaired),
                path,
            )
            return {
                "success": True,
                "path": path,
                "dryRun": False,
                "flat_symbols_found": flat_found,
                "repaired": repaired,
                "message": (
                    f"Wrapped {len(repaired)} flat symbol(s) in a _1_1 sub-unit: "
                    f"{', '.join(repaired)}"
                ),
            }
        except Exception as e:
            logger.error(f"repair_flat_symbols failed: {e}")
            return {
                "success": False,
                "message": f"repair_flat_symbols failed: {e}",
                "errorDetails": traceback.format_exc(),
            }
