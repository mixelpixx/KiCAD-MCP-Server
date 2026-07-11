"""Unit tests for the ``set_footprint_type`` command.

Tests exercise both the SWIG-path handler (``ComponentCommands.set_footprint_type``)
and the IPC-path handler (``KiCADInterface._ipc_set_footprint_type``).

conftest.py pre-installs a MagicMock for ``pcbnew`` in sys.modules; these tests
configure the relevant attribute constants on that mock so that component.py can
run without a real KiCAD install.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

# The conftest.py-installed pcbnew MagicMock is already in sys.modules.
# We set the FP_* integer constants we need once at module level so they are
# stable for the life of the test session (conftest doesn't reset them).
import pcbnew as _pcbnew_stub  # noqa: E402 — must come after sys.path insert

_pcbnew_stub.FP_THROUGH_HOLE = 1
_pcbnew_stub.FP_SMD = 2
_pcbnew_stub.FP_EXCLUDE_FROM_POS_FILES = 4
_pcbnew_stub.FP_EXCLUDE_FROM_BOM = 8
_pcbnew_stub.FP_BOARD_ONLY = 16
_pcbnew_stub.FP_DNP = 32
_pcbnew_stub.F_CrtYd = 0
_pcbnew_stub.B_CrtYd = 1


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_footprint_mock(attrs=0, excluded_pos=False, excluded_bom=False, board_only=False):
    """Return a MagicMock mimicking a pcbnew.FOOTPRINT for attribute editing."""
    fp = MagicMock()
    fp.GetAttributes.return_value = attrs
    fp.IsExcludedFromPosFiles.return_value = excluded_pos
    fp.IsExcludedFromBOM.return_value = excluded_bom
    fp.IsBoardOnly.return_value = board_only
    return fp


def _make_component_commands(fp_mock):
    """Return a ComponentCommands wired to a board holding *fp_mock*."""
    from kicad_mcp.commands.component import ComponentCommands

    board = MagicMock()
    board.FindFootprintByReference.return_value = fp_mock
    cmd = ComponentCommands.__new__(ComponentCommands)
    cmd.board = board
    cmd.library_manager = MagicMock()
    return cmd


# ---------------------------------------------------------------------------
# SWIG path – ComponentCommands.set_footprint_type
# ---------------------------------------------------------------------------


class TestSetFootprintTypeSwig:
    def test_set_through_hole_clears_smd_bit(self):
        """Setting through_hole must set FP_THROUGH_HOLE and clear FP_SMD."""
        fp = _make_footprint_mock(attrs=_pcbnew_stub.FP_SMD)
        cmd = _make_component_commands(fp)

        result = cmd.set_footprint_type({"reference": "R1", "type": "through_hole"})

        assert result["success"] is True
        fp.SetAttributes.assert_called_once()
        written = fp.SetAttributes.call_args[0][0]
        assert written & _pcbnew_stub.FP_THROUGH_HOLE
        assert not (written & _pcbnew_stub.FP_SMD)

    def test_set_smd_clears_through_hole_bit(self):
        fp = _make_footprint_mock(attrs=_pcbnew_stub.FP_THROUGH_HOLE)
        cmd = _make_component_commands(fp)

        result = cmd.set_footprint_type({"reference": "U1", "type": "smd"})

        assert result["success"] is True
        written = fp.SetAttributes.call_args[0][0]
        assert written & _pcbnew_stub.FP_SMD
        assert not (written & _pcbnew_stub.FP_THROUGH_HOLE)

    def test_set_unspecified_clears_both_bits(self):
        fp = _make_footprint_mock(attrs=_pcbnew_stub.FP_THROUGH_HOLE | _pcbnew_stub.FP_SMD)
        cmd = _make_component_commands(fp)

        result = cmd.set_footprint_type({"reference": "TP1", "type": "unspecified"})

        assert result["success"] is True
        written = fp.SetAttributes.call_args[0][0]
        assert not (written & _pcbnew_stub.FP_SMD)
        assert not (written & _pcbnew_stub.FP_THROUGH_HOLE)

    def test_exclude_from_pos_files_set(self):
        fp = _make_footprint_mock()
        cmd = _make_component_commands(fp)

        cmd.set_footprint_type({"reference": "R2", "type": "smd", "exclude_from_pos_files": True})

        fp.SetExcludedFromPosFiles.assert_called_once_with(True)

    def test_exclude_from_bom_set(self):
        fp = _make_footprint_mock()
        cmd = _make_component_commands(fp)

        cmd.set_footprint_type({"reference": "R3", "type": "smd", "exclude_from_bom": True})

        fp.SetExcludedFromBOM.assert_called_once_with(True)

    def test_not_in_schematic_set(self):
        fp = _make_footprint_mock()
        cmd = _make_component_commands(fp)

        cmd.set_footprint_type(
            {"reference": "MH1", "type": "unspecified", "not_in_schematic": True}
        )

        fp.SetBoardOnly.assert_called_once_with(True)

    def test_omitted_optional_flags_not_called(self):
        """When optional flags are omitted, their setters must NOT be called."""
        fp = _make_footprint_mock()
        cmd = _make_component_commands(fp)

        cmd.set_footprint_type({"reference": "C1", "type": "smd"})

        fp.SetExcludedFromPosFiles.assert_not_called()
        fp.SetExcludedFromBOM.assert_not_called()
        fp.SetBoardOnly.assert_not_called()

    def test_missing_reference_returns_error(self):
        fp = _make_footprint_mock()
        cmd = _make_component_commands(fp)

        result = cmd.set_footprint_type({"type": "smd"})

        assert result["success"] is False
        assert "reference" in result["errorDetails"].lower()

    def test_invalid_type_returns_error(self):
        fp = _make_footprint_mock()
        cmd = _make_component_commands(fp)

        result = cmd.set_footprint_type({"reference": "R1", "type": "bad_type"})

        assert result["success"] is False

    def test_component_not_found_returns_error(self):
        cmd = _make_component_commands(None)
        cmd.board.FindFootprintByReference.return_value = None

        result = cmd.set_footprint_type({"reference": "ZZZ", "type": "smd"})

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_no_board_returns_error(self):
        fp = _make_footprint_mock()
        cmd = _make_component_commands(fp)
        cmd.board = None

        result = cmd.set_footprint_type({"reference": "R1", "type": "smd"})

        assert result["success"] is False
        assert "no board" in result["message"].lower()

    def test_response_includes_readback_type(self):
        """Response component.type must reflect the resolved type after the write."""
        # First call (before SetAttributes): original value; second call (readback): FP_SMD
        fp = _make_footprint_mock(attrs=0)
        fp.GetAttributes.side_effect = [0, _pcbnew_stub.FP_SMD]
        cmd = _make_component_commands(fp)

        result = cmd.set_footprint_type({"reference": "R1", "type": "smd"})

        assert result["success"] is True
        assert result["component"]["type"] == "smd"

    def test_response_includes_exclusion_flags(self):
        """Response must include exclude_from_pos_files, exclude_from_bom, not_in_schematic."""
        fp = _make_footprint_mock()
        fp.GetAttributes.side_effect = [0, 0]
        fp.IsExcludedFromPosFiles.return_value = True
        fp.IsExcludedFromBOM.return_value = False
        fp.IsBoardOnly.return_value = False
        cmd = _make_component_commands(fp)

        result = cmd.set_footprint_type(
            {"reference": "R1", "type": "smd", "exclude_from_pos_files": True}
        )

        assert result["success"] is True
        comp = result["component"]
        assert comp["exclude_from_pos_files"] is True
        assert comp["exclude_from_bom"] is False
        assert comp["not_in_schematic"] is False


# ---------------------------------------------------------------------------
# get_component_properties – verify extended attributes in response
# ---------------------------------------------------------------------------


class TestGetComponentPropertiesAttributes:
    """Verify that get_component_properties now returns human-readable type + flags."""

    def _setup(self, attrs, excluded_pos=False, excluded_bom=False, board_only=False):
        fp = _make_footprint_mock(
            attrs=attrs,
            excluded_pos=excluded_pos,
            excluded_bom=excluded_bom,
            board_only=board_only,
        )
        # get_component_properties needs GetPosition, GetBoundingBox etc.
        fp.GetPosition.return_value = MagicMock(x=0, y=0)
        fp.GetOrientation.return_value = MagicMock()
        fp.GetOrientation.return_value.AsDegrees.return_value = 0.0
        fp.GetCourtyard.return_value = MagicMock()
        fp.GetCourtyard.return_value.OutlineCount.return_value = 0
        fp.GetBoundingBox.return_value = MagicMock(
            GetLeft=lambda: 0,
            GetTop=lambda: 0,
            GetRight=lambda: 0,
            GetBottom=lambda: 0,
        )
        cmd = _make_component_commands(fp)
        # board.GetLayerName must return a string
        cmd.board.GetLayerName.return_value = "F.Cu"
        return cmd

    def test_smd_type_string(self):
        cmd = self._setup(_pcbnew_stub.FP_SMD)
        result = cmd.get_component_properties({"reference": "R1"})
        assert result["success"] is True
        assert result["component"]["attributes"]["type"] == "smd"

    def test_through_hole_type_string(self):
        cmd = self._setup(_pcbnew_stub.FP_THROUGH_HOLE)
        result = cmd.get_component_properties({"reference": "R1"})
        assert result["component"]["attributes"]["type"] == "through_hole"

    def test_unspecified_type_string(self):
        cmd = self._setup(0)
        result = cmd.get_component_properties({"reference": "R1"})
        assert result["component"]["attributes"]["type"] == "unspecified"

    def test_exclusion_flags_reported(self):
        cmd = self._setup(
            _pcbnew_stub.FP_SMD,
            excluded_pos=True,
            excluded_bom=True,
            board_only=False,
        )
        result = cmd.get_component_properties({"reference": "R1"})
        attrs = result["component"]["attributes"]
        assert attrs["exclude_from_pos_files"] is True
        assert attrs["exclude_from_bom"] is True
        assert attrs["not_in_schematic"] is False


# ---------------------------------------------------------------------------
# IPC path – KiCADInterface._ipc_set_footprint_type
# ---------------------------------------------------------------------------


def _make_ipc_iface():
    """Construct a minimal KiCADInterface with a mocked IPC board API."""
    with patch("kicad_interface.USE_IPC_BACKEND", True):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    iface.use_ipc = True
    iface.board = None
    iface.ipc_board_api = MagicMock()
    iface.component_commands = MagicMock()
    return iface


def _make_kipy_fp_mock(reference: str):
    """Return a MagicMock that looks enough like a kipy Footprint proto wrapper."""
    fp = MagicMock()
    fp.reference_field.text.value = reference
    fp.proto.attributes.mounting_style = 0
    fp.proto.attributes.exclude_from_position_files = False
    fp.proto.attributes.exclude_from_bill_of_materials = False
    fp.proto.attributes.not_in_schematic = False
    return fp


def _fms_stub():
    return types.SimpleNamespace(FMS_THROUGH_HOLE=1, FMS_SMD=2, FMS_UNSPECIFIED=3)


class TestSetFootprintTypeIpc:
    def test_ipc_sets_mounting_style_smd(self):
        iface = _make_ipc_iface()
        target_fp = _make_kipy_fp_mock("U1")
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = [target_fp]

        fms = _fms_stub()
        proto_mod = types.ModuleType("kipy.proto.board.board_types_pb2")
        proto_mod.FootprintMountingStyle = fms
        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": proto_mod}):
            result = iface._ipc_set_footprint_type({"reference": "U1", "type": "smd"})

        assert result["success"] is True
        assert target_fp.proto.attributes.mounting_style == fms.FMS_SMD
        board_mock.update_items.assert_called_once_with([target_fp])

    def test_ipc_sets_mounting_style_through_hole(self):
        iface = _make_ipc_iface()
        target_fp = _make_kipy_fp_mock("J1")
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = [target_fp]

        fms = _fms_stub()
        proto_mod = types.ModuleType("kipy.proto.board.board_types_pb2")
        proto_mod.FootprintMountingStyle = fms
        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": proto_mod}):
            result = iface._ipc_set_footprint_type({"reference": "J1", "type": "through_hole"})

        assert result["success"] is True
        assert target_fp.proto.attributes.mounting_style == fms.FMS_THROUGH_HOLE

    def test_ipc_sets_exclude_from_pos_when_provided(self):
        iface = _make_ipc_iface()
        target_fp = _make_kipy_fp_mock("R1")
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = [target_fp]

        fms = _fms_stub()
        proto_mod = types.ModuleType("kipy.proto.board.board_types_pb2")
        proto_mod.FootprintMountingStyle = fms
        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": proto_mod}):
            result = iface._ipc_set_footprint_type(
                {"reference": "R1", "type": "through_hole", "exclude_from_pos_files": True}
            )

        assert result["success"] is True
        assert target_fp.proto.attributes.exclude_from_position_files is True

    def test_ipc_sets_exclude_from_bom(self):
        iface = _make_ipc_iface()
        target_fp = _make_kipy_fp_mock("R1")
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = [target_fp]

        fms = _fms_stub()
        proto_mod = types.ModuleType("kipy.proto.board.board_types_pb2")
        proto_mod.FootprintMountingStyle = fms
        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": proto_mod}):
            result = iface._ipc_set_footprint_type(
                {"reference": "R1", "type": "smd", "exclude_from_bom": True}
            )

        assert result["success"] is True
        assert target_fp.proto.attributes.exclude_from_bill_of_materials is True

    def test_ipc_not_in_schematic_written(self):
        iface = _make_ipc_iface()
        target_fp = _make_kipy_fp_mock("MH1")
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = [target_fp]

        fms = _fms_stub()
        proto_mod = types.ModuleType("kipy.proto.board.board_types_pb2")
        proto_mod.FootprintMountingStyle = fms
        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": proto_mod}):
            result = iface._ipc_set_footprint_type(
                {"reference": "MH1", "type": "unspecified", "not_in_schematic": True}
            )

        assert result["success"] is True
        assert target_fp.proto.attributes.not_in_schematic is True

    def test_ipc_component_not_found_returns_error(self):
        iface = _make_ipc_iface()
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = []

        fms = _fms_stub()
        proto_mod = types.ModuleType("kipy.proto.board.board_types_pb2")
        proto_mod.FootprintMountingStyle = fms
        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": proto_mod}):
            result = iface._ipc_set_footprint_type({"reference": "ZZZ", "type": "smd"})

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_ipc_invalid_type_returns_error(self):
        iface = _make_ipc_iface()
        result = iface._ipc_set_footprint_type({"reference": "R1", "type": "bad_type"})
        assert result["success"] is False

    def test_ipc_fallback_to_swig_on_proto_error(self):
        """When kipy proto import fails, the handler must fall back to the SWIG path."""
        iface = _make_ipc_iface()
        target_fp = _make_kipy_fp_mock("R1")
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = [target_fp]
        iface.board = MagicMock()  # SWIG board available

        swig_result = {"success": True, "component": {"reference": "R1", "type": "smd"}}
        iface.component_commands.set_footprint_type.return_value = swig_result

        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": None}):
            result = iface._ipc_set_footprint_type({"reference": "R1", "type": "smd"})

        iface.component_commands.set_footprint_type.assert_called_once()
        assert result["success"] is True
        assert result.get("_backend") == "swig"

    def test_ipc_response_includes_backend_marker(self):
        """Successful IPC response must carry _backend: 'ipc'."""
        iface = _make_ipc_iface()
        target_fp = _make_kipy_fp_mock("C1")
        board_mock = iface.ipc_board_api._get_board.return_value
        board_mock.get_footprints.return_value = [target_fp]

        fms = _fms_stub()
        proto_mod = types.ModuleType("kipy.proto.board.board_types_pb2")
        proto_mod.FootprintMountingStyle = fms
        with patch.dict(sys.modules, {"kipy.proto.board.board_types_pb2": proto_mod}):
            result = iface._ipc_set_footprint_type({"reference": "C1", "type": "smd"})

        assert result.get("_backend") == "ipc"
        assert result.get("_realtime") is True
