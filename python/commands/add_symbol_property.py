"""Add or update a property on a symbol in a .kicad_sym library file."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _find_symbol_in_lib(content: str, symbol_name: str) -> tuple[int, int, str] | None:
    """Return (start, end, block) for a symbol in .kicad_sym, or None."""
    marker = f'(symbol "{symbol_name}"'
    sym_start = content.find(marker)
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
    return bool(re.search(rf'\(property\s+"{re.escape(prop_name)}"', symbol_block))


def _build_property(
    name: str, value: str, pos: dict[str, float] | None = None, hide: bool = False
) -> str:
    x = pos.get("x", 0) if pos else 0
    y = pos.get("y", 0) if pos else 0
    lines = [f'(property "{name}" "{value}" (at {x} {y} 0)']
    if hide:
        lines.append("(hide yes)")
    lines.append("(effects (font (size 1.27 1.27)))")
    lines.append(")")
    return "\n\t\t\t".join(lines)


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
    new_prop = _build_property(prop_name, prop_value, pos, hide)

    updated = False
    block = content[sym_start:sym_end]
    if _has_property(block, prop_name):
        updated = True
        # Remove old property
        old = re.search(
            rf'\(property "{re.escape(prop_name)}"\s+"[^"]*".*?\)',
            block, re.DOTALL
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
    lib_path.write_text(content, encoding="utf-8")

    action = "Updated" if updated else "Added"
    return {
        "success": True,
        "message": f"Property '{prop_name}' = '{prop_value}' {action.lower()} to '{symbol_name}'",
        "propertyAdded": prop_name,
        "propertyValue": prop_value,
    }
