"""Copper-fill rule areas use live KiCad IPC and report observed state."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytest.importorskip("kipy.board_types")
from kicad_api.ipc_backend import IPCBoardAPI, _same_keepout_outline  # noqa: E402
from kicad_interface import KiCADInterface  # noqa: E402
from kipy.board_types import Zone  # noqa: E402
from kipy.proto.board.board_types_pb2 import BoardLayer  # noqa: E402

RECTANGLE = [
    {"x": 1.0, "y": 1.0},
    {"x": 10.0, "y": 1.0},
    {"x": 10.0, "y": 8.0},
    {"x": 1.0, "y": 8.0},
]
BOARD_PATH = "/private/tmp/keepout-test.kicad_pcb"


class FakeBoard:
    def __init__(self) -> None:
        self.document = SimpleNamespace(
            board_filename=Path(BOARD_PATH).name,
            project=SimpleNamespace(path=str(Path(BOARD_PATH).parent)),
        )
        self.created = []
        self.refills = 0
        self.refill_error = None

    def get_enabled_layers(self):
        return [BoardLayer.BL_F_Cu, BoardLayer.BL_In1_Cu, BoardLayer.BL_B_Cu]

    def begin_commit(self):
        return object()

    def create_items(self, zone):
        assert isinstance(zone, Zone)
        zone._proto.id.value = "12345678-1234-1234-1234-123456789abc"
        self.created.append(zone)
        return [zone]

    def push_commit(self, _commit, _message):
        pass

    def drop_commit(self, _commit):
        raise AssertionError("No successful test should roll back")

    def get_zones(self):
        return self.created

    def refill_zones(self):
        self.refills += 1
        if self.refill_error:
            raise RuntimeError(self.refill_error)


def api_for(board):
    kicad = Mock()
    kicad.get_open_documents.return_value = [board.document]
    api = IPCBoardAPI(kicad, Mock())
    api._board = board
    return api


def test_creates_and_reads_back_copper_only_rule_area() -> None:
    board = FakeBoard()
    assert board.document.board_filename == "keepout-test.kicad_pcb"
    assert board.document.project.path == str(Path(BOARD_PATH).parent)
    result = api_for(board).add_copper_keepout(
        BOARD_PATH, "NFC coil", ["F.Cu", "In1.Cu", "B.Cu"], RECTANGLE
    )

    assert result["status"] == "applied"
    assert result["verified"] is True
    assert result["refilled"] is True
    assert result["id"] == "12345678-1234-1234-1234-123456789abc"
    assert board.refills == 1
    rule = board.created[0]._proto.rule_area_settings
    assert rule.keepout_copper
    assert not any(
        (rule.keepout_tracks, rule.keepout_vias, rule.keepout_pads, rule.keepout_footprints)
    )


@pytest.mark.parametrize(
    "layers,points",
    [
        (["In2.Cu"], RECTANGLE),
        (["F.SilkS"], RECTANGLE),
        (["F.Cu", "F.Cu"], RECTANGLE),
        (["F.Cu"], RECTANGLE + [RECTANGLE[0]]),
        (["F.Cu"], [{"x": 0, "y": 0}, {"x": 2, "y": 2}, {"x": 0, "y": 2}, {"x": 2, "y": 0}]),
    ],
)
def test_invalid_input_does_not_mutate(layers, points) -> None:
    board = FakeBoard()
    result = api_for(board).add_copper_keepout(BOARD_PATH, "NFC coil", layers, points)
    assert result["success"] is False
    assert board.created == []
    assert board.refills == 0


def test_refill_failure_reports_applied_result() -> None:
    board = FakeBoard()
    board.refill_error = "busy"
    result = api_for(board).add_copper_keepout(BOARD_PATH, "NFC coil", ["F.Cu"], RECTANGLE)
    assert result["success"] is True
    assert result["status"] == "applied_not_refilled"
    assert result["refill_error"] == "busy"
    assert len(board.created) == 1


def test_wrong_open_board_does_not_mutate() -> None:
    board = FakeBoard()
    result = api_for(board).add_copper_keepout(
        "/private/tmp/another-board.kicad_pcb", "NFC coil", ["F.Cu"], RECTANGLE
    )
    assert result["success"] is False
    assert "not open" in result["message"]
    assert board.created == []


def test_same_filename_in_another_directory_does_not_mutate() -> None:
    board = FakeBoard()
    result = api_for(board).add_copper_keepout(
        "/private/tmp/other/keepout-test.kicad_pcb", "NFC coil", ["F.Cu"], RECTANGLE
    )
    assert result["success"] is False
    assert "not open" in result["message"]
    assert board.created == []


def test_readback_accepts_rotated_or_reversed_outline() -> None:
    requested = [(point["x"], point["y"]) for point in RECTANGLE]
    assert _same_keepout_outline(requested[2:] + requested[:2], requested)
    assert _same_keepout_outline(list(reversed(requested)), requested)
    assert not _same_keepout_outline(requested[:-1] + [(2.0, 8.0)], requested)


def test_readback_mismatch_is_reported() -> None:
    class BadReadback(FakeBoard):
        def get_zones(self):
            self.created[0]._proto.rule_area_settings.keepout_tracks = True
            return self.created

    result = api_for(BadReadback()).add_copper_keepout(BOARD_PATH, "NFC coil", ["F.Cu"], RECTANGLE)
    assert result["status"] == "applied_readback_mismatch"
    assert result["verified"] is False
    assert result["refilled"] is True


def test_failed_commit_and_rollback_reports_uncertain_mutation() -> None:
    class FailedCommit(FakeBoard):
        def push_commit(self, _commit, _message):
            raise RuntimeError("commit failed")

        def drop_commit(self, _commit):
            raise RuntimeError("rollback failed")

    board = FailedCommit()
    result = api_for(board).add_copper_keepout(BOARD_PATH, "NFC coil", ["F.Cu"], RECTANGLE)
    assert result["status"] == "mutation_outcome_uncertain"
    assert len(board.created) == 1


def test_no_ipc_refuses_without_file_fallback() -> None:
    interface = KiCADInterface.__new__(KiCADInterface)
    interface.use_ipc = False
    interface.ipc_board_api = None
    interface._refuse_if_schematic_open = Mock(return_value=None)
    interface.command_routes = {"add_copper_keepout": Mock()}
    result = interface.handle_command(
        "add_copper_keepout",
        {"boardPath": BOARD_PATH, "name": "NFC coil", "layers": ["F.Cu"], "points": RECTANGLE},
    )
    assert result["success"] is False
    assert "live KiCad" in result["message"]
    interface.command_routes["add_copper_keepout"].assert_not_called()
