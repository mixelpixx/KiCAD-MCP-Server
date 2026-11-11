"""A sync_schematic_to_board preview (dryRun) must not save the board.

handle_command auto-saves the loaded board after every command in
_BOARD_MUTATING_COMMANDS, and sync_schematic_to_board is one of them. The
handler itself wrote nothing in a dry run, but the auto-save that followed it
rewrote the board file with whatever unsaved edits the loaded board held, and
left a backup in .mcp-backups, while the reply said "Preview only, nothing
saved". The handler-level tests called the handler directly, so they missed
it. These tests go through handle_command.

A dry run on a loaded board that has no file name used to run the sync on that
board in memory; it is refused instead.
"""

import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    iface.use_ipc = False
    iface.ipc_backend = None
    iface.ipc_board_api = None
    iface.board = None
    iface.session_backend = "swig"
    iface._board_disk_signature = None
    iface._auto_save_backup_keep = 5
    iface._current_project_path = None
    iface._last_auto_save_status = None
    iface._update_command_handlers = lambda: None
    iface._build_hierarchical_pad_net_map = lambda *a, **k: ({}, [])
    iface._add_missing_footprints_from_schematic = lambda *a, **k: ([], [])
    iface._find_kicad_cli_static = lambda: None  # plain callable: a staticmethod object on an instance is not callable before Python 3.10
    iface.command_routes = {"sync_schematic_to_board": iface._handle_sync_schematic_to_board}
    return iface


def _fake_board(path: Path) -> MagicMock:
    board = MagicMock(name="board")
    board.GetFileName.return_value = str(path)
    board.GetFootprints.return_value = []
    board.Save.side_effect = lambda p: Path(p).write_text("(kicad_pcb ; synced)\n")
    return board


@pytest.fixture()
def project(tmp_path: Path):
    pcb = tmp_path / "p.kicad_pcb"
    pcb.write_text("(kicad_pcb ; on disk)\n")
    sch = tmp_path / "p.kicad_sch"
    sch.write_text("(kicad_sch)\n")
    return pcb, sch


def _run(iface: Any, params: dict) -> tuple:
    """handle_command with pcbnew stubbed; returns (result, SaveBoard mock)."""
    with (
        patch("commands.schematic_handlers.pcbnew"),
        patch("commands.schematic_handlers.preserve_project_settings", lambda p: nullcontext()),
        patch("kicad_interface.pcbnew") as mock_pcb,
    ):
        # The auto-save writes the loaded board, unsaved edits included.
        mock_pcb.SaveBoard.side_effect = lambda p, b: Path(p).write_text(
            "(kicad_pcb ; moved footprint)\n"
        )
        result = iface.handle_command("sync_schematic_to_board", params)
    return result, mock_pcb.SaveBoard


@pytest.mark.unit
def test_dry_run_through_handle_command_does_not_auto_save(project) -> None:
    """open_project, move a footprint without saving, sync with dryRun: the
    board file and the backup directory must be exactly as they were."""
    pcb, sch = project
    iface = _make_iface()
    loaded = _fake_board(pcb)  # the loaded board, holding an unsaved move
    iface.board = loaded
    iface._record_board_signature()
    iface._safe_load_board = lambda p: _fake_board(pcb)  # the preview's own copy
    before = pcb.read_bytes()

    result, save_board = _run(iface, {"schematicPath": str(sch), "dryRun": True})

    assert result["success"], result
    assert result["dryRun"] is True
    assert result["message"].startswith("Preview only, nothing saved")
    save_board.assert_not_called()
    loaded.Save.assert_not_called()
    assert pcb.read_bytes() == before
    assert not (pcb.parent / ".mcp-backups").exists()
    assert "autoSave" not in result
    assert iface._last_auto_save_status is None


@pytest.mark.unit
def test_real_sync_through_handle_command_still_auto_saves(project) -> None:
    """Control: without dryRun the auto-save after the sync runs as before."""
    pcb, sch = project
    iface = _make_iface()
    board = _fake_board(pcb)
    iface.board = board
    iface._record_board_signature()
    iface._safe_load_board = lambda p: board

    result, save_board = _run(iface, {"schematicPath": str(sch), "boardPath": str(pcb)})

    assert result["success"], result
    assert result["dryRun"] is False
    board.Save.assert_called_once()
    save_board.assert_called_once()
    assert iface._last_auto_save_status["saved"] is True


@pytest.mark.unit
def test_dry_run_refuses_a_loaded_board_with_no_file_name(project) -> None:
    """With no file to preview against, the sync used to run on the loaded
    board itself and change it in memory. It is refused instead."""
    pcb, sch = project
    iface = _make_iface()
    board = _fake_board(pcb)
    board.GetFileName.return_value = ""
    iface.board = board
    iface._safe_load_board = lambda p: pytest.fail("must not load a board")

    result, save_board = _run(iface, {"schematicPath": str(sch), "dryRun": True})

    assert result["success"] is False
    assert result["dryRun"] is True
    assert "no file name" in result["message"]
    board.GetFootprints.assert_not_called()
    board.Add.assert_not_called()
    board.Save.assert_not_called()
    save_board.assert_not_called()
