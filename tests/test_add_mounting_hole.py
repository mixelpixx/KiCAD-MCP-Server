"""
Regression tests for BoardOutlineCommands.add_mounting_hole.

Covers two prior bugs:

1. Empty FPID
   The footprint was created with no library:name id, producing
   `(footprint "" ...)` in the .kicad_pcb. KiCad's GUI Move tool refuses to
   select footprints with no library link, so users couldn't drag the
   resulting MHs in the editor.

2. NPTH pad on copper layers
   The pad was emitted with the default LSET (`*.Cu` + `*.Mask`) even when
   `plated:false`. With `padDiameter > diameter` that produces phantom
   copper annular rings on every Cu layer, which trigger DRC clearance
   errors against neighbouring nets.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import pcbnew  # noqa: E402  — pcbnew is stubbed by conftest


@pytest.fixture
def fresh_pcbnew_mock(monkeypatch):
    """
    The conftest pcbnew is a long-lived MagicMock. Reset its call history
    before each test so we can make precise assertions about what
    add_mounting_hole calls on the pcbnew API.
    """
    pcbnew.reset_mock()
    # PAD_ATTRIB constants must compare unequal so the conditional in the
    # implementation picks the right branch.
    pcbnew.PAD_ATTRIB_NPTH = "NPTH"
    pcbnew.PAD_ATTRIB_PTH = "PTH"
    pcbnew.PAD_SHAPE_CIRCLE = "circle"
    pcbnew.F_Mask = "F.Mask"
    pcbnew.B_Mask = "B.Mask"
    return pcbnew


@pytest.fixture
def cmds(fresh_pcbnew_mock):
    from commands.board.outline import BoardOutlineCommands

    board = MagicMock(name="board")
    board.GetFootprints.return_value = []  # no existing MHs
    return BoardOutlineCommands(board=board)


def _captured_module(pcbnew_mock):
    """Return the FOOTPRINT mock instance created by the call under test."""
    return pcbnew_mock.FOOTPRINT.return_value


def _captured_pad(pcbnew_mock):
    """Return the PAD mock instance created by the call under test."""
    return pcbnew_mock.PAD.return_value


# ---------------------------------------------------------------------------
# Bug #1: empty FPID
# ---------------------------------------------------------------------------


class TestFootprintLibIdSet:
    def test_default_fpid_uses_diameter(self, cmds, fresh_pcbnew_mock):
        result = cmds.add_mounting_hole(
            {
                "position": {"x": 117, "y": 84.5, "unit": "mm"},
                "diameter": 3.2,
                "padDiameter": 3.5,
            }
        )

        assert result["success"] is True

        # LIB_ID was constructed with a non-empty library and footprint name
        fresh_pcbnew_mock.LIB_ID.assert_called_once_with("MountingHole", "MountingHole_3.2mm")
        # And the FOOTPRINT had its FPID set
        _captured_module(fresh_pcbnew_mock).SetFPID.assert_called_once_with(
            fresh_pcbnew_mock.LIB_ID.return_value
        )
        # The response surfaces the lib id used
        assert result["mountingHole"]["footprintLibId"] == "MountingHole:MountingHole_3.2mm"

    def test_default_fpid_strips_trailing_zeros(self, cmds, fresh_pcbnew_mock):
        cmds.add_mounting_hole(
            {
                "position": {"x": 0, "y": 0, "unit": "mm"},
                "diameter": 3.0,  # would become "3.0mm" with %f, "3" with %g
            }
        )

        # %g formatting: 3.0 → "3"
        fresh_pcbnew_mock.LIB_ID.assert_called_once_with("MountingHole", "MountingHole_3mm")

    def test_explicit_fpid_override(self, cmds, fresh_pcbnew_mock):
        cmds.add_mounting_hole(
            {
                "position": {"x": 50, "y": 50, "unit": "mm"},
                "diameter": 3.2,
                "footprintLibId": "MountingHole:MountingHole_3.2mm_M3",
            }
        )

        fresh_pcbnew_mock.LIB_ID.assert_called_once_with("MountingHole", "MountingHole_3.2mm_M3")

    def test_explicit_fpid_without_colon_falls_back_to_mountinghole_lib(
        self, cmds, fresh_pcbnew_mock
    ):
        cmds.add_mounting_hole(
            {
                "position": {"x": 0, "y": 0, "unit": "mm"},
                "diameter": 2.5,
                "footprintLibId": "MyCustomHole",
            }
        )

        fresh_pcbnew_mock.LIB_ID.assert_called_once_with("MountingHole", "MyCustomHole")


# ---------------------------------------------------------------------------
# Bug #2: NPTH pad layers
# ---------------------------------------------------------------------------


class TestNpthPadLayers:
    def test_npth_pad_layers_are_mask_only(self, cmds, fresh_pcbnew_mock):
        cmds.add_mounting_hole(
            {
                "position": {"x": 117, "y": 84.5, "unit": "mm"},
                "diameter": 3.2,
                "padDiameter": 3.5,
                "plated": False,
            }
        )

        pad = _captured_pad(fresh_pcbnew_mock)

        # The pad must have been set to NPTH attr
        pad.SetAttribute.assert_called_once_with("NPTH")

        # SetLayerSet was called exactly once with an LSET that has
        # F_Mask and B_Mask added — and nothing on Cu layers.
        pad.SetLayerSet.assert_called_once()
        lset_arg = pad.SetLayerSet.call_args.args[0]

        added_layers = [c.args[0] for c in lset_arg.AddLayer.call_args_list]
        assert "F.Mask" in added_layers
        assert "B.Mask" in added_layers
        assert all(
            "Cu" not in str(layer) for layer in added_layers
        ), f"NPTH pad must not include any Cu layers, got: {added_layers}"

    def test_npth_is_default(self, cmds, fresh_pcbnew_mock):
        # Omit `plated` entirely; default must be NPTH.
        cmds.add_mounting_hole(
            {
                "position": {"x": 0, "y": 0, "unit": "mm"},
                "diameter": 3.2,
            }
        )

        pad = _captured_pad(fresh_pcbnew_mock)
        pad.SetAttribute.assert_called_once_with("NPTH")
        pad.SetLayerSet.assert_called_once()

    def test_pth_keeps_default_layers(self, cmds, fresh_pcbnew_mock):
        cmds.add_mounting_hole(
            {
                "position": {"x": 0, "y": 0, "unit": "mm"},
                "diameter": 3.2,
                "padDiameter": 3.5,
                "plated": True,
            }
        )

        pad = _captured_pad(fresh_pcbnew_mock)
        pad.SetAttribute.assert_called_once_with("PTH")

        # For PTH, the default LSET (*.Cu + *.Mask) is correct, so we must
        # NOT override it via SetLayerSet.
        pad.SetLayerSet.assert_not_called()
