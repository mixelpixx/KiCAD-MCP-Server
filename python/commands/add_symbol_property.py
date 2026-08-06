"""Add or update a property on a symbol in a .kicad_sym library file."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from utils.sexpr_format import escape_sexpr_string

# A property belongs to the symbol itself, so it has to sit at the same nesting
# level as (property "Reference" ...). Inside the parent block that is depth 2:
# depth 1 is the parent's own "(".
_CHILD_DEPTH = 2


def _match_paren(content: str, open_idx: int) -> int:
    """Index of the ``)`` closing the ``(`` at *open_idx*, or -1 if unbalanced.

    Parentheses inside quoted tokens are literal text -- a Description of
    ``"Cap (X7R)"`` must not be read as a nested list.
    """
    depth = 0
    in_string = False
    i = open_idx
    while i < len(content):
        ch = content[i]
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
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _paren_balance(content: str) -> int:
    """Signed paren balance of *content*, ignoring parens inside quoted tokens."""
    balance = 0
    in_string = False
    i = 0
    while i < len(content):
        ch = content[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            balance += 1
        elif ch == ")":
            balance -= 1
        i += 1
    return balance


def _iter_children(block: str) -> Iterator[int]:
    """Yield the offset of every direct child list inside a symbol *block*."""
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
            if depth == _CHILD_DEPTH:
                yield i
        elif ch == ")":
            depth -= 1
        i += 1


def _find_symbol_in_lib(content: str, symbol_name: str) -> tuple[int, int, str] | None:
    """Return (start, end, block) for a symbol in .kicad_sym, or None.

    ``end`` is the index of the symbol's closing paren and ``block`` includes it.
    """
    marker = f'(symbol "{escape_sexpr_string(symbol_name)}"'
    sym_start = content.find(marker)
    if sym_start == -1:
        return None

    sym_end = _match_paren(content, sym_start)
    if sym_end == -1:
        return None
    return sym_start, sym_end, content[sym_start : sym_end + 1]


def _has_property(symbol_block: str, prop_name: str) -> bool:
    return _find_property_span(symbol_block, prop_name) is not None


def _find_property_span(block: str, prop_name: str) -> tuple[int, int] | None:
    """Span of the symbol's own ``(property "prop_name" ...)``, end-exclusive.

    Only direct children count. A multi-unit symbol repeats property names
    inside its ``NAME_0_1`` sub-symbols, and rewriting one of those leaves the
    parent untouched while corrupting the sub-symbol.
    """
    head = re.compile(rf'\(property\s+"{re.escape(escape_sexpr_string(prop_name))}"[\s()"]')
    for offset in _iter_children(block):
        if head.match(block, offset):
            close = _match_paren(block, offset)
            if close != -1:
                return offset, close + 1
    return None


def _first_subsymbol_offset(block: str) -> int | None:
    """Offset of the first ``(symbol "..."`` unit inside a parent symbol block."""
    for offset in _iter_children(block):
        if block.startswith('(symbol "', offset):
            return offset
    return None


def _indent_at(block: str, offset: int) -> str | None:
    """Leading whitespace of the line holding *offset*, or None if not alone."""
    line_start = block.rfind("\n", 0, offset) + 1
    prefix = block[line_start:offset]
    return prefix if prefix.strip() == "" else None


def _child_indent(block: str) -> str:
    """Indentation used by this symbol's direct children.

    Libraries written by eeschema use tabs; hand-edited and Eagle-imported ones
    use spaces. Copying whatever the file already does keeps the diff to the
    inserted lines.
    """
    for offset in _iter_children(block):
        indent = _indent_at(block, offset)
        if indent:
            return indent
    return "\t\t"


def _placement_of(prop_block: str) -> tuple[str | None, bool]:
    """Return the ``(at ...)`` token and hidden flag of an existing property.

    Rewriting a property means regenerating it from scratch, so anything the
    caller did not supply has to be carried over -- otherwise updating a BOM
    value would silently un-hide the field and drop it back to the origin.
    """
    at_text: str | None = None
    hidden = False
    for offset in _iter_children(prop_block):
        close = _match_paren(prop_block, offset)
        if close == -1:
            continue
        child = prop_block[offset : close + 1]
        if at_text is None and child.startswith("(at "):
            at_text = child
        elif re.fullmatch(r"\(hide\s+yes\)", child):
            hidden = True
    return at_text, hidden


def _build_property(
    name: str,
    value: str,
    at_text: str = "(at 0 0 0)",
    hide: bool = False,
    indent: str = "\t\t",
) -> str:
    """Render a property block; the first line carries no indent."""
    inner = indent + ("\t" if "\t" in indent else "  ")
    lines = [
        f'(property "{escape_sexpr_string(name)}" ' f'"{escape_sexpr_string(value)}" {at_text}'
    ]
    if hide:
        lines.append(f"{inner}(hide yes)")
    lines.append(f"{inner}(effects (font (size 1.27 1.27)))")
    lines.append(f"{indent})")
    return "\n".join(lines)


def add_symbol_property(params: dict[str, Any]) -> dict[str, Any]:
    lib_path = Path(params["libraryPath"])
    symbol_name = params["symbolName"]
    prop_name = params["propertyName"]
    prop_value = params["propertyValue"]
    pos = params.get("position")
    hide = bool(params.get("hide", False))

    if not lib_path.exists():
        return {"success": False, "message": f"Library not found: {lib_path}"}

    content = lib_path.read_text(encoding="utf-8")
    found = _find_symbol_in_lib(content, symbol_name)
    if not found:
        return {
            "success": False,
            "message": f"Symbol '{symbol_name}' not found in library",
        }

    sym_start, sym_end, block = found
    indent = _child_indent(block)
    at_text = f"(at {pos.get('x', 0)} {pos.get('y', 0)} 0)" if pos else None

    existing = _find_property_span(block, prop_name)
    if existing:
        updated = True
        start, end = existing
        old_at, old_hidden = _placement_of(block[start:end])
        new_prop = _build_property(
            prop_name,
            prop_value,
            at_text or old_at or "(at 0 0 0)",
            hide if "hide" in params else old_hidden,
            indent,
        )
        block = block[:start] + new_prop + block[end:]
    else:
        updated = False
        new_prop = _build_property(prop_name, prop_value, at_text or "(at 0 0 0)", hide, indent)
        sub = _first_subsymbol_offset(block)
        if sub is not None:
            # Properties must precede the unit definitions, so anchor to the
            # start of the sub-symbol's line rather than the "(" itself.
            line_start = block.rfind("\n", 0, sub) + 1
            block = block[:line_start] + indent + new_prop + "\n" + block[line_start:]
        else:
            close = block.rfind(")")
            line_start = block.rfind("\n", 0, close) + 1
            block = block[:line_start] + indent + new_prop + "\n" + block[line_start:]

    updated_content = content[:sym_start] + block + content[sym_end + 1 :]

    # Adding or replacing a property is a balanced edit, so the file's balance
    # cannot move. Comparing against the original rather than checking for zero
    # keeps the guard usable on Eagle-imported libraries that arrive unbalanced.
    if _paren_balance(updated_content) != _paren_balance(content):
        return {
            "success": False,
            "message": (
                f"Refusing to write {lib_path.name}: editing property "
                f"'{prop_name}' on '{symbol_name}' would unbalance the file"
            ),
        }

    lib_path.write_text(updated_content, encoding="utf-8")

    # This rewrote a .kicad_sym file: drop the module-level symbol caches so a
    # subsequent extract/list sees the new property instead of a stale block
    # (the mtime guards over there also catch this; the explicit clear keeps
    # every library-mutating write path uniform).
    from commands.symbol_creator import _invalidate_symbol_caches

    _invalidate_symbol_caches()

    action = "Updated" if updated else "Added"
    return {
        "success": True,
        "message": f"Property '{prop_name}' = '{prop_value}' {action.lower()} to '{symbol_name}'",
        "propertyAdded": prop_name,
        "propertyValue": prop_value,
    }
