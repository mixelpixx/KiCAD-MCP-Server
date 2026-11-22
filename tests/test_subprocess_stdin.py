"""Every subprocess the server starts gets its own stdin (subprocess.DEVNULL), never the server's.

The Python half of the server reads its JSON-RPC commands on stdin. A child that inherits that handle
(kicad-cli, java/Freerouting, pgrep, ...) can read bytes meant for the server, and on Windows an
inherited console or pipe handle the child can't use fails the call with "[WinError 6] The handle is
invalid" (WinError 50 under Git Bash). Tristan Lewis's Windows 11 retest of #556 (2026-11-18) traced
11 remaining real-pcbnew failures to server-side calls: netlist export, DRC, via audit and the Eagle
import post-check. This test reads the source: every subprocess.run / Popen / call / check_call /
check_output under python/ passes stdin= (or input=, which supplies a pipe).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "python"
FUNCS = {"run", "Popen", "call", "check_call", "check_output"}


def _offenders():
    out = []
    for f in sorted(SRC.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (
                isinstance(fn, ast.Attribute)
                and fn.attr in FUNCS
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "subprocess"
            ):
                continue
            kws = {k.arg for k in node.keywords}
            if not ({"stdin", "input"} & kws) and None not in kws:
                out.append(
                    f"{f.relative_to(SRC)}:{node.lineno} subprocess.{fn.attr} without stdin="
                )
    return out


def test_every_server_subprocess_has_its_own_stdin():
    offenders = _offenders()
    assert not offenders, "subprocess calls that inherit the server's stdin:\n" + "\n".join(
        offenders
    )
