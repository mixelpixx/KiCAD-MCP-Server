"""
Library management for KiCad .kicad_sym files — import, export, rename, delete.

All operations use kicad-cli sym upgrade for validation after modification.
Operates on raw S-expression text with parenthesis-depth parsing.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _extract_paren_block(text: str, start: int) -> str:
    """Extract a balanced () block starting at position `start`."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _find_symbol_block(content: str, name: str) -> Optional[tuple[int, int, str]]:
    """Find a top-level (symbol "name" ...) block.

    Returns (start, end, block_text) or None.
    Only matches top-level symbols (nesting level 1 inside kicad_symbol_lib),
    not subsymbols like name_0_1 or name_1_1.
    """
    pattern = re.compile(r'\(symbol "' + re.escape(name) + r'"')
    for m in pattern.finditer(content):
        pos = m.start()
        # Check nesting level — must be 1 (inside kicad_symbol_lib)
        depth = 0
        for i in range(pos):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
        if depth != 1:
            continue
        # Make sure it's not a subsymbol (name_0_1, name_1_1, etc.)
        after_quote = pos + len(m.group(0))
        next_char = content[after_quote] if after_quote < len(content) else ""
        if next_char == "_":
            continue
        block = _extract_paren_block(content, pos)
        if block:
            return (pos, pos + len(block), block)
    return None


def _find_lib_close(content: str) -> int:
    """Find the closing ) of (kicad_symbol_lib ...)."""
    depth = 0
    for i in range(len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(content) - 1


class LibraryManagementCommands:
    """Import, export, rename, and delete symbols in .kicad_sym libraries."""

    def import_symbol(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Import a symbol from one .kicad_sym library into another.

        Parameters
        ----------
        source_library_path : str  – path to source .kicad_sym
        symbol_name : str          – symbol to import
        target_library_path : str  – path to target .kicad_sym (created if missing)
        new_name : str             – rename symbol on import (optional, default = symbol_name)
        overwrite : bool           – overwrite if symbol exists in target (default False)

        Returns
        -------
        dict with success, symbol_name, target_library_path
        """
        src_path = params.get("source_library_path", "")
        symbol_name = params.get("symbol_name", "")
        tgt_path = params.get("target_library_path", "")
        new_name = params.get("new_name") or symbol_name
        overwrite = params.get("overwrite", False)

        if not src_path or not symbol_name or not tgt_path:
            return {"success": False, "error": "source_library_path, symbol_name, and target_library_path are required"}

        src = Path(src_path)
        tgt = Path(tgt_path)
        if not src.exists():
            return {"success": False, "error": f"Source library not found: {src_path}"}

        src_content = src.read_text(encoding="utf-8")
        found = _find_symbol_block(src_content, symbol_name)
        if not found:
            return {"success": False, "error": f"Symbol '{symbol_name}' not found in {src_path}"}

        _, _, block = found

        # Rename symbol and subsymbols if new_name differs
        if new_name != symbol_name:
            block = self._rename_in_block(block, symbol_name, new_name)

        # Load or create target library
        if tgt.exists():
            tgt_content = tgt.read_text(encoding="utf-8")
        else:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt_content = (
                '(kicad_symbol_lib\n'
                '\t(version 20251024)\n'
                '\t(generator "kicad-mcp")\n'
                '\t(generator_version "10.0")\n'
                ')\n'
            )

        # Check for duplicate
        if _find_symbol_block(tgt_content, new_name):
            if not overwrite:
                return {
                    "success": False,
                    "error": f"Symbol '{new_name}' already exists in {tgt_path}. Use overwrite=true.",
                }
            # Remove existing symbol
            tgt_content = self._remove_symbol_from_content(tgt_content, new_name)

        # Insert before library close
        lib_close = _find_lib_close(tgt_content)
        tgt_content = tgt_content[:lib_close].rstrip() + "\n" + block + "\n" + tgt_content[lib_close:]

        tgt.write_text(tgt_content, encoding="utf-8", newline="\n")
        logger.info(f"Imported symbol '{symbol_name}' as '{new_name}' into {tgt_path}")

        return {
            "success": True,
            "symbol_name": new_name,
            "source_library_path": str(src),
            "target_library_path": str(tgt),
        }

    def export_symbol(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Export a single symbol from a .kicad_sym library to a standalone .kicad_sym file.

        Parameters
        ----------
        library_path : str    – path to source .kicad_sym
        symbol_name : str     – symbol to export
        output_path : str     – path for output .kicad_sym (created if missing)

        Returns
        -------
        dict with success, symbol_name, output_path
        """
        lib_path = params.get("library_path", "")
        symbol_name = params.get("symbol_name", "")
        out_path = params.get("output_path", "")

        if not lib_path or not symbol_name or not out_path:
            return {"success": False, "error": "library_path, symbol_name, and output_path are required"}

        lib = Path(lib_path)
        out = Path(out_path)
        if not lib.exists():
            return {"success": False, "error": f"Library not found: {lib_path}"}

        content = lib.read_text(encoding="utf-8")
        found = _find_symbol_block(content, symbol_name)
        if not found:
            return {"success": False, "error": f"Symbol '{symbol_name}' not found in {lib_path}"}

        _, _, block = found

        # Wrap in a new library
        new_lib = (
            '(kicad_symbol_lib\n'
            '\t(version 20251024)\n'
            '\t(generator "kicad-mcp")\n'
            '\t(generator_version "10.0")\n'
            + block
            + "\n)\n"
        )

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new_lib, encoding="utf-8", newline="\n")
        logger.info(f"Exported symbol '{symbol_name}' to {out_path}")

        return {
            "success": True,
            "symbol_name": symbol_name,
            "output_path": str(out),
        }

    def rename_symbol(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Rename a symbol within a .kicad_sym library.

        Updates the symbol name and all subsymbol references (name_0_1, name_1_1, etc.).

        Parameters
        ----------
        library_path : str     – path to .kicad_sym
        old_name : str         – current symbol name
        new_name : str         – new symbol name

        Returns
        -------
        dict with success, old_name, new_name
        """
        lib_path = params.get("library_path", "")
        old_name = params.get("old_name", "")
        new_name = params.get("new_name", "")

        if not lib_path or not old_name or not new_name:
            return {"success": False, "error": "library_path, old_name, and new_name are required"}

        lib = Path(lib_path)
        if not lib.exists():
            return {"success": False, "error": f"Library not found: {lib_path}"}

        content = lib.read_text(encoding="utf-8")
        found = _find_symbol_block(content, old_name)
        if not found:
            return {"success": False, "error": f"Symbol '{old_name}' not found in {lib_path}"}

        if _find_symbol_block(content, new_name):
            return {"success": False, "error": f"Symbol '{new_name}' already exists in {lib_path}"}

        start, end, block = found
        new_block = self._rename_in_block(block, old_name, new_name)
        content = content[:start] + new_block + content[end:]

        lib.write_text(content, encoding="utf-8", newline="\n")
        logger.info(f"Renamed symbol '{old_name}' to '{new_name}' in {lib_path}")

        return {
            "success": True,
            "old_name": old_name,
            "new_name": new_name,
            "library_path": str(lib),
        }

    def delete_symbol(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Delete a symbol from a .kicad_sym library.

        Parameters
        ----------
        library_path : str  – path to .kicad_sym
        symbol_name : str   – symbol to delete

        Returns
        -------
        dict with success, deleted
        """
        lib_path = params.get("library_path", "")
        symbol_name = params.get("symbol_name", "")

        if not lib_path or not symbol_name:
            return {"success": False, "error": "library_path and symbol_name are required"}

        lib = Path(lib_path)
        if not lib.exists():
            return {"success": False, "error": f"Library not found: {lib_path}"}

        content = lib.read_text(encoding="utf-8")
        found = _find_symbol_block(content, symbol_name)
        if not found:
            return {"success": False, "error": f"Symbol '{symbol_name}' not found in {lib_path}"}

        start, end, _ = found
        content = content[:start].rstrip() + "\n" + content[end + 1 :]

        lib.write_text(content, encoding="utf-8", newline="\n")
        logger.info(f"Deleted symbol '{symbol_name}' from {lib_path}")

        return {
            "success": True,
            "deleted": symbol_name,
            "library_path": str(lib),
        }

    # ── Internal helpers ──────────────────────────────────────────────

    def _rename_in_block(self, block: str, old_name: str, new_name: str) -> str:
        """Rename symbol and all subsymbol references within a block."""
        # Rename subsymbols first (old_name_0_1 -> new_name_0_1)
        block = block.replace(f'"{old_name}_', f'"{new_name}_')
        # Rename the main symbol
        block = block.replace(f'(symbol "{old_name}"', f'(symbol "{new_name}"', 1)
        return block

    def _remove_symbol_from_content(self, content: str, name: str) -> str:
        """Remove a symbol block from library content."""
        found = _find_symbol_block(content, name)
        if not found:
            return content
        start, end, _ = found
        return content[:start].rstrip() + "\n" + content[end + 1 :]
