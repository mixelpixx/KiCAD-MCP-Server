"""Symbol instance entries: one per use of a sheet, each with its own reference.

KiCad records a placed symbol's reference per use of its sheet. Inside the
symbol, ``(instances (project "<name>" (path "<instance path>" (reference "R1")
(unit 1)) ...))`` holds one ``(path ...)`` entry for every use. The
complex_hierarchy demo that ships with KiCad places ampli_ht.kicad_sch twice,
and its potentiometer is RV201 in one use and RV301 in the other.

A symbol with a single entry on a sheet used twice has no reference of its own
in the second use: with KiCad 10.0.5, ``kicad-cli sch export netlist`` reports
"schematic has annotation errors", one part drops out of the netlist and
another appears twice, while ERC reports nothing (#428). So a placement needs
an entry for every use, and each entry needs a reference that no other part in
the project has.

``references_for_new_symbol`` serves ``create_component_instance``, and
``add_missing_instances`` serves ``fix_subsheet_instances``, which runs when a
sheet is linked into the hierarchy.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from utils.file_io import read_text_preserve_newline, write_text_atomic
from utils.sexpr_format import (
    QUOTED_VALUE,
    escape_sexpr_string,
    iter_child_offsets,
    match_paren,
    unescape_sexpr_string,
)
from utils.sheet_tree import _real_key, instance_paths, project_name, sheet_info

_NUMBERED = re.compile(r"^(.*?)(\d+)$")
_SYMBOL_HEAD = re.compile(r"\(symbol[\s(]")
_LIB_ID_HEAD = re.compile(r"\(lib_id[\s(]")
_INSTANCES_HEAD = re.compile(r"\(instances[\s(]")
_PROJECT_HEAD = re.compile(rf"\(project\s+{QUOTED_VALUE}")
_PATH_HEAD = re.compile(rf"\(path\s+{QUOTED_VALUE}")
_REFERENCE = re.compile(rf"\(reference\s+{QUOTED_VALUE}\s*\)")
_UNIT = re.compile(r"\(unit\s+(\d+)\s*\)")
_REFERENCE_FIELD = re.compile(rf'\(property\s+"Reference"\s+{QUOTED_VALUE}')


class ReferenceAllocator:
    """Hands out references that no part in the project uses yet."""

    def __init__(self, used: Iterable[str]) -> None:
        self._numbers: Dict[str, Set[int]] = {}
        for reference in used:
            self.take(reference)

    def take(self, reference: str) -> None:
        """Mark *reference* as used."""
        m = _NUMBERED.match(reference)
        if m:
            self._numbers.setdefault(m.group(1), set()).add(int(m.group(2)))

    def next_for(self, reference: str) -> str:
        """The first unused number with *reference*'s prefix.

        That is what KiCad's annotator does by default ("use first free
        number"). A reference without a number, such as ``R?``, is returned
        as it is. KiCad numbers power symbols with a leading zero (#PWR01),
        and the zero is kept.
        """
        m = _NUMBERED.match(reference)
        if not m:
            return reference
        prefix, digits = m.groups()
        numbers = self._numbers.setdefault(prefix, set())
        n = 1
        while n in numbers:
            n += 1
        numbers.add(n)
        zero = "0" if len(digits) > 1 and digits.startswith("0") else ""
        return f"{prefix}{zero}{n}"


def project_references(root: Optional[Path], sheet: Path) -> Set[str]:
    """Every reference used in the project: all sheets *root* reaches.

    Only *sheet* when there is no root. Walks the cached ``sheet_info`` rather
    than ``sheet_tree``, which re-reads every file: on KiCad's vme-wren demo
    (37 sheets, 21 MB) that is 10 ms instead of 1.7 s per placement.
    """
    used: Set[str] = set()
    queue: List[Path] = [root if root is not None else Path(sheet)]
    seen: Set[str] = set()
    while queue:
        current = queue.pop()
        key = _real_key(current)
        if key in seen:
            continue
        seen.add(key)
        info = sheet_info(current)
        if info is None:
            continue
        used.update(info.references)
        if root is not None:
            queue.extend(current.parent / name for _, name in info.sub_sheets)
    return used


class _Entry(NamedTuple):
    """One ``(path ...)`` entry; offsets are into the symbol block."""

    path: str
    reference: str
    unit: str
    start: int
    end: int


def _placed_symbols(text: str) -> List[Tuple[int, int]]:
    """Spans of the placed symbols in a schematic, not the lib_symbols definitions."""
    spans: List[Tuple[int, int]] = []
    for offset in iter_child_offsets(text):
        if not _SYMBOL_HEAD.match(text, offset):
            continue
        end = match_paren(text, offset)
        if end == -1:
            continue
        block = text[offset : end + 1]
        if any(_LIB_ID_HEAD.match(block, child) for child in iter_child_offsets(block)):
            spans.append((offset, end + 1))
    return spans


def _project_entries(block: str, project: str) -> Optional[List[_Entry]]:
    """The ``(path ...)`` entries of *block*'s ``(project ...)`` for *project*.

    Falls back to the first project entry when none has that name, as the
    previous fixer did. None when the symbol has no instance data at all.
    """
    for inst in iter_child_offsets(block):
        if not _INSTANCES_HEAD.match(block, inst):
            continue
        inst_end = match_paren(block, inst)
        if inst_end == -1:
            return None
        inst_block = block[inst : inst_end + 1]
        chosen: Optional[Tuple[int, int]] = None
        for offset in iter_child_offsets(inst_block):
            m = _PROJECT_HEAD.match(inst_block, offset)
            if not m:
                continue
            span = (inst + offset, inst + match_paren(inst_block, offset) + 1)
            if unescape_sexpr_string(m.group(1)) == project:
                chosen = span
                break
            if chosen is None:
                chosen = span
        if chosen is None:
            return None
        project_block = block[chosen[0] : chosen[1]]
        entries: List[_Entry] = []
        for offset in iter_child_offsets(project_block):
            m = _PATH_HEAD.match(project_block, offset)
            if not m:
                continue
            end = match_paren(project_block, offset) + 1
            entry = project_block[offset:end]
            ref = _REFERENCE.search(entry)
            unit = _UNIT.search(entry)
            entries.append(
                _Entry(
                    path=unescape_sexpr_string(m.group(1)),
                    reference=unescape_sexpr_string(ref.group(1)) if ref else "",
                    unit=unit.group(1) if unit else "1",
                    start=chosen[0] + offset,
                    end=chosen[0] + end,
                )
            )
        return entries
    return None


def _base_reference(entries: List[_Entry], paths: List[str], block: str) -> str:
    """The part's reference in its first use; what identifies it across uses."""
    by_path = {e.path: e for e in entries}
    for path in paths:
        if path in by_path and by_path[path].reference:
            return by_path[path].reference
    if entries and entries[0].reference:
        return entries[0].reference
    m = _REFERENCE_FIELD.search(block)
    return unescape_sexpr_string(m.group(1)) if m else ""


class _Numbering:
    """References for the uses of one sheet, shared by the units of a part.

    Units of one part are separate symbols with the same reference, and they
    must share a reference in every use too: unit A as U2 and unit B as U3 in
    the second use would split one package into two.
    """

    def __init__(
        self, text: str, paths: List[str], project: str, allocator: ReferenceAllocator
    ) -> None:
        self._allocator = allocator
        self._known: Dict[Tuple[str, str], str] = {}
        for start, end in _placed_symbols(text):
            block = text[start:end]
            entries = _project_entries(block, project)
            if not entries:
                continue
            base = _base_reference(entries, paths, block)
            for entry in entries:
                if entry.path in paths and entry.reference:
                    self._known.setdefault((entry.path, base), entry.reference)

    def reference_at(self, path: str, base: str) -> str:
        """The reference the part known as *base* has, or gets, in *path*."""
        key = (path, base)
        if key not in self._known:
            self._known[key] = self._allocator.next_for(base)
        return self._known[key]


def references_for_new_symbol(sheet: Path, reference: str, project: str) -> List[Tuple[str, str]]:
    """``(instance path, reference)`` for each use of *sheet*, for a new symbol.

    The first use gets *reference*. Each other use gets the reference another
    unit of the same part already has there, or else the first number with the
    same prefix that no part in the project uses.
    """
    root, paths = instance_paths(sheet)
    if len(paths) == 1:
        return [(paths[0], reference)]
    text, _newline = read_text_preserve_newline(Path(sheet))
    allocator = ReferenceAllocator(project_references(root, sheet))
    allocator.take(reference)
    numbering = _Numbering(text, paths, project, allocator)
    return [(paths[0], reference)] + [
        (path, numbering.reference_at(path, reference)) for path in paths[1:]
    ]


def instance_report(placed: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Response fields for a part placed on a sheet used more than once, else {}.

    The references for the other uses come from the project's free numbers,
    so the caller has to see them to avoid giving them to other parts.
    """
    if len(placed) < 2:
        return {}
    references = ", ".join(reference for _path, reference in placed)
    return {
        "instances": [{"path": path, "reference": reference} for path, reference in placed],
        "instances_note": (
            f"This sheet is used {len(placed)} times, and KiCad gives a part a "
            f"reference in each use: {references}, in sheet order. Do not give "
            "these references to other parts."
        ),
    }


def _entry_text(template: str, path: str, reference: str, unit: str) -> str:
    """A copy of the *template* entry with its path, reference and unit replaced."""
    text = _PATH_HEAD.sub(lambda _m: f'(path "{escape_sexpr_string(path)}"', template, count=1)
    text = _REFERENCE.sub(
        lambda _m: f'(reference "{escape_sexpr_string(reference)}")', text, count=1
    )
    return _UNIT.sub(lambda _m: f"(unit {unit})", text, count=1)


def _with_entries(block: str, entries: List[_Entry], new: List[Tuple[str, str, str]]) -> str:
    """*block* with *new* ``(path, reference, unit)`` entries after its last one.

    Each new entry copies an existing one, so the file keeps its own layout:
    KiCad's one-token-per-line form or this server's compact one.
    """
    last = entries[-1]
    template = block[entries[0].start : entries[0].end]
    line_start = block.rfind("\n", 0, last.start) + 1
    indent = block[line_start : last.start]
    separator = "\n" + indent if not indent.strip() else " "
    added = "".join(separator + _entry_text(template, *entry) for entry in new)
    return block[: last.end] + added + block[last.end :]


def add_missing_instances(sheets: Iterable[Path]) -> List[str]:
    """Give every placed symbol in *sheets* an entry for each use of its sheet.

    For a sheet that was just linked into the hierarchy. A symbol placed while
    its sheet was unlinked carries a one-level ``/<sheet-uuid>`` path; it keeps
    its reference in its first real use. A symbol placed before its sheet's
    second use existed has one entry; the new use gets a reference of its own.
    Existing entries are never changed or removed (KiCad drops stale ones when
    it saves). A sheet no root reaches is left alone. Returns the files
    rewritten.
    """
    modified: List[str] = []
    allocators: Dict[str, ReferenceAllocator] = {}
    for sheet in sheets:
        root, paths = instance_paths(sheet)
        if root is None:
            continue
        project = project_name(sheet)
        text, newline = read_text_preserve_newline(Path(sheet))
        root_key = _real_key(root)
        if root_key not in allocators:
            allocators[root_key] = ReferenceAllocator(project_references(root, sheet))
        numbering = _Numbering(text, paths, project, allocators[root_key])

        edits: List[Tuple[int, int, str]] = []
        for start, end in _placed_symbols(text):
            block = text[start:end]
            entries = _project_entries(block, project)
            if not entries:
                continue
            present = {e.path for e in entries}
            missing = [p for p in paths if p not in present]
            if not missing:
                continue
            base = _base_reference(entries, paths, block)
            linked = any(p in present for p in paths)
            unit = next((e.unit for e in entries if e.path in paths), entries[0].unit)
            new: List[Tuple[str, str, str]] = []
            for path in missing:
                if not linked and path == missing[0]:
                    reference = base  # the part's first real use keeps its reference
                else:
                    reference = numbering.reference_at(path, base)
                new.append((path, reference, unit))
            edits.append((start, end, _with_entries(block, entries, new)))

        if edits:
            for start, end, block in reversed(edits):
                text = text[:start] + block + text[end:]
            write_text_atomic(Path(sheet), text, newline)
            modified.append(str(sheet))
    return modified
