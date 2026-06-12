"""Tests for the session-pinned backend (issue #223).

Once a project is loaded, every board command must run on the backend that
owns that load ("swig" or "ipc") until the project is closed/reopened. Before
this fix, create_project/open_project always ran on SWIG while save_project
silently upgraded to IPC mid-session and saved the GUI's (stale) board —
losing the SWIG edits.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_interface  # noqa: E402
from kicad_interface import KiCADInterface, KiCADProcessManager  # noqa: E402


class _FakeBoard:
    def __init__(self, filename):
        self._filename = str(filename)

    def GetFileName(self):
        return self._filename


class _FakeIPCBoardAPI:
    def get_size(self):
        return {"width": 10, "height": 20, "unit": "mm"}


class _FakeIPCBackend:
    def __init__(self, open_board_path=None, connected=True):
        self.connected = connected
        self.open_board_path = open_board_path
        self.save_calls = 0

    def connect(self):
        self.connected = True
        return True

    def is_connected(self):
        return self.connected

    def get_board(self):
        return _FakeIPCBoardAPI()

    def get_open_board_path(self):
        return self.open_board_path

    def get_version(self):
        return "10.0-test"


def _make_iface(command_routes, ipc_backend, use_ipc=True, board=None):
    iface = KiCADInterface.__new__(KiCADInterface)
    iface.use_ipc = use_ipc
    iface.ipc_backend = ipc_backend
    iface.ipc_board_api = None
    iface.board = board
    iface.command_routes = command_routes
    iface._board_disk_signature = None
    iface._current_project_path = None
    iface._last_auto_save_status = None
    iface.session_backend = None
    iface.session_board_path = None
    # Neutralize machinery irrelevant to routing decisions.
    iface._is_board_healthy = lambda *a, **k: True
    iface._update_command_handlers = lambda: None
    iface._record_board_signature = lambda: None
    return iface


def _project_routes(iface_holder, board_path):
    """command_routes with fake SWIG create/open/save handlers."""

    def create_project(params):
        board = _FakeBoard(board_path)
        iface_holder["iface"].project_commands.board = board
        return {"success": True, "project": {"boardPath": str(board_path)}}

    def save_project(params):
        iface_holder["swig_saves"] = iface_holder.get("swig_saves", 0) + 1
        return {"success": True, "message": "saved via swig"}

    return {
        "create_project": create_project,
        "open_project": create_project,
        "save_project": save_project,
    }


class _ProjectCommandsStub:
    board = None


def _loaded_iface(tmp_path, gui_board_path, monkeypatch, connected=True):
    """Build an interface and run open_project through handle_command."""
    board_path = tmp_path / "proj" / "proj.kicad_pcb"
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text("(kicad_pcb)")

    holder = {}
    backend = _FakeIPCBackend(
        open_board_path=str(gui_board_path) if gui_board_path else None,
        connected=connected,
    )
    routes = _project_routes(holder, board_path)
    iface = _make_iface(routes, backend)
    iface.project_commands = _ProjectCommandsStub()
    holder["iface"] = iface
    monkeypatch.setattr(KiCADProcessManager, "is_running", staticmethod(lambda: False))

    result = iface.handle_command("open_project", {"path": str(board_path)})
    assert result["success"] is True
    return iface, backend, holder, board_path, result


@pytest.mark.unit
class TestSessionPinning:
    def test_open_without_matching_gui_board_pins_swig(self, tmp_path, monkeypatch):
        iface, _, _, _, result = _loaded_iface(
            tmp_path, gui_board_path=None, monkeypatch=monkeypatch
        )
        assert iface.session_backend == "swig"
        assert result["_backend"] == "swig"
        assert result["sessionBackend"] == "swig"

    def test_open_with_different_gui_board_pins_swig(self, tmp_path, monkeypatch):
        other = tmp_path / "other" / "other.kicad_pcb"
        iface, _, _, _, _ = _loaded_iface(tmp_path, gui_board_path=other, monkeypatch=monkeypatch)
        assert iface.session_backend == "swig"

    def test_open_with_matching_gui_board_pins_ipc(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, _, _, _, result = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        assert iface.session_backend == "ipc"
        assert result["_backend"] == "ipc"
        assert result["_realtime"] is True

    def test_path_match_is_case_and_separator_insensitive(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        sloppy = str(board_path).replace("\\", "/").upper()
        iface, _, _, _, _ = _loaded_iface(tmp_path, gui_board_path=sloppy, monkeypatch=monkeypatch)
        if sys.platform == "win32":
            assert iface.session_backend == "ipc"
        else:
            # Case differences are significant on POSIX filesystems.
            assert iface.session_backend == "swig"


@pytest.mark.unit
class TestIssue223Repro:
    def test_save_after_swig_open_stays_swig_even_with_ipc_connected(self, tmp_path, monkeypatch):
        """The literal #223 bug: open on SWIG, save must NOT silently go IPC."""
        iface, backend, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=None, monkeypatch=monkeypatch
        )
        assert iface.session_backend == "swig"

        # IPC save handler must not run.
        def _boom(params):
            raise AssertionError("IPC save must not be used in a SWIG-pinned session")

        iface._ipc_save_project = _boom

        result = iface.handle_command("save_project", {})
        assert result["success"] is True
        assert result["_backend"] == "swig"
        assert holder.get("swig_saves") == 1
        assert "_backend_note" in result

    def test_swig_pinned_session_blocks_other_ipc_capable_commands(self, tmp_path, monkeypatch):
        iface, backend, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=None, monkeypatch=monkeypatch
        )

        def swig_board_info(params):
            return {"success": True, "board": {}}

        iface.command_routes["get_board_info"] = swig_board_info
        iface.ipc_board_api = _FakeIPCBoardAPI()  # IPC fully available...

        result = iface.handle_command("get_board_info", {})
        assert result["_backend"] == "swig"  # ...but the pin wins
        assert result["_realtime"] is False

    def test_ipc_pinned_session_routes_save_via_ipc(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, backend, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        assert iface.session_backend == "ipc"

        def ipc_save(params):
            holder["ipc_saves"] = holder.get("ipc_saves", 0) + 1
            return {"success": True, "message": "saved via ipc"}

        iface._ipc_save_project = ipc_save

        result = iface.handle_command("save_project", {})
        assert result["_backend"] == "ipc"
        assert holder.get("ipc_saves") == 1
        assert holder.get("swig_saves") is None


@pytest.mark.unit
class TestSessionTransitions:
    def test_ipc_pinned_session_downgrades_when_connection_lost(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, backend, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        assert iface.session_backend == "ipc"

        backend.connected = False  # GUI closed
        iface._safe_load_board = lambda path: _FakeBoard(path)

        result = iface.handle_command("save_project", {})
        assert iface.session_backend == "swig"
        assert result["_backend"] == "swig"
        assert holder.get("swig_saves") == 1

    def test_reopen_repins(self, tmp_path, monkeypatch):
        iface, backend, holder, board_path, _ = _loaded_iface(
            tmp_path, gui_board_path=None, monkeypatch=monkeypatch
        )
        assert iface.session_backend == "swig"

        # User opens the project in the GUI, then re-opens via MCP.
        backend.open_board_path = str(board_path)
        result = iface.handle_command("open_project", {"path": str(board_path)})
        assert iface.session_backend == "ipc"
        assert result["_backend"] == "ipc"


@pytest.mark.unit
class TestBackendStateReporting:
    def test_backend_status_reports_session_pin(self, tmp_path, monkeypatch):
        iface, _, _, _, _ = _loaded_iface(tmp_path, gui_board_path=None, monkeypatch=monkeypatch)
        status = iface._backend_status()
        # IPC is connected, but the session pin is the truth.
        assert status["backend"] == "swig"
        assert status["realtime_sync"] is False
        assert status["ipc_connected"] is True

    def test_backend_status_without_project_uses_connectivity(self):
        iface = _make_iface({}, _FakeIPCBackend(connected=True), use_ipc=True)
        status = iface._backend_status()
        assert status["backend"] == "ipc"


@pytest.mark.unit
class TestPathNormalization:
    def test_normalize_handles_none_and_empty(self):
        assert KiCADInterface._normalize_board_path(None) is None
        assert KiCADInterface._normalize_board_path("") is None

    def test_match_false_without_backend(self):
        iface = _make_iface({}, None, use_ipc=False)
        assert iface._ipc_board_path_matches("C:/x/y.kicad_pcb") is False

    def test_match_false_when_backend_raises(self):
        class _Raising(_FakeIPCBackend):
            def get_open_board_path(self):
                raise RuntimeError("ipc down")

        iface = _make_iface({}, _Raising(), use_ipc=True)
        assert iface._ipc_board_path_matches("C:/x/y.kicad_pcb") is False
