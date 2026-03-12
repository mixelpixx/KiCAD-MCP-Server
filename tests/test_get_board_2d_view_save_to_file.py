"""Test that ``get_board_2d_view`` writes the rendered image to a file
next to the PCB instead of returning base64-encoded data inline.

The original implementation returned the rendered PNG/JPG/SVG inside the
JSON response as ``imageData`` (base64), which routinely exceeded MCP
message-size limits on real boards. The change writes
``<board_name>_2d_view.<ext>`` next to the ``.kicad_pcb`` and returns a
``filePath`` pointing at it.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_view_cmd(tmp_path: Path):
    """Build a BoardViewCommands instance with a fake board."""
    from commands.board.view import BoardViewCommands

    board_path = tmp_path / "MyBoard.kicad_pcb"
    board_path.write_text("(kicad_pcb)")

    fake_board = MagicMock()
    fake_board.GetFileName.return_value = str(board_path)
    return BoardViewCommands(board=fake_board), tmp_path


def _patched_plotter(temp_svg: Path):
    """Return a context manager that patches PLOT_CONTROLLER to write the
    given temp SVG when ClosePlot is called.
    """
    plotter = MagicMock()
    plotter.GetPlotFileName.return_value = str(temp_svg)
    plotter.OpenPlotfile.return_value = True
    plot_options = MagicMock()
    plotter.GetPlotOptions.return_value = plot_options
    return patch("commands.board.view.pcbnew.PLOT_CONTROLLER", return_value=plotter)


def test_svg_format_writes_file_next_to_pcb(tmp_path):
    cmd, root = _make_view_cmd(tmp_path)
    temp_svg = root / "scratch.svg"
    temp_svg.write_text("<svg/>")

    with _patched_plotter(temp_svg):
        result = cmd.get_board_2d_view({"format": "svg"})

    assert result["success"] is True
    assert result["format"] == "svg"
    expected = root / "MyBoard_2d_view.svg"
    assert Path(result["filePath"]).resolve() == expected.resolve()
    assert expected.exists()
    # Old contract removed
    assert "imageData" not in result


def test_png_format_writes_file_next_to_pcb(tmp_path):
    cmd, root = _make_view_cmd(tmp_path)
    temp_svg = root / "scratch.svg"
    temp_svg.write_text("<svg/>")

    fake_png_bytes = b"\x89PNG\r\n\x1a\n" + b"fakeimagebytes"

    with (
        _patched_plotter(temp_svg),
        patch("cairosvg.svg2png", return_value=fake_png_bytes, create=True),
    ):
        # cairosvg is imported lazily inside the function, install a stub if missing
        if "cairosvg" not in sys.modules:
            sys.modules["cairosvg"] = MagicMock(svg2png=lambda **kwargs: fake_png_bytes)
        result = cmd.get_board_2d_view({"format": "png", "width": 1000, "height": 800})

    assert result["success"] is True
    assert result["format"] == "png"
    expected = root / "MyBoard_2d_view.png"
    assert Path(result["filePath"]).resolve() == expected.resolve()
    assert expected.exists()
    assert expected.read_bytes() == fake_png_bytes
    assert "imageData" not in result
