"""String-aware parenthesis matching for KiCad s-expression text.

KiCad writes a ``(`` or ``)`` inside a quoted token as is (the stock STM32
libraries have pin names like ``"PA13(JTMS"``), so a scanner that counts every
bracket is thrown off to the end of the file by one such name. These two
helpers skip quoted text, so callers can slice a block out of a file and
splice a new one back without a parser.

This module deliberately imports nothing beyond the standard library:
``utils.kicad_dru`` is loaded through ``commands/__init__`` and so runs under
KiCad's own Python, which has no ``sexpdata``. ``utils.sexpr_format``
re-exports both helpers, so either import path works.
"""

from __future__ import annotations


def match_paren(content: str, open_idx: int) -> int:
    """Index of the ``)`` closing the ``(`` at *open_idx*, or -1 if unbalanced.

    Parens inside quoted tokens are literal text, not structure.
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


def paren_delta(text: str) -> int:
    """Net nesting change across *text*: ``(`` count minus ``)`` count, outside quotes.

    For scanners that walk a file line by line. KiCad never breaks a quoted
    token across lines (a newline inside a string is written as ``\\n``), so
    each line can be measured on its own.
    """
    delta = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            delta += 1
        elif ch == ")":
            delta -= 1
        i += 1
    return delta
