"""Tests for ``get_board_2d_view`` responseMode parameter.

Two modes are supported:
- ``responseMode="inline"`` (default): image bytes are base64-encoded and returned in the
  ``imageData`` field of the response.  No file is written to disk.
- ``responseMode="file"``: image is written next to the ``.kicad_pcb`` file as
  ``<board_name>_2d_view.<ext>`` and ``filePath`` is returned.  No ``imageData`` field is
  present.
"""

import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_view_cmd(tmp_path: Path):
    """Build a BoardViewCommands instance with a fake board."""
    from commands.board.view import BoardViewCommands

    board_path = tmp_path / "MyBoard.kicad_pcb"
    board_path.write_text("(kicad_pcb)")

    fake_board = MagicMock()
    fake_board.GetFileName.return_value = str(board_path)
    return BoardViewCommands(board=fake_board), tmp_path


def _patched_plotter(temp_svg: Path):
    """Context manager that stubs PLOT_CONTROLLER to return the given temp SVG path."""
    plotter = MagicMock()
    plotter.GetPlotFileName.return_value = str(temp_svg)
    plotter.OpenPlotfile.return_value = True
    plotter.GetPlotOptions.return_value = MagicMock()
    return patch("commands.board.view.pcbnew.PLOT_CONTROLLER", return_value=plotter)


_FAKE_SVG = b"<svg><rect/></svg>"
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngbytes"


def _install_cairosvg_stub(png_bytes: bytes) -> None:
    """Inject a cairosvg stub into sys.modules if the real library is absent."""
    if "cairosvg" not in sys.modules:
        stub = MagicMock()
        stub.svg2png.return_value = png_bytes
        sys.modules["cairosvg"] = stub


# ---------------------------------------------------------------------------
# inline mode tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_inline_png_returns_base64_image_data(tmp_path):
    """responseMode='inline' with format='png' returns valid base64 in imageData."""
    cmd, root = _make_view_cmd(tmp_path)
    temp_svg = root / "scratch.svg"
    temp_svg.write_bytes(_FAKE_SVG)
    _install_cairosvg_stub(_FAKE_PNG)

    with (
        _patched_plotter(temp_svg),
        patch("cairosvg.svg2png", return_value=_FAKE_PNG, create=True),
    ):
        result = cmd.get_board_2d_view({"format": "png", "responseMode": "inline"})

    assert result["success"] is True
    assert result["format"] == "png"
    assert "imageData" in result
    decoded = base64.b64decode(result["imageData"])
    assert decoded == _FAKE_PNG
    # No file should have been written for inline mode
    assert not (root / "MyBoard_2d_view.png").exists()
    assert "filePath" not in result


@pytest.mark.unit
def test_inline_svg_returns_base64_image_data(tmp_path):
    """responseMode='inline' with format='svg' returns valid base64 in imageData."""
    cmd, root = _make_view_cmd(tmp_path)
    temp_svg = root / "scratch.svg"
    temp_svg.write_bytes(_FAKE_SVG)

    with _patched_plotter(temp_svg):
        result = cmd.get_board_2d_view({"format": "svg", "responseMode": "inline"})

    assert result["success"] is True
    assert result["format"] == "svg"
    assert "imageData" in result
    decoded = base64.b64decode(result["imageData"])
    assert decoded == _FAKE_SVG
    assert "filePath" not in result


@pytest.mark.unit
def test_default_response_mode_is_inline(tmp_path):
    """Omitting responseMode defaults to inline behavior (imageData, no filePath)."""
    cmd, root = _make_view_cmd(tmp_path)
    temp_svg = root / "scratch.svg"
    temp_svg.write_bytes(_FAKE_SVG)
    _install_cairosvg_stub(_FAKE_PNG)

    with (
        _patched_plotter(temp_svg),
        patch("cairosvg.svg2png", return_value=_FAKE_PNG, create=True),
    ):
        result = cmd.get_board_2d_view({"format": "png"})

    assert result["success"] is True
    assert "imageData" in result
    assert "filePath" not in result


# ---------------------------------------------------------------------------
# file mode tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_mode_svg_writes_file_and_returns_path(tmp_path):
    """responseMode='file' with format='svg' writes the file and returns filePath."""
    cmd, root = _make_view_cmd(tmp_path)
    temp_svg = root / "scratch.svg"
    temp_svg.write_bytes(_FAKE_SVG)

    with _patched_plotter(temp_svg):
        result = cmd.get_board_2d_view({"format": "svg", "responseMode": "file"})

    assert result["success"] is True
    assert result["format"] == "svg"
    expected = root / "MyBoard_2d_view.svg"
    assert Path(result["filePath"]).resolve() == expected.resolve()
    assert expected.exists()
    assert expected.read_bytes() == _FAKE_SVG
    assert "imageData" not in result


@pytest.mark.unit
def test_file_mode_png_writes_file_and_returns_path(tmp_path):
    """responseMode='file' with format='png' writes the PNG and returns filePath."""
    cmd, root = _make_view_cmd(tmp_path)
    temp_svg = root / "scratch.svg"
    temp_svg.write_bytes(_FAKE_SVG)
    _install_cairosvg_stub(_FAKE_PNG)

    with (
        _patched_plotter(temp_svg),
        patch("cairosvg.svg2png", return_value=_FAKE_PNG, create=True),
    ):
        result = cmd.get_board_2d_view({"format": "png", "responseMode": "file"})

    assert result["success"] is True
    assert result["format"] == "png"
    expected = root / "MyBoard_2d_view.png"
    assert Path(result["filePath"]).resolve() == expected.resolve()
    assert expected.exists()
    assert expected.read_bytes() == _FAKE_PNG
    assert "imageData" not in result
