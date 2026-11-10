"""modify_trace over IPC (live KiCad GUI), follow-up to #515.

#515 fixed modify_trace reporting success while writing nothing to disk on
the SWIG path. It also has no IPC path at all, unlike route_trace/add_via —
it always runs headless, so a KiCad window already open on the board won't
show the new width/layer/net until File -> Revert. This adds
IPCBoardAPI.modify_track (the kipy-side mutation, mirroring the
update_items pattern already used by move_component/add_3d_model) and wires
modify_trace into IPC_CAPABLE_COMMANDS so a live session uses it.

An unrecognized layer or net name is a reported error here, not a silent
fallback to F.Cu like add_track's ``layer_map.get(layer, BL_F_Cu)`` — modify
already shipped once silently doing nothing; silently doing something other
than what was asked is the same failure shape with a different cause.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

# --- handler-level: param plumbing in kicad_interface._ipc_modify_trace -----


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", True):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)

    iface.use_ipc = True
    iface.board = None
    iface.ipc_board_api = MagicMock()
    iface.ipc_board_api.modify_track.return_value = {"success": True}
    return iface


def test_handler_reads_schema_key_traceUuid():
    iface = _make_iface()
    iface._ipc_modify_trace({"traceUuid": "abc-123", "width": 0.3})
    _, kwargs = iface.ipc_board_api.modify_track.call_args
    assert kwargs == {"uuid": "abc-123", "width": 0.3, "layer": None, "net_name": None}


def test_handler_accepts_legacy_uuid_key():
    iface = _make_iface()
    iface._ipc_modify_trace({"uuid": "abc-123", "layer": "B.Cu"})
    _, kwargs = iface.ipc_board_api.modify_track.call_args
    assert kwargs["uuid"] == "abc-123"
    assert kwargs["layer"] == "B.Cu"


def test_handler_refuses_without_an_identifier():
    iface = _make_iface()
    result = iface._ipc_modify_trace({"width": 0.3})
    assert not result["success"]
    assert "traceUuid" in result["errorDetails"]
    iface.ipc_board_api.modify_track.assert_not_called()


# --- backend-level: the kipy mutation in IPCBoardAPI.modify_track ----------

bt = pytest.importorskip("kipy.board_types", reason="kipy (kicad-python) not installed")
pytest.importorskip("kipy.proto.board.board_types_pb2")

from kicad_api.ipc_backend import IPCBoardAPI  # noqa: E402

TRACE_UUID = "11111111-1111-1111-1111-111111111111"


def _api_with_board(monkeypatch, board: Any) -> IPCBoardAPI:
    api = IPCBoardAPI.__new__(IPCBoardAPI)
    monkeypatch.setattr(IPCBoardAPI, "_get_board", lambda self: board)
    monkeypatch.setattr(IPCBoardAPI, "_notify", lambda self, *a, **k: None, raising=False)
    return api


def _track(uuid: str = TRACE_UUID) -> Any:
    # A real kipy Track, so track.id is a KIID message as on a live board.
    # A MagicMock with a plain-string id hid a lookup that never matched.
    track = bt.Track()
    track._proto.id.value = uuid
    return track


def _net(name: str) -> Any:
    net = bt.Net()
    net.name = name
    return net


def test_modify_track_applies_width_layer_net_and_commits(monkeypatch):
    track = _track()
    board = MagicMock()
    board.get_tracks.return_value = [track]
    board.get_nets.return_value = [_net("GND"), _net("+12V")]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(TRACE_UUID, width=0.3, layer="B.Cu", net_name="+12V")

    assert result["success"], result
    assert set(result["modifications"]) == {"width=0.3mm", "layer=B.Cu", "net=+12V"}
    assert result["uuid"] == TRACE_UUID
    (pushed,), _ = board.update_items.call_args
    assert pushed == [track]
    board.begin_commit.assert_called_once()
    board.push_commit.assert_called_once()

    from kipy.proto.board.board_types_pb2 import BoardLayer
    from kipy.util.units import from_mm

    assert track.width == from_mm(0.3)
    assert track.layer == BoardLayer.BL_B_Cu
    assert track.net.name == "+12V"


@pytest.mark.parametrize("layer", ["F.Cu", "In3.Cu", "In30.Cu", "B.Cu"])
def test_modify_track_accepts_every_copper_layer(monkeypatch, layer):
    """A 6-layer board needs In3.Cu and up, which the SWIG path handles."""
    from kipy.proto.board.board_types_pb2 import BoardLayer

    track = _track()
    board = MagicMock()
    board.get_tracks.return_value = [track]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(TRACE_UUID, layer=layer)

    assert result["success"], result
    assert track.layer == BoardLayer.Value("BL_" + layer.replace(".", "_"))


def test_modify_track_rejects_non_copper_layer(monkeypatch):
    """F.SilkS is a valid BoardLayer name, but a track cannot live on it."""
    board = MagicMock()
    board.get_tracks.return_value = [_track()]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(TRACE_UUID, layer="F.SilkS")

    assert not result["success"]
    assert result["message"] == "Invalid layer"
    board.update_items.assert_not_called()


def test_get_tracks_id_round_trips_into_modify_track(monkeypatch):
    """query_traces hands out get_tracks ids, and modify_trace takes them
    back, so the id must be the bare UUID that modify_track compares."""
    board = MagicMock()
    board.get_tracks.return_value = [_track()]
    api = _api_with_board(monkeypatch, board)

    (listed,) = api.get_tracks()

    assert listed["id"] == TRACE_UUID
    assert api.modify_track(listed["id"], width=0.3)["success"]


VIA_UUID = "22222222-2222-2222-2222-222222222222"


def _via(uuid: str = VIA_UUID) -> Any:
    via = bt.Via()
    via._proto.id.value = uuid
    return via


def test_modify_track_changes_via_diameter_and_net(monkeypatch):
    """SWIG modify_trace walks board.Tracks(), which includes vias. kipy
    lists vias apart from tracks, so modify_track has to search both."""
    from kipy.util.units import from_mm

    via = _via()
    board = MagicMock()
    board.get_tracks.return_value = [_track()]
    board.get_vias.return_value = [via]
    board.get_nets.return_value = [_net("GND")]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(VIA_UUID, width=0.8, net_name="GND")

    assert result["success"], result
    assert via.diameter == from_mm(0.8)
    assert via.net.name == "GND"
    (pushed,), _ = board.update_items.call_args
    assert pushed == [via]


def test_modify_track_rejects_layer_change_on_via(monkeypatch):
    board = MagicMock()
    board.get_tracks.return_value = []
    board.get_vias.return_value = [_via()]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(VIA_UUID, width=0.8, layer="B.Cu")

    assert not result["success"]
    assert result["message"] == "Invalid layer"
    board.update_items.assert_not_called()


def test_get_vias_id_round_trips_into_modify_track(monkeypatch):
    """query_traces with includeVias hands out get_vias ids."""
    board = MagicMock()
    board.get_tracks.return_value = []
    board.get_vias.return_value = [_via()]
    api = _api_with_board(monkeypatch, board)

    (listed,) = api.get_vias()

    assert listed["id"] == VIA_UUID
    assert api.modify_track(listed["id"], width=0.8)["success"]


def test_modify_track_missing_uuid_is_reported_not_silent(monkeypatch):
    board = MagicMock()
    board.get_tracks.return_value = [_track("other-uuid")]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(TRACE_UUID, width=0.3)

    assert not result["success"]
    assert "not found" in result["message"].lower()
    board.update_items.assert_not_called()


def test_modify_track_invalid_layer_is_rejected_not_defaulted(monkeypatch):
    """add_track defaults an unrecognized layer to F.Cu; modify_track must
    not, or a typo'd layer name would silently move the trace instead of
    refusing — the same silent-wrong-result shape as #515."""
    track = _track()
    board = MagicMock()
    board.get_tracks.return_value = [track]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(TRACE_UUID, layer="Nonexistent.Cu")

    assert not result["success"]
    assert result["message"] == "Invalid layer"
    board.update_items.assert_not_called()


def test_modify_track_invalid_net_is_rejected_not_silently_skipped(monkeypatch):
    """add_track silently leaves the net unset when the name doesn't match;
    modify_track must refuse instead, for the same reason as the layer case."""
    track = _track()
    board = MagicMock()
    board.get_tracks.return_value = [track]
    board.get_nets.return_value = [_net("GND")]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(TRACE_UUID, net_name="DOES_NOT_EXIST")

    assert not result["success"]
    assert result["message"] == "Invalid net"
    board.update_items.assert_not_called()


def test_modify_track_requires_at_least_one_field(monkeypatch):
    track = _track()
    board = MagicMock()
    board.get_tracks.return_value = [track]
    api = _api_with_board(monkeypatch, board)

    result = api.modify_track(TRACE_UUID)

    assert not result["success"]
    assert result["message"] == "No modifications specified"
    board.update_items.assert_not_called()
