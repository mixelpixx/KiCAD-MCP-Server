"""Schema parameter names reach the handlers that read them (#403).

``modify_trace`` declared ``traceUuid`` in its zod schema
(src/tools/routing.ts) while the handler read ``params["uuid"]``, so the
documented UUID path always answered "Missing trace identifier" and only the
position fallback worked. ``add_net`` had the same shape -- schema
``netClass``, handler ``class`` -- so the class was silently dropped. Both
handlers now read the schema's name first and keep the old key for JSON-RPC
callers that used it.

tests/test_schema_param_names.py guards the whole class of bug; these pin
the two fixes.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from commands import routing as routing_mod  # noqa: E402
from commands.routing import RoutingCommands  # noqa: E402

# --- modify_trace -----------------------------------------------------------


class _Uuid:
    def __init__(self, value: str):
        self._value = value

    def AsString(self) -> str:
        return self._value


class _Track:
    def __init__(self, uuid: str):
        self.m_Uuid = _Uuid(uuid)
        self.width = None

    def Type(self):
        return "PCB_TRACE_T"  # never equal to pcbnew.PCB_VIA_T

    def SetWidth(self, width_nm: int) -> None:
        self.width = width_nm


class _TrackBoard:
    def __init__(self, tracks):
        self._tracks = tracks

    def Tracks(self):
        return list(self._tracks)


TRACE_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def board_with_track():
    track = _Track(TRACE_UUID)
    return _TrackBoard([track]), track


def test_modify_trace_finds_track_by_traceUuid(board_with_track):
    """The key the zod schema documents must select the track."""
    board, track = board_with_track
    result = RoutingCommands(board).modify_trace({"traceUuid": TRACE_UUID, "width": 0.25})
    assert result["success"], result
    assert track.width == 250_000
    assert result["uuid"] == TRACE_UUID


def test_modify_trace_still_accepts_legacy_uuid_key(board_with_track):
    """JSON-RPC callers that sent ``uuid`` keep working."""
    board, track = board_with_track
    result = RoutingCommands(board).modify_trace({"uuid": TRACE_UUID, "width": 0.3})
    assert result["success"], result
    assert track.width == 300_000


def test_modify_trace_error_names_the_documented_key(board_with_track):
    board, _ = board_with_track
    result = RoutingCommands(board).modify_trace({"width": 0.25})
    assert not result["success"]
    assert "traceUuid" in result["errorDetails"]


# --- add_net ----------------------------------------------------------------


class _NetsByName:
    def has_key(self, name: str) -> bool:
        return False


class _NetInfo:
    def NetsByName(self):
        return _NetsByName()


class _NetClasses:
    def __init__(self, known):
        self._known = known

    def Find(self, name: str):
        return self._known.get(name)


class _Net:
    def __init__(self):
        self.net_class = None

    def SetClass(self, net_class) -> None:
        self.net_class = net_class

    def GetNetCode(self) -> int:
        return 7


class _NetBoard:
    def __init__(self, classes):
        self.added = []
        self._classes = _NetClasses(classes)

    def GetNetInfo(self):
        return _NetInfo()

    def GetNetClasses(self):
        return self._classes

    def Add(self, item) -> None:
        self.added.append(item)


@pytest.fixture
def new_net(monkeypatch):
    """Route NETINFO_ITEM construction to a recording fake."""
    net = _Net()
    monkeypatch.setattr(routing_mod.pcbnew, "NETINFO_ITEM", lambda board, name: net)
    return net


def test_add_net_honours_schema_netClass(new_net):
    """``netClass`` is what src/tools/routing.ts declares; it must be applied."""
    power = object()
    board = _NetBoard({"Power": power})
    result = RoutingCommands(board).add_net({"name": "VBUS", "netClass": "Power"})
    assert result["success"], result
    assert new_net.net_class is power
    assert result["net"]["class"] == "Power"
    assert board.added == [new_net]


def test_add_net_accepts_legacy_class_key(new_net):
    power = object()
    board = _NetBoard({"Power": power})
    result = RoutingCommands(board).add_net({"name": "VBUS", "class": "Power"})
    assert result["success"], result
    assert new_net.net_class is power
