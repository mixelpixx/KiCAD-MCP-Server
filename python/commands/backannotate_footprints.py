"""Copy footprint assignments from a board back into its schematic.

``sync_schematic_to_board`` pushes the schematic onto the PCB. There was no way
back, and after a layout pass the board is the side that is right: footprints
get swapped in pcbnew, and an Eagle import lands with schematic-side footprint
fields that never matched the placed parts. Recovering meant parsing
``.kicad_pcb`` by hand and editing each ``(property "Footprint" ...)``.

Matching is by reference designator, the same key ``sync_schematic_to_board``
uses. References beginning with ``#`` are power and other virtual symbols; they
carry no footprint and are skipped. Multi-unit symbols appear as several
instance blocks sharing one reference and all of them are updated, because
KiCad treats a disagreement between units as a conflict.

Nesting is tracked structurally rather than by indentation: KiCad's writers
emit board files whose indentation does not always match depth.

Tools:
  - backannotate_footprints: PCB footprint assignments -> schematic instances
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.sexpr_format import (
    QUOTED_VALUE,
    escape_sexpr_string,
    iter_child_offsets,
    match_paren,
    unescape_sexpr_string,
)

logger = logging.getLogger("kicad_interface")

# Power, ground and other virtual symbols. They have no physical part, and
# KiCad leaves their Footprint field empty on purpose.
_VIRTUAL_REFERENCE = re.compile(r"^#")

_PROPERTY_HEAD = re.compile(rf"\(property\s+{QUOTED_VALUE}\s+{QUOTED_VALUE}")

_FOOTPRINT_HEAD = re.compile(rf"\(footprint\s+{QUOTED_VALUE}")

_INSTANCE_HEAD = re.compile(r"\(symbol[\s(]")

# KiCad 6+ stores a footprint's designator as a property; KiCad 5 used fp_text.
_FP_TEXT_REFERENCE = re.compile(rf"\(fp_text\s+reference\s+{QUOTED_VALUE}")


def _read(path: Path, kind: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not path.exists():
        return None, {"success": False, "message": f"{kind} not found: {path}"}
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, {"success": False, "message": f"Could not read {path}: {exc}"}


def _properties(block: str) -> Dict[str, Tuple[str, int, int]]:
    """Direct-child properties of a block: name -> (value, start, end)."""
    found: Dict[str, Tuple[str, int, int]] = {}
    for offset in iter_child_offsets(block):
        m = _PROPERTY_HEAD.match(block, offset)
        if not m:
            continue
        end = match_paren(block, offset)
        if end == -1:
            continue
        name = unescape_sexpr_string(m.group(1))
        found.setdefault(name, (unescape_sexpr_string(m.group(2)), offset, end + 1))
    return found


def read_board_footprints(board_text: str) -> Dict[str, str]:
    """Reference designator -> footprint lib id, as placed on the board."""
    placed: Dict[str, str] = {}
    for offset in iter_child_offsets(board_text):
        m = _FOOTPRINT_HEAD.match(board_text, offset)
        if not m:
            continue
        end = match_paren(board_text, offset)
        if end == -1:
            continue
        block = board_text[offset : end + 1]
        props = _properties(block)
        if "Reference" in props:
            reference = props["Reference"][0]
        else:
            legacy = _FP_TEXT_REFERENCE.search(block)
            if not legacy:
                continue
            reference = unescape_sexpr_string(legacy.group(1))
        if reference:
            placed[reference] = unescape_sexpr_string(m.group(1))
    return placed


def _indent_of(block: str, offset: int) -> str:
    line_start = block.rfind("\n", 0, offset) + 1
    prefix = block[line_start:offset]
    return prefix if prefix.strip() == "" else "\t\t"


def _build_footprint_property(value: str, at_text: str, indent: str) -> str:
    inner = indent + ("\t" if "\t" in indent else "  ")
    return "\n".join(
        [
            f'{indent}(property "Footprint" "{escape_sexpr_string(value)}"',
            f"{inner}{at_text}",
            f"{inner}(hide yes)",
            f"{inner}(effects (font (size 1.27 1.27)))",
            f"{indent})",
        ]
    )


def _at_token(block: str, prop_span: Tuple[int, int]) -> str:
    """The ``(at ...)`` of an existing property, so a new field lands with it."""
    prop = block[prop_span[0] : prop_span[1]]
    for offset in iter_child_offsets(prop):
        if prop.startswith("(at ", offset):
            end = match_paren(prop, offset)
            if end != -1:
                return prop[offset : end + 1]
    return "(at 0 0 0)"


def _plan_sheet(
    text: str, placed: Dict[str, str], wanted: Optional[set], add_missing: bool
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Work out the edits for one sheet without applying them."""
    edits: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    # Depth 2 is a direct child of (kicad_sch ...), which is where placed
    # instances live. The lib_symbols cache is a sibling, so its symbol
    # definitions sit a level deeper and are excluded by construction.
    for offset in iter_child_offsets(text, depth=2):
        if not _INSTANCE_HEAD.match(text, offset):
            continue
        end = match_paren(text, offset)
        if end == -1:
            continue
        block = text[offset : end + 1]
        props = _properties(block)
        if "Reference" not in props:
            continue
        reference = props["Reference"][0]
        if _VIRTUAL_REFERENCE.match(reference):
            continue
        if wanted is not None and reference not in wanted:
            continue
        if reference not in placed:
            skipped.append({"reference": reference, "reason": "not on the board"})
            continue

        board_footprint = placed[reference]
        if "Footprint" in props:
            current, prop_start, prop_end = props["Footprint"]
            if current == board_footprint:
                continue
            indent = _indent_of(block, prop_start)
            at_text = _at_token(block, (prop_start, prop_end))
            edits.append(
                {
                    "reference": reference,
                    "from": current,
                    "to": board_footprint,
                    "start": offset + prop_start,
                    "end": offset + prop_end,
                    "text": _build_footprint_property(board_footprint, at_text, indent).lstrip(
                        "\t "
                    ),
                }
            )
        elif add_missing:
            anchor = props.get("Value") or props.get("Reference")
            if anchor is None:
                skipped.append(
                    {"reference": reference, "reason": "no anchor field to insert after"}
                )
                continue
            _, anchor_start, anchor_end = anchor
            indent = _indent_of(block, anchor_start)
            at_text = _at_token(block, (anchor_start, anchor_end))
            edits.append(
                {
                    "reference": reference,
                    "from": None,
                    "to": board_footprint,
                    "start": offset + anchor_end,
                    "end": offset + anchor_end,
                    "text": "\n" + _build_footprint_property(board_footprint, at_text, indent),
                }
            )
        else:
            skipped.append({"reference": reference, "reason": "no Footprint field"})

    return edits, skipped


def _apply(text: str, edits: List[Dict[str, Any]]) -> str:
    """Splice edits in, back to front, so earlier offsets stay valid."""
    for edit in sorted(edits, key=lambda e: e["start"], reverse=True):
        text = text[: edit["start"]] + edit["text"] + text[edit["end"] :]
    return text


def backannotate_footprints(params: Dict[str, Any]) -> Dict[str, Any]:
    """Copy footprint assignments from a .kicad_pcb into its schematic sheets."""
    board_path = Path(params["boardPath"])
    dry_run = bool(params.get("dryRun", False))
    add_missing = bool(params.get("addMissing", True))
    references = params.get("references")
    wanted = set(references) if references else None

    board_text, error = _read(board_path, "Board")
    if error:
        return error
    assert board_text is not None

    placed = read_board_footprints(board_text)
    if not placed:
        return {
            "success": False,
            "message": f"No placed footprints found in {board_path.name}",
        }

    sheet_param = params.get("schematicPath")
    if sheet_param:
        sheets = [Path(sheet_param)]
    else:
        sheets = sorted(board_path.parent.rglob("*.kicad_sch"))
    if not sheets:
        return {
            "success": False,
            "message": f"No .kicad_sch files found next to {board_path.name}",
        }

    changes: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    updated_files: List[str] = []

    for sheet in sheets:
        text, error = _read(sheet, "Schematic")
        if error:
            return error
        assert text is not None

        edits, sheet_skipped = _plan_sheet(text, placed, wanted, add_missing)
        for item in sheet_skipped:
            item["sheet"] = sheet.name
        skipped.extend(sheet_skipped)
        if not edits:
            continue

        for edit in edits:
            changes.append(
                {
                    "sheet": sheet.name,
                    "reference": edit["reference"],
                    "from": edit["from"],
                    "to": edit["to"],
                    "action": "added" if edit["from"] is None else "updated",
                }
            )

        if not dry_run:
            try:
                sheet.write_text(_apply(text, edits), encoding="utf-8")
            except OSError as exc:
                return {"success": False, "message": f"Could not write {sheet}: {exc}"}
            updated_files.append(str(sheet))

    verb = "Would update" if dry_run else "Updated"
    if changes:
        message = (
            f"{verb} {len(changes)} footprint field(s) across "
            f"{len({c['sheet'] for c in changes})} sheet(s)"
        )
    else:
        message = "Every schematic footprint field already matches the board"

    return {
        "success": True,
        "message": message,
        "dryRun": dry_run,
        "boardPath": str(board_path),
        "boardFootprintCount": len(placed),
        "sheetsScanned": [s.name for s in sheets],
        "updatedFiles": updated_files,
        "changeCount": len(changes),
        "changes": changes,
        "skipped": skipped,
    }
