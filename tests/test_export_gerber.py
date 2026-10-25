"""Regression tests for export_gerber writing no Gerber files on the SWIG backend.

PLOT_CONTROLLER.PlotLayer() draws into the plot file that is currently open; with
none open it returns False and writes nothing. export_gerber called SetLayer() and
PlotLayer() for every layer but never OpenPlotfile() or ClosePlot(), so no .gbr
file reached the disk (only the kicad-cli drill files did) while the response
still listed every layer as exported.

These stub-mode tests pin the call sequence against a mock plot controller. The
real-pcbnew smoke test in test_real_pcbnew_matrix.py checks the files on disk.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

PLOT_CALLS = ("SetLayer", "OpenPlotfile", "PlotLayer", "ClosePlot")

# Layer IDs as KiCad 10 numbers them; only their identity matters here.
LAYERS = {"F.Cu": 0, "B.Cu": 2, "Edge.Cuts": 25}


@pytest.fixture()
def plotter(monkeypatch):
    """A fresh mock PLOT_CONTROLLER instance for the stubbed pcbnew module."""
    import pcbnew

    instance = MagicMock(name="plotter")
    monkeypatch.setattr(pcbnew, "PLOT_CONTROLLER", MagicMock(return_value=instance))
    monkeypatch.setattr(pcbnew, "PCB_LAYER_ID_COUNT", 30, raising=False)
    return instance


def _commands():
    from commands.export import ExportCommands

    board = MagicMock(name="board")
    board.GetLayerID.side_effect = lambda name: LAYERS.get(name, -1)
    board.IsLayerEnabled.side_effect = lambda layer_id: layer_id in LAYERS.values()
    board.GetLayerName.side_effect = {v: k for k, v in LAYERS.items()}.get
    return ExportCommands(board)


def _plot_sequence(plotter):
    return [c for c in plotter.mock_calls if c[0] in PLOT_CALLS]


def _expected_sequence(layer_names):
    import pcbnew

    expected = []
    for name in layer_names:
        expected += [
            call.SetLayer(LAYERS[name]),
            call.OpenPlotfile(name.replace(".", "_"), pcbnew.PLOT_FORMAT_GERBER, name),
            call.PlotLayer(),
        ]
    return expected + [call.ClosePlot()]


@pytest.mark.unit
def test_requested_layers_each_get_their_own_plot_file(plotter, tmp_path):
    result = _commands().export_gerber(
        {
            "outputDir": str(tmp_path),
            "layers": ["F.Cu", "Edge.Cuts"],
            "generateDrillFiles": False,
        }
    )

    assert result["success"] is True, result
    assert result["files"]["gerber"] == ["F.Cu", "Edge.Cuts"]
    assert _plot_sequence(plotter) == _expected_sequence(["F.Cu", "Edge.Cuts"])


@pytest.mark.unit
def test_all_enabled_layers_each_get_their_own_plot_file(plotter, tmp_path):
    result = _commands().export_gerber({"outputDir": str(tmp_path), "generateDrillFiles": False})

    assert result["success"] is True, result
    assert result["files"]["gerber"] == ["F.Cu", "B.Cu", "Edge.Cuts"]
    assert _plot_sequence(plotter) == _expected_sequence(["F.Cu", "B.Cu", "Edge.Cuts"])


@pytest.mark.unit
def test_unknown_layer_opens_no_plot_file(plotter, tmp_path):
    result = _commands().export_gerber(
        {
            "outputDir": str(tmp_path),
            "layers": ["F.Cu", "No.Such.Layer"],
            "generateDrillFiles": False,
        }
    )

    assert result["success"] is True, result
    assert result["files"]["gerber"] == ["F.Cu"]
    assert _plot_sequence(plotter) == _expected_sequence(["F.Cu"])
