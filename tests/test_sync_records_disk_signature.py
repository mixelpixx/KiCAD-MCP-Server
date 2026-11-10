"""
sync_schematic_to_board saves the board file itself. Before the fix it did not
record that save, so the auto-save that follows every board-mutating command
compared the file against the pre-sync signature and refused, reporting the
file as "changed externally". Every later mutation in the session was refused
the same way until the project was reopened or save_board was forced.
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
    iface.board = None
    iface._board_disk_signature = None
    iface._auto_save_backup_keep = 5
    iface._update_command_handlers = lambda: None
    iface._build_hierarchical_pad_net_map = lambda *a, **k: ({}, [])
    iface._add_missing_footprints_from_schematic = lambda *a, **k: ([], [])
    return iface


def _fake_board(path: Path) -> MagicMock:
    board = MagicMock(name="board")
    board.GetFileName.return_value = str(path)
    board.GetFootprints.return_value = []
    # The sync writes the file, as pcbnew's BOARD.Save does.
    board.Save.side_effect = lambda p: Path(p).write_text("(kicad_pcb ; synced)\n")
    return board


@pytest.fixture()
def project(tmp_path: Path):
    pcb = tmp_path / "p.kicad_pcb"
    pcb.write_text("(kicad_pcb ; before sync)\n")
    sch = tmp_path / "p.kicad_sch"
    sch.write_text("(kicad_sch)\n")
    return pcb, sch


def _sync(iface: Any, params: dict) -> dict:
    with (
        patch("commands.schematic_handlers.pcbnew"),
        patch("commands.schematic_handlers.preserve_project_settings", lambda p: nullcontext()),
    ):
        return iface._handle_sync_schematic_to_board(params)


@pytest.mark.unit
@pytest.mark.parametrize("pass_board_path", [True, False])
def test_sync_records_its_own_save(project, pass_board_path) -> None:
    pcb, sch = project
    iface = _make_iface()
    board = _fake_board(pcb)
    iface.board = board
    iface._record_board_signature()  # as open_project does
    iface._safe_load_board = lambda p: board

    params = {"schematicPath": str(sch)}
    if pass_board_path:
        params["boardPath"] = str(pcb)
    result = _sync(iface, params)

    assert result["success"], result
    assert "synced" in pcb.read_text()
    assert iface._board_disk_signature == iface._disk_signature(str(pcb))


@pytest.mark.unit
def test_auto_save_after_sync_is_not_refused(project) -> None:
    pcb, sch = project
    iface = _make_iface()
    board = _fake_board(pcb)
    iface.board = board
    iface._record_board_signature()
    iface._safe_load_board = lambda p: board

    assert _sync(iface, {"schematicPath": str(sch), "boardPath": str(pcb)})["success"]

    with patch("kicad_interface.pcbnew") as mock_pcb:
        mock_pcb.SaveBoard.side_effect = lambda p, b: Path(p).write_text("(kicad_pcb ; moved)\n")
        status = iface._auto_save_board()

    assert status["saved"] is True, status
    assert "diskChangedExternally" not in status
