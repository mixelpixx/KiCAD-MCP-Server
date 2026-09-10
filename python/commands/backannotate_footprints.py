"""Copy footprint assignments from a board back into its schematic.

``sync_schematic_to_board`` pushes the schematic onto the PCB. There was no way
back, and after a layout pass the board is the side that is right: footprints
get swapped in pcbnew, and an Eagle import lands with schematic-side footprint
fields that never matched the placed parts. Recovering meant parsing
``.kicad_pcb`` by hand and editing each ``(property "Footprint" ...)``.

Matching is by reference designator, the same key ``sync_schematic_to_board``
uses. From KiCad 7 on the designators a symbol actually carries live in its
``(instances ...)`` block, one per sheet instance -- the ``(property
"Reference" ...)`` holds only one of them -- so the candidates for a symbol come
from there, falling back to the property when the block is absent. That matters
for a sub-sheet instantiated more than once: its single ``Footprint`` field is
shared by every instance, so if the board disagrees between them nothing is
written and a ``conflicts`` entry names the references and the footprints.

References beginning with ``#`` are power and other virtual symbols; they carry
no footprint and are skipped. Multi-unit symbols appear as several instance
blocks sharing one reference and all of them are updated, because KiCad treats a
disagreement between units as a conflict.

Updating an existing field replaces only the quoted value token, so ``hide``,
``show_name``, ``unlocked``, justification, font and the field's exact layout
survive untouched -- the file stays byte-identical to what eeschema would write
apart from the value. Only the ``addMissing`` insertion path builds a field from
scratch, because there is no existing state to keep.

Sheets are found by walking the real sheet tree from the root schematic beside
the board, so local history, backup copies and unrelated projects under the same
directory are never rewritten.

Nesting is tracked structurally rather than by indentation: KiCad's writers
emit board files whose indentation does not always match depth.

Tools:
  - backannotate_footprints: PCB footprint assignments -> schematic instances
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

from utils.file_io import read_text_preserve_newline as _read_text
from utils.file_io import write_text_atomic as _write_text
from utils.sexpr_format import (
    QUOTED_VALUE,
    escape_sexpr_string,
    iter_child_offsets,
    match_paren,
    unescape_sexpr_string,
)
from utils.sheet_tree import _real_key
from utils.sheet_tree import sheet_tree as _sheet_tree

logger = logging.getLogger("kicad_interface")

# Power, ground and other virtual symbols. They have no physical part, and
# KiCad leaves their Footprint field empty on purpose.
_VIRTUAL_REFERENCE = re.compile(r"^#")

_PROPERTY_HEAD = re.compile(rf"\(property\s+{QUOTED_VALUE}\s+{QUOTED_VALUE}")

_FOOTPRINT_HEAD = re.compile(rf"\(footprint\s+{QUOTED_VALUE}")

_INSTANCE_HEAD = re.compile(r"\(symbol[\s(]")

# '(sheet ' only -- '(sheet_instances' is a different list at the same depth.

_REFERENCE_TOKEN = re.compile(rf"\(reference\s+{QUOTED_VALUE}")

# KiCad 6+ stores a footprint's designator as a property; KiCad 5 used fp_text.
_FP_TEXT_REFERENCE = re.compile(rf"\(fp_text\s+reference\s+{QUOTED_VALUE}")


def _read(path: Path, kind: str) -> Tuple[Optional[str], str, Optional[Dict[str, Any]]]:
    """Text and newline style of *path*, or an error payload."""
    if not path.exists():
        return None, "\n", {"success": False, "message": f"{kind} not found: {path}"}
    try:
        text, newline = _read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        return None, "\n", {"success": False, "message": f"Could not read {path}: {exc}"}
    return text, newline, None


class _Property(NamedTuple):
    """One ``(property "name" "value" ...)`` list located inside a block.

    ``value_start``/``value_end`` bound the escaped value *between* its quotes,
    which is the only span an update is allowed to touch.
    """

    value: str
    start: int
    end: int
    value_start: int
    value_end: int


def _properties(block: str) -> Dict[str, _Property]:
    """Direct-child properties of a block, by name."""
    found: Dict[str, _Property] = {}
    for offset in iter_child_offsets(block):
        m = _PROPERTY_HEAD.match(block, offset)
        if not m:
            continue
        end = match_paren(block, offset)
        if end == -1:
            continue
        name = unescape_sexpr_string(m.group(1))
        found.setdefault(
            name,
            _Property(
                value=unescape_sexpr_string(m.group(2)),
                start=offset,
                end=end + 1,
                value_start=m.start(2),
                value_end=m.end(2),
            ),
        )
    return found


def read_board_placements(board_text: str) -> Dict[str, List[str]]:
    """Reference designator -> every footprint the board gives it, in file order.

    A reference should appear once. When it appears twice the board is what is
    ambiguous, so both are kept for the caller to refuse rather than one of them
    silently overwriting the other.
    """
    placements: Dict[str, List[str]] = {}
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
            reference = props["Reference"].value
        else:
            legacy = _FP_TEXT_REFERENCE.search(block)
            if not legacy:
                continue
            reference = unescape_sexpr_string(legacy.group(1))
        if reference:
            placements.setdefault(reference, []).append(unescape_sexpr_string(m.group(1)))
    return placements


def read_board_footprints(board_text: str) -> Dict[str, str]:
    """Reference designator -> footprint lib id, as placed on the board.

    Duplicated references keep the first placement; use
    :func:`read_board_placements` to see the ambiguity.
    """
    return {reference: values[0] for reference, values in read_board_placements(board_text).items()}


def _indent_of(block: str, offset: int) -> str:
    line_start = block.rfind("\n", 0, offset) + 1
    prefix = block[line_start:offset]
    return prefix if prefix.strip() == "" else "\t\t"


def _build_footprint_property(value: str, at_text: str, indent: str) -> str:
    """A brand-new Footprint field. Only for insertion -- never for an update."""
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


def _instance_references(block: str) -> List[str]:
    """Reference designators from a symbol's ``(instances ...)``, in file order.

    KiCad 7+ keeps one per sheet instance here; the ``Reference`` property is
    only ever one of them, so a sub-sheet placed twice has a second designator
    that exists nowhere else.
    """
    references: List[str] = []
    for offset in iter_child_offsets(block):
        if not block.startswith("(instances", offset):
            continue
        end = match_paren(block, offset)
        if end == -1:
            continue
        instances = block[offset : end + 1]
        for project_offset in iter_child_offsets(instances):
            project_end = match_paren(instances, project_offset)
            if project_end == -1:
                continue
            project = instances[project_offset : project_end + 1]
            for path_offset in iter_child_offsets(project):
                if not project.startswith("(path", path_offset):
                    continue
                path_end = match_paren(project, path_offset)
                if path_end == -1:
                    continue
                path_block = project[path_offset : path_end + 1]
                for token_offset in iter_child_offsets(path_block):
                    m = _REFERENCE_TOKEN.match(path_block, token_offset)
                    if m:
                        references.append(unescape_sexpr_string(m.group(1)))
    return references


def _candidate_references(block: str, props: Dict[str, _Property]) -> List[str]:
    """Every designator the symbol's shared Footprint field speaks for."""
    found = _instance_references(block)
    if not found and "Reference" in props:
        found = [props["Reference"].value]
    ordered: List[str] = []
    for reference in found:
        if reference and reference not in ordered:
            ordered.append(reference)
    return ordered


def _sheets_beside(board_path: Path) -> List[Path]:
    """Fallback when no root schematic is named after the board.

    Non-recursive, which puts ``.history`` and backup directories out of reach by
    construction -- the ``.history``/``backup`` path filter
    ``update_symbol_from_library`` needs for its recursive walk would only ever
    match an ancestor here, and would then exclude the whole project. KiCad's
    autosave copies do sit in the project directory, so those are named out.
    """
    return sorted(
        p
        for p in board_path.parent.glob("*.kicad_sch")
        if not p.name.startswith(("_autosave-", "#auto_saved_"))
    )


def _display(sheet: Path, root_dir: Path) -> str:
    """Project-relative path, so two sheets named ``s.kicad_sch`` differ."""
    try:
        return sheet.relative_to(root_dir).as_posix()
    except ValueError:
        return str(sheet)


class _SheetPlan(NamedTuple):
    sheet: Path
    label: str
    text: str
    newline: str
    edits: List[Dict[str, Any]]


def _plan_sheet(
    text: str,
    placed: Dict[str, str],
    ambiguous: Dict[str, List[str]],
    wanted: Optional[Set[str]],
    add_missing: bool,
    seen: Set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Work out the edits for one sheet without applying them."""
    edits: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

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
        references = [
            r for r in _candidate_references(block, props) if not _VIRTUAL_REFERENCE.match(r)
        ]
        if not references:
            continue
        # Recorded before the filter: what the board has that the schematic does
        # not is a fact about the design, not about this invocation's filter.
        seen.update(references)
        if wanted is not None and not wanted.intersection(references):
            continue

        resolvable: Dict[str, str] = {}
        for reference in references:
            if reference in ambiguous:
                skipped.append(
                    {
                        "reference": reference,
                        "reason": "the board assigns more than one footprint to this reference",
                    }
                )
            elif reference in placed:
                resolvable[reference] = placed[reference]
            elif reference.endswith("?"):
                skipped.append(
                    {"reference": reference, "reason": "not annotated yet -- annotate first"}
                )
            else:
                skipped.append({"reference": reference, "reason": "not on the board"})
        if not resolvable:
            continue

        # One Footprint field serves every instance of the symbol, so the board
        # has to agree about them before anything may be written.
        if len(set(resolvable.values())) > 1:
            conflicts.append(
                {
                    "references": sorted(resolvable),
                    "footprints": sorted(set(resolvable.values())),
                    "reason": (
                        "instances sharing one Footprint field are assigned "
                        "different footprints on the board"
                    ),
                }
            )
            continue
        board_footprint = next(iter(resolvable.values()))
        # Name the change after a designator the board actually knows about, not
        # merely the first one the symbol carries.
        reference = next(iter(resolvable))

        if "Footprint" in props:
            existing = props["Footprint"]
            if existing.value == board_footprint:
                continue
            # Only the quoted value token moves. Rebuilding the field would
            # discard hide, show_name, unlocked, justify and the font the user
            # set, and reflow what eeschema wrote.
            edits.append(
                {
                    "reference": reference,
                    "references": sorted(resolvable),
                    "from": existing.value,
                    "to": board_footprint,
                    "start": offset + existing.value_start,
                    "end": offset + existing.value_end,
                    "text": escape_sexpr_string(board_footprint),
                }
            )
        elif add_missing:
            anchor = props.get("Value") or props.get("Reference")
            if anchor is None:
                skipped.append(
                    {"reference": reference, "reason": "no anchor field to insert after"}
                )
                continue
            indent = _indent_of(block, anchor.start)
            at_text = _at_token(block, (anchor.start, anchor.end))
            edits.append(
                {
                    "reference": reference,
                    "references": sorted(resolvable),
                    "from": None,
                    "to": board_footprint,
                    "start": offset + anchor.end,
                    "end": offset + anchor.end,
                    "text": "\n" + _build_footprint_property(board_footprint, at_text, indent),
                }
            )
        else:
            skipped.append({"reference": reference, "reason": "no Footprint field"})

    return edits, skipped, conflicts


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

    board_text, _newline, error = _read(board_path, "Board")
    if error:
        return error
    assert board_text is not None

    placements = read_board_placements(board_text)
    if not placements:
        return {
            "success": False,
            "message": f"No placed footprints found in {board_path.name}",
        }

    # A reference the board uses twice cannot be back-annotated: there is no
    # single right answer, and picking one writes a possibly-wrong footprint.
    ambiguous = {ref: values for ref, values in placements.items() if len(values) > 1}
    placed = {ref: values[0] for ref, values in placements.items() if ref not in ambiguous}

    conflicts: List[Dict[str, Any]] = [
        {
            "references": [ref],
            "footprints": sorted(set(ambiguous[ref])),
            "reason": "the board has more than one footprint carrying this reference",
        }
        for ref in sorted(ambiguous)
    ]

    warnings: List[str] = []
    root_sheet = board_path.with_suffix(".kicad_sch")
    tree = _sheet_tree(root_sheet) if root_sheet.is_file() else []

    sheet_param = params.get("schematicPath")
    if sheet_param:
        sheets = [Path(sheet_param)]
        if tree and _real_key(sheets[0]) not in {_real_key(p) for p in tree}:
            warnings.append(
                f"{sheet_param} is not part of {root_sheet.name}'s sheet tree; "
                "updating it anyway because it was named explicitly"
            )
    else:
        sheets = tree or _sheets_beside(board_path)
    if not sheets:
        return {
            "success": False,
            "message": f"No .kicad_sch files found next to {board_path.name}",
        }

    root_dir = board_path.parent
    changes: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    updated_files: List[str] = []
    seen: Set[str] = set()

    # Plan every sheet before touching any of them: a write that fails halfway
    # through used to leave the earlier sheets edited and drop the report.
    plans: List[_SheetPlan] = []
    for sheet in sheets:
        label = _display(sheet, root_dir)
        text, newline, error = _read(sheet, "Schematic")
        if error:
            failures.append({"sheet": label, "path": str(sheet), "error": error["message"]})
            continue
        assert text is not None

        edits, sheet_skipped, sheet_conflicts = _plan_sheet(
            text, placed, ambiguous, wanted, add_missing, seen
        )
        for item in sheet_skipped:
            item["sheet"] = label
        skipped.extend(sheet_skipped)
        for item in sheet_conflicts:
            item["sheet"] = label
        conflicts.extend(sheet_conflicts)
        if not edits:
            continue
        plans.append(_SheetPlan(sheet, label, text, newline, edits))
        for edit in edits:
            changes.append(
                {
                    "sheet": label,
                    "reference": edit["reference"],
                    "references": edit["references"],
                    "from": edit["from"],
                    "to": edit["to"],
                    "action": "added" if edit["from"] is None else "updated",
                }
            )

    if not dry_run:
        for plan in plans:
            try:
                _write_text(plan.sheet, _apply(plan.text, plan.edits), plan.newline)
            except OSError as exc:
                logger.error("backannotate_footprints could not write %s: %s", plan.sheet, exc)
                failures.append({"sheet": plan.label, "path": str(plan.sheet), "error": str(exc)})
                continue
            updated_files.append(str(plan.sheet))

    on_board = set(placed) & wanted if wanted is not None else set(placed)
    not_in_schematic = sorted(on_board - seen)

    verb = "Would update" if dry_run else "Updated"
    if changes:
        message = (
            f"{verb} {len(changes)} footprint field(s) across "
            f"{len({c['sheet'] for c in changes})} sheet(s)"
        )
    else:
        message = "Every schematic footprint field already matches the board"
    if conflicts:
        message += f"; {len(conflicts)} conflict(s) left untouched"
    if failures:
        message += f"; {len(failures)} sheet(s) failed"

    return {
        "success": not failures,
        "message": message,
        "dryRun": dry_run,
        "boardPath": str(board_path),
        "boardFootprintCount": len(placements),
        "sheetsScanned": [_display(s, root_dir) for s in sheets],
        "updatedFiles": updated_files,
        "changeCount": len(changes),
        "changes": changes,
        "skipped": skipped,
        "conflicts": conflicts,
        "notInSchematic": not_in_schematic,
        "warnings": warnings,
        "failures": failures,
    }
