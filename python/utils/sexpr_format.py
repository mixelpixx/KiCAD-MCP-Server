"""KiCad-compatible S-expression serialization for schematic (.kicad_sch) files.

Background
----------
The schematic write tools in this server manipulate the parsed s-expression tree
with :mod:`sexpdata` and then serialize it back with ``sexpdata.dumps()``.  That
function emits the *entire* file as a single minified line.  KiCad's own editor
(eeschema) always writes the file in a canonical, multi-line "pretty" format.
The mismatch means a one-symbol edit made through this server rewrites the whole
file onto one line, producing unreviewable diffs (thousands of deletions, one
insertion) and churning the file back and forth every time it is opened and saved
in the KiCad UI.

This module re-implements KiCad's canonical formatter so that tool writes are
byte-for-byte identical to what eeschema's "Save" produces.  ``dumps()`` here is a
drop-in replacement for ``sexpdata.dumps()`` for schematic data.

Implementation
--------------
:func:`prettify` is a faithful port of KiCad's ``Prettify()``
(``common/io/kicad/kicad_io_utils.cpp``) for ``FORMAT_MODE::DEFAULT`` -- the mode
eeschema uses for ``.kicad_sch``.  It is a character-level transform over an
already-serialized compact s-expression string (exactly how KiCad implements it),
so it does not re-interpret atoms; it only decides where line breaks and
indentation go.  Because :func:`sexpdata.dumps` already emits atoms (numbers,
quoted/escaped strings) the same way KiCad does, the combination round-trips real
eeschema files byte-for-byte.

The two special cases that DEFAULT mode does not use (``COMPACT_TEXT_PROPERTIES``
for board text and ``LIBRARY_TABLE`` for fp-lib-table rows) are intentionally
omitted -- schematics never trigger them.

Divergence note
---------------
``Prettify()`` has been layout-stable across KiCad 7-10; this port was verified
byte-identical against ``kicad-cli`` (KiCad 10) output.  If a future KiCad
release changes the layout, tool writes would drift from UI saves again -- but
only cosmetically: :func:`dumps` re-parses its own output and falls back to the
(minified but data-correct) compact form if the layout pass ever fails to
round-trip, so a formatter change can never corrupt schematic data.
"""

from __future__ import annotations

import logging

import sexpdata

logger = logging.getLogger("kicad_interface")

# Formatting constants, mirrored from KiCad's Prettify().
_QUOTE_CHAR = '"'
_INDENT_CHAR = "\t"
_INDENT_SIZE = 1
# Long runs of (xy ...) points are kept on one line until this column.
_XY_SPECIAL_CASE_COLUMN_LIMIT = 99
# Whitespace inside a list past this column becomes a newline + indent.
_CONSECUTIVE_TOKEN_WRAP_THRESHOLD = 72


def _is_whitespace(c: str) -> bool:
    return c in (" ", "\t", "\n", "\r")


def prettify(source: str) -> str:
    """Reformat a compact s-expression string into KiCad's canonical layout.

    Port of KiCad ``Prettify()`` for ``FORMAT_MODE::DEFAULT``.  ``source`` should
    be a valid single-line (or arbitrarily-spaced) s-expression such as the output
    of :func:`sexpdata.dumps`.  Returns the pretty-printed text, terminated with a
    trailing newline (matching KiCad, for clean git diffs).
    """
    n = len(source)
    formatted: list[str] = []

    list_depth = 0
    last_non_whitespace = ""
    in_quote = False
    has_inserted_space = False
    in_multi_line_list = False
    in_xy = False
    column = 0
    backslash_count = 0

    def next_non_whitespace(i: int) -> str:
        while i < n and _is_whitespace(source[i]):
            i += 1
        return chr(0) if i >= n else source[i]

    def is_xy(i: int) -> bool:
        # True if source[i:] starts with "(xy " (the point-list special case).
        return i + 3 < n and source[i + 1] == "x" and source[i + 2] == "y" and source[i + 3] == " "

    cursor = 0
    while cursor < n:
        cur = source[cursor]

        if _is_whitespace(cur) and not in_quote:
            nxt = next_non_whitespace(cursor)
            if (
                not has_inserted_space  # only one space between tokens
                and list_depth > 0  # never touch the outer list
                and last_non_whitespace != "("  # no space right after "("
                and nxt != ")"  # no space right before ")"
                and nxt != "("  # a newline (below) handles this instead
            ):
                if in_xy or column < _CONSECUTIVE_TOKEN_WRAP_THRESHOLD:
                    formatted.append(" ")
                    column += 1
                else:
                    formatted.append("\n" + _INDENT_CHAR * (list_depth * _INDENT_SIZE))
                    column = list_depth * _INDENT_SIZE
                    in_multi_line_list = True
                has_inserted_space = True
        else:
            has_inserted_space = False

            if cur == "(" and not in_quote:
                current_is_xy = is_xy(cursor)

                if not formatted:
                    formatted.append("(")
                    column += 1
                elif in_xy and current_is_xy and column < _XY_SPECIAL_CASE_COLUMN_LIMIT:
                    # Keep consecutive (xy ...) points on the same line.
                    formatted.append(" (")
                    column += 2
                else:
                    formatted.append("\n" + _INDENT_CHAR * (list_depth * _INDENT_SIZE) + "(")
                    column = list_depth * _INDENT_SIZE + 1

                in_xy = current_is_xy
                list_depth += 1
            elif cur == ")" and not in_quote:
                if list_depth > 0:
                    list_depth -= 1

                if last_non_whitespace == ")" or in_multi_line_list:
                    formatted.append("\n" + _INDENT_CHAR * (list_depth * _INDENT_SIZE) + ")")
                    column = list_depth * _INDENT_SIZE + 1
                    in_multi_line_list = False
                else:
                    formatted.append(")")
                    column += 1
            else:
                # Track escaped quotes: a '"' only toggles quote state when
                # preceded by an even number of backslashes.
                if cur == "\\":
                    backslash_count += 1
                elif cur == _QUOTE_CHAR and (backslash_count & 1) == 0:
                    in_quote = not in_quote

                if cur != "\\":
                    backslash_count = 0

                formatted.append(cur)
                column += 1

            last_non_whitespace = cur

        cursor += 1

    # Trailing newline for POSIX compliance / clean git diffs (matches KiCad).
    formatted.append("\n")
    return "".join(formatted)


def dumps(data) -> str:
    """Serialize a sexpdata tree to KiCad's canonical pretty format.

    Drop-in replacement for ``sexpdata.dumps(data)`` at schematic write sites.

    Data-integrity guard: :func:`prettify` only moves whitespace outside quoted
    strings, so it cannot change the parsed data.  As cheap insurance against a
    latent formatter bug (or a future KiCad layout change this port doesn't
    track), the pretty output is re-parsed and compared to the compact form; on
    any mismatch we log and fall back to the compact string, which is ugly
    (single line) but guaranteed to preserve the schematic exactly.
    """
    compact = sexpdata.dumps(data)
    pretty = prettify(compact)
    if sexpdata.dumps(sexpdata.loads(pretty)) != compact:
        logger.error(
            "sexpr_format.dumps: pretty output did not round-trip to the same "
            "data; writing compact form to avoid corruption. Please report this."
        )
        return compact
    return pretty
