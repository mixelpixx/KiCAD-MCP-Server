"""Update schematic lib_symbols from a KiCad symbol library (Update Symbol from Library)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from commands.dynamic_symbol_loader import DynamicSymbolLoader

_MIRROR_SUFFIX = re.compile(r"__m\d+(?:_\d+)?$")


def _adapt_library_block_for_schematic(block: str) -> str:
    """Convert .kicad_sym layout to .kicad_sch lib_symbols layout (flatten (power) wrapper)."""
    if not re.search(r"\n\s*\(power\)\s*\n", block):
        return block
    block = re.sub(
        r"(\(on_board yes\))\s*\n\s*\(power\)\s*\n",
        r"\1 (power)\n",
        block,
        count=1,
    )
    lines = block.split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        out.append(line[2:] if line.startswith("    ") else line)
    return "\n".join(out)


def _extract_paren_block(text: str, start: int) -> tuple[str, int]:
    depth, i = 0, start
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1], i + 1
        i += 1
    return text[start:], len(text)


def _lib_symbols_range(content: str) -> tuple[int, int] | None:
    lib_sym_start = content.find("(lib_symbols")
    if lib_sym_start == -1:
        return None
    depth = 0
    for i in range(lib_sym_start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return lib_sym_start, i
    return None


def _lib_ids_in_lib_symbols(content: str, library_name: str) -> set[str]:
    rng = _lib_symbols_range(content)
    if not rng:
        return set()
    start, end = rng
    section = content[start:end]
    return set(re.findall(rf'\(symbol "{re.escape(library_name)}:([^"]+)"', section))


def _used_lib_ids(content: str, library_name: str) -> set[str]:
    return set(re.findall(rf'\(lib_id "{re.escape(library_name)}:([^"]+)"', content))


def _indent_block(block: str) -> str:
    return "\n".join("    " + line if line.strip() else line for line in block.split("\n"))


def _library_block(loader: DynamicSymbolLoader, library_name: str, symbol_name: str) -> str | None:
    if _MIRROR_SUFFIX.search(symbol_name):
        return None
    block = loader.extract_symbol_from_library(library_name, symbol_name)
    if not block:
        return None
    return _adapt_library_block_for_schematic(block)


def _iter_mirror_blocks(content: str, library_name: str, lib_start: int, lib_end: int) -> list[tuple[str, int, int]]:
    blocks: list[tuple[str, int, int]] = []
    pos = lib_start
    marker = f'(symbol "{library_name}:'
    while True:
        sym_start = content.find(marker, pos)
        if sym_start == -1 or sym_start > lib_end:
            break
        name_end = content.find('"', sym_start + len(marker))
        name = content[sym_start + len(marker) : name_end]
        block, end = _extract_paren_block(content, sym_start)
        if _MIRROR_SUFFIX.search(name):
            blocks.append((name, sym_start, end))
        pos = end
    return blocks


def repair_mirror_lib_symbols(
    schematic_path: Path,
    backup_path: Path,
    library_name: str,
) -> int:
    if not backup_path.exists():
        return 0
    content = schematic_path.read_text(encoding="utf-8")
    backup = backup_path.read_text(encoding="utf-8")
    rng = _lib_symbols_range(content)
    backup_rng = _lib_symbols_range(backup)
    if not rng or not backup_rng:
        return 0

    backup_map = {
        name: (start, end)
        for name, start, end in _iter_mirror_blocks(backup, library_name, backup_rng[0], backup_rng[1])
    }
    if not backup_map:
        return 0

    replacements: list[tuple[int, int, str]] = []
    restored = 0
    for name, sym_start, sym_end in _iter_mirror_blocks(content, library_name, rng[0], rng[1]):
        if name not in backup_map:
            continue
        b_start, b_end = backup_map[name]
        new_block = backup[b_start:b_end]
        if content[sym_start:sym_end] == new_block:
            continue
        replacements.append((sym_start, sym_end, new_block))
        restored += 1

    for start, end, new in sorted(replacements, key=lambda r: r[0], reverse=True):
        content = content[:start] + new + content[end:]
    if restored:
        schematic_path.write_text(content, encoding="utf-8")
    return restored


def update_schematic_symbols(
    schematic_path: Path,
    library_name: str,
    only_symbols: set[str] | None = None,
) -> dict[str, int]:
    loader = DynamicSymbolLoader(project_path=schematic_path.parent)
    content = schematic_path.read_text(encoding="utf-8")
    rng = _lib_symbols_range(content)
    if not rng:
        return {"updated": 0, "injected": 0, "skipped": 0}

    lib_start, lib_end = rng
    targets = sorted(_lib_ids_in_lib_symbols(content, library_name) | _used_lib_ids(content, library_name))
    if only_symbols:
        targets = [s for s in targets if s in only_symbols]
    if not targets:
        return {"updated": 0, "injected": 0, "skipped": 0}

    updated = injected = skipped = 0
    replacements: list[tuple[int, int, str, str]] = []

    for symbol_name in targets:
        if _MIRROR_SUFFIX.search(symbol_name):
            skipped += 1
            continue
        full_name = f"{library_name}:{symbol_name}"
        new_block = _library_block(loader, library_name, symbol_name)
        if not new_block:
            skipped += 1
            continue

        marker = f'(symbol "{full_name}"'
        sym_start = content.find(marker, lib_start)
        if sym_start == -1 or sym_start > lib_end:
            replacements.append((lib_end, lib_end, "", _indent_block(new_block) + "\n  "))
            injected += 1
            continue

        old_block, _ = _extract_paren_block(content, sym_start)
        if old_block.strip() == new_block.strip():
            continue
        replacements.append((sym_start, sym_start + len(old_block), old_block, _indent_block(new_block)))
        updated += 1

    if replacements:
        for start, end, _old, new in sorted(replacements, key=lambda r: r[0], reverse=True):
            content = content[:start] + new + content[end:]
        schematic_path.write_text(content, encoding="utf-8")

    return {"updated": updated, "injected": injected, "skipped": skipped}


def update_symbol_from_library(params: dict[str, Any]) -> dict[str, Any]:
    library_name = params.get("libraryName")
    if not library_name:
        return {"success": False, "message": "libraryName is required (sym-lib-table nickname, e.g. Device)"}
    only_symbols = set(params["symbols"]) if params.get("symbols") else None
    backup_dir = Path(params["backupDir"]) if params.get("backupDir") else None
    repair_mirror = bool(params.get("repairMirrorFromBackup", False))

    schematic_paths: list[Path] = []
    if params.get("schematicPath"):
        schematic_paths.append(Path(params["schematicPath"]))
    elif params.get("schematicPaths"):
        schematic_paths.extend(Path(p) for p in params["schematicPaths"])
    elif params.get("projectsDir"):
        projects_dir = Path(params["projectsDir"])
        schematic_paths = sorted(
            p
            for p in projects_dir.glob("*/*.kicad_sch")
            if ".history" not in p.parts and "backup" not in p.parts
        )
    else:
        return {"success": False, "message": "Provide schematicPath, schematicPaths, or projectsDir"}

    results = []
    total_updated = total_injected = total_skipped = total_mirror = 0

    for sch in schematic_paths:
        if not sch.exists():
            results.append({"schematic": str(sch), "error": "not found"})
            continue
        mirror_restored = 0
        if repair_mirror and backup_dir:
            mirror_restored = repair_mirror_lib_symbols(sch, backup_dir / sch.name, library_name)
        counts = update_schematic_symbols(sch, library_name, only_symbols)
        total_updated += counts["updated"]
        total_injected += counts["injected"]
        total_skipped += counts["skipped"]
        total_mirror += mirror_restored
        if counts["updated"] or counts["injected"] or mirror_restored:
            results.append(
                {
                    "schematic": str(sch),
                    "updated": counts["updated"],
                    "injected": counts["injected"],
                    "skipped": counts["skipped"],
                    "mirror_restored": mirror_restored,
                }
            )

    return {
        "success": True,
        "message": (
            f"Updated {len(results)} schematic(s): "
            f"{total_updated} symbol(s) updated, {total_injected} injected, "
            f"{total_skipped} skipped, {total_mirror} mirror block(s) restored"
        ),
        "schematics_changed": len(results),
        "updated": total_updated,
        "injected": total_injected,
        "skipped": total_skipped,
        "mirror_restored": total_mirror,
        "results": results,
    }
