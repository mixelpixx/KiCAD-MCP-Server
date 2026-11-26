"""edit_component is auto-saved like the other board edits.

handle_command saves the loaded board after every command in
_BOARD_MUTATING_COMMANDS. edit_component was not in it, so a footprint swap
or a value change (also made through replace_component, its alias) reported
success but reached the file only on an explicit save_project, unlike
place_component, move_component or delete_component.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit


def _make_iface(board: MagicMock) -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    iface.use_ipc = False
    iface.ipc_backend = None
    iface.ipc_board_api = None
    iface.board = board
    iface.session_backend = "swig"
    iface._board_disk_signature = None
    iface._auto_save_backup_keep = 5
    iface._current_project_path = None
    iface._last_auto_save_status = None
    iface._update_command_handlers = lambda: None
    iface.command_routes = {
        "edit_component": lambda params: {"success": True, "message": "Updated component: R1"}
    }
    return iface


def test_edit_component_is_a_board_mutating_command() -> None:
    from kicad_interface import KiCADInterface

    assert "edit_component" in KiCADInterface._BOARD_MUTATING_COMMANDS


def test_edit_component_through_handle_command_saves_the_board(tmp_path: Path) -> None:
    pcb = tmp_path / "p.kicad_pcb"
    pcb.write_text("(kicad_pcb ; before)\n")
    board = MagicMock(name="board")
    board.GetFileName.return_value = str(pcb)
    iface = _make_iface(board)
    iface._record_board_signature()

    with patch("kicad_interface.pcbnew") as mock_pcb:
        mock_pcb.SaveBoard.side_effect = lambda p, b: Path(p).write_text(
            "(kicad_pcb ; value changed)\n"
        )
        result = iface.handle_command("edit_component", {"reference": "R1", "value": "4k7"})

    assert result["success"] is True
    mock_pcb.SaveBoard.assert_called_once()
    assert pcb.read_text() == "(kicad_pcb ; value changed)\n"
    assert "autoSave" not in result  # only reported when the save did not happen
