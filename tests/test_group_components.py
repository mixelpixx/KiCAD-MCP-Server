"""group_components creates a PCB group (#407).

The tool was registered on the Node side, but no Python command answered it,
so every call failed with "unknown command". The handler creates a
``PCB_GROUP`` named ``groupName`` that holds the given footprints. Nothing is
created unless every reference is found and none is already in a group.

These tests run against the pcbnew stub; the real-board check is done by hand
on KiCad before merging, as for #544.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = [pytest.mark.unit, pytest.mark.stub_pcbnew]

import pcbnew as _pcbnew_stub  # noqa: E402


def _footprint(reference: str, group=None) -> MagicMock:
    fp = MagicMock(name=f"footprint:{reference}")
    fp.GetReference.return_value = reference
    fp.GetParentGroup.return_value = group
    return fp


def _commands(*footprints: MagicMock):
    from commands.component import ComponentCommands

    by_ref = {fp.GetReference.return_value: fp for fp in footprints}
    board = MagicMock(name="board")
    board.FindFootprintByReference.side_effect = by_ref.get

    cmd = ComponentCommands.__new__(ComponentCommands)
    cmd.board = board
    cmd.library_manager = MagicMock(name="library_manager")

    _pcbnew_stub.reset_mock()
    group = MagicMock(name="group")
    group.m_Uuid.AsString.return_value = "0b4a7c1e-0000-4000-8000-000000000001"
    _pcbnew_stub.PCB_GROUP.side_effect = None
    _pcbnew_stub.PCB_GROUP.return_value = group
    return cmd, board, group


def test_groups_the_footprints_under_the_name() -> None:
    r1, r2, c1 = _footprint("R1"), _footprint("R2"), _footprint("C1")
    cmd, board, group = _commands(r1, r2, c1)

    result = cmd.group_components({"references": ["R1", "R2", "C1"], "groupName": "Input filter"})

    assert result["success"] is True, result
    _pcbnew_stub.PCB_GROUP.assert_called_once_with(board)
    group.SetName.assert_called_once_with("Input filter")
    board.Add.assert_called_once_with(group)
    assert [c.args[0] for c in group.AddItem.call_args_list] == [r1, r2, c1]
    assert result["groupName"] == "Input filter"
    assert result["references"] == ["R1", "R2", "C1"]
    assert result["uuid"] == "0b4a7c1e-0000-4000-8000-000000000001"


def test_a_repeated_reference_is_added_once() -> None:
    r1, r2 = _footprint("R1"), _footprint("R2")
    cmd, _, group = _commands(r1, r2)

    result = cmd.group_components({"references": ["R1", "R2", "R1"], "groupName": "G"})

    assert result["success"] is True, result
    assert group.AddItem.call_count == 2
    assert result["references"] == ["R1", "R2"]


def test_a_missing_reference_creates_nothing_and_is_named() -> None:
    cmd, board, _ = _commands(_footprint("R1"))

    result = cmd.group_components({"references": ["R1", "R7", "U9"], "groupName": "G"})

    assert result["success"] is False
    assert "R7" in result["message"] and "U9" in result["message"]
    assert result["missing"] == ["R7", "U9"]
    _pcbnew_stub.PCB_GROUP.assert_not_called()
    board.Add.assert_not_called()


def test_a_footprint_already_in_a_group_creates_nothing() -> None:
    existing = MagicMock(name="existing-group")
    existing.GetName.return_value = "Power"
    cmd, board, _ = _commands(_footprint("R1"), _footprint("U1", group=existing))

    result = cmd.group_components({"references": ["R1", "U1"], "groupName": "G"})

    assert result["success"] is False
    assert "U1" in result["message"] and "Power" in result["message"]
    _pcbnew_stub.PCB_GROUP.assert_not_called()
    board.Add.assert_not_called()


@pytest.mark.parametrize(
    "params",
    [
        {"groupName": "G"},
        {"references": [], "groupName": "G"},
        {"references": "R1", "groupName": "G"},
        {"references": ["R1", ""], "groupName": "G"},
        {"references": ["R1"]},
        {"references": ["R1"], "groupName": "  "},
    ],
)
def test_bad_parameters_are_refused(params: dict) -> None:
    cmd, board, _ = _commands(_footprint("R1"))

    result = cmd.group_components(params)

    assert result["success"] is False
    board.Add.assert_not_called()


def test_no_board_loaded() -> None:
    cmd, _, _ = _commands()
    cmd.board = None

    result = cmd.group_components({"references": ["R1"], "groupName": "G"})

    assert result["success"] is False
    assert result["message"] == "No board is loaded"


def test_routed_and_saved_like_other_board_edits() -> None:
    from kicad_interface import KiCADInterface

    assert "group_components" in KiCADInterface._BOARD_MUTATING_COMMANDS
