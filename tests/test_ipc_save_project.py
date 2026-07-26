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
