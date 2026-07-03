"""Tests for IPC->SWIG fallback on file-answerable read tools.

When the live KiCad (IPC) has no document open, file-answerable reads
(get_board_info, get_component_properties, ...) must fall back to the SWIG/file
backend instead of returning a misleading "not found" or a false-success zeroed
payload. When a board IS open in the live KiCad, the IPC realtime path is preserved.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeIPCBackend:
    """Stands in for the IPC backend: only get_open_board_path matters here."""

    def __init__(self, open_board_path: Optional[str]):
        self._open_board_path = open_board_path

    def get_open_board_path(self) -> Optional[str]:
        return self._open_board_path

    def is_connected(self) -> bool:
        return True


class _FakeBoardAPI:
    """Configurable IPC board API. ``size`` may carry an error (no open document)."""

    def __init__(self, components: List[Dict[str, Any]], size: Optional[Dict[str, Any]] = None):
        self._components = components
        self._size = size if size is not None else {"width": 10, "height": 20, "unit": "mm"}

    def get_size(self) -> Dict[str, Any]:
        return self._size

    def list_components(self) -> List[Dict[str, Any]]:
        return list(self._components)

    def get_tracks(self) -> List[Dict[str, Any]]:
        return []

    def get_vias(self) -> List[Dict[str, Any]]:
        return []

    def get_nets(self) -> List[Dict[str, Any]]:
        return []


def _make_iface(
    *,
    open_board_path: Optional[str],
    board_api: Optional[_FakeBoardAPI],
    command_routes: Dict[str, Any],
):
    from kicad_interface import KiCADInterface

    iface = KiCADInterface.__new__(KiCADInterface)
    iface.use_ipc = True
    iface.ipc_backend = _FakeIPCBackend(open_board_path)
    iface.ipc_board_api = board_api
    iface.session_backend = "ipc"  # allow IPC routing
    iface.board = None
    iface.command_routes = command_routes
    iface._board_disk_signature = None
    iface._current_project_path = None
    iface._last_auto_save_status = None
    # Keep dispatch focused on routing: neutralise reconnect/liveness side effects.
    iface._try_enable_ipc_backend = lambda *a, **k: None  # type: ignore[assignment]
    iface._ipc_session_alive = lambda: True  # type: ignore[assignment]
    return iface


_SWIG_COMPONENT = {
    "success": True,
    "component": {"reference": "J1", "value": "Conn", "_served_from": "disk"},
}
_SWIG_BOARD = {
    "success": True,
    "board": {"filename": "/proj/board.kicad_pcb", "size": {"width": 50, "height": 40}},
}


# --------------------------------------------------------------------------- #
# Verification 1: no live document -> get_component_properties via SWIG fallback
# --------------------------------------------------------------------------- #


def test_get_component_properties_falls_back_to_swig_when_no_open_document():
    iface = _make_iface(
        open_board_path=None,  # live KiCad has nothing open
        board_api=_FakeBoardAPI(components=[]),
        command_routes={"get_component_properties": lambda params: dict(_SWIG_COMPONENT)},
    )

    result = iface.handle_command("get_component_properties", {"reference": "J1"})

    assert result["success"] is True
    assert result["_backend"] == "swig"
    assert result["component"]["reference"] == "J1"
    assert "_backend_note" in result and "swig" in result["_backend_note"].lower()


# --------------------------------------------------------------------------- #
# Verification 2: get_board_info with no live document — file fallback or clean fail
# --------------------------------------------------------------------------- #


def test_get_board_info_file_fallback_when_no_open_document():
    iface = _make_iface(
        open_board_path=None,
        board_api=_FakeBoardAPI(components=[], size={"width": 0, "height": 0, "error": "no doc"}),
        command_routes={"get_board_info": lambda params: dict(_SWIG_BOARD)},
    )

    result = iface.handle_command("get_board_info", {})

    assert result["success"] is True
    assert result["_backend"] == "swig"
    assert result["board"]["filename"].endswith("board.kicad_pcb")


def test_get_board_info_clean_failure_when_neither_backend_has_board():
    iface = _make_iface(
        open_board_path=None,
        board_api=_FakeBoardAPI(components=[], size={"width": 0, "height": 0, "error": "no doc"}),
        command_routes={
            "get_board_info": lambda params: {"success": False, "message": "No board is loaded"}
        },
    )

    result = iface.handle_command("get_board_info", {})

    # Must be a clean failure — never success:true with zeroed data + an error.
    assert result["success"] is False
    assert result["_backend"] == "swig"


def test_ipc_get_board_info_never_returns_false_success():
    """The IPC handler itself must not report success:true with a zeroed/error size."""
    iface = _make_iface(
        open_board_path="/proj/board.kicad_pcb",
        board_api=_FakeBoardAPI(
            components=[], size={"width": 0, "height": 0, "error": "No board open in KiCAD"}
        ),
        command_routes={},
    )

    result = iface._ipc_get_board_info({})

    assert result["success"] is False
    assert result.get("_no_open_document") is True


# --------------------------------------------------------------------------- #
# Verification 3: board genuinely open in live KiCad -> IPC realtime path
# --------------------------------------------------------------------------- #


def test_get_component_properties_uses_ipc_when_board_open():
    iface = _make_iface(
        open_board_path="/proj/board.kicad_pcb",
        board_api=_FakeBoardAPI(
            components=[{"reference": "J1", "value": "Conn", "boundingBox": {"x": 0}}]
        ),
        command_routes={"get_component_properties": lambda params: dict(_SWIG_COMPONENT)},
    )

    result = iface.handle_command("get_component_properties", {"reference": "J1"})

    assert result["success"] is True
    assert result["_backend"] == "ipc"
    assert result["_realtime"] is True
    # Served live from IPC's component list, not the SWIG disk stub.
    assert result["component"].get("_served_from") != "disk"


def test_get_board_info_uses_ipc_when_board_open():
    iface = _make_iface(
        open_board_path="/proj/board.kicad_pcb",
        board_api=_FakeBoardAPI(components=[{"reference": "J1"}]),
        command_routes={"get_board_info": lambda params: dict(_SWIG_BOARD)},
    )

    result = iface.handle_command("get_board_info", {})

    assert result["success"] is True
    assert result["_backend"] == "ipc"
    assert result["boardInfo"]["backend"] == "ipc"


# --------------------------------------------------------------------------- #
# Verification 4: genuinely-absent component -> "not found", distinct from no-board
# --------------------------------------------------------------------------- #


def test_absent_component_reports_not_found_not_no_board():
    iface = _make_iface(
        open_board_path="/proj/board.kicad_pcb",  # board IS open
        board_api=_FakeBoardAPI(components=[{"reference": "R1"}]),  # J1 absent
        command_routes={"get_component_properties": lambda params: dict(_SWIG_COMPONENT)},
    )

    result = iface.handle_command("get_component_properties", {"reference": "J1"})

    assert result["success"] is False
    assert "not found" in result["message"].lower()
    # This is a genuine miss served by IPC, not a no-document fallback.
    assert result["_backend"] == "ipc"


# --------------------------------------------------------------------------- #
# Verification 5 + reactive fallback: every response reports the backend
# --------------------------------------------------------------------------- #


def test_reactive_fallback_when_ipc_read_reports_no_open_document():
    """Even if the open-document probe passes, an IPC read that comes back with
    _no_open_document must be retried on SWIG (race / stale probe)."""
    iface = _make_iface(
        open_board_path="/proj/board.kicad_pcb",  # probe says open...
        board_api=_FakeBoardAPI(
            components=[], size={"width": 0, "height": 0, "error": "no doc"}  # ...but read fails
        ),
        command_routes={"get_board_info": lambda params: dict(_SWIG_BOARD)},
    )

    result = iface.handle_command("get_board_info", {})

    assert result["success"] is True
    assert result["_backend"] == "swig"
    assert result["board"]["filename"].endswith("board.kicad_pcb")


def test_every_response_reports_a_backend():
    iface = _make_iface(
        open_board_path=None,
        board_api=_FakeBoardAPI(components=[]),
        command_routes={"get_component_list": lambda params: {"success": True, "components": []}},
    )

    result = iface.handle_command("get_component_list", {})

    assert result["_backend"] in {"ipc", "swig"}
    assert "_realtime" in result
