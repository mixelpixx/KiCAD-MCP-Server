"""add_board_text applies the style its schema declares (#407).

The zod schema offers ``style`` (``normal`` / ``italic`` / ``bold``) and the
Node tool sends it, but neither the SWIG handler nor the IPC handler read it,
so every text came out upright and regular.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = [pytest.mark.unit, pytest.mark.stub_pcbnew]

import pcbnew as _pcbnew_stub  # noqa: E402

PARAMS = {"text": "REV A", "position": {"x": 10, "y": 20, "unit": "mm"}, "layer": "F.SilkS"}


def _swig_add(**extra):
    from commands.board.outline import BoardOutlineCommands

    board = MagicMock(name="board")
    board.GetLayerID.return_value = 37
    commands = BoardOutlineCommands.__new__(BoardOutlineCommands)
    commands.board = board
    _pcbnew_stub.reset_mock()
    text = MagicMock(name="pcb_text")
    _pcbnew_stub.PCB_TEXT.side_effect = None
    _pcbnew_stub.PCB_TEXT.return_value = text
    return commands.add_text({**PARAMS, **extra}), text, board


@pytest.mark.parametrize(
    "style, bold, italic",
    [
        (None, False, False),
        ("normal", False, False),
        ("bold", True, False),
        ("italic", False, True),
    ],
)
def test_swig_text_gets_the_style(style, bold, italic) -> None:
    extra = {} if style is None else {"style": style}
    result, text, board = _swig_add(**extra)
    assert result["success"] is True, result
    text.SetBold.assert_called_once_with(bold)
    text.SetItalic.assert_called_once_with(italic)
    assert result["text"]["style"] == (style or "normal")
    board.Add.assert_called_once_with(text)


def test_swig_unknown_style_is_refused() -> None:
    result, _, board = _swig_add(style="underline")
    assert result["success"] is False
    assert "style" in result["message"]
    board.Add.assert_not_called()


def _ipc_iface():
    from kicad_interface import KiCADInterface

    iface = KiCADInterface.__new__(KiCADInterface)
    iface.ipc_board_api = MagicMock(name="ipc_board_api")
    iface.ipc_board_api.add_text.return_value = True
    return iface


@pytest.mark.parametrize(
    "style, bold, italic",
    [(None, False, False), ("bold", True, False), ("italic", False, True)],
)
def test_ipc_handler_forwards_the_style(style, bold, italic) -> None:
    iface = _ipc_iface()
    extra = {} if style is None else {"style": style}
    result = iface._ipc_add_text({**PARAMS, **extra})
    assert result["success"] is True, result
    kwargs = iface.ipc_board_api.add_text.call_args.kwargs
    assert (kwargs["bold"], kwargs["italic"]) == (bold, italic)


def test_ipc_unknown_style_is_refused() -> None:
    iface = _ipc_iface()
    result = iface._ipc_add_text({**PARAMS, "style": "underline"})
    assert result["success"] is False
    iface.ipc_board_api.add_text.assert_not_called()
