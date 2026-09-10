"""Walk a schematic hierarchy from its root sheet.

The design is the set of sheets reachable from the root through ``(sheet ...)``
references, and nothing else. Globbing the project directory for ``*.kicad_sch``
looks equivalent and is not: KiCad's own Local History (``.history/``), the
``.mcp-backups/`` copies this server writes, hand-made backup folders and any
unrelated project below the directory all match the glob. Read as live sheets
they inject nets and parts the design no longer has, and whichever copy sorts
last overwrites the live sheet's nets (#400 -- 25 wrong pad nets on a real
board). Rewritten as live sheets they destroy the fallback at the moment the
risky edit happens (#365).

Shared by ``backannotate_footprints`` (writes) and ``sync_schematic_to_board``
(reads); anything that needs "the sheets of this design" should use it too.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Set

from utils.file_io import read_text_preserve_newline
from utils.sexpr_format import QUOTED_VALUE, iter_child_offsets, match_paren, unescape_sexpr_string

_SHEET_HEAD = re.compile(r"\(sheet[\s(]")
_PROPERTY_HEAD = re.compile(rf"\(property\s+{QUOTED_VALUE}\s+{QUOTED_VALUE}")


def sub_sheet_files(text: str) -> List[str]:
    """The ``Sheetfile`` of every top-level ``(sheet ...)`` in one schematic.

    Older files spell the property ``Sheet file``; both are accepted. Values
    are unescaped, so a file name containing a quote round-trips.
    """
    files: List[str] = []
    for offset in iter_child_offsets(text):
        if not _SHEET_HEAD.match(text, offset):
            continue
        end = match_paren(text, offset)
        if end == -1:
            continue
        block = text[offset : end + 1]
        for prop_offset in iter_child_offsets(block):
            m = _PROPERTY_HEAD.match(block, prop_offset)
            if not m:
                continue
            name = unescape_sexpr_string(m.group(1))
            if name in ("Sheetfile", "Sheet file"):
                value = unescape_sexpr_string(m.group(2))
                if value:
                    files.append(value)
                break
    return files


def _real_key(path: Path) -> str:
    """Identity of a file on disk, so the same sheet is never visited twice."""
    return os.path.normcase(os.path.realpath(str(path)))


def sheet_tree(root: Path) -> List[Path]:
    """Sheets reachable from *root*, root first, one entry per file on disk.

    A sheet file referenced twice (a reused sub-sheet) is listed once. A
    reference to a file that does not exist is skipped; KiCad reports that as a
    missing sheet and so should the tool that owns the operation, not this
    walker. Unreadable files are skipped for the same reason.
    """
    order: List[Path] = []
    seen: Set[str] = set()
    queue: List[Path] = [Path(root)]
    while queue:
        sheet = queue.pop(0)
        key = _real_key(sheet)
        if key in seen:
            continue
        seen.add(key)
        if not sheet.is_file():
            continue
        order.append(sheet)
        try:
            text, _newline = read_text_preserve_newline(sheet)
        except (OSError, UnicodeDecodeError):
            continue
        for name in sub_sheet_files(text):
            queue.append(sheet.parent / name)
    return order
