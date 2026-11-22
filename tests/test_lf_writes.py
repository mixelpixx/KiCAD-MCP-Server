"""Every text file the server writes is written with LF line endings, on every OS.

KiCad writes its files with LF on Windows too. A Python text-mode write without ``newline=""``
translates each "\\n" to "\\r\\n" on Windows, so after one MCP edit git shows the whole file changed
(.kicad_sch, .kicad_dru, library tables). Found on Windows 11 / KiCad 10.0.1 by Tristan Lewis
(2026-11-17): voltage_rules.py, wire_manager.py and the library-table writers.

This test reads the source rather than running on Windows: any ``open(..., "w"/"a"/"x")``,
``os.fdopen(fd, "w")`` or ``tempfile.NamedTemporaryFile(mode="w")`` (and the other tempfile file
factories) in text mode must pass ``newline=``, and ``Path.write_text`` (whose ``newline`` argument
needs Python 3.10; the project supports 3.9) is not used for files; ``write_bytes(text.encode("utf-8"))``
is. The os.fdopen and tempfile forms were missed at first (the atomic-replace writers of .kicad_dru
and .kicad_pro); Tristan's Windows retest of #556 found them (2026-11-18).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "python"


# Callables that open a file object, with the position of their mode argument and its default.
_OPENERS = {
    "open": (1, "r"),
    "fdopen": (1, "r"),
    "NamedTemporaryFile": (0, "w+b"),
    "TemporaryFile": (0, "w+b"),
    "SpooledTemporaryFile": (1, "w+b"),
}


def _opener_name(call):
    fn = call.func
    if isinstance(fn, ast.Name) and fn.id == "open":
        return "open"
    if isinstance(fn, ast.Attribute) and fn.attr in _OPENERS and fn.attr != "open":
        return fn.attr
    return None


def _text_write_mode(call, name="open"):
    pos, mode = _OPENERS[name]
    if len(call.args) > pos and isinstance(call.args[pos], ast.Constant):
        mode = call.args[pos].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return isinstance(mode, str) and "b" not in mode and any(c in mode for c in "wax+")


def _offenders():
    out = []
    for f in sorted(SRC.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            rel = f.relative_to(SRC)
            name = _opener_name(node)
            if name and _text_write_mode(node, name):
                if not any(kw.arg == "newline" for kw in node.keywords):
                    out.append(f"{rel}:{node.lineno} {name}() in text write mode without newline=")
            elif isinstance(fn, ast.Attribute) and fn.attr == "write_text":
                if not any(kw.arg == "newline" for kw in node.keywords):
                    out.append(f"{rel}:{node.lineno} .write_text() (CRLF on Windows)")
    return out


def test_every_text_write_is_lf():
    offenders = _offenders()
    assert not offenders, "text writes that turn LF into CRLF on Windows:\n" + "\n".join(offenders)


def test_the_scan_sees_fdopen_and_tempfile_forms():
    """The scanner itself: each opener form is flagged without newline= and passes with it."""
    cases = {
        'os.fdopen(fd, "w", encoding="utf-8")': True,
        'os.fdopen(fd, "w", encoding="utf-8", newline="")': False,
        'os.fdopen(fd, "wb")': False,
        'tempfile.NamedTemporaryFile(mode="w", suffix=".json")': True,
        'tempfile.NamedTemporaryFile(mode="w", newline="", suffix=".json")': False,
        'tempfile.NamedTemporaryFile(suffix=".xml")': False,
        'open(p, "w", encoding="utf-8")': True,
        'open(p, "a", newline="")': False,
    }
    for src, flagged in cases.items():
        call = ast.parse(src).body[0].value
        name = _opener_name(call)
        hit = bool(
            name
            and _text_write_mode(call, name)
            and not any(k.arg == "newline" for k in call.keywords)
        )
        assert hit == flagged, src
