"""delete_trace over IPC (live KiCad GUI), issue #553.

_ipc_delete_trace used to call the SWIG delete_trace, which edited the
server's own copy of the board. KiCad kept the track, yet the dispatcher
stamped the reply ``_backend: ipc`` / ``_realtime: true``. A move done as
delete + route_trace then left the old copper on the live board.

These tests cover IPCBoardAPI.delete_tracks (the kipy mutation), the handler
param plumbing, the dispatcher not stamping SWIG fallbacks as realtime, and
the run_drc warning in a realtime session.
"""

import sys
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", True):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)

    iface.use_ipc = True
    iface.board = None
    iface.ipc_backend = None
    iface.ipc_board_api = MagicMock()
    iface.ipc_board_api.delete_tracks.return_value = {"success": True}
    iface.routing_commands = MagicMock()
    iface.command_routes = {}
    iface._board_disk_signature = None
    iface._current_project_path = None
    iface._last_auto_save_status = None
    return iface


# --- handler-level: kicad_interface._ipc_delete_trace -----------------------


def test_handler_passes_the_swig_parameter_contract():
    iface = _make_iface()
    iface._ipc_delete_trace(
        {
            "traceUuid": "abc",
            "position": {"x": 1, "y": 2},
            "net": "GND",
            "layer": "B.Cu",
            "includeVias": True,
        }
    )
    _, kwargs = iface.ipc_board_api.delete_tracks.call_args
    assert kwargs == {
        "uuid": "abc",
        "position": {"x": 1, "y": 2},
        "net_name": "GND",
        "layer": "B.Cu",
        "include_vias": True,
    }


def test_handler_never_falls_back_to_the_swig_board_copy():
    iface = _make_iface()
    iface._ipc_delete_trace({"traceUuid": "abc"})
    iface.routing_commands.delete_trace.assert_not_called()


def test_handler_reports_missing_backend_support_as_error():
    iface = _make_iface()
    iface.ipc_board_api = object()  # no delete_tracks
    result = iface._ipc_delete_trace({"traceUuid": "abc"})
    assert result["success"] is False
    iface.routing_commands.delete_trace.assert_not_called()


# --- dispatcher: realtime stamping ------------------------------------------


def _dispatch(iface: Any, command: str, params: dict) -> dict:
    import kicad_interface

    with patch.object(kicad_interface, "KICAD_BACKEND", "swig"):
        return iface.handle_command(command, params)


def test_dispatcher_stamps_a_live_delete_as_realtime():
    iface = _make_iface()
    result = _dispatch(iface, "delete_trace", {"traceUuid": "abc"})
    assert result["_backend"] == "ipc"
    assert result["_realtime"] is True


def test_dispatcher_keeps_a_swig_tag_from_an_ipc_handler():
    """An IPC handler that delegated to SWIG must not come back realtime."""
    iface = _make_iface()
    iface._ipc_delete_trace = MagicMock(  # type: ignore[method-assign]
        return_value={"success": True, "_backend": "swig"}
    )
    result = _dispatch(iface, "delete_trace", {"traceUuid": "abc"})
    assert result["_backend"] == "swig"
    assert result["_realtime"] is False
    assert "not over IPC" in result["_backend_note"]


def test_rectangle_board_outline_fallback_is_not_reported_as_realtime():
    iface = _make_iface()
    iface.board_commands = MagicMock()
    iface.board_commands.add_board_outline.return_value = {"success": True}
    result = _dispatch(iface, "add_board_outline", {"shape": "rectangle"})
    assert result["_backend"] == "swig"
    assert result["_realtime"] is False


def test_run_drc_in_a_realtime_session_warns_that_it_checked_the_file():
    iface = _make_iface()
    iface.session_backend = "ipc"
    iface.ipc_backend = MagicMock()
    iface.ipc_backend.is_connected.return_value = True
    iface._try_enable_ipc_backend = lambda: None  # type: ignore[method-assign]
    iface.command_routes = {
        "run_drc": lambda params: {"success": True, "violations": [], "warnings": []}
    }
    result = _dispatch(iface, "run_drc", {})
    assert result["_backend"] == "swig"
    assert result["checkedSource"] == "file"
    assert any("not the board open in KiCad" in w for w in result["warnings"])


def test_run_drc_without_a_realtime_session_has_no_warning():
    iface = _make_iface()
    iface.use_ipc = False
    iface.session_backend = "swig"
    iface.command_routes = {
        "run_drc": lambda params: {"success": True, "violations": [], "warnings": []}
    }
    result = _dispatch(iface, "run_drc", {})
    assert "checkedSource" not in result
    assert result["warnings"] == []


# --- backend-level: the kipy mutation in IPCBoardAPI.delete_tracks ----------

bt = pytest.importorskip("kipy.board_types", reason="kipy (kicad-python) not installed")

from kicad_api.ipc_backend import IPCBoardAPI  # noqa: E402

T1 = "11111111-1111-1111-1111-111111111111"
T2 = "22222222-2222-2222-2222-222222222222"
ARC = "33333333-3333-3333-3333-333333333333"
VIA = "44444444-4444-4444-4444-444444444444"


def _net(name: str) -> Any:
    net = bt.Net()
    net.name = name
    return net


def _track(uuid: str, net: str = "GND", layer: str = "F.Cu", xy=(0, 0, 10, 0)) -> Any:
    # Real kipy objects, so item.id is a KIID message as on a live board; a
    # MagicMock with a plain-string id would hide a lookup that never matches
    # (the protobuf-text id bug from #515).
    from kipy.geometry import Vector2
    from kipy.proto.board.board_types_pb2 import BoardLayer
    from kipy.util.units import from_mm

    track = bt.Track()
    track._proto.id.value = uuid
    track.net = _net(net)
    track.layer = BoardLayer.Value("BL_" + layer.replace(".", "_"))
    track.start = Vector2.from_xy(from_mm(xy[0]), from_mm(xy[1]))
    track.end = Vector2.from_xy(from_mm(xy[2]), from_mm(xy[3]))
    return track


def _arc(uuid: str, net: str = "GND") -> Any:
    from kipy.geometry import Vector2
    from kipy.util.units import from_mm

    arc = bt.ArcTrack()
    arc._proto.id.value = uuid
    arc.net = _net(net)
    arc.start = Vector2.from_xy(from_mm(20), from_mm(0))
    arc.end = Vector2.from_xy(from_mm(30), from_mm(0))
    return arc


def _via(uuid: str, net: str = "GND", x: float = 50, y: float = 50) -> Any:
    from kipy.geometry import Vector2
    from kipy.util.units import from_mm

    via = bt.Via()
    via._proto.id.value = uuid
    via.net = _net(net)
    via.position = Vector2.from_xy(from_mm(x), from_mm(y))
    return via


class _LiveBoard:
    """A board double that really removes items, like KiCad would."""

    def __init__(self, items: List[Any], honour_remove: bool = True) -> None:
        self.items = list(items)
        self.honour_remove = honour_remove
        self.begin_commit = MagicMock(return_value="commit")
        self.push_commit = MagicMock()
        self.drop_commit = MagicMock()
        self.removed: List[Any] = []

    def get_tracks(self) -> List[Any]:
        return [i for i in self.items if not isinstance(i, bt.Via)]

    def get_vias(self) -> List[Any]:
        return [i for i in self.items if isinstance(i, bt.Via)]

    def remove_items(self, items: List[Any]) -> None:
        self.removed.extend(items)
        if self.honour_remove:
            gone = {i.id.value for i in items}
            self.items = [i for i in self.items if i.id.value not in gone]


def _api(monkeypatch, board: Any) -> IPCBoardAPI:
    api = IPCBoardAPI.__new__(IPCBoardAPI)
    api._notify = lambda *a, **k: None  # type: ignore[assignment]
    monkeypatch.setattr(IPCBoardAPI, "_get_board", lambda self: board)
    return api


def test_delete_by_uuid_removes_the_track_in_one_commit(monkeypatch):
    board = _LiveBoard([_track(T1), _track(T2)])
    result = _api(monkeypatch, board).delete_tracks(uuid=T1)

    assert result["success"], result
    assert result["message"] == f"Deleted track: {T1}"
    assert result["deletedUuids"] == [T1]
    assert [i.id.value for i in board.items] == [T2]
    board.begin_commit.assert_called_once()
    board.push_commit.assert_called_once()
    board.drop_commit.assert_not_called()


def test_query_traces_uuid_round_trips_into_delete(monkeypatch):
    """The UUID query_traces hands out (get_tracks id) must match on delete."""
    board = _LiveBoard([_track(T1)])
    api = _api(monkeypatch, board)
    (listed,) = api.get_tracks()
    assert api.delete_tracks(uuid=listed["id"])["success"]
    assert board.items == []


def test_delete_by_uuid_finds_arcs_and_vias(monkeypatch):
    board = _LiveBoard([_track(T1), _arc(ARC), _via(VIA)])
    api = _api(monkeypatch, board)
    assert api.delete_tracks(uuid=ARC)["success"]
    assert api.delete_tracks(uuid=VIA)["success"]
    assert [i.id.value for i in board.items] == [T1]


def test_delete_unknown_uuid_is_an_error_and_touches_nothing(monkeypatch):
    board = _LiveBoard([_track(T1)])
    result = _api(monkeypatch, board).delete_tracks(uuid=T2)

    assert result["success"] is False
    assert result["message"] == "Track not found"
    assert board.removed == []
    board.begin_commit.assert_not_called()


def test_delete_that_kicad_ignores_is_an_error(monkeypatch):
    """remove_items() drops KiCad's per-item status, so read the board back."""
    board = _LiveBoard([_track(T1)], honour_remove=False)
    result = _api(monkeypatch, board).delete_tracks(uuid=T1)

    assert result["success"] is False
    assert result["remainingUuids"] == [T1]


def test_delete_that_raises_drops_the_commit(monkeypatch):
    board = _LiveBoard([_track(T1)])
    board.remove_items = MagicMock(side_effect=RuntimeError("IDS_IMMUTABLE"))  # type: ignore
    result = _api(monkeypatch, board).delete_tracks(uuid=T1)

    assert result["success"] is False
    assert "IDS_IMMUTABLE" in result["errorDetails"]
    board.drop_commit.assert_called_once_with("commit")
    board.push_commit.assert_not_called()


def test_delete_by_net_matches_swig_filters(monkeypatch):
    board = _LiveBoard(
        [
            _track(T1, net="GND", layer="F.Cu"),
            _track(T2, net="GND", layer="B.Cu"),
            _arc(ARC, net="VCC"),
            _via(VIA, net="GND"),
        ]
    )
    api = _api(monkeypatch, board)

    result = api.delete_tracks(net_name="GND", layer="B.Cu")
    assert result["success"], result
    assert result["deletedUuids"] == [T2]  # layer filter, via skipped

    result = api.delete_tracks(net_name="GND", include_vias=True)
    assert sorted(result["deletedUuids"]) == sorted([T1, VIA])
    assert [i.id.value for i in board.items] == [ARC]


def test_delete_by_net_with_no_match_reports_zero(monkeypatch):
    board = _LiveBoard([_track(T1, net="GND")])
    result = _api(monkeypatch, board).delete_tracks(net_name="NOPE")
    assert result["success"] is True
    assert result["deletedCount"] == 0
    board.begin_commit.assert_not_called()


def test_delete_by_position_picks_the_nearest_within_1mm(monkeypatch):
    board = _LiveBoard([_track(T1, xy=(0, 0, 10, 0)), _track(T2, xy=(0, 5, 10, 5))])
    api = _api(monkeypatch, board)

    result = api.delete_tracks(position={"x": 5, "y": 4.5, "unit": "mm"})
    assert result["success"], result
    assert result["deletedUuids"] == [T2]

    miss = api.delete_tracks(position={"x": 5, "y": 2.5})
    assert miss["success"] is False
    assert miss["message"] == "No track found"


def test_delete_by_position_converts_mil(monkeypatch):
    board = _LiveBoard([_via(VIA, x=2.54, y=2.54)])
    result = _api(monkeypatch, board).delete_tracks(position={"x": 100, "y": 100, "unit": "mil"})
    assert result["success"], result
    assert result["deletedUuids"] == [VIA]


def test_delete_without_a_selector_is_an_error(monkeypatch):
    board = _LiveBoard([_track(T1)])
    result = _api(monkeypatch, board).delete_tracks()
    assert result["success"] is False
    assert board.removed == []
