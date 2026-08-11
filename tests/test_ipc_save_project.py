from pathlib import Path
from unittest.mock import MagicMock

import pytest
from kicad_api.ipc_backend import IPCBackend


@pytest.mark.unit
def test_save_project_passes_overwrite_to_board_save_as(tmp_path):
    destination = tmp_path / "existing.kicad_pcb"
    destination.write_text("(existing-board)")
    board = MagicMock()
    backend = IPCBackend()
    backend._connected = True
    backend._kicad = MagicMock()
    backend._kicad.get_board.return_value = board

    result = backend.save_project(Path(destination), overwrite=True)

    assert result["success"] is True
    board.save_as.assert_called_once_with(str(destination), overwrite=True)


@pytest.mark.unit
def test_save_project_preserves_overwrite_false(tmp_path):
    destination = tmp_path / "existing.kicad_pcb"
    destination.write_text("(existing-board)")
    board = MagicMock()
    backend = IPCBackend()
    backend._connected = True
    backend._kicad = MagicMock()
    backend._kicad.get_board.return_value = board

    result = backend.save_project(Path(destination), overwrite=False)

    assert result["success"] is True
    board.save_as.assert_called_once_with(str(destination), overwrite=False)


@pytest.mark.unit
def test_save_project_reports_false_from_ipc_save_as(tmp_path):
    destination = tmp_path / "new.kicad_pcb"
    board = MagicMock()
    board.save_as.return_value = False
    backend = IPCBackend()
    backend._connected = True
    backend._kicad = MagicMock()
    backend._kicad.get_board.return_value = board

    result = backend.save_project(Path(destination), overwrite=False)

    assert result["success"] is False
    assert "returned false" in result["errorDetails"]


@pytest.mark.unit
def test_save_current_project_reports_false_from_ipc_save():
    board = MagicMock()
    board.save.return_value = False
    backend = IPCBackend()
    backend._connected = True
    backend._kicad = MagicMock()
    backend._kicad.get_board.return_value = board

    result = backend.save_project()

    assert result["success"] is False
    assert "returned false" in result["errorDetails"]
