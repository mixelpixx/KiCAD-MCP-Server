"""Add or update a property on a symbol definition in the lib_symbols section."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kicad_mcp.utils.sexpr_format import prettify


def _find_symbol_in_lib_symbols(
    content: str, library_name: str, symbol_name: str
) -> tuple[int, int, str] | None:
    """Return (start, end, block_text) for a symbol in lib_symbols, or None."""
    full = f"{library_name}:{symbol_name}"
    lib_start = content.find("(lib_symbols")
    if lib_start == -1:
        return None

    marker = f'(symbol "{full}"'
    sym_start = content.find(marker, lib_start)
    if sym_start == -1:
        return None

    depth = 0
    for i in range(sym_start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return sym_start, i, content[sym_start : i + 1]

    return None


def _has_property(symbol_block: str, prop_name: str) -> bool:
    """Check if a property already exists in a symbol block."""
    return bool(re.search(rf'\(property\s+"{re.escape(prop_name)}"', symbol_block))


def _property_s_expr(
    name: str, value: str, pos: dict[str, float] | None = None, hide: bool = False
) -> str:
    """Build a (property ...) s-expression string."""
    x = pos.get("x", 0) if pos else 0
    y = pos.get("y", 0) if pos else 0
    parts = [f'(property "{name}" "{value}" (at {x} {y} 0)']
    if hide:
        parts.append("(hide yes)")
    parts.append("(effects (font (size 1.27 1.27)))")
    parts.append(")")
    return "\n\t\t\t".join(parts)


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
    new_prop = _property_s_expr(prop_name, prop_value, pos, hide)

    if _has_property(block, prop_name):
        old = re.search(
            rf'(\(property\s+"{re.escape(prop_name)}"[^)]*(?:\([^)]*\))*[^)]*\s*\n?\s*(?:\(hide[^)]*\)\s*\n?\s*)?(?:\(effects[^)]*(?:\([^)]*\))*[^)]*\))?\s*\))',
            block,
            re.DOTALL,
        )
        if old:
            block = block[: old.start()] + new_prop + block[old.end() :]
        else:
            block = block.rstrip()[:-1] + "\n\t\t\t" + new_prop + "\n\t\t)"
    else:
        sub = re.search(r'\n\t\t\t\(symbol "', block)
        if sub:
            insert_at = sub.start()
            block = block[:insert_at] + "\n\t\t\t" + new_prop + block[insert_at:]
        else:
            block = block.rstrip()[:-1] + "\n\t\t\t" + new_prop + "\n\t\t)"

    content = content[:sym_start] + block + content[sym_end + 1 :]
    schematic_path.write_text(prettify(content), encoding="utf-8")

    return {
        "success": True,
        "message": f"Property '{prop_name}' set to '{prop_value}' in {library_name}:{symbol_name}",
        "propertyAdded": prop_name,
        "propertyValue": prop_value,
    }
