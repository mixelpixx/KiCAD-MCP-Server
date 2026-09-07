"""Regression tests for #399: edit_component's footprint swap only rewrote the FPID.

``edit_component(footprint=...)`` used to call ``module.SetFPID(fpid)`` and stop: the
library-ID string changed but the physical footprint (pads, courtyard, silkscreen) stayed
whatever the component already had. KiCAD then reports ``lib_footprint_mismatch`` plus
unconnected pads once the new and old footprints have a different pad count.

The fix loads the new footprint from the library and exchanges it in place, preserving
reference, value, position, orientation and pad-to-net connectivity (matched by pad
number), mirroring KiCAD's own ``PCB_EDIT_FRAME::ExchangeFootprint()``.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

import pcbnew as _pcbnew_stub  # noqa: E402 (must come after sys.path insert)


def _make_pad(number, net):
    pad = MagicMock(name=f"pad:{number}")
    pad.GetNumber.return_value = number
    pad.GetNet.return_value = net
    return pad


def _make_footprint(reference, value, position, orientation, pads, flipped=False):
    fp = MagicMock(name=f"footprint:{reference}")
    fp.GetReference.return_value = reference
    fp.GetValue.return_value = value
    fp.GetPosition.return_value = position
    fp.GetOrientation.return_value = orientation
    fp.Pads.return_value = pads
    fp.IsFlipped.return_value = flipped
    return fp


def _make_component_commands(old_module, new_module, library_path="/libs/SOT-23.pretty"):
    """Wire a ComponentCommands whose board holds old_module and whose library manager
    resolves any lib name to library_path, with pcbnew.FootprintLoad returning new_module."""
    from commands.component import ComponentCommands

    board = MagicMock(name="board")
    board.FindFootprintByReference.return_value = old_module

    lib_mgr = MagicMock(name="library_manager")
    lib_mgr.get_library_path.return_value = library_path

    cmd = ComponentCommands.__new__(ComponentCommands)
    cmd.board = board
    cmd.library_manager = lib_mgr

    _pcbnew_stub.reset_mock()
    _pcbnew_stub.FootprintLoad.return_value = new_module
    _pcbnew_stub.LIB_ID.side_effect = lambda lib, fp: (lib, fp)
    return cmd, board


class TestFootprintExchange:
    def test_swap_loads_new_footprint_instead_of_only_rewriting_fpid(self):
        old_pads = [_make_pad("1", "net:VCC"), _make_pad("2", "net:GND")]
        old = _make_footprint("D1", "1N4148", (1000, 2000), 900, old_pads)

        new_pads = [_make_pad("1", None), _make_pad("2", None), _make_pad("3", None)]
        new = _make_footprint("SOT-23-proto", "", (0, 0), 0, new_pads)

        cmd, board = _make_component_commands(old, new)

        result = cmd.edit_component(
            {"reference": "D1", "footprint": "Package_TO_SOT_SMD:SOT-23"}
        )

        assert result["success"] is True
        # The loaded footprint was fetched from the library, not fabricated from the FPID.
        _pcbnew_stub.FootprintLoad.assert_called_once_with(
            "/libs/SOT-23.pretty", "SOT-23"
        )
        # It replaced the old footprint on the board rather than mutating it in place.
        board.Add.assert_called_once_with(new)
        board.Delete.assert_called_once_with(old)

    def test_position_reference_and_value_survive_the_swap(self):
        old = _make_footprint("D1", "1N4148", (1000, 2000), 900, [])
        new = _make_footprint("SOT-23-proto", "", (0, 0), 0, [])
        cmd, _board = _make_component_commands(old, new)

        cmd.edit_component({"reference": "D1", "footprint": "Package_TO_SOT_SMD:SOT-23"})

        new.SetReference.assert_called_once_with("D1")
        new.SetValue.assert_called_once_with("1N4148")
        new.SetPosition.assert_called_once_with((1000, 2000))
        new.SetOrientation.assert_called_once_with(900)

    def test_pads_are_reconnected_to_the_old_nets_by_number(self):
        """The prior fix (SetFPID only) left every new pad netless; a maintainer-cited DRC
        symptom was unconnected pads even when the pad count happened to match."""
        old_pads = [_make_pad("1", "net:VCC"), _make_pad("2", "net:GND")]
        old = _make_footprint("D1", "1N4148", (1000, 2000), 900, old_pads)

        new_pad_1 = _make_pad("1", None)
        new_pad_2 = _make_pad("2", None)
        new = _make_footprint("SOT-23-proto", "", (0, 0), 0, [new_pad_1, new_pad_2])

        cmd, _board = _make_component_commands(old, new)
        cmd.edit_component({"reference": "D1", "footprint": "Package_TO_SOT_SMD:SOT-23"})

        new_pad_1.SetNet.assert_called_once_with("net:VCC")
        new_pad_2.SetNet.assert_called_once_with("net:GND")

    def test_extra_pad_on_the_new_footprint_is_left_unset(self):
        """SOT-23 has 3 pads where SOD-323 has 2, the reporter's exact repro shape.
        The unmatched pad number must not raise and must be left without a SetNet call."""
        old_pads = [_make_pad("1", "net:A"), _make_pad("2", "net:K")]
        old = _make_footprint("D1", "1N4148", (0, 0), 0, old_pads)

        new_pads = [_make_pad("1", None), _make_pad("2", None), _make_pad("3", None)]
        new = _make_footprint("SOT-23-proto", "", (0, 0), 0, new_pads)

        cmd, _board = _make_component_commands(old, new)
        result = cmd.edit_component(
            {"reference": "D1", "footprint": "Package_TO_SOT_SMD:SOT-23"}
        )

        assert result["success"] is True
        _pcbnew_stub.FootprintLoad.assert_called_once_with(
            "/libs/SOT-23.pretty", "SOT-23"
        )
        new_pads[2].SetNet.assert_not_called()

    def test_bare_footprint_name_keeps_the_existing_library(self):
        old_fpid = MagicMock()
        old_fpid.GetLibNickname.return_value.GetUTF8.return_value = "Diode_SMD"
        old = _make_footprint("D1", "1N4148", (0, 0), 0, [])
        old.GetFPID.return_value = old_fpid

        new = _make_footprint("proto", "", (0, 0), 0, [])
        cmd, _board = _make_component_commands(old, new)

        cmd.edit_component({"reference": "D1", "footprint": "D_SOD-323"})

        _pcbnew_stub.FootprintLoad.assert_called_once_with(
            "/libs/SOT-23.pretty", "D_SOD-323"
        )

    def test_flipped_component_is_flipped_after_re_add(self):
        """Flip() needs board context in KiCAD 9 (established convention elsewhere in this
        file); calling it before board.Add() would hang, so the new footprint must be
        added to the board first and only flipped afterwards."""
        old = _make_footprint("D1", "1N4148", (0, 0), 0, [], flipped=True)
        new = _make_footprint("proto", "", (0, 0), 0, [], flipped=False)
        cmd, board = _make_component_commands(old, new)

        calls = []
        board.Add.side_effect = lambda *_a: calls.append("add")
        new.Flip.side_effect = lambda *_a, **_k: calls.append("flip")

        cmd.edit_component({"reference": "D1", "footprint": "Package_TO_SOT_SMD:SOT-23"})

        assert calls == ["add", "flip"]

    def test_unknown_library_reports_failure_without_touching_the_board(self):
        old = _make_footprint("D1", "1N4148", (0, 0), 0, [])
        new = _make_footprint("proto", "", (0, 0), 0, [])
        cmd, board = _make_component_commands(old, new, library_path=None)

        result = cmd.edit_component(
            {"reference": "D1", "footprint": "NoSuchLib:Whatever"}
        )

        assert result["success"] is False
        board.Add.assert_not_called()
        board.Delete.assert_not_called()
