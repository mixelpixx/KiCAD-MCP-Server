"""Regression tests for #405: one bad command must not kill the Python worker.

The worker's stdin loop in ``kicad_interface.main()`` caught only
``json.JSONDecodeError`` per line. Anything else that escaped while a response
was being built or written -- a value ``json.dumps`` rejects in a handler's
result, a request whose JSON is valid but not an object -- fell through to
the outer ``except Exception``, which called ``sys.exit(1)``. From then on every
tool call failed with "Python process for KiCAD scripting is not running"
until someone restarted the server.

These run the real ``main()`` in a subprocess (the fd redirection it does at
startup cannot be undone in-process) with ``handle_command`` patched to return
an unserialisable result for one command, and check that the commands after
it are still answered and that the process ends normally at stdin EOF.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"

_WORKER = f"""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, {str(PYTHON_DIR)!r})

pcbnew = MagicMock(name="pcbnew")
pcbnew.__file__ = "/fake/pcbnew.py"
pcbnew.__spec__ = None
pcbnew.GetBuildVersion.return_value = "9.0.0-stub"
sys.modules["pcbnew"] = pcbnew

import kicad_interface

_real_handle_command = kicad_interface.KiCADInterface.handle_command


def _handle_command(self, command, params):
    if command == "ping":
        return {{"success": True, "n": params.get("n")}}
    if command == "unserialisable":
        # handle_command's own try/except never sees this: the handler
        # returns normally and json.dumps rejects the value later.
        return {{"success": True, "payload": object()}}
    return _real_handle_command(self, command, params)


kicad_interface.KiCADInterface.handle_command = _handle_command
kicad_interface.main()
"""


def _run_worker(lines, tmp_path):
    env = dict(os.environ)
    # Keep the worker's per-PID log file out of the real profile directory
    # and skip the symbol-library warm-up thread.
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env["KICAD_SKIP_SYMBOL_WARMUP"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", _WORKER],
        input="".join(line + "\n" for line in lines),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    frames = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return result, frames


def test_worker_answers_commands_after_an_unserialisable_result(tmp_path):
    lines = [
        json.dumps({"command": "ping", "params": {"n": 1}, "requestId": 1}),
        json.dumps({"command": "unserialisable", "params": {}, "requestId": 2}),
        json.dumps({"command": "ping", "params": {"n": 3}, "requestId": 3}),
    ]
    result, frames = _run_worker(lines, tmp_path)

    assert result.returncode == 0, (
        "the worker must reach stdin EOF and exit normally, not die on the bad "
        f"command\nstderr:\n{result.stderr[-3000:]}"
    )
    assert frames[0] == {"type": "ready"}
    by_id = {f.get("_requestId"): f for f in frames[1:]}
    assert by_id[1]["n"] == 1

    error = by_id[2]
    assert error["success"] is False
    assert "not JSON serializable" in error["errorDetails"]
    assert "unserialisable" in error["message"]

    # The request after the failure is answered by the same worker.
    assert by_id[3]["n"] == 3


def test_worker_survives_request_that_is_valid_json_but_not_an_object(tmp_path):
    lines = [
        "42",
        "[1, 2]",
        json.dumps({"command": "ping", "params": {"n": 9}, "requestId": 9}),
    ]
    result, frames = _run_worker(lines, tmp_path)

    assert result.returncode == 0, result.stderr[-3000:]
    assert frames[0] == {"type": "ready"}
    errors = [f for f in frames[1:] if f.get("success") is False]
    assert len(errors) == 2
    for error in errors:
        # No request id could be read from the input, so none is echoed;
        # the host discards the frame as stale rather than misrouting it.
        assert "_requestId" not in error
    assert frames[-1] == {"success": True, "n": 9, "_requestId": 9}


def test_worker_reports_json_rpc_error_instead_of_dying(tmp_path):
    lines = [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "unserialisable", "arguments": {}},
            }
        ),
        json.dumps({"command": "ping", "params": {"n": 8}, "requestId": 8}),
    ]
    result, frames = _run_worker(lines, tmp_path)

    assert result.returncode == 0, result.stderr[-3000:]
    rpc_error = frames[1]
    assert rpc_error["jsonrpc"] == "2.0"
    assert rpc_error["id"] == 7
    assert rpc_error["error"]["code"] == -32603
    assert "not JSON serializable" in rpc_error["error"]["message"]
    assert frames[2] == {"success": True, "n": 8, "_requestId": 8}
