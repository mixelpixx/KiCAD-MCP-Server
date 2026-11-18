"""Every text file the server writes is written with LF line endings, on every OS.

KiCad writes its files with LF on Windows too. A Python text-mode write without ``newline=""``
translates each "\\n" to "\\r\\n" on Windows, so after one MCP edit git shows the whole file changed
(.kicad_sch, .kicad_dru, library tables). Found on Windows 11 / KiCad 10.0.1 by Tristan Lewis
(2026-11-17): voltage_rules.py, wire_manager.py and the library-table writers.

This test reads the source rather than running on Windows: any ``open(..., "w"/"a"/"x")`` in text
mode must pass ``newline=``, and ``Path.write_text`` (whose ``newline`` argument needs Python
3.10; the project supports 3.9) is not used for files; ``write_bytes(text.encode("utf-8"))`` is.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "python"


def _text_write_mode(call):
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
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
            if isinstance(fn, ast.Name) and fn.id == "open" and _text_write_mode(node):
                if not any(kw.arg == "newline" for kw in node.keywords):
                    out.append(f"{rel}:{node.lineno} open() in text write mode without newline=")
            elif isinstance(fn, ast.Attribute) and fn.attr == "write_text":
                if not any(kw.arg == "newline" for kw in node.keywords):
                    out.append(f"{rel}:{node.lineno} .write_text() (CRLF on Windows)")
    return out


def test_every_text_write_is_lf():
    offenders = _offenders()
    assert not offenders, "text writes that turn LF into CRLF on Windows:\n" + "\n".join(offenders)
