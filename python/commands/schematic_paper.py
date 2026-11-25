"""Schematic paper size: read and rewrite the root-level ``(paper ...)`` token."""

from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

# The named sizes KiCad's Page Settings dialog offers (custom "User" sizes excluded).
PAPER_SIZES: Tuple[str, ...] = (
    "A5",
    "A4",
    "A3",
    "A2",
    "A1",
    "A0",
    "A",
    "B",
    "C",
    "D",
    "E",
    "USLetter",
    "USLegal",
    "USLedger",
)


# Each size's (width, height) in mm, landscape, as KiCad's Page Settings gives it.
# A portrait sheet swaps the two.
PAPER_DIMENSIONS_MM: Dict[str, Tuple[float, float]] = {
    "A5": (210.0, 148.0),
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "A": (279.4, 215.9),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
    "USLetter": (279.4, 215.9),
    "USLegal": (355.6, 215.9),
    "USLedger": (431.8, 279.4),
}


def normalize_paper(name: str) -> Optional[str]:
    """Return KiCad's spelling of a paper name, matched without case, or None."""
    wanted = name.strip().lower()
    return next((size for size in PAPER_SIZES if size.lower() == wanted), None)


def _root_children(text: str) -> Iterator[Tuple[int, int]]:
    """Yield (start, end) of each direct child list of the root s-expression."""
    depth = 0
    in_string = False
    escaped = False
    start = 0
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
            if depth == 2:
                start = i
        elif ch == ")":
            if depth == 2:
                yield start, i + 1
            depth -= 1


def _find_child(text: str, head: str) -> Optional[Tuple[int, int]]:
    prefix = f"({head}"
    for start, end in _root_children(text):
        if text.startswith(prefix, start) and text[start + len(prefix)] in " \t\n)":
            return start, end
    return None


def set_paper(path: Path, paper: str, portrait: bool = False) -> None:
    """Set the sheet's paper size, replacing or inserting the root ``(paper ...)``.

    Raises ValueError for a name KiCad does not offer, leaving the file unchanged.
    """
    size = normalize_paper(paper)
    if size is None:
        raise ValueError(f"Unknown paper size {paper!r}. Valid sizes: {', '.join(PAPER_SIZES)}")
    token = f'(paper "{size}"{" portrait" if portrait else ""})'

    # read_text turns CRLF into LF and the write below keeps LF. KiCad writes LF,
    # so a file KiCad saved comes back byte for byte apart from the paper token.
    text = path.read_text(encoding="utf-8")
    existing = _find_child(text, "paper")
    if existing:
        start, end = existing
        text = text[:start] + token + text[end:]
    else:
        anchor = _find_child(text, "uuid")
        if anchor is None:
            raise ValueError(f"{path} has no root (uuid ...); is it a .kicad_sch file?")
        start, end = anchor
        line_prefix = text[text.rfind("\n", 0, start) + 1 : start]
        # Put the token on its own line with (uuid's indent, or, when (uuid shares
        # its line with other tokens (a one-line file), right after it.
        separator = "\n" + line_prefix if line_prefix.strip() == "" else " "
        text = text[:end] + separator + token + text[end:]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
