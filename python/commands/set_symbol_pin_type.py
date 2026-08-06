"""Change the electrical type (and graphic style) of pins in a .kicad_sym library.

The server can read pins (``list_symbol_pins``, ``batch_list_symbol_pins``) but
had no way to write them, so bulk fixes were done with ``sed`` over the whole
library file. That is unsafe for three reasons this module addresses:

* A blind substitution rewrites *every* matching pin in the file, including
  symbols the caller never meant to touch.
* ``sed`` cannot see which symbol or which pin number it is standing on, so
  "make only the shield pins passive" is not expressible.
* Nothing checks the replacement token. KiCad silently refuses to load a
  library containing an unknown pin type, and the error it reports points at
  the file, not at the pin.

Imported libraries are the usual reason to need this. Parts converted from
Eagle or pulled from SnapEDA arrive with every pin marked ``unspecified`` or
``bidirectional``; ERC then reports conflicts on nets that are electrically
fine, and the noise hides the real errors.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from utils.pin_types import PIN_STYLES, PIN_TYPES
from utils.sexpr_format import match_paren

logger = logging.getLogger("kicad_interface")

_HEAD = re.compile(r"\(\s*([A-Za-z_][\w]*)")
_PIN_HEAD = re.compile(r"\(pin\s+([A-Za-z_][\w]*)\s+([A-Za-z_][\w]*)")


def _read_string(text: str, i: int) -> Tuple[Optional[str], int]:
    """Read the quoted token starting at or after *i*; return (value, end)."""
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != '"':
        return None, i
    out: List[str] = []
    i += 1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return None, i


def _child_string(block: str, key: str) -> Optional[str]:
    """Value of a direct child list ``(key "value" ...)``, or None.

    Only direct children count: a pin's ``(name ...)`` must not be confused with
    the ``(name ...)`` of a font or an effects block nested inside it.
    """
    depth = 0
    in_string = False
    i = 0
    while i < len(block):
        ch = block[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
            if depth == 2:
                m = _HEAD.match(block, i)
                if m and m.group(1) == key:
                    value, _ = _read_string(block, m.end())
                    if value is not None:
                        return value
        elif ch == ")":
            depth -= 1
        i += 1
    return None


def iter_library_pins(text: str) -> Iterator[Dict[str, Any]]:
    """Yield ``{"offset", "symbol", "unit"}`` for every pin in a .kicad_sym.

    ``symbol`` is the top-level symbol the pin belongs to; ``unit`` is the
    enclosing body sub-symbol (``R_0402_1_1``), which is where pins actually
    live. Walking with a stack rather than a regex keeps a pin attributed to
    its own symbol even though the two names differ.
    """
    depth = 0
    in_string = False
    stack: List[Tuple[int, Optional[str]]] = []
    i = 0
    while i < len(text):
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
        if ch == ")":
            depth -= 1
            while stack and stack[-1][0] > depth:
                stack.pop()
            i += 1
            continue
        if ch != "(":
            i += 1
            continue
        depth += 1
        m = _HEAD.match(text, i)
        token = m.group(1) if m else ""
        if token == "symbol" and m:
            name, _ = _read_string(text, m.end())
            stack.append((depth, name))
        elif token == "pin" and stack:
            yield {"offset": i, "symbol": stack[0][1], "unit": stack[-1][1]}
        i += 1


def _root_token(text: str) -> Optional[str]:
    m = _HEAD.search(text)
    return m.group(1) if m else None


def _as_set(value: Any) -> Optional[Set[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return {str(v) for v in value}


def set_symbol_pin_type(params: Dict[str, Any]) -> Dict[str, Any]:
    """Set the electrical type and/or graphic style of pins in a symbol library."""
    lib_path = Path(params.get("libraryPath", ""))
    new_type = params.get("type")
    new_style = params.get("style")
    dry_run = bool(params.get("dryRun", False))

    if new_type is None and new_style is None:
        return {
            "success": False,
            "message": "Nothing to do: pass type, style, or both",
        }
    if new_type is not None and new_type not in PIN_TYPES:
        return {
            "success": False,
            "message": (
                f"'{new_type}' is not a KiCad pin type. KiCad refuses to load a "
                f"library containing one it does not know. Valid: {', '.join(PIN_TYPES)}"
            ),
            "validTypes": list(PIN_TYPES),
        }
    if new_style is not None and new_style not in PIN_STYLES:
        return {
            "success": False,
            "message": (
                f"'{new_style}' is not a KiCad pin graphic style. "
                f"Valid: {', '.join(PIN_STYLES)}"
            ),
            "validStyles": list(PIN_STYLES),
        }

    if not lib_path.is_file():
        return {"success": False, "message": f"Library not found: {lib_path}"}

    try:
        text = lib_path.read_text(encoding="utf-8")
    except OSError as e:
        return {"success": False, "message": f"Could not read {lib_path}: {e}"}

    root = _root_token(text)
    if root != "kicad_symbol_lib":
        return {
            "success": False,
            "message": (
                f"{lib_path.name} is not a symbol library "
                f"(root form is '{root}', expected 'kicad_symbol_lib')"
            ),
        }

    want_symbols = _as_set(params.get("symbols"))
    want_numbers = _as_set(params.get("pinNumbers"))
    want_names = _as_set(params.get("pinNames"))
    from_type = params.get("fromType")

    seen_symbols: Set[str] = set()
    seen_numbers: Set[str] = set()
    changes: List[Dict[str, Any]] = []
    edits: List[Tuple[int, int, str]] = []
    unchanged = 0

    for pin in iter_library_pins(text):
        symbol = pin["symbol"]
        if symbol:
            seen_symbols.add(symbol)
        if want_symbols is not None and symbol not in want_symbols:
            continue

        head = _PIN_HEAD.match(text, pin["offset"])
        if not head:
            continue
        cur_type, cur_style = head.group(1), head.group(2)

        end = match_paren(text, pin["offset"])
        if end == -1:
            return {
                "success": False,
                "message": (
                    f"Unbalanced parentheses in {lib_path.name}: the pin at offset "
                    f"{pin['offset']} is never closed. Refusing to write."
                ),
            }
        block = text[pin["offset"] : end + 1]
        number = _child_string(block, "number") or ""
        name = _child_string(block, "name") or ""

        if number:
            seen_numbers.add(number)
        if want_numbers is not None and number not in want_numbers:
            continue
        if want_names is not None and name not in want_names:
            continue
        if from_type is not None and cur_type != from_type:
            continue

        to_type = new_type or cur_type
        to_style = new_style or cur_style
        if to_type == cur_type and to_style == cur_style:
            unchanged += 1
            continue

        edits.append((head.start(), head.end(), f"(pin {to_type} {to_style}"))
        changes.append(
            {
                "symbol": symbol,
                "unit": pin["unit"],
                "number": number,
                "name": name,
                "fromType": cur_type,
                "toType": to_type,
                "fromStyle": cur_style,
                "toStyle": to_style,
            }
        )

    missing_symbols = sorted(want_symbols - seen_symbols) if want_symbols else []
    missing_numbers = sorted(want_numbers - seen_numbers) if want_numbers else []

    if edits and not dry_run:
        updated = text
        for start, stop, replacement in reversed(edits):
            updated = updated[:start] + replacement + updated[stop:]
        if updated.count("(") != text.count("(") or updated.count(")") != text.count(")"):
            return {
                "success": False,
                "message": "Internal error: the edit changed the file structure. Nothing written.",
            }
        try:
            lib_path.write_text(updated, encoding="utf-8")
        except OSError as e:
            return {"success": False, "message": f"Could not write {lib_path}: {e}"}

        # The file is already on disk, so a cache that refuses to clear must not
        # turn a successful write into a reported failure -- the caller would
        # retry an edit that has in fact happened.
        try:
            from commands.symbol_creator import _invalidate_symbol_caches

            _invalidate_symbol_caches()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Symbol caches not invalidated after pin edit: %s", e)

    touched = sorted({c["symbol"] for c in changes if c["symbol"]})
    if changes:
        verb = "Would change" if dry_run else "Changed"
        message = f"{verb} {len(changes)} pin(s) across {len(touched)} symbol(s)"
    elif missing_symbols:
        message = f"No pins changed: symbol(s) not in this library: {', '.join(missing_symbols)}"
    elif unchanged:
        message = f"No pins changed: all {unchanged} matching pin(s) already have that type"
    else:
        message = "No pins matched the given filters"

    return {
        "success": True,
        "message": message,
        "libraryPath": str(lib_path),
        "dryRun": dry_run,
        "changeCount": len(changes),
        "alreadyCorrect": unchanged,
        "symbolsChanged": touched,
        "changes": changes,
        "missingSymbols": missing_symbols,
        "missingPinNumbers": missing_numbers,
    }
