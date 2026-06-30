"""
Tests for the close_project command (issue #225).

close_project is the symmetric counterpart to open_project / create_project:
it optionally saves, then drops the in-memory board (SWIG + IPC) and clears all
per-project session state.

KiCADInterface.__init__ scans the system footprint/symbol libraries, which is
slow and environment-dependent, so these tests build the interface via
object.__new__ and populate just the attributes the handler under test touches.
"""

import sys
import types
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


class _FakeBoard:
    """Minimal stand-in that passes KiCADInterface._is_board_healthy."""

    def __init__(self, filename: str) -> None:
        self._filename = filename

    def GetFileName(self) -> str:
        return self._filename

    def GetDesignSettings(self) -> object:
        return object()

    def GetBoardEdgesBoundingBox(self) -> object:
        return object()


class _FakeProjectCommands:
    def __init__(self, save_result: Any) -> None:
        self.board: Any = None
        self._save_result = save_result
        self.save_calls = 0

    def save_project(self, params: dict) -> Any:
        self.save_calls += 1
        if isinstance(self._save_result, Exception):
            raise self._save_result
        return self._save_result


def _make_interface(board: Any, project_commands: Any) -> Any:
    """Build a KiCADInterface without running its heavy __init__."""
    from kicad_interface import KiCADInterface

    iface = object.__new__(KiCADInterface)
    iface.board = board
    iface.project_commands = project_commands
    # Command handlers that _update_command_handlers writes .board onto.
    for name in (
        "board_commands",
        "component_commands",
        "routing_commands",
        "design_rule_commands",
        "export_commands",
        "freerouting_commands",
    ):
        setattr(iface, name, types.SimpleNamespace(board=board))
    # Per-project session state populated by a real open/create.
    iface.ipc_board_api = object()
    iface.session_backend = "swig"
    iface.session_board_path = "/proj/board.kicad_pcb"
    iface._board_disk_signature = (123, "abc")
    iface._last_auto_save_status = None
    iface.project_filename = "/proj/board.kicad_pro"
    iface._current_project_path = Path("/proj")
    return iface


@pytest.mark.unit
class TestCloseProject:
    def test_no_project_loaded_is_idempotent(self) -> None:
        pc = _FakeProjectCommands({"success": True})
        iface = _make_interface(board=None, project_commands=pc)

        result = iface._handle_close_project({})

        assert result["success"] is True
        assert result["closed"] is False
        assert pc.save_calls == 0

    def test_close_saves_by_default_and_clears_state(self) -> None:
        board = _FakeBoard("/proj/board.kicad_pcb")
        pc = _FakeProjectCommands({"success": True, "project": {"path": "/proj/board.kicad_pcb"}})
        iface = _make_interface(board=board, project_commands=pc)

        result = iface._handle_close_project({})

        assert result["success"] is True
        assert result["closed"] is True
        assert result["saved"] is True
        assert result["savedPath"] == "/proj/board.kicad_pcb"
        assert pc.save_calls == 1
        # State fully scrubbed, symmetric with a fresh interface.
        assert iface.board is None
        assert iface.ipc_board_api is None
        assert iface.session_backend is None
        assert iface.session_board_path is None
        assert iface._board_disk_signature is None
        assert iface.project_filename is None
        assert iface._current_project_path is None
        # Board reference cleared on every command handler too.
        assert iface.board_commands.board is None
        assert iface.export_commands.board is None

    def test_save_false_on_dirty_board_warns_but_closes(self) -> None:
        board = _FakeBoard("/proj/board.kicad_pcb")
        pc = _FakeProjectCommands({"success": True})
        iface = _make_interface(board=board, project_commands=pc)
        # Make _dirty_state report dirty without touching the disk.
        iface._last_auto_save_status = {"memChangesUnsaved": True}

        result = iface._handle_close_project({"save": False})

        assert result["success"] is True
        assert result["closed"] is True
        assert result["saved"] is False
        assert pc.save_calls == 0
        assert any("discarded" in w for w in result.get("warnings", []))
        assert iface.board is None

    def test_save_failure_refuses_to_close(self) -> None:
        board = _FakeBoard("/proj/board.kicad_pcb")
        pc = _FakeProjectCommands({"success": False, "message": "disk full"})
        iface = _make_interface(board=board, project_commands=pc)

        result = iface._handle_close_project({})

        assert result["success"] is False
        assert result["closed"] is False
        # Board NOT dropped — work is preserved so the caller can retry.
        assert iface.board is board
        assert iface.session_backend == "swig"

    def test_save_exception_refuses_to_close(self) -> None:
        board = _FakeBoard("/proj/board.kicad_pcb")
        pc = _FakeProjectCommands(RuntimeError("boom"))
        iface = _make_interface(board=board, project_commands=pc)

        result = iface._handle_close_project({})

        assert result["success"] is False
        assert result["closed"] is False
        assert "boom" in result["errorDetails"]
        assert iface.board is board
