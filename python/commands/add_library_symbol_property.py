"""Add or update a property on a symbol definition in the lib_symbols section."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# The property edit itself is the one #362 fixed for .kicad_sym libraries: a
# lib_symbols entry has the same shape as a library symbol, so the same
# string-aware, direct-child helpers apply unchanged.
from commands.add_symbol_property import (
    _build_property,
    _child_indent,
    _existing_parts,
    _find_property_span,
    _first_subsymbol_offset,
    _indent_at,
    _splice_child,
)
from utils.sexpr_format import escape_sexpr_string, match_paren, paren_delta, prettify


def _find_symbol_in_lib_symbols(
    content: str, library_name: str, symbol_name: str
) -> tuple[int, int, str] | None:
    """Return (start, end, block_text) for a symbol in lib_symbols, or None."""
    full = f"{library_name}:{symbol_name}"
    lib_start = content.find("(lib_symbols")
    if lib_start == -1:
        return None

    marker = f'(symbol "{escape_sexpr_string(full)}"'
    sym_start = content.find(marker, lib_start)
    if sym_start == -1:
        return None

    end = match_paren(content, sym_start)
    if end == -1:
        return None
    return sym_start, end, content[sym_start : end + 1]


def _has_property(symbol_block: str, prop_name: str) -> bool:
    """Whether the symbol itself (not one of its units) has *prop_name*."""
    return _find_property_span(symbol_block, prop_name) is not None


def _is_direct_child(content: str, library_name: str, symbol_name: str, prop_name: str) -> bool:
    """Whether *prop_name* ended up a direct child of the lib_symbols entry.

    Re-locates the symbol in the text about to be written. The paren-balance
    guard cannot see a well-formed property spliced in at the wrong depth.
    """
    found = _find_symbol_in_lib_symbols(content, library_name, symbol_name)
    if found is None:
        return False
    return _find_property_span(found[2], prop_name) is not None


def add_library_symbol_property(params: dict[str, Any]) -> dict[str, Any]:
    schematic_path = Path(params["schematicPath"])
    library_name = params["libraryName"]
    symbol_name = params["symbolName"]
    prop_name = params["propertyName"]
    prop_value = params["propertyValue"]
    pos = params.get("position")
    hide = bool(params.get("hide", False))

    if not schematic_path.exists():
        return {"success": False, "message": f"Schematic not found: {schematic_path}"}

    content = schematic_path.read_text(encoding="utf-8")
    found = _find_symbol_in_lib_symbols(content, library_name, symbol_name)
    if not found:
        return {
            "success": False,
            "message": f"Symbol {library_name}:{symbol_name} not found in lib_symbols",
        }

    sym_start, sym_end, block = found
    sym_indent = _indent_at(content, sym_start) or ""
    indent = _child_indent(block, sym_indent + "\t")
    at_text = f"(at {pos.get('x', 0)} {pos.get('y', 0)} 0)" if pos else None

    existing = _find_property_span(block, prop_name)
    if existing:
        # Replace the whole property block, located by string-aware paren
        # matching. A pattern that stops at the first ")" ends inside
        # "(at x y angle)" and leaves the old (effects ...) tail behind.
        start, end = existing
        old_at, old_hidden, old_others = _existing_parts(block[start:end])
        new_prop = _build_property(
            prop_name,
            prop_value,
            at_text or old_at or "(at 0 0 0)",
            hide if "hide" in params else old_hidden,
            indent,
            old_others,
        )
        block = block[:start] + new_prop + block[end:]
    else:
        new_prop = _build_property(prop_name, prop_value, at_text or "(at 0 0 0)", hide, indent)
        sub = _first_subsymbol_offset(block)
        if sub is not None:
            # Properties precede the unit definitions.
            anchor, tail_indent = sub, indent
        else:
            anchor, tail_indent = block.rfind(")"), sym_indent
        block = _splice_child(block, anchor, indent, tail_indent, new_prop)

    updated = prettify(content[:sym_start] + block + content[sym_end + 1 :])

    # Setting a property is a balanced edit, so the file's balance cannot move.
    if paren_delta(updated) != paren_delta(content):
        return {
            "success": False,
            "message": (
                f"Refusing to write {schematic_path.name}: editing property "
                f"'{prop_name}' on {library_name}:{symbol_name} would unbalance the file"
            ),
        }

    if not _is_direct_child(updated, library_name, symbol_name, prop_name):
        return {
            "success": False,
            "message": (
                f"Refusing to write {schematic_path.name}: property '{prop_name}' would "
                f"not be a direct child of {library_name}:{symbol_name}"
            ),
        }

    schematic_path.write_text(updated, encoding="utf-8")

    return {
        "success": True,
        "message": f"Property '{prop_name}' set to '{prop_value}' in {library_name}:{symbol_name}",
        "propertyAdded": prop_name,
        "propertyValue": prop_value,
    }
