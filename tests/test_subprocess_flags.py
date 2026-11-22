"""Every subprocess call in ``python/`` hides its console window on Windows.

On Windows, a console program started by a process that owns no console gets
a new, visible console window of its own. The server is started by an MCP
client with piped stdio, so neither the Node process nor the Python worker
owns one, and every ``kicad-cli`` call flashed a console window (issue #577).
Each ``subprocess.run``/``Popen`` call in ``python/`` must therefore pass
``creationflags=windows_no_console_flags(...)`` (``utils.subprocess_flags``),
which is ``CREATE_NO_WINDOW`` on win32 and a no-op elsewhere, so the guard
runs on every OS in CI, not only on Windows.

This test reads the source rather than running on Windows: it parses each
file and checks the ``creationflags`` keyword of every subprocess call.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import utils.subprocess_flags as sf

SRC = Path(__file__).resolve().parent.parent / "python"
HELPER = "windows_no_console_flags"


def _uses_helper(value) -> bool:
    """True when an expression calls the helper (alone, or ORed with flags)."""
    for node in ast.walk(value):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == HELPER:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == HELPER:
                return True
    return False


def _offenders(source: str, rel: str = "<snippet>"):
    """Subprocess calls in one source text that do not use the helper."""
    out = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (
            isinstance(fn, ast.Attribute)
            and fn.attr in ("run", "Popen")
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "subprocess"
        ):
            continue
        flags = [kw for kw in node.keywords if kw.arg == "creationflags"]
        if not flags or not _uses_helper(flags[0].value):
            out.append(f"{rel}:{node.lineno} subprocess.{fn.attr}() without {HELPER}()")
    return out


def _all_offenders():
    out = []
    for f in sorted(SRC.rglob("*.py")):
        out.extend(_offenders(f.read_text(encoding="utf-8"), str(f.relative_to(SRC))))
    return out


def test_every_subprocess_call_uses_no_console_flags():
    offenders = _all_offenders()
    assert not offenders, (
        "subprocess calls that flash a console window on Windows:\\n" + "\\n".join(offenders)
    )


def test_the_scan_sees_bare_calls():
    """The scanner itself: bare calls are flagged, helper calls pass."""
    assert _offenders('import subprocess\nsubprocess.run(["x"], capture_output=True)\n')
    assert not _offenders(
        "import subprocess\n"
        "from utils.subprocess_flags import windows_no_console_flags\n"
        "subprocess.run([\"x\"], creationflags=windows_no_console_flags())\n"
    )
    assert not _offenders(
        "import subprocess\n"
        "from utils.subprocess_flags import windows_no_console_flags\n"
        "subprocess.Popen([\"x\"], creationflags=windows_no_console_flags(\n"
        "    subprocess.CREATE_NEW_PROCESS_GROUP))\n"
    )
    assert _offenders(
        "import subprocess\n"
        "subprocess.run([\"x\"], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)\n"
    )


def test_helper_is_noop_off_windows(monkeypatch):
    """Off win32 the helper returns whatever extra flags it was given."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert sf.windows_no_console_flags() == 0
    assert sf.windows_no_console_flags(0x10) == 0x10


def test_helper_returns_no_window_on_windows(monkeypatch):
    """On win32 the helper ORs CREATE_NO_WINDOW with the extra flags."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert sf.windows_no_console_flags() == 0x08000000
    assert sf.windows_no_console_flags(0x10) == 0x08000010


def test_helper_uses_real_flag_on_windows(monkeypatch):
    """The win32 branch reads the real CREATE_NO_WINDOW, not a literal."""
    monkeypatch.setattr(sys, "platform", "win32")
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        pytest.skip("CREATE_NO_WINDOW is not defined on this platform")
    assert sf.windows_no_console_flags() == subprocess.CREATE_NO_WINDOW
