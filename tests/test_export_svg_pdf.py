"""Regression tests for export_svg writing no file on the SWIG backend (#467).

PLOT_CONTROLLER.PlotLayer() draws into the plot file that is currently open; with
none open it writes nothing. export_svg never called OpenPlotfile() or
ClosePlot(), so no SVG reached the disk while the response reported success:
the export_gerber bug of #455, in a second exporter.

Both export_svg and export_pdf now report the file KiCad actually wrote
(``<board>-<name>.<ext>``, from GetPlotFileName()) and fail when it is missing.
These stub tests pin that behaviour; the real-pcbnew smoke tests in
test_real_pcbnew_matrix.py check the files on disk.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

PLOT_CALLS = ("SetLayer", "OpenPlotfile", "PlotLayer", "ClosePlot")
LAYERS = {"F.Cu": 0, "B.Cu": 2, "Edge.Cuts": 25}


@pytest.fixture()
def plotter(monkeypatch):
    import pcbnew

    instance = MagicMock(name="plotter")
    instance.OpenPlotfile.return_value = True
    instance.PlotLayer.return_value = True
    monkeypatch.setattr(pcbnew, "PLOT_CONTROLLER", MagicMock(return_value=instance))
    monkeypatch.setattr(pcbnew, "PCB_LAYER_ID_COUNT", 30, raising=False)
    return instance


def _commands():
    from commands.export import ExportCommands

    board = MagicMock(name="board")
    board.GetLayerID.side_effect = lambda name: LAYERS.get(name, -1)
    board.IsLayerEnabled.side_effect = lambda layer_id: layer_id in LAYERS.values()
    board.GetLayerName.side_effect = {v: k for k, v in LAYERS.items()}.get
    board.GetFileName.return_value = "/boards/demo.kicad_pcb"
    return ExportCommands(board)


def _sequence(plotter):
    return [c for c in plotter.mock_calls if c[0] in PLOT_CALLS]


@pytest.mark.unit
def test_svg_opens_one_plot_file_for_all_layers_and_closes_it(plotter, tmp_path):
    import pcbnew

    written = tmp_path / "demo-board.svg"
    written.write_text("<svg/>")
    plotter.GetPlotFileName.return_value = str(written)

    result = _commands().export_svg(
        {"outputPath": str(tmp_path / "board.svg"), "layers": ["F.Cu", "Edge.Cuts"]}
    )

    assert result["success"] is True, result
    assert _sequence(plotter) == [
        call.OpenPlotfile("board", pcbnew.PLOT_FORMAT_SVG, ""),
        call.SetLayer(0),
        call.PlotLayer(),
        call.SetLayer(25),
        call.PlotLayer(),
        call.ClosePlot(),
    ]
    assert result["file"]["path"] == str(written)
    assert result["file"]["requestedPath"] == str(tmp_path / "board.svg")
    assert result["file"]["layers"] == ["F.Cu", "Edge.Cuts"]


@pytest.mark.unit
def test_svg_fails_when_no_file_was_written(plotter, tmp_path):
    plotter.GetPlotFileName.return_value = str(tmp_path / "demo-board.svg")  # never created

    result = _commands().export_svg({"outputPath": str(tmp_path / "board.svg")})

    assert result["success"] is False
    assert "was not written" in result["errorDetails"]


@pytest.mark.unit
def test_svg_fails_when_no_layer_was_plotted(plotter, tmp_path):
    written = tmp_path / "demo-board.svg"
    written.write_text("<svg/>")
    plotter.GetPlotFileName.return_value = str(written)

    result = _commands().export_svg(
        {"outputPath": str(tmp_path / "board.svg"), "layers": ["Nope.Layer"]}
    )

    assert result["success"] is False
    assert result["errorDetails"] == "No layer was plotted"


@pytest.mark.unit
def test_svg_fails_when_kicad_cannot_open_the_plot_file(plotter, tmp_path):
    plotter.OpenPlotfile.return_value = False

    result = _commands().export_svg({"outputPath": str(tmp_path / "board.svg")})

    assert result["success"] is False
    plotter.PlotLayer.assert_not_called()


@pytest.mark.unit
def test_pdf_reports_the_file_kicad_wrote(plotter, tmp_path):
    written = tmp_path / "demo-board.pdf"
    written.write_bytes(b"%PDF")
    plotter.GetPlotFileName.return_value = str(written)

    result = _commands().export_pdf({"outputPath": str(tmp_path / "board.pdf")})

    assert result["success"] is True, result
    assert result["file"]["path"] == str(written)


@pytest.mark.unit
def test_pdf_fails_when_no_file_was_written(plotter, tmp_path):
    plotter.GetPlotFileName.return_value = str(tmp_path / "demo-board.pdf")

    result = _commands().export_pdf({"outputPath": str(tmp_path / "board.pdf")})

    assert result["success"] is False
    assert "was not written" in result["errorDetails"]


@pytest.mark.unit
def test_plot_file_name_falls_back_to_kicads_naming(tmp_path):
    from commands.export import _plot_file_name

    plotter = MagicMock(spec=[])  # no GetPlotFileName
    board = MagicMock()
    board.GetFileName.return_value = "/boards/demo.kicad_pcb"

    name = _plot_file_name(plotter, board, str(tmp_path / "x.svg"), "x", "svg")

    assert name == str(tmp_path / "demo-x.svg")
