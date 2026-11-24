"""Every subprocess launch passes creationflags=no_window_flags(...) (#577).

The server runs without a console (an MCP client starts it with piped stdio), so on Windows each
console program it launches, kicad-cli.exe above all, flashed a console window open and closed
again. ``utils.subprocess_flags.no_window_flags`` adds CREATE_NO_WINDOW on Windows.

This test reads the source rather than running on Windows, so it guards every OS in CI: any
``subprocess.run``/``Popen``/``call``/``check_call``/``check_output`` call in ``python/`` must pass
``creationflags=no_window_flags(...)``, and nothing may import those functions by name, which
would hide a call from the scan.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from utils.subprocess_flags import CREATE_NO_WINDOW, no_window_flags

SRC = Path(__file__).resolve().parent.parent / "python"

_LAUNCHERS = {"run", "Popen", "call", "check_call", "check_output"}


def _launch_offence(node):
    """Why this AST node is an unguarded subprocess launch, or None."""
    if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
        names = sorted(a.name for a in node.names if a.name in _LAUNCHERS)
        if names:
            return f"from subprocess import {', '.join(names)} (call it as subprocess.<name>)"
        return None
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    if not (
        isinstance(fn, ast.Attribute)
        and fn.attr in _LAUNCHERS
        and isinstance(fn.value, ast.Name)
        and fn.value.id == "subprocess"
    ):
        return None
    for kw in node.keywords:
        if kw.arg == "creationflags":
            value = kw.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "no_window_flags"
            ):
                return None
            return f"subprocess.{fn.attr}() with creationflags not from no_window_flags()"
    return f"subprocess.{fn.attr}() without creationflags=no_window_flags()"


def _offenders():
    out = []
    for f in sorted(SRC.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            why = _launch_offence(node)
            if why:
                out.append(f"{f.relative_to(SRC)}:{node.lineno} {why}")
    return out


def test_every_subprocess_launch_hides_its_console():
    offenders = _offenders()
    assert (
        not offenders
    ), "subprocess launches that open a console window on Windows (#577):\n" + "\n".join(offenders)


def test_the_scan_flags_unguarded_launches():
    """The scanner itself: each launcher form is flagged without the helper and passes with it."""
    cases = {
        'subprocess.run(["kicad-cli", "version"], capture_output=True)': True,
        "subprocess.Popen(cmd, stdout=subprocess.PIPE)": True,
        "subprocess.check_output(cmd)": True,
        "subprocess.run(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)": True,
        "subprocess.run(cmd, creationflags=no_window_flags())": False,
        "subprocess.Popen(cmd, creationflags=no_window_flags(subprocess.CREATE_NEW_PROCESS_GROUP))": False,
        "from subprocess import run": True,
        "from subprocess import PIPE, TimeoutExpired": False,
        "other.run(cmd)": False,
    }
    for src, flagged in cases.items():
        node = ast.parse(src).body[0]
        if isinstance(node, ast.Expr):
            node = node.value
        assert bool(_launch_offence(node)) == flagged, src


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_flags_unchanged_off_windows(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    assert no_window_flags() == 0
    assert no_window_flags(0x200) == 0x200


def test_no_window_added_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert no_window_flags() == CREATE_NO_WINDOW
    new_process_group = 0x00000200
    assert no_window_flags(new_process_group) == new_process_group | CREATE_NO_WINDOW


@pytest.mark.parametrize("console_flag", [0x00000010, 0x00000008])
def test_explicit_console_requests_are_left_alone(monkeypatch, console_flag):
    """CREATE_NEW_CONSOLE and DETACHED_PROCESS cannot be combined with CREATE_NO_WINDOW."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert no_window_flags(console_flag) == console_flag


@pytest.mark.skipif(sys.platform != "win32", reason="creationflags only exist on Windows")
def test_a_console_program_runs_with_the_flags():
    result = subprocess.run(
        [sys.executable, "-c", "print('ok')"],
        capture_output=True,
        text=True,
        creationflags=no_window_flags(),
    )
    assert result.stdout.strip() == "ok"
