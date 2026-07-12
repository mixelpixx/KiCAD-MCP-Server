"""
Library management for KiCad .kicad_sym files — import, export, and rename.

Operates on raw S-expression text with parenthesis-depth parsing. Deletion is
deliberately NOT here: the existing delete_symbol tool (SymbolCreator) owns
that capability — one tool per capability keeps the dispatch table honest.

New/exported library files reuse SymbolCreator's header constants so every
.kicad_sym this server writes carries the same, oldest-supported format token
(KiCad refuses files claiming a newer format version than the running build).
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from commands.symbol_creator import KICAD9_SYMBOL_LIB_VERSION, _invalidate_symbol_caches

logger = logging.getLogger("kicad_interface")

_NEW_LIB_HEADER = (
    "(kicad_symbol_lib\n"
    f"\t(version {KICAD9_SYMBOL_LIB_VERSION})\n"
    '\t(generator "kicad-mcp")\n'
    '\t(generator_version "9.0")\n'
    ")\n"
)


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


def _find_symbol_block(content: str, name: str) -> Optional[Tuple[int, int, str]]:
    """Find the top-level (symbol "name" ...) block inside kicad_symbol_lib.

    Returns (start, end, block_text) or None. Only matches symbols at nesting
    level 1 directly inside ``(kicad_symbol_lib ...)`` — never sub-symbols
    (``name_0_1`` at depth 2), so a caller cannot accidentally address a bare
    body/pin shard (importing one would produce a broken library).
    """
    pattern = re.compile(r'\(symbol "' + re.escape(name) + r'"')
    for m in pattern.finditer(content):
        pos = m.start()
        depth = 0
        for i in range(pos):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
        if depth != 1:
            continue
        block = _extract_paren_block(content, pos)
        if block:
            return (pos, pos + len(block), block)
    return None


def _find_lib_close(content: str) -> int:
    """Find insertion point before the library's closing paren.

    Scans backwards line-by-line. The last line whose only non-whitespace
    character is ``)`` is treated as the library close — symbols are
    inserted just above it.
    """
    lines = content.split("\n")
    for lineno in range(len(lines) - 1, -1, -1):
        stripped = lines[lineno].strip()
        if stripped == ")":
            pos = 0
            for i in range(lineno):
                pos += len(lines[i]) + 1  # +1 for \n
            return pos  # index of the line start of the closing ) line
    return len(content) - 1


class LibraryManagementCommands:
    """Import, export, and rename symbols in .kicad_sym libraries."""

    def import_symbol(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Import a symbol from one .kicad_sym library into another.

        Params
        ------
        sourceLibraryPath : str – path to source .kicad_sym
        symbolName : str        – symbol to import
        targetLibraryPath : str – path to target .kicad_sym (created if missing)
        newName : str           – rename symbol on import (optional)
        overwrite : bool        – overwrite if symbol exists in target (default False)

        Note: a derived symbol (one using ``(extends "Parent")``) needs its
        parent present in the target library too — import the parent first.
        """
        src_path = params.get("sourceLibraryPath", "")
        symbol_name = params.get("symbolName", "")
        tgt_path = params.get("targetLibraryPath", "")
        new_name = params.get("newName") or symbol_name
        overwrite = params.get("overwrite", False)

        if not src_path or not symbol_name or not tgt_path:
            return {
                "success": False,
                "error": "sourceLibraryPath, symbolName, and targetLibraryPath are required",
            }

        src = Path(src_path)
        tgt = Path(tgt_path)
        if not src.exists():
            return {"success": False, "error": f"Source library not found: {src_path}"}

        src_content = src.read_text(encoding="utf-8")
        found = _find_symbol_block(src_content, symbol_name)
        if not found:
            return {"success": False, "error": f"Symbol '{symbol_name}' not found in {src_path}"}

        _, _, block = found

        if new_name != symbol_name:
            block = self._rename_in_block(block, symbol_name, new_name)

        if tgt.exists():
            tgt_content = tgt.read_text(encoding="utf-8")
        else:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt_content = _NEW_LIB_HEADER

        if _find_symbol_block(tgt_content, new_name):
            if not overwrite:
                return {
                    "success": False,
                    "error": f"Symbol '{new_name}' already exists in {tgt_path}. Use overwrite=true.",
                }
            tgt_content = self._remove_symbol_from_content(tgt_content, new_name)

        lib_close = _find_lib_close(tgt_content)
        tgt_content = (
            tgt_content[:lib_close].rstrip() + "\n" + block + "\n" + tgt_content[lib_close:]
        )

        tgt.write_text(tgt_content, encoding="utf-8", newline="\n")
        logger.info(f"Imported symbol '{symbol_name}' as '{new_name}' into {tgt_path}")
        _invalidate_symbol_caches()

        return {
            "success": True,
            "symbol_name": new_name,
            "source_library_path": str(src),
            "target_library_path": str(tgt),
        }

    def export_symbol(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Export a single symbol from a .kicad_sym library to a standalone .kicad_sym file.

        Params
        ------
        libraryPath : str – path to source .kicad_sym
        symbolName : str  – symbol to export
        outputPath : str  – path for output .kicad_sym (created if missing)
        """
        lib_path = params.get("libraryPath", "")
        symbol_name = params.get("symbolName", "")
        out_path = params.get("outputPath", "")

        if not lib_path or not symbol_name or not out_path:
            return {
                "success": False,
                "error": "libraryPath, symbolName, and outputPath are required",
            }

        lib = Path(lib_path)
        out = Path(out_path)
        if not lib.exists():
            return {"success": False, "error": f"Library not found: {lib_path}"}

        content = lib.read_text(encoding="utf-8")
        found = _find_symbol_block(content, symbol_name)
        if not found:
            return {"success": False, "error": f"Symbol '{symbol_name}' not found in {lib_path}"}

        _, _, block = found

        # Wrap in a new library shell (header before the block, then close).
        new_lib = _NEW_LIB_HEADER[: _NEW_LIB_HEADER.rfind(")")] + block + "\n)\n"

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new_lib, encoding="utf-8", newline="\n")
        logger.info(f"Exported symbol '{symbol_name}' to {out_path}")
        _invalidate_symbol_caches()

        return {
            "success": True,
            "symbol_name": symbol_name,
            "output_path": str(out),
        }

    def rename_symbol(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rename a symbol within a .kicad_sym library.

        Updates the symbol name, its sub-symbol shards (name_0_1, name_1_1,
        ...), and every ``(extends "old")`` reference from derived symbols
        elsewhere in the same library — leaving those dangling would orphan
        the children (#282's failure class).

        Params
        ------
        libraryPath : str – path to .kicad_sym
        oldName : str     – current symbol name
        newName : str     – new symbol name
        """
        lib_path = params.get("libraryPath", "")
        old_name = params.get("oldName", "")
        new_name = params.get("newName", "")

        if not lib_path or not old_name or not new_name:
            return {
                "success": False,
                "error": "libraryPath, oldName, and newName are required",
            }

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

        # Repoint derived symbols that extend the renamed one.
        extends_updated = content.count(f'(extends "{old_name}")')
        if extends_updated:
            content = content.replace(f'(extends "{old_name}")', f'(extends "{new_name}")')

        lib.write_text(content, encoding="utf-8", newline="\n")
        logger.info(f"Renamed symbol '{old_name}' to '{new_name}' in {lib_path}")
        _invalidate_symbol_caches()

        return {
            "success": True,
            "old_name": old_name,
            "new_name": new_name,
            "extends_updated": extends_updated,
            "library_path": str(lib),
        }

    # ── Internal helpers ──────────────────────────────────────────────

    def _rename_in_block(self, block: str, old_name: str, new_name: str) -> str:
        """Rename a symbol and its sub-symbol shards within one block.

        Sub-symbol references only ever appear as ``(symbol "NAME_N_M"`` —
        anchoring on ``(symbol "`` keeps the replace from touching property
        VALUES that happen to start with the symbol name.
        """
        block = block.replace(f'(symbol "{old_name}_', f'(symbol "{new_name}_')
        block = block.replace(f'(symbol "{old_name}"', f'(symbol "{new_name}"', 1)
        return block

    def _remove_symbol_from_content(self, content: str, name: str) -> str:
        """Remove a top-level symbol block from library content."""
        found = _find_symbol_block(content, name)
        if not found:
            return content
        start, end, _ = found
        rest = content[end:]
        # Consume the newline that followed the removed block, if any —
        # never an arbitrary character (that could be a closing paren).
        if rest.startswith("\n"):
            rest = rest[1:]
        return content[:start].rstrip() + "\n" + rest
