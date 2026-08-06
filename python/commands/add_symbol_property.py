"""Add or update a property on a symbol in a .kicad_sym library file."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from utils.sexpr_format import escape_sexpr_string

# A property belongs to the symbol itself, so it has to sit at the same nesting
# level as (property "Reference" ...). Inside the parent block that is depth 2:
# depth 1 is the parent's own "(".
_CHILD_DEPTH = 2

# Any whitespace separates the head of an s-expression from its arguments, so
# "(at\t5 6 90)" and "(at\n5 6 90)" are as legal as "(at 5 6 90)".
_AT_HEAD = re.compile(r"\(at\s")

_HIDE_LIST = re.compile(r"\(hide\s+(yes|no)\s*\)")


def _read_text(path: Path) -> tuple[str, str]:
    """File text with LF newlines, plus the newline style to write back.

    ``Path.read_text``/``write_text`` apply universal-newline translation, so on
    Windows a CRLF library round-tripped through them keeps its line endings by
    luck and an LF one silently gains a ``\\r`` on every line -- turning a
    one-property edit into a whole-file diff.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def _write_text(path: Path, text: str, newline: str) -> None:
    """Atomic write that keeps the file's original newline style.

    ``write_text`` truncates in place, so a failure part-way through the write
    leaves a 2 MB library half-written with no copy of the original anywhere.
    """
    tmp = path.with_name(path.name + ".mcp-tmp")
    with open(tmp, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)
    os.replace(tmp, path)


def _match_paren(content: str, open_idx: int) -> int:
    """Index of the ``)`` closing the ``(`` at *open_idx*, or -1 if unbalanced.

    Parentheses inside quoted tokens are literal text -- a Description of
    ``"Cap (X7R)"`` must not be read as a nested list.
    """
    depth = 0
    in_string = False
    i = open_idx
    while i < len(content):
        ch = content[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _paren_balance(content: str) -> int:
    """Signed paren balance of *content*, ignoring parens inside quoted tokens."""
    balance = 0
    in_string = False
    i = 0
    while i < len(content):
        ch = content[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            balance += 1
        elif ch == ")":
            balance -= 1
        i += 1
    return balance


def _iter_children(block: str) -> Iterator[int]:
    """Yield the offset of every direct child list inside a symbol *block*."""
    depth = 0
    in_string = False
    i = 0
    while i < len(block):
        ch = block[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
            if depth == _CHILD_DEPTH:
                yield i
        elif ch == ")":
            depth -= 1
        i += 1


def _iter_bare_atoms(block: str) -> Iterator[tuple[int, int]]:
    """Yield spans of the atoms that are direct children of *block*.

    Only used to locate KiCad 7's bare ``hide`` token inside ``(effects ...)``.
    Quoted tokens between children are split on whitespace like anything else,
    which is harmless for the ``(effects ...)`` blocks this is applied to: their
    only quoted value is a font face, nested one level further down.
    """
    gaps: list[tuple[int, int]] = []
    cursor = 1
    for offset in _iter_children(block):
        close = _match_paren(block, offset)
        if close == -1:
            break
        gaps.append((cursor, offset))
        cursor = close + 1
    gaps.append((cursor, len(block) - 1 if block.endswith(")") else len(block)))
    for lo, hi in gaps:
        for match in re.finditer(r"[^\s()]+", block[lo:hi]):
            yield lo + match.start(), lo + match.end()


def _cut_span(text: str, start: int, end: int) -> str:
    """Remove ``text[start:end]``, taking the whole line when it owns one."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    owns_line = (
        text[line_start:start].strip() == "" and line_end != -1 and text[end:line_end].strip() == ""
    )
    if owns_line:
        return text[:line_start] + text[line_end + 1 :]
    lead = start
    while lead > line_start and text[lead - 1] in " \t":
        lead -= 1
    return text[:lead] + text[end:]


def _strip_hide(block: str) -> tuple[str, bool | None]:
    """Drop *block*'s own hide markers; report the visibility they declared.

    KiCad 8 and 9 nest ``(hide yes)`` inside ``(effects ...)`` and KiCad 7 wrote
    a bare ``hide`` token there, so a property's visibility can live a level
    below the property itself. Both forms are removed here and re-emitted as a
    single property-level ``(hide yes)``; kicad-cli canonicalises the nested and
    property-level spellings to byte-identical output, so nothing is lost.

    Returns None for the flag when the block declared no visibility at all,
    which is what lets a caller-supplied ``hide`` win over an absent marker
    without inventing one.
    """
    out = block
    declared: bool | None = None
    for offset in reversed(list(_iter_children(out))):
        close = _match_paren(out, offset)
        if close == -1:
            continue
        match = _HIDE_LIST.fullmatch(out[offset : close + 1])
        if match:
            declared = match.group(1) == "yes"
            out = _cut_span(out, offset, close + 1)
    for start, end in reversed(list(_iter_bare_atoms(out))):
        if out[start:end] == "hide":
            declared = True
            out = _cut_span(out, start, end)
    return out, declared


def _find_symbol_in_lib(content: str, symbol_name: str) -> tuple[int, int, str] | None:
    """Return (start, end, block) for a symbol in .kicad_sym, or None.

    ``end`` is the index of the symbol's closing paren and ``block`` includes it.

    The marker is located with a plain substring search, so a value that
    literally contained ``(symbol "NAME"`` would match ahead of the real symbol.
    No library eeschema writes can produce that -- a property value is a single
    quoted token and the search includes the opening paren -- and making the
    search position-aware would mean parsing the whole file to place one edit.
    """
    marker = f'(symbol "{escape_sexpr_string(symbol_name)}"'
    sym_start = content.find(marker)
    if sym_start == -1:
        return None

    sym_end = _match_paren(content, sym_start)
    if sym_end == -1:
        return None
    return sym_start, sym_end, content[sym_start : sym_end + 1]


def _find_property_span(block: str, prop_name: str) -> tuple[int, int] | None:
    """Span of the symbol's own ``(property "prop_name" ...)``, end-exclusive.

    Only direct children count. A multi-unit symbol repeats property names
    inside its ``NAME_0_1`` sub-symbols, and rewriting one of those leaves the
    parent untouched while corrupting the sub-symbol.
    """
    head = re.compile(rf'\(property\s+"{re.escape(escape_sexpr_string(prop_name))}"[\s()"]')
    for offset in _iter_children(block):
        if head.match(block, offset):
            close = _match_paren(block, offset)
            if close != -1:
                return offset, close + 1
    return None


def _first_subsymbol_offset(block: str) -> int | None:
    """Offset of the first ``(symbol "..."`` unit inside a parent symbol block."""
    for offset in _iter_children(block):
        if block.startswith('(symbol "', offset):
            return offset
    return None


def _indent_at(block: str, offset: int) -> str | None:
    """Leading whitespace of the line holding *offset*, or None if not alone."""
    line_start = block.rfind("\n", 0, offset) + 1
    prefix = block[line_start:offset]
    return prefix if prefix.strip() == "" else None


def _child_indent(block: str, fallback: str) -> str:
    """Indentation used by this symbol's direct children.

    Libraries written by eeschema use tabs; hand-edited and Eagle-imported ones
    use spaces. Copying whatever the file already does keeps the diff to the
    inserted lines. *fallback* covers a symbol whose children all share a line
    with something else, so none of them shows its own indentation.
    """
    for offset in _iter_children(block):
        indent = _indent_at(block, offset)
        if indent:
            return indent
    return fallback


def _existing_parts(prop_block: str) -> tuple[str | None, bool, list[str]]:
    """The ``(at ...)``, hidden flag and other children of an existing property.

    Rewriting a property means regenerating its opening line, so every child the
    caller did not supply has to be carried over verbatim. Rendering a fresh
    ``(effects (font (size 1.27 1.27)))`` instead threw away the field's font
    size, thickness, bold/italic, justification and -- because KiCad 8 and 9
    write it in there rather than on the property -- its hidden state.
    """
    at_text: str | None = None
    declared: list[bool] = []
    others: list[str] = []
    for offset in _iter_children(prop_block):
        close = _match_paren(prop_block, offset)
        if close == -1:
            continue
        child = prop_block[offset : close + 1]
        hide_match = _HIDE_LIST.fullmatch(child)
        if hide_match:
            declared.append(hide_match.group(1) == "yes")
        elif at_text is None and _AT_HEAD.match(child):
            at_text = child
        elif child.startswith("(effects"):
            cleaned, nested = _strip_hide(child)
            if nested is not None:
                declared.append(nested)
            others.append(cleaned)
        else:
            others.append(child)
    return at_text, any(declared), others


def _build_property(
    name: str,
    value: str,
    at_text: str = "(at 0 0 0)",
    hide: bool = False,
    indent: str = "\t\t",
    others: Sequence[str] = (),
) -> str:
    """Render a property block; the first line carries no indent.

    *others* are an existing property's remaining children, re-emitted exactly
    as they were found. A default ``(effects ...)`` is only supplied when the
    property has none of its own.
    """
    inner = indent + ("\t" if "\t" in indent else "  ")
    lines = [
        f'(property "{escape_sexpr_string(name)}" ' f'"{escape_sexpr_string(value)}" {at_text}'
    ]
    if hide:
        lines.append(f"{inner}(hide yes)")
    lines.extend(f"{inner}{child}" for child in others)
    if not any(child.startswith("(effects") for child in others):
        lines.append(f"{inner}(effects (font (size 1.27 1.27)))")
    lines.append(f"{indent})")
    return "\n".join(lines)


def _splice_child(block: str, anchor: int, indent: str, tail_indent: str, new_prop: str) -> str:
    """Insert *new_prop* into *block* as a direct child, just before *anchor*.

    When *anchor* starts its own line the property becomes a new line above it.
    When it shares a line the line has to be broken instead -- taking the line
    start as ``block.rfind("\\n", 0, anchor) + 1`` gives 0 there, which is the
    symbol's own ``(``, and splicing at 0 makes the property a *sibling* of the
    symbol rather than a child of it. Compact libraries hit this whenever the
    first unit shares the parent's line, as does a bare ``(symbol "EMPTY")``
    whose closing paren is on the opening line.
    """
    newline_before = block.rfind("\n", 0, anchor)
    if newline_before != -1 and block[newline_before + 1 : anchor].strip() == "":
        line_start = newline_before + 1
        return block[:line_start] + indent + new_prop + "\n" + block[line_start:]
    head = block[:anchor].rstrip(" \t")
    return f"{head}\n{indent}{new_prop}\n{tail_indent}{block[anchor:]}"


def _is_direct_child(content: str, symbol_name: str, prop_name: str) -> bool:
    """Whether *prop_name* ended up a direct child of *symbol_name*.

    Re-locates the symbol in the text about to be written rather than trusting
    the splice arithmetic that produced it. The paren-balance check cannot see
    this class of mistake on its own: a well-formed property inserted at the
    wrong nesting depth leaves the file's balance exactly as it was.
    """
    found = _find_symbol_in_lib(content, symbol_name)
    if found is None:
        return False
    return _find_property_span(found[2], prop_name) is not None


def add_symbol_property(params: dict[str, Any]) -> dict[str, Any]:
    lib_path = Path(params["libraryPath"])
    symbol_name = params["symbolName"]
    prop_name = params["propertyName"]
    prop_value = params["propertyValue"]
    pos = params.get("position")
    hide = bool(params.get("hide", False))

    if not lib_path.exists():
        return {"success": False, "message": f"Library not found: {lib_path}"}

    content, newline = _read_text(lib_path)
    found = _find_symbol_in_lib(content, symbol_name)
    if not found:
        return {
            "success": False,
            "message": f"Symbol '{symbol_name}' not found in library",
        }

    sym_start, sym_end, block = found
    sym_indent = _indent_at(content, sym_start) or ""
    indent = _child_indent(block, sym_indent + "\t")
    at_text = f"(at {pos.get('x', 0)} {pos.get('y', 0)} 0)" if pos else None

    existing = _find_property_span(block, prop_name)
    if existing:
        updated = True
        start, end = existing
        old_at, old_hidden, old_others = _existing_parts(block[start:end])
        new_prop = _build_property(
            prop_name,
            prop_value,
            at_text or old_at or "(at 0 0 0)",
            hide if "hide" in params else old_hidden,
            indent,
            old_others,
        )
        block = block[:start] + new_prop + block[end:]
    else:
        updated = False
        new_prop = _build_property(prop_name, prop_value, at_text or "(at 0 0 0)", hide, indent)
        sub = _first_subsymbol_offset(block)
        if sub is not None:
            # Properties must precede the unit definitions, so anchor to the
            # first sub-symbol; otherwise anchor to the symbol's own closer.
            anchor, tail_indent = sub, indent
        else:
            anchor, tail_indent = block.rfind(")"), sym_indent
        block = _splice_child(block, anchor, indent, tail_indent, new_prop)

    updated_content = content[:sym_start] + block + content[sym_end + 1 :]

    # Adding or replacing a property is a balanced edit, so the file's balance
    # cannot move. Comparing against the original rather than checking for zero
    # keeps the guard usable on Eagle-imported libraries that arrive unbalanced.
    # This catches dropped or surplus parens only -- see _is_direct_child for
    # the nesting-depth half, which balance alone is blind to.
    if _paren_balance(updated_content) != _paren_balance(content):
        return {
            "success": False,
            "message": (
                f"Refusing to write {lib_path.name}: editing property "
                f"'{prop_name}' on '{symbol_name}' would unbalance the file"
            ),
        }

    if not _is_direct_child(updated_content, symbol_name, prop_name):
        return {
            "success": False,
            "message": (
                f"Refusing to write {lib_path.name}: property '{prop_name}' would "
                f"not be a direct child of symbol '{symbol_name}'"
            ),
        }

    _write_text(lib_path, updated_content, newline)

    # This rewrote a .kicad_sym file: drop the module-level symbol caches so a
    # subsequent extract/list sees the new property instead of a stale block
    # (the mtime guards over there also catch this; the explicit clear keeps
    # every library-mutating write path uniform).
    from commands.symbol_creator import _invalidate_symbol_caches

    _invalidate_symbol_caches()

    action = "Updated" if updated else "Added"
    return {
        "success": True,
        "message": f"Property '{prop_name}' = '{prop_value}' {action.lower()} to '{symbol_name}'",
        "propertyAdded": prop_name,
        "propertyValue": prop_value,
    }
