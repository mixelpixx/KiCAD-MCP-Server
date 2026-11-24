"""KiCADProcessManager.is_running on macOS must not mistake this server for KiCad.

The server runs on KiCad's bundled Python, which lives inside KiCad.app, so a
full-command-line match on "KiCad" always finds the server itself.
"""

import re
import subprocess
from typing import List, Tuple

import pytest
from utils.kicad_process import KiCADProcessManager

from utils import kicad_process

KICAD_PYTHON = (
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9"
    "/Resources/Python.app/Contents/MacOS/Python"
)
MCP_SERVER = ("Python", f"{KICAD_PYTHON} /Users/someone/KiCAD-MCP-Server/python/kicad_interface.py")
KICAD_GUI = ("kicad", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad")
PCBNEW_GUI = (
    "pcbnew",
    "/Applications/KiCad/KiCad.app/Contents/Applications/pcbnew.app/Contents/MacOS/pcbnew",
)


def fake_pgrep(processes: List[Tuple[str, str]]):
    """A subprocess.run stand-in that answers pgrep like BSD pgrep would."""

    def run(cmd, **_kwargs):
        assert cmd[0] == "pgrep", cmd
        flags, pattern = cmd[1:-1], cmd[-1]
        full = "-f" in flags
        exact = "-x" in flags
        hits = []
        for pid, (name, cmdline) in enumerate(processes, start=100):
            target = cmdline if full else name
            match = re.fullmatch(pattern, target) if exact else re.search(pattern, target)
            if match:
                hits.append(str(pid))
        return subprocess.CompletedProcess(cmd, 0 if hits else 1, "\n".join(hits), "")

    return run


@pytest.fixture
def macos(monkeypatch):
    monkeypatch.setattr(kicad_process.platform, "system", lambda: "Darwin")

    def with_processes(*processes: Tuple[str, str]) -> None:
        monkeypatch.setattr(kicad_process.subprocess, "run", fake_pgrep(list(processes)))

    return with_processes


def test_server_on_kicad_python_is_not_kicad(macos) -> None:
    macos(MCP_SERVER)
    assert KiCADProcessManager.is_running() is False


def test_kicad_project_manager_is_detected(macos) -> None:
    macos(MCP_SERVER, KICAD_GUI)
    assert KiCADProcessManager.is_running() is True


def test_standalone_pcbnew_is_detected(macos) -> None:
    macos(MCP_SERVER, PCBNEW_GUI)
    assert KiCADProcessManager.is_running() is True
