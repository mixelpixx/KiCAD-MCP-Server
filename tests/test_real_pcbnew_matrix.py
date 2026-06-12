import os
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_pcbnew,
    pytest.mark.linux,
]


@pytest.fixture(autouse=True)
def require_real_pcbnew() -> None:
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("real pcbnew smoke tests require KICAD_USE_REAL_PCBNEW=1")


def test_project_commands_create_and_load_board_with_real_pcbnew(tmp_path: Path) -> None:
    import pcbnew

    from commands.project import ProjectCommands

    version = pcbnew.GetBuildVersion()
    assert version
    assert not str(version).endswith("-stub")

    commands = ProjectCommands()
    result = commands.create_project({"name": "matrix_smoke", "path": str(tmp_path)})

    assert result["success"] is True, result

    board_path = Path(result["project"]["boardPath"])
    assert board_path.exists()

    board = pcbnew.LoadBoard(str(board_path))
    assert board is not None
    assert hasattr(board, "GetFileName")
    assert board.GetFileName().endswith(".kicad_pcb")
