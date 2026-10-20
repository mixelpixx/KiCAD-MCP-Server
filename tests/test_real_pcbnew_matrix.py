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


def _add_segment(board, layer, start_mm, end_mm, width_mm=0.25):
    import pcbnew

    track = pcbnew.PCB_TRACK(board) if pcbnew.IsCopperLayer(layer) else pcbnew.PCB_SHAPE(board)
    track.SetLayer(layer)
    track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(start_mm[0]), pcbnew.FromMM(start_mm[1])))
    track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end_mm[0]), pcbnew.FromMM(end_mm[1])))
    track.SetWidth(pcbnew.FromMM(width_mm))
    board.Add(track)


def test_export_gerber_writes_a_file_for_every_reported_layer(tmp_path: Path) -> None:
    import pcbnew
    from commands.export import ExportCommands

    board = pcbnew.BOARD()
    corners = [(0, 0), (20, 0), (20, 10), (0, 10)]
    for start, end in zip(corners, corners[1:] + corners[:1]):
        _add_segment(board, pcbnew.Edge_Cuts, start, end, width_mm=0.1)
    _add_segment(board, pcbnew.F_Cu, (2, 5), (18, 5))

    board_path = tmp_path / "gerber_smoke.kicad_pcb"
    pcbnew.SaveBoard(str(board_path), board)
    board = pcbnew.LoadBoard(str(board_path))

    out_dir = tmp_path / "gerbers"
    result = ExportCommands(board).export_gerber(
        {"outputDir": str(out_dir), "generateDrillFiles": False}
    )

    assert result["success"] is True, result
    assert "F.Cu" in result["files"]["gerber"]
    assert "Edge.Cuts" in result["files"]["gerber"]

    for layer_name in result["files"]["gerber"]:
        gerber = out_dir / f"gerber_smoke-{layer_name.replace('.', '_')}.gbr"
        assert gerber.is_file(), f"{layer_name} reported but {gerber.name} not written"
        # ClosePlot() flushes the file; an unclosed Gerber has no M02 end marker.
        assert gerber.read_text().rstrip().endswith("M02*"), gerber.name

    # D01 is an interpolation: the track and the four outline edges were drawn.
    assert (out_dir / "gerber_smoke-F_Cu.gbr").read_text().count("D01*") == 1
    assert (out_dir / "gerber_smoke-Edge_Cuts.gbr").read_text().count("D01*") == 4
