"""Find symbols that are the same part stored twice in a .kicad_sym library.

Libraries accumulate duplicates the moment more than one source feeds them:
an Eagle import lands the same resistor the curated library already had, a
SnapEDA download arrives under the vendor's naming, someone re-adds a part
because search did not find the existing name. Nothing in KiCad reports this,
because the names differ -- which is exactly why grepping for the name does
not find it either.

Five ways to notice the same part twice, each catching what the others miss:

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

``name``
    Names that differ only in separators: ``R_10K``, ``R-10K``, ``R 10K``. The
    weakest signal -- it finds the copy someone made by retyping a name, and
    little else -- so it is off by default. The decimal point is deliberately
    NOT collapsed: stripping it makes ``C_1.0uF_0805`` and ``C_10uF_0805``, or
    ``R_1.5K`` and ``R_15K``, the same key.

Whichever strategy produced a key, a value that only means "this field was not
filled in" cannot be one: an importer with nothing to write puts ``N/A``,
``TBD`` or ``-`` in the field, and KiCad's own empty marker is ``~``. Those are
rejected, because grouping on them is the failure ``graphics`` has on passives
-- one huge group of unrelated parts -- happening under the defaults.

Usage counts from the project's schematics turn the report into a decision:
the duplicate that nothing instantiates is the one to retire. Two things make
those counts mean what they say. Placements are attributed by library and not
by bare symbol name, so this library's ``R`` does not inherit the fifty
placements of ``Device:R``; and a sub-sheet instantiated four times counts
four times, as KiCad's own netlist has it.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

from utils.duplicate_strategies import DEFAULT_DUPLICATE_STRATEGIES, DUPLICATE_STRATEGIES
from utils.sexpr_format import (
    QUOTED_VALUE,
    iter_child_offsets,
    match_paren,
    unescape_sexpr_string,
)

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
_LIB_ID = re.compile(r"\(lib_id\s+" + QUOTED_VALUE)
_WHITESPACE = re.compile(r"\s+")

# Values that say "this field was not filled in" rather than naming anything.
# Eagle and Altium importers and hand entry write these into MPN and Value
# fields; ``~`` is KiCad's own empty-field marker.
PLACEHOLDER_VALUES = frozenset({"", "~", "-", "--", "N/A", "NA", "NONE", "TBD", "?", "X"})

# eeschema writes ``_autosave-<sheet>.kicad_sch`` beside the real sheet while a
# project is open and leaves it there after a crash; KiCad's backup archives
# unpack into ``<project>-backups``; editors keep their own copies in dot
# directories (the library this was developed against has 15 sheets under
# ``.history`` beside 20 real ones). Each is a complete copy of a sheet that is
# already being scanned, so counting them multiplies every usage count.
_AUTOSAVE_PREFIX = "_autosave-"

# A hierarchy of N sheets can in principle have exponentially many instance
# paths. Real designs have a handful; this only stops a pathological or
# malformed one from walking forever.
_MAX_SHEET_WALK = 100_000

_TABLE_NAME = re.compile(r"\(\s*name\s+" + QUOTED_VALUE + r"\s*\)")
_TABLE_URI = re.compile(r"\(\s*uri\s+" + QUOTED_VALUE + r"\s*\)")


def _norm_key(name: str) -> str:
    """Collapse a property name so MANUFACTURER PART NUMBER == Manufacturer_Part-Number."""
    return re.sub(r"[\s_\-.#]+", "", name).upper()


def _is_placeholder(value: str) -> bool:
    """True if *value* only means the field was left blank.

    Grouping on a placeholder is what makes ``graphics`` useless on passives --
    one enormous group of unrelated parts -- except that it happens under the
    default strategies, where it cannot be opted out of. Six parts with nothing
    in common but ``(property "MPN" "N/A")`` are not the same part.
    """
    return value.strip().upper() in PLACEHOLDER_VALUES


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
    """Return (value, property name) for the first of *keys* holding a real value.

    A field filled in with a placeholder is skipped rather than returned, so a
    symbol whose ``MPN`` is ``N/A`` and whose ``PART NUMBER`` is a real part
    number matches on the real one.
    """
    for key in keys:
        value = symbol["normalized"].get(key, "").strip()
        if _is_placeholder(value):
            continue
        original = next(
            (k for k in symbol["properties"] if _norm_key(k) == key),
            key,
        )
        return value, original
    return "", ""


def _read_sheet_references(text: str) -> List[str]:
    """The Sheetfile of every ``(sheet ...)`` block, once per instantiation.

    Repeats are the point: a four-channel design has four ``(sheet ...)``
    blocks naming one file, and that file's contents exist four times.
    """
    root = _HEAD.search(text)
    if not root:
        return []
    refs: List[str] = []
    for off in iter_child_offsets(text[root.start() :]):
        off += root.start()
        head = _HEAD.match(text, off)
        if not head or head.group(1) != "sheet":
            continue
        end = match_paren(text, off)
        if end == -1:
            continue
        block = text[off : end + 1]
        for child in iter_child_offsets(block):
            child_head = _HEAD.match(block, child)
            if not child_head or child_head.group(1) != "property":
                continue
            key, after = _read_string(block, child_head.end())
            # KiCad 7 wrote "Sheetfile", 8+ writes "Sheet file"; _norm_key
            # makes them the same lookup.
            if key and _norm_key(key) == "SHEETFILE":
                value, _ = _read_string(block, after)
                if value:
                    refs.append(value)
                break
    return refs


def _sheet_instance_counts(texts: Dict[Path, str]) -> Dict[Path, int]:
    """How many times each scanned sheet file is instantiated in the hierarchy.

    A sheet file reused by four ``(sheet ...)`` blocks holds four of every part
    drawn on it, which is what KiCad's netlist and BOM report. Counting sheet
    files instead of instances undercounts every part on a reused sheet.

    A file no other scanned sheet references is a root and counts once, so a
    flat design and an unrelated pile of sheets both come out as 1 each --
    exactly the previous behaviour.
    """
    children: Dict[Path, List[Path]] = {}
    referenced: Set[Path] = set()
    for path, text in texts.items():
        kids: List[Path] = []
        for ref in _read_sheet_references(text):
            try:
                target = (path.parent / ref).resolve()
            except OSError:
                continue
            if target in texts:
                kids.append(target)
                referenced.add(target)
        children[path] = kids

    counts: Dict[Path, int] = dict.fromkeys(texts, 0)
    stack = [(path, frozenset()) for path in texts if path not in referenced]
    steps = 0
    while stack:
        path, on_path = stack.pop()
        if path in on_path:  # a sheet cycle; KiCad rejects these, files can hold them
            continue
        steps += 1
        if steps > _MAX_SHEET_WALK:
            logger.warning(
                "Sheet hierarchy has more than %d instance paths; usage counts "
                "fall back to one per sheet file",
                _MAX_SHEET_WALK,
            )
            return dict.fromkeys(texts, 1)
        counts[path] += 1
        deeper = on_path | {path}
        stack.extend((kid, deeper) for kid in children[path])
    # A sheet reachable only through a cycle would otherwise count zero times.
    return {path: max(count, 1) for path, count in counts.items()}


def _nicknames_from_table(table: Path, lib_path: Path) -> Set[str]:
    """Nicknames in one ``sym-lib-table`` whose uri is *lib_path*."""
    try:
        text = table.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read %s: %s", table, e)
        return set()
    root = _HEAD.search(text)
    if not root:
        return set()
    found: Set[str] = set()
    for off in iter_child_offsets(text[root.start() :]):
        off += root.start()
        head = _HEAD.match(text, off)
        if not head or head.group(1) != "lib":
            continue
        end = match_paren(text, off)
        if end == -1:
            continue
        block = text[off : end + 1]
        name = _TABLE_NAME.search(block)
        uri = _TABLE_URI.search(block)
        if not name or not uri:
            continue
        # ${KIPRJMOD} is the directory holding the table. Any other variable
        # points somewhere this code cannot resolve (a stock library path), and
        # an unresolved one must not be compared as a literal.
        expanded = unescape_sexpr_string(uri.group(1)).replace("${KIPRJMOD}", str(table.parent))
        if "${" in expanded or "$(" in expanded:
            continue
        try:
            if Path(expanded).resolve() == lib_path:
                found.add(unescape_sexpr_string(name.group(1)))
        except OSError:
            continue
    return found


def resolve_library_nicknames(
    lib_path: Path,
    sheets: Sequence[Path],
    override: Any = None,
) -> Set[str]:
    """The nicknames under which *lib_path* may legitimately appear in a lib_id.

    The nickname is whatever ``sym-lib-table`` chose to call the library, which
    is not always the file name -- so the table beside each scanned sheet is
    read and every entry resolving to this file contributes its name. The file
    stem is accepted too, because it is what KiCad proposes when a library is
    added and therefore what most tables say.

    *override* wins outright when given: it is the escape hatch for a library
    registered under a name no scanned project's table mentions.
    """
    if isinstance(override, str):
        override = [override]
    chosen = {n.strip() for n in (override or ()) if isinstance(n, str) and n.strip()}
    if chosen:
        return chosen

    chosen.add(lib_path.stem)
    try:
        target = lib_path.resolve()
    except OSError:
        return chosen
    for directory in dict.fromkeys(sheet.parent for sheet in sheets):
        table = directory / "sym-lib-table"
        if table.is_file():
            chosen |= _nicknames_from_table(table, target)
    return chosen


class ScanResult(NamedTuple):
    """Sheets to scan, what to call them in the report, and what did not exist."""

    sheets: List[Path]
    labels: Dict[Path, str]
    missing: List[str]


def _iter_schematics(paths: Iterable[str]) -> ScanResult:
    """Expand a mix of .kicad_sch files and directories into sheets to scan.

    Autosave sheets and backup locations are skipped during directory expansion,
    since they duplicate sheets already in the list. A path named explicitly is
    always honoured -- naming one is a deliberate act.

    Inputs that resolve to nothing are collected rather than dropped: a typo in
    a directory name used to produce an empty scan and a report that confidently
    said every symbol was unused.
    """
    sheets: List[Path] = []
    labels: Dict[Path, str] = {}
    missing: List[str] = []
    seen: Set[Path] = set()

    def add(sheet: Path, label: str) -> None:
        try:
            resolved = sheet.resolve()
        except OSError as e:
            logger.warning("Could not resolve %s: %s", sheet, e)
            return
        if resolved in seen:
            return
        seen.add(resolved)
        sheets.append(resolved)
        labels[resolved] = label

    for raw in paths:
        path = Path(str(raw))
        if path.is_dir():
            for sheet in sorted(path.rglob("*.kicad_sch")):
                if sheet.name.startswith(_AUTOSAVE_PREFIX):
                    continue
                relative = sheet.relative_to(path)
                if any(
                    part.startswith(".") or part.endswith("-backups")
                    for part in relative.parts[:-1]
                ):
                    continue
                # Labelled by path below the scanned root, not by basename:
                # a project with analog/power.kicad_sch and
                # digital/power.kicad_sch has two different sheets.
                add(sheet, relative.as_posix())
        elif path.is_file():
            add(path, path.name)
        else:
            missing.append(str(path))
    return ScanResult(sheets, labels, missing)


class SymbolUsage(NamedTuple):
    """Instance counts per symbol, and the evidence for how they were attributed."""

    counts: Dict[str, Dict[str, int]]
    nicknames_seen: List[str]
    sheet_instances: Dict[str, int]


def count_symbol_usage(
    sheets: Sequence[Path],
    nicknames: Optional[Iterable[str]] = None,
    labels: Optional[Dict[Path, str]] = None,
) -> SymbolUsage:
    """Count placed instances of one library's symbols, per sheet.

    A lib_id names the library it came from, and that half cannot be discarded.
    Bare names collide with the stock libraries constantly -- ``R``, ``C``,
    ``D``, ``LED``, ``GND`` -- so crediting the fifty placements of ``Device:R``
    to this library's ``R`` reports the symbol nothing references as the popular
    one, and then recommends retiring the only copy anything actually places.

    Only nicknames in *nicknames* are counted; pass nothing to count every
    nickname, which is name-only matching and cannot distinguish libraries. The
    nicknames actually encountered come back in the result, so a library
    registered under a name the caller did not expect is visible rather than
    silently reported as unused.

    A lib_id with no nickname at all is counted by name: that is all the
    information the file carries about it.

    Instances of a sub-sheet are counted per instantiation, so a sheet file used
    by four ``(sheet ...)`` blocks contributes four of every part on it.
    """
    accepted = {n.strip().upper() for n in (nicknames or ()) if n and n.strip()}
    labels = labels or {}

    texts: Dict[Path, str] = {}
    for sheet in sheets:
        try:
            texts[sheet] = sheet.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Could not read %s: %s", sheet, e)
    instances = _sheet_instance_counts(texts)

    usage: Dict[str, Dict[str, int]] = {}
    seen: Set[str] = set()
    for sheet, text in texts.items():
        label = labels.get(sheet, sheet.name)
        weight = instances.get(sheet, 1)
        # Only placed instances carry (lib_id ...); the lib_symbols cache keys
        # its entries by the id itself, so counting lib_id counts placements.
        for m in _LIB_ID.finditer(text):
            lib_id = unescape_sexpr_string(m.group(1))
            nickname, separator, symbol_name = lib_id.partition(":")
            if not separator:  # no nickname at all; the id is the symbol name
                nickname, symbol_name = "", nickname
            if nickname:
                seen.add(nickname)
                if accepted and nickname.upper() not in accepted:
                    continue
            per_sheet = usage.setdefault(symbol_name, {})
            per_sheet[label] = per_sheet.get(label, 0) + weight

    return SymbolUsage(
        usage,
        sorted(seen),
        {labels.get(path, path.name): count for path, count in instances.items() if count > 1},
    )


def _group_key(symbol: Dict[str, Any], strategy: str, ignore_case: bool) -> Tuple[str, str]:
    """Return (key, provenance) for one symbol under one strategy; '' means skip."""
    if strategy == "mpn":
        value, source = _first_property(symbol, MPN_KEYS)
    elif strategy == "supplier":
        value, source = _first_property(symbol, SUPPLIER_KEYS)
    elif strategy == "value_footprint":
        value_field = symbol["normalized"].get("VALUE", "").strip()
        footprint = symbol["normalized"].get("FOOTPRINT", "").strip()
        if _is_placeholder(value_field) or _is_placeholder(footprint):
            return "", ""
        value, source = f"{value_field} @ {footprint}", "Value + Footprint"
    elif strategy == "graphics":
        value, source = symbol["fingerprint"], "body"
    elif strategy == "name":
        # Separators are noise; the decimal point is not. Collapsing it makes
        # C_1.0uF_0805 and C_10uF_0805 -- and R_1.5K and R_15K -- one key.
        value = re.sub(r"[\s_\-]+", "", symbol["name"])
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
    else:
        # best is the maximum by usageCount, so zero here means every member is
        # unused and the field-completeness tie-break is what decided it.
        reason = "none are used; most complete fields"
    return best["name"], reason


def find_duplicate_symbols(params: Dict[str, Any]) -> Dict[str, Any]:
    """Group symbols in a library that look like the same part stored twice.

    Each group is one connected set of symbols with every strategy that linked
    any of them attached as evidence, so no symbol appears in two groups and
    ``duplicateSymbolCount`` never exceeds ``symbolCount - groupCount``.

    ``usageCount`` counts placements of THIS library's symbols only, decided by
    the lib_id nickname (see :func:`count_symbol_usage`), and counts a reused
    sub-sheet once per instantiation. ``libraryNicknames`` and ``nicknamesSeen``
    in the result show how that attribution was made; ``missingPaths`` lists any
    ``schematicPaths`` entry that does not exist, so an empty scan is never
    mistaken for an unused library.
    """
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
    try:
        min_group_size = max(2, int(params.get("minGroupSize", 2)))
    except (TypeError, ValueError):
        return {
            "success": False,
            "message": (
                "minGroupSize must be a whole number, got " f"{params.get('minGroupSize')!r}"
            ),
        }

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

    requested_paths = params.get("schematicPaths") or []
    if isinstance(requested_paths, str):
        requested_paths = [requested_paths]
    scan = _iter_schematics(requested_paths)
    nicknames = resolve_library_nicknames(lib_path, scan.sheets, params.get("libraryNicknames"))
    usage = count_symbol_usage(scan.sheets, nicknames, scan.labels)

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

    # A pair of symbols usually trips more than one strategy, and the member
    # sets need not nest neatly: A and B can share an MPN while A, B and C share
    # a Value and a Footprint. Merging on the exact member set made {A,B} and
    # {A,B,C} two separate groups -- so a caller iterating groups handled A and
    # B twice, and three of three symbols were called redundant. Merging by
    # connected component gives the one entry per real duplicate the report
    # promises, and makes the redundant count right by construction.
    parent: Dict[str, str] = {}

    def find(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for group in buckets.values():
        root_name = find(group[0]["name"])
        for symbol in group[1:]:
            other = find(symbol["name"])
            if other != root_name:
                parent[other] = root_name

    merged: Dict[str, Dict[str, Any]] = {}
    for (strategy, key), group in buckets.items():
        entry = merged.setdefault(find(group[0]["name"]), {"symbols": {}, "evidence": []})
        entry["symbols"].update({s["name"]: s for s in group})
        source = _group_key(group[0], strategy, ignore_case)[1]
        entry["evidence"].append({"strategy": strategy, "key": key, "from": source})

    groups: List[Dict[str, Any]] = []
    for entry in merged.values():
        members: List[Dict[str, Any]] = []
        for symbol in sorted(entry["symbols"].values(), key=lambda s: s["name"]):
            sheets_used = usage.counts.get(symbol["name"], {})
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
                "evidence": sorted(entry["evidence"], key=lambda e: (e["strategy"], e["key"])),
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
        if scan.sheets:
            retirable = sum(len(g["unusedMembers"]) for g in groups)
            message += f"; {retirable} unused across {len(scan.sheets)} sheet(s)"
        elif requested_paths:
            # Saying "pass schematicPaths" to someone who did is how a typo'd
            # directory became a report claiming every symbol was retirable.
            message += (
                f"; none of the {len(requested_paths)} schematicPaths given exist, so "
                "no usage could be counted and no symbol should be retired on the "
                "strength of this report"
            )
        else:
            message += "; pass schematicPaths to see which ones are actually used"

    if scan.sheets and not usage.counts and usage.nicknames_seen:
        # Every placement named some other library. Either this library is
        # registered under a nickname no scanned sym-lib-table mentions, or the
        # sheets genuinely belong to another project -- both of which would
        # otherwise read as "nothing here is used".
        message += (
            f"; nothing in the scanned sheets references {'/'.join(sorted(nicknames))}, "
            f"so no usage was attributed to this library (nicknames seen: "
            f"{', '.join(usage.nicknames_seen)}) -- pass libraryNicknames if it is "
            "registered under a different name"
        )

    return {
        "success": True,
        "message": message,
        "libraryPath": str(lib_path),
        "symbolCount": len(symbols),
        "sheetsScanned": [scan.labels.get(s, s.name) for s in scan.sheets],
        "missingPaths": scan.missing,
        "libraryNicknames": sorted(nicknames),
        "nicknamesSeen": usage.nicknames_seen,
        "sheetInstances": usage.sheet_instances,
        "matchBy": list(requested),
        "groupCount": len(groups),
        "duplicateSymbolCount": duplicate_count,
        "groups": groups,
    }
