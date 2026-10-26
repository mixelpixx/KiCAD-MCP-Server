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


def _courtyard_footprint(pcbnew, board, ref, rects_mm, at_mm):
    """Footprint whose F.CrtYd is the given rectangles (mm, relative)."""
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference(ref)
    for x1, y1, x2, y2 in rects_mm:
        shape = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_RECT)
        shape.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
        shape.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
        shape.SetLayer(pcbnew.F_CrtYd)
        shape.SetWidth(pcbnew.FromMM(0.05))
        fp.Add(shape)
    board.Add(fp)
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(at_mm[0]), pcbnew.FromMM(at_mm[1])))
    fp.BuildCourtyardCaches()
    return fp


def test_check_courtyard_overlaps_uses_each_courtyard_outline_with_real_pcbnew() -> None:
    """#406: a part between two disjoint courtyard outlines is not an overlap."""
    import pcbnew
    from commands.component import ComponentCommands

    board = pcbnew.BOARD()
    # Two header rows 20 x 2 mm with 8 mm free between them (y 12..20).
    module = _courtyard_footprint(pcbnew, board, "A1", [(0, 0, 20, 2), (0, 10, 20, 12)], (10, 10))
    _courtyard_footprint(pcbnew, board, "R1", [(-1, -0.5, 1, 0.5)], (20, 16))

    assert module.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() == 2

    commands = ComponentCommands(board=board)
    boxes = commands._footprint_courtyard_outline_boxes(module, None)
    assert boxes is not None and len(boxes) == 2
    # One box per header row, with the gap between them left out ...
    upper, lower = sorted(boxes, key=lambda b: b[1])
    assert upper[3] < 13 and lower[1] > 19, boxes
    # ... and together they span exactly the combined courtyard bbox, so
    # per-outline boxes can only drop overlaps the combined box reported.
    union = (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
    assert union == pytest.approx(commands._footprint_courtyard_bbox(module, None))

    clear = commands.check_courtyard_overlaps({"include_boundary": False})
    assert clear["success"] is True, clear
    assert clear["overlaps"] == []

    # Virtually move R1 onto the second row: now it is an overlap.
    hit = commands.check_courtyard_overlaps(
        {"include_boundary": False, "positions": {"R1": [20.0, 20.5]}}
    )
    assert [{o["a"], o["b"]} for o in hit["overlaps"]] == [{"A1", "R1"}]


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


def _plot_smoke_board(tmp_path: Path):
    import pcbnew

    board = pcbnew.BOARD()
    corners = [(0, 0), (20, 0), (20, 10), (0, 10)]
    for start, end in zip(corners, corners[1:] + corners[:1]):
        _add_segment(board, pcbnew.Edge_Cuts, start, end, width_mm=0.1)
    _add_segment(board, pcbnew.F_Cu, (2, 5), (18, 5))
    board_path = tmp_path / "plot_smoke.kicad_pcb"
    pcbnew.SaveBoard(str(board_path), board)
    return pcbnew.LoadBoard(str(board_path))


def test_export_svg_writes_the_file_it_reports(tmp_path: Path) -> None:
    from commands.export import ExportCommands

    board = _plot_smoke_board(tmp_path)
    result = ExportCommands(board).export_svg(
        {"outputPath": str(tmp_path / "out" / "board.svg"), "layers": ["F.Cu", "Edge.Cuts"]}
    )

    assert result["success"] is True, result
    svg = Path(result["file"]["path"])
    assert svg.name == "plot_smoke-board.svg"
    assert svg.is_file()
    assert "</svg>" in svg.read_text()  # ClosePlot() finished the document


def test_export_pdf_writes_the_file_it_reports(tmp_path: Path) -> None:
    from commands.export import ExportCommands

    board = _plot_smoke_board(tmp_path)
    result = ExportCommands(board).export_pdf({"outputPath": str(tmp_path / "out" / "board.pdf")})

    assert result["success"] is True, result
    pdf = Path(result["file"]["path"])
    assert pdf.name == "plot_smoke-board.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
