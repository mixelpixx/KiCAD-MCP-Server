"""Find symbols that are the same part stored twice in a .kicad_sym library.

Libraries accumulate duplicates the moment more than one source feeds them:
an Eagle import lands the same resistor the curated library already had, a
SnapEDA download arrives under the vendor's naming, someone re-adds a part
because search did not find the existing name. Nothing in KiCad reports this,
because the names differ -- which is exactly why grepping for the name does
not find it either.

Four ways to notice the same part twice, each catching what the others miss:

``mpn``
    Same manufacturer part number. The strongest signal, and the one that has
    to work across inconsistent property naming: a real library holds the same
    field as ``MPN``, ``MP``, ``MANUFACTURER PART NUMBER`` and ``PART NUMBER``
    depending on which importer wrote it, so a plain group-by finds nothing.

``supplier``
    Same distributor part number, for parts that never got an MPN field.

``value_footprint``
    Same Value on the same Footprint. Catches the passives that make up most
    of a library, where there is no MPN to compare.

``graphics``
    Byte-identical body: same pins in the same places, same drawing. Catches a
    custom part copied under a new name whatever its fields say -- but every
    resistor in a library shares one body, so on passives it groups the whole
    family and means nothing. Off by default for that reason; ask for it when
    hunting a copied IC, and read it as evidence rather than as a verdict.
    Symbols that ``extends`` another are excluded: sharing a body is the point.

Usage counts from the project's schematics turn the report into a decision:
the duplicate that nothing instantiates is the one to retire.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from utils.duplicate_strategies import DEFAULT_DUPLICATE_STRATEGIES, DUPLICATE_STRATEGIES
from utils.sexpr_format import iter_child_offsets, match_paren

logger = logging.getLogger("kicad_interface")

STRATEGIES = DUPLICATE_STRATEGIES
DEFAULT_STRATEGIES = DEFAULT_DUPLICATE_STRATEGIES

# Property names that hold a manufacturer part number, best first. Compared
# after _norm_key, so spacing and punctuation do not matter.
MPN_KEYS = (
    "MPN",
    "MANUFACTURERPARTNUMBER",
    "MFRPARTNUMBER",
    "MFGPARTNUMBER",
    "MANUFACTURERPARTNO",
    "MP",
    "PARTNUMBER",
)

SUPPLIER_KEYS = (
    "DIGIKEY",
    "DIGIKEYPARTNUMBER",
    "DIGIKEYPN",
    "SUPPLIERPARTNUMBER1",
    "SUPPLIERPARTNUMBER",
    "LCSC",
    "LCSCPARTNUMBER",
    "MOUSER",
    "MOUSERPARTNUMBER",
)

_HEAD = re.compile(r"\(\s*([A-Za-z_][\w]*)")
_LIB_ID = re.compile(r'\(lib_id\s+"((?:[^"\\]|\\.)*)"')
_WHITESPACE = re.compile(r"\s+")


def _norm_key(name: str) -> str:
    """Collapse a property name so MANUFACTURER PART NUMBER == Manufacturer_Part-Number."""
    return re.sub(r"[\s_\-.#]+", "", name).upper()


def _read_string(text: str, i: int) -> Tuple[Optional[str], int]:
    """Read the quoted token at or after *i*; return (value, index after it)."""
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


def _fingerprint(block: str, symbol_name: str) -> str:
    """Hash of a symbol's drawn body, blind to its name and to formatting.

    Unit sub-symbols are named after their parent (``R_0402_1_1``), so the same
    body copied under a new name hashes differently unless the parent name is
    stripped first. Whitespace is collapsed because a hand-edited library and
    one written by the symbol editor differ in indentation and nothing else.
    """
    parts: List[str] = []
    for off in iter_child_offsets(block):
        head = _HEAD.match(block, off)
        if not head or head.group(1) != "symbol":
            continue
        end = match_paren(block, off)
        if end == -1:
            continue
        unit = block[off : end + 1]
        name, _ = _read_string(block, head.end())
        if name and name.startswith(symbol_name):
            unit = unit.replace(f'"{name}"', f'"{name[len(symbol_name):]}"', 1)
        parts.append(_WHITESPACE.sub(" ", unit).strip())
    if not parts:
        return ""
    return hashlib.sha1("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def read_library_symbols(text: str) -> List[Dict[str, Any]]:
    """Parse a .kicad_sym into one record per top-level symbol."""
    root = _HEAD.search(text)
    if not root:
        return []
    lib_start = root.start()
    symbols: List[Dict[str, Any]] = []

    for off in iter_child_offsets(text[lib_start:]):
        off += lib_start
        head = _HEAD.match(text, off)
        if not head or head.group(1) != "symbol":
            continue
        end = match_paren(text, off)
        if end == -1:
            continue
        block = text[off : end + 1]
        name, _ = _read_string(text, head.end())
        if not name:
            continue

        properties: Dict[str, str] = {}
        extends: Optional[str] = None
        for child in iter_child_offsets(block):
            child_head = _HEAD.match(block, child)
            if not child_head:
                continue
            token = child_head.group(1)
            if token == "property":
                key, after = _read_string(block, child_head.end())
                value, _ = _read_string(block, after)
                if key is not None:
                    properties[key] = value or ""
            elif token == "extends":
                extends, _ = _read_string(block, child_head.end())

        symbols.append(
            {
                "name": name,
                "properties": properties,
                "normalized": {_norm_key(k): v for k, v in properties.items()},
                "extends": extends,
                "pinCount": len(re.findall(r"\(pin\s+[A-Za-z_]", block)),
                "fingerprint": "" if extends else _fingerprint(block, name),
            }
        )
    return symbols


def _first_property(symbol: Dict[str, Any], keys: Sequence[str]) -> Tuple[str, str]:
    """Return (value, property name) for the first of *keys* that is filled."""
    for key in keys:
        value = symbol["normalized"].get(key, "").strip()
        if value:
            original = next(
                (k for k in symbol["properties"] if _norm_key(k) == key),
                key,
            )
            return value, original
    return "", ""


def _iter_schematics(paths: Iterable[str]) -> List[Path]:
    """Expand a mix of .kicad_sch files and directories into sheet paths."""
    sheets: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            sheets.extend(sorted(path.rglob("*.kicad_sch")))
        elif path.is_file():
            sheets.append(path)
    seen: Set[Path] = set()
    unique = []
    for sheet in sheets:
        resolved = sheet.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(sheet)
    return unique


def count_symbol_usage(sheets: Sequence[Path]) -> Dict[str, Dict[str, int]]:
    """Count symbol instances per symbol name, per sheet.

    The library nickname in a lib_id is ignored: the same library is registered
    under different nicknames in different projects, and the question being
    asked is which symbol is in use, not which table entry pointed at it.
    """
    usage: Dict[str, Dict[str, int]] = {}
    for sheet in sheets:
        try:
            text = sheet.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Could not read %s: %s", sheet, e)
            continue
        # Only placed instances carry (lib_id ...); the lib_symbols cache keys
        # its entries by the id itself, so counting lib_id counts placements.
        for m in _LIB_ID.finditer(text):
            lib_id = m.group(1)
            symbol_name = lib_id.split(":", 1)[1] if ":" in lib_id else lib_id
            usage.setdefault(symbol_name, {})
            usage[symbol_name][sheet.name] = usage[symbol_name].get(sheet.name, 0) + 1
    return usage


def _group_key(symbol: Dict[str, Any], strategy: str, ignore_case: bool) -> Tuple[str, str]:
    """Return (key, provenance) for one symbol under one strategy; '' means skip."""
    if strategy == "mpn":
        value, source = _first_property(symbol, MPN_KEYS)
    elif strategy == "supplier":
        value, source = _first_property(symbol, SUPPLIER_KEYS)
    elif strategy == "value_footprint":
        value_field = symbol["normalized"].get("VALUE", "").strip()
        footprint = symbol["normalized"].get("FOOTPRINT", "").strip()
        if not value_field or not footprint:
            return "", ""
        value, source = f"{value_field} @ {footprint}", "Value + Footprint"
    elif strategy == "graphics":
        value, source = symbol["fingerprint"], "body"
    elif strategy == "name":
        value = re.sub(r"[\s_\-.]+", "", symbol["name"])
        source = "name"
    else:
        return "", ""

    if not value:
        return "", ""
    if ignore_case and strategy != "graphics":
        value = value.upper()
    return value, source


def _suggest_keep(members: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Pick the member to keep, and say why. Deterministic on ties."""
    best = max(
        members,
        key=lambda m: (
            m["usageCount"],
            sum(1 for f in ("mpn", "datasheet", "description") if m.get(f)),
            -len(m["name"]),
            [-ord(c) for c in m["name"]],
        ),
    )
    if best["usageCount"] > 0 and all(
        m["usageCount"] == 0 for m in members if m["name"] != best["name"]
    ):
        reason = f"only one in use ({best['usageCount']} instance(s))"
    elif best["usageCount"] > 0:
        reason = f"most used ({best['usageCount']} instance(s))"
    elif any(m["usageCount"] for m in members):
        reason = "most used"
    else:
        reason = "none are used; most complete fields"
    return best["name"], reason


def find_duplicate_symbols(params: Dict[str, Any]) -> Dict[str, Any]:
    """Group symbols in a library that look like the same part stored twice."""
    lib_path = Path(params.get("libraryPath", ""))
    requested = params.get("matchBy") or list(DEFAULT_STRATEGIES)
    if isinstance(requested, str):
        requested = [requested]
    unknown = [s for s in requested if s not in STRATEGIES]
    if unknown:
        return {
            "success": False,
            "message": f"Unknown matchBy value(s): {', '.join(unknown)}",
            "validStrategies": list(STRATEGIES),
        }

    ignore_case = bool(params.get("ignoreCase", True))
    min_group_size = max(2, int(params.get("minGroupSize", 2)))

    if not lib_path.is_file():
        return {"success": False, "message": f"Library not found: {lib_path}"}
    try:
        text = lib_path.read_text(encoding="utf-8")
    except OSError as e:
        return {"success": False, "message": f"Could not read {lib_path}: {e}"}

    root = _HEAD.search(text)
    if not root or root.group(1) != "kicad_symbol_lib":
        found = root.group(1) if root else "nothing"
        return {
            "success": False,
            "message": (
                f"{lib_path.name} is not a symbol library "
                f"(root form is '{found}', expected 'kicad_symbol_lib')"
            ),
        }

    symbols = read_library_symbols(text)
    if not symbols:
        return {
            "success": True,
            "message": f"{lib_path.name} contains no symbols",
            "symbolCount": 0,
            "groups": [],
        }

    sheets = _iter_schematics(params.get("schematicPaths") or [])
    usage = count_symbol_usage(sheets)

    # A pair of symbols usually trips more than one strategy. Group by the set
    # of members so the report has one entry per real duplicate, listing the
    # evidence, instead of the same pair three times.
    buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for strategy in requested:
        by_key: Dict[str, List[Dict[str, Any]]] = {}
        for symbol in symbols:
            key, _ = _group_key(symbol, strategy, ignore_case)
            if key:
                by_key.setdefault(key, []).append(symbol)
        for key, group in by_key.items():
            if len(group) >= min_group_size:
                buckets[(strategy, key)] = group

    merged: Dict[frozenset, Dict[str, Any]] = {}
    for (strategy, key), group in buckets.items():
        names = frozenset(s["name"] for s in group)
        entry = merged.setdefault(names, {"symbols": group, "evidence": []})
        source = _group_key(group[0], strategy, ignore_case)[1]
        entry["evidence"].append({"strategy": strategy, "key": key, "from": source})

    groups: List[Dict[str, Any]] = []
    for entry in merged.values():
        members: List[Dict[str, Any]] = []
        for symbol in sorted(entry["symbols"], key=lambda s: s["name"]):
            sheets_used = usage.get(symbol["name"], {})
            mpn, mpn_from = _first_property(symbol, MPN_KEYS)
            members.append(
                {
                    "name": symbol["name"],
                    "value": symbol["properties"].get("Value", ""),
                    "footprint": symbol["properties"].get("Footprint", ""),
                    "datasheet": symbol["properties"].get("Datasheet", ""),
                    "description": symbol["properties"].get("Description", ""),
                    "mpn": mpn,
                    "mpnProperty": mpn_from,
                    "extends": symbol["extends"],
                    "pinCount": symbol["pinCount"],
                    "usageCount": sum(sheets_used.values()),
                    "usedIn": sorted(sheets_used),
                }
            )
        keep, reason = _suggest_keep(members)
        groups.append(
            {
                "size": len(members),
                "evidence": sorted(entry["evidence"], key=lambda e: e["strategy"]),
                "matchedBy": sorted({e["strategy"] for e in entry["evidence"]}),
                "members": members,
                "suggestedKeep": keep,
                "keepReason": reason,
                "unusedMembers": [m["name"] for m in members if m["usageCount"] == 0],
            }
        )

    groups.sort(key=lambda g: (-g["size"], g["members"][0]["name"]))
    duplicate_count = sum(g["size"] - 1 for g in groups)

    if not groups:
        message = f"No duplicates found among {len(symbols)} symbol(s)"
    else:
        message = (
            f"{len(groups)} duplicate group(s) covering {duplicate_count} "
            f"redundant symbol(s) out of {len(symbols)}"
        )
        if sheets:
            retirable = sum(len(g["unusedMembers"]) for g in groups)
            message += f"; {retirable} unused across {len(sheets)} sheet(s)"
        else:
            message += "; pass schematicPaths to see which ones are actually used"

    return {
        "success": True,
        "message": message,
        "libraryPath": str(lib_path),
        "symbolCount": len(symbols),
        "sheetsScanned": [s.name for s in sheets],
        "matchBy": list(requested),
        "groupCount": len(groups),
        "duplicateSymbolCount": duplicate_count,
        "groups": groups,
    }
