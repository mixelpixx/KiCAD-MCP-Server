"""Tests for ``get_board_2d_view`` responseMode parameter.

Two modes are supported:
- ``responseMode="inline"`` (default): image bytes are base64-encoded and returned in the
  ``imageData`` field of the response.  No file is written to disk.
- ``responseMode="file"``: image is written next to the ``.kicad_pcb`` file as
  ``<board_name>_2d_view.<ext>`` and ``filePath`` is returned.  No ``imageData`` field is
  present.
"""

import base64
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FAKE_SVG = b"<svg><rect/></svg>"
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngbytes"


def _make_view_cmd(tmp_path: Path):
    """Build a BoardViewCommands instance with a real PCB file and optional fake board."""
    from commands.board.view import BoardViewCommands

    board_path = tmp_path / "MyBoard.kicad_pcb"
    board_path.write_text("(kicad_pcb)")

    fake_board = MagicMock()
    fake_board.GetFileName.return_value = str(board_path)
    return BoardViewCommands(board=fake_board), tmp_path, board_path


def _patch_kicad_cli(svg_dir: Path):
    """Stubs that make kicad-cli appear to succeed and produce an SVG in svg_dir."""
    svg_path = svg_dir / "MyBoard.svg"
    svg_path.write_bytes(_FAKE_SVG)

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stderr = ""
    fake_result.stdout = ""

    return (
        patch("shutil.which", return_value="/usr/bin/kicad-cli"),
        patch("subprocess.run", return_value=fake_result),
        patch("glob.glob", return_value=[str(svg_path)]),
    )


# ---------------------------------------------------------------------------
# inline mode tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_inline_png_returns_base64_image_data(tmp_path):
    """responseMode='inline' with format='png' returns valid base64 in imageData."""
    cmd, root, board_path = _make_view_cmd(tmp_path)
    w1, w2, w3 = _patch_kicad_cli(root)

    with w1, w2, w3, patch("commands.board.view._svg_to_png", return_value=_FAKE_PNG):
        result = cmd.get_board_2d_view(
            {"pcbPath": str(board_path), "format": "png", "responseMode": "inline"}
        )

    assert result["success"] is True
    assert result["format"] == "png"
    assert "imageData" in result
    assert base64.b64decode(result["imageData"]) == _FAKE_PNG
    assert not (root / "MyBoard_2d_view.png").exists()
    assert "filePath" not in result


@pytest.mark.unit
def test_export_frames_to_board_area(tmp_path):
    """The export drops the drawing sheet and crops to the board area, so a small
    board isn't rendered on a mostly-empty A4 page (kicad-cli's default)."""
    cmd, root, board_path = _make_view_cmd(tmp_path)
    w1, w2, w3 = _patch_kicad_cli(root)
    with w1, w2 as run, w3, patch("commands.board.view._svg_to_png", return_value=_FAKE_PNG):
        cmd.get_board_2d_view({"pcbPath": str(board_path), "format": "png"})
    argv = run.call_args[0][0]
    assert "--exclude-drawing-sheet" in argv
    assert argv[argv.index("--page-size-mode") + 1] == "2"


@pytest.mark.unit
def test_inline_svg_returns_base64_image_data(tmp_path):
    """responseMode='inline' with format='svg' returns base64-encoded SVG in imageData."""
    cmd, root, board_path = _make_view_cmd(tmp_path)
    w1, w2, w3 = _patch_kicad_cli(root)

    with w1, w2, w3:
        result = cmd.get_board_2d_view(
            {"pcbPath": str(board_path), "format": "svg", "responseMode": "inline"}
        )

    assert result["success"] is True
    assert result["format"] == "svg"
    assert "imageData" in result
    assert base64.b64decode(result["imageData"]) == _FAKE_SVG
    assert "filePath" not in result


@pytest.mark.unit
def test_default_response_mode_is_inline(tmp_path):
    """Omitting responseMode defaults to inline behavior (imageData, no filePath)."""
    cmd, root, board_path = _make_view_cmd(tmp_path)
    w1, w2, w3 = _patch_kicad_cli(root)

    with w1, w2, w3, patch("commands.board.view._svg_to_png", return_value=_FAKE_PNG):
        result = cmd.get_board_2d_view({"pcbPath": str(board_path), "format": "png"})

    assert result["success"] is True
    assert "imageData" in result
    assert "filePath" not in result


# ---------------------------------------------------------------------------
# file mode tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_mode_svg_writes_file_and_returns_path(tmp_path):
    """responseMode='file' with format='svg' writes the file and returns filePath."""
    cmd, root, board_path = _make_view_cmd(tmp_path)
    w1, w2, w3 = _patch_kicad_cli(root)

    with w1, w2, w3:
        result = cmd.get_board_2d_view(
            {"pcbPath": str(board_path), "format": "svg", "responseMode": "file"}
        )

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
    cmd, root, board_path = _make_view_cmd(tmp_path)
    w1, w2, w3 = _patch_kicad_cli(root)

    with w1, w2, w3, patch("commands.board.view._svg_to_png", return_value=_FAKE_PNG):
        result = cmd.get_board_2d_view(
            {"pcbPath": str(board_path), "format": "png", "responseMode": "file"}
        )

    assert result["success"] is True
    assert result["format"] == "png"
    expected = root / "MyBoard_2d_view.png"
    assert Path(result["filePath"]).resolve() == expected.resolve()
    assert expected.exists()
    assert expected.read_bytes() == _FAKE_PNG
    assert "imageData" not in result


# ---------------------------------------------------------------------------
# KiCad 10 kicad-cli compatibility (issue #209)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kicad10_exit_code_2_with_svg_produced_is_success(tmp_path):
    """KiCad 9+/10 returns exit code 2 on a deprecation warning even when the SVG
    is written. Success must be judged by the produced SVG, not the exit code."""
    cmd, root, board_path = _make_view_cmd(tmp_path)
    svg_path = root / "MyBoard.svg"
    svg_path.write_bytes(_FAKE_SVG)

    fake_result = MagicMock()
    fake_result.returncode = 2  # deprecation warning exit code
    fake_result.stderr = "This command has deprecated behavior as of KiCad 9.0..."
    fake_result.stdout = "Done."

    with (
        patch("shutil.which", return_value="/usr/bin/kicad-cli"),
        patch("subprocess.run", return_value=fake_result),
        patch("glob.glob", return_value=[str(svg_path)]),
    ):
        result = cmd.get_board_2d_view(
            {"pcbPath": str(board_path), "format": "svg", "responseMode": "inline"}
        )

    assert result["success"] is True
    assert base64.b64decode(result["imageData"]) == _FAKE_SVG


@pytest.mark.unit
def test_kicad10_export_cmd_uses_file_output_and_mode_single(tmp_path):
    """The export command must pass a FILE path to --output (not a directory) and
    include --mode-single, as required by KiCad 10."""
    cmd, root, board_path = _make_view_cmd(tmp_path)
    svg_path = root / "MyBoard.svg"
    svg_path.write_bytes(_FAKE_SVG)

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stderr = ""
    fake_result.stdout = ""

    with (
        patch("shutil.which", return_value="/usr/bin/kicad-cli"),
        patch("subprocess.run", return_value=fake_result) as run_mock,
        patch("glob.glob", return_value=[str(svg_path)]),
    ):
        cmd.get_board_2d_view(
            {"pcbPath": str(board_path), "format": "svg", "responseMode": "inline"}
        )

    argv = run_mock.call_args[0][0]
    assert "--mode-single" in argv
    out_idx = argv.index("--output")
    out_arg = argv[out_idx + 1]
    assert out_arg.endswith(".svg")  # a file path, not a directory
