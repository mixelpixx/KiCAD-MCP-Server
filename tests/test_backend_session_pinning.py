"""Tests for the session-pinned backend (issue #223).

Once a project is loaded, every board command must run on the backend that
owns that load ("swig" or "ipc") until the project is closed/reopened. Before
this fix, create_project/open_project always ran on SWIG while save_project
silently upgraded to IPC mid-session and saved the GUI's (stale) board —
losing the SWIG edits.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_interface  # noqa: E402
from kicad_interface import KiCADInterface, KiCADProcessManager  # noqa: E402


class _FakeBoard:
    def __init__(self, filename):
        self._filename = str(filename)

    def GetFileName(self):
        return self._filename


class _CreatableFakeBoard(_FakeBoard):
    def __init__(self):
        super().__init__("")
        self.title = None

    def SetFileName(self, filename):
        self._filename = str(filename)

    def GetTitleBlock(self):
        title_block = MagicMock()
        title_block.SetTitle.side_effect = lambda title: setattr(self, "title", title)
        return title_block


class _FakeIPCBoardAPI:
    def __init__(self):
        self.save_calls = 0

    def get_size(self):
        return {"width": 10, "height": 20, "unit": "mm"}

    def save(self):
        self.save_calls += 1
        return True


class _FakeIPCBackend:
    def __init__(self, open_board_path=None, connected=True):
        self.connected = connected
        self.open_board_path = open_board_path
        self.board_api = _FakeIPCBoardAPI()
        self.save_calls = 0
        self.save_as_paths = []
        self.save_as_overwrites = []

    def connect(self):
        self.connected = True
        return True

    def is_connected(self):
        return self.connected

    def get_board(self):
        return self.board_api

    def get_open_board_path(self):
        return self.open_board_path

    def get_version(self):
        return "10.0-test"

    def save_project(self, path=None, overwrite=False):
        if path is not None:
            self.save_as_paths.append(str(path))
            self.save_as_overwrites.append(overwrite)
            if Path(path).exists() and not overwrite:
                return {
                    "success": False,
                    "message": f"Destination already exists: {path}",
                }
            self.open_board_path = str(path)
        else:
            self.save_calls += 1
        return {"success": True, "message": "saved via ipc backend"}


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
    def test_create_board_from_schematic_repins_after_board_swap(self, tmp_path, monkeypatch):
        """A newly created board must not inherit the previous board's IPC pin."""
        old_board_path = tmp_path / "old" / "old.kicad_pcb"
        new_board_path = tmp_path / "new" / "new.kicad_pcb"
        schematic_path = tmp_path / "new" / "new.kicad_sch"
        schematic_path.parent.mkdir(parents=True)
        schematic_path.write_text("(kicad_sch)")

        backend = _FakeIPCBackend(open_board_path=str(old_board_path))
        iface = _make_iface({}, backend, board=_FakeBoard(old_board_path))
        iface.session_backend = "ipc"
        iface.session_board_path = iface._normalize_board_path(old_board_path)
        iface._handle_sync_schematic_to_board = lambda params: {"success": True}

        created_board = _CreatableFakeBoard()
        monkeypatch.setattr(kicad_interface.pcbnew, "BOARD", lambda: created_board)
        monkeypatch.setattr(
            kicad_interface.pcbnew,
            "SaveBoard",
            lambda path, board: Path(path).write_text("(kicad_pcb)"),
        )
        monkeypatch.setattr(KiCADProcessManager, "is_running", staticmethod(lambda: False))

        result = iface._handle_create_board_from_schematic(
            {
                "schematicPath": str(schematic_path),
                "boardPath": str(new_board_path),
            }
        )

        assert result["success"] is True
        assert iface.session_board_path == iface._normalize_board_path(new_board_path)
        assert iface.session_backend == "swig"

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
        # The board must be RELOADED from disk, not left as the stale
        # pre-IPC copy.
        assert isinstance(iface.board, _FakeBoard)
        assert iface.board.GetFileName() == iface.session_board_path

    def test_failed_reopen_clears_stale_pin(self, tmp_path, monkeypatch):
        """An unrecoverable open after a pinned session must drop the old pin.

        Otherwise a leftover "ipc" pin from the previous project could route
        later commands to the old board's IPC context.
        """
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, backend, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        assert iface.session_backend == "ipc"

        # Next open succeeds at the handler level but the board is
        # SWIG-dehydrated and recovery fails.
        iface._is_board_healthy = lambda *a, **k: False
        iface._safe_load_board = lambda path: None

        result = iface.handle_command("open_project", {"path": str(board_path)})
        assert result["success"] is False
        assert iface.session_backend is None
        assert iface.session_board_path is None

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
class TestNewBoardLifecycleRouting:
    def test_save_board_uses_ipc_dispatch_in_ipc_pinned_session(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, _, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_board"] = iface._handle_save_board

        def ipc_save(params):
            holder["ipc_saves"] = holder.get("ipc_saves", 0) + 1
            return {"success": True, "message": "saved via ipc"}

        iface._ipc_save_project = ipc_save
        result = iface.handle_command("save_board", {})

        assert result["success"] is True
        assert result["_backend"] == "ipc"
        assert holder.get("ipc_saves") == 1
        assert holder.get("swig_saves") is None

    def test_close_project_saves_through_ipc_in_ipc_pinned_session(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, _, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["close_project"] = iface._handle_close_project
        iface._clear_project_state = MagicMock()

        def ipc_save(params):
            holder["ipc_saves"] = holder.get("ipc_saves", 0) + 1
            return {"success": True, "message": "saved via ipc"}

        iface._ipc_save_project = ipc_save

        result = iface.handle_command("close_project", {"save": True})

        assert result["success"] is True
        assert result["saved"] is True
        assert result["_backend"] == "ipc"
        assert holder.get("ipc_saves") == 1
        assert holder.get("swig_saves") is None
        iface._clear_project_state.assert_called_once_with()

    def test_save_as_uses_ipc_and_repins_new_path(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        new_path = tmp_path / "copy" / "copy.kicad_pcb"
        iface, backend, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_as"] = iface._handle_save_as
        iface._safe_load_board = lambda path: _FakeBoard(path)
        iface._refresh_project_context_for_board = MagicMock()
        iface._pin_session_backend = MagicMock(
            side_effect=AssertionError("successful IPC Save As must not re-probe ownership")
        )

        result = iface.handle_command("save_as", {"boardPath": str(new_path)})

        assert result["success"] is True
        assert result["_backend"] == "ipc"
        assert backend.save_as_paths == [str(new_path.resolve())]
        assert backend.save_as_overwrites == [False]
        assert iface.session_board_path == iface._normalize_board_path(new_path)
        assert iface.session_backend == "ipc"
        assert iface.board.GetFileName() == str(new_path.resolve())
        iface._refresh_project_context_for_board.assert_called_once_with(str(new_path.resolve()))
        iface._pin_session_backend.assert_not_called()
        assert holder.get("swig_saves") is None

    def test_save_as_existing_path_requires_overwrite_in_ipc_session(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        existing_path = tmp_path / "copy" / "copy.kicad_pcb"
        existing_path.parent.mkdir(parents=True)
        existing_path.write_text("(existing-board)")
        iface, backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_as"] = iface._handle_save_as
        iface._safe_load_board = lambda path: _FakeBoard(path)

        result = iface.handle_command("save_as", {"boardPath": str(existing_path)})

        assert result["success"] is False
        assert backend.save_as_paths == [str(existing_path.resolve())]
        assert backend.save_as_overwrites == [False]
        assert iface.session_board_path == iface._normalize_board_path(board_path)

    def test_save_as_existing_path_respects_explicit_overwrite_in_ipc_session(
        self, tmp_path, monkeypatch
    ):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        existing_path = tmp_path / "copy" / "copy.kicad_pcb"
        existing_path.parent.mkdir(parents=True)
        existing_path.write_text("(existing-board)")
        iface, backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_as"] = iface._handle_save_as
        iface._safe_load_board = lambda path: _FakeBoard(path)

        result = iface.handle_command(
            "save_as", {"boardPath": str(existing_path), "overwrite": True}
        )

        assert result["success"] is True
        assert backend.save_as_paths == [str(existing_path.resolve())]
        assert backend.save_as_overwrites == [True]
        assert iface.session_board_path == iface._normalize_board_path(existing_path)

    def test_save_board_current_path_uses_ipc_save_not_save_as(self, tmp_path, monkeypatch):
        """Passing the current board path is a save, not a Save As.

        ``board.save_as(current, overwrite=False)`` refuses an existing
        destination by API contract, so forwarding the echoed path made an
        ordinary save fail on IPC while succeeding on SWIG.
        """
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, backend, holder, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_board"] = iface._handle_save_board
        iface._safe_load_board = lambda path: _FakeBoard(path)

        result = iface.handle_command("save_board", {"boardPath": str(board_path)})

        assert result["success"] is True, result.get("message")
        assert result["_backend"] == "ipc"
        assert backend.save_as_paths == []  # never routed through save_as
        assert backend.save_calls == 1
        assert result["boardPath"] == iface._normalize_board_path(board_path)
        assert iface.session_board_path == iface._normalize_board_path(board_path)
        assert holder.get("swig_saves") is None

    def test_save_project_current_path_uses_ipc_save_not_save_as(self, tmp_path, monkeypatch):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_project"] = iface._handle_save_project
        iface._dirty_state = lambda path: {"diskChangedExternally": False}

        result = iface.handle_command("save_project", {"filename": str(board_path)})

        assert result["success"] is True, result.get("message")
        assert result["_backend"] == "ipc"
        assert backend.save_as_paths == []
        assert backend.save_calls == 1

    def test_ipc_save_handler_collapses_current_path_even_when_called_directly(
        self, tmp_path, monkeypatch
    ):
        """Defense in depth: the IPC handler itself must not build a Save As."""
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )

        result = iface._ipc_save_project({"filename": str(board_path)})

        assert result["success"] is True
        assert backend.save_as_paths == []
        assert backend.save_calls == 1
        assert result["boardPath"] == str(board_path.resolve())

    def test_save_board_current_path_has_same_semantics_on_ipc_and_swig(
        self, tmp_path, monkeypatch
    ):
        """The identical call must succeed on both backends (parity guard)."""
        board_path = tmp_path / "proj" / "proj.kicad_pcb"

        ipc_iface, ipc_backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        ipc_iface.command_routes["save_board"] = ipc_iface._handle_save_board
        ipc_iface._safe_load_board = lambda path: _FakeBoard(path)
        assert ipc_iface.session_backend == "ipc"
        ipc_result = ipc_iface.handle_command("save_board", {"boardPath": str(board_path)})

        swig_iface, _, holder, swig_board_path, _ = _loaded_iface(
            tmp_path, gui_board_path=None, monkeypatch=monkeypatch
        )
        swig_iface.command_routes["save_board"] = swig_iface._handle_save_board
        swig_iface.board = _FakeBoard(swig_board_path)
        assert swig_iface.session_backend == "swig"
        swig_result = swig_iface.handle_command("save_board", {"boardPath": str(swig_board_path)})

        assert ipc_result["success"] == swig_result["success"] is True
        assert ipc_result["_backend"] == "ipc"
        assert swig_result["_backend"] == "swig"
        assert ipc_backend.save_as_paths == []
        assert holder.get("swig_saves") == 1

    def test_save_board_still_treats_a_different_path_as_save_as(self, tmp_path, monkeypatch):
        """The same-path collapse must not disable real Save As."""
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        new_path = tmp_path / "copy" / "copy.kicad_pcb"
        iface, backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_board"] = iface._handle_save_board
        iface._safe_load_board = lambda path: _FakeBoard(path)
        iface._refresh_project_context_for_board = MagicMock()

        result = iface.handle_command("save_board", {"boardPath": str(new_path)})

        assert result["success"] is True
        assert backend.save_as_paths == [str(new_path.resolve())]
        assert iface.session_board_path == iface._normalize_board_path(new_path)

    def test_save_as_ipc_reload_failure_does_not_leave_stale_swig_board(
        self, tmp_path, monkeypatch
    ):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        new_path = tmp_path / "copy" / "copy.kicad_pcb"
        iface, backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.command_routes["save_as"] = iface._handle_save_as
        iface._safe_load_board = lambda path: None
        board_handlers = (
            "project_commands",
            "board_commands",
            "component_commands",
            "routing_commands",
            "design_rule_commands",
            "export_commands",
            "freerouting_commands",
        )
        for handler_name in board_handlers:
            handler = MagicMock()
            handler.board = iface.board
            setattr(iface, handler_name, handler)
        iface._update_command_handlers = KiCADInterface._update_command_handlers.__get__(
            iface, KiCADInterface
        )
        iface._record_board_signature = KiCADInterface._record_board_signature.__get__(
            iface, KiCADInterface
        )
        iface._board_disk_signature = (1, "old-board-signature")

        result = iface.handle_command("save_as", {"boardPath": str(new_path)})

        assert result["success"] is True
        assert result["_backend"] == "ipc"
        assert iface.session_board_path == iface._normalize_board_path(new_path)
        assert iface.session_backend == "ipc"
        assert iface.board is None
        assert iface._board_disk_signature is None
        assert all(getattr(iface, handler_name).board is None for handler_name in board_handlers)
        assert any("stale SWIG fallback was cleared" in warning for warning in result["warnings"])

        # The IPC session remains a fully loaded lifecycle state even without
        # a SWIG fallback. Every follow-up operation must use the same path.
        monkeypatch.setattr(KiCADProcessManager, "is_running", staticmethod(lambda: False))
        iface.command_routes.update(
            {
                "get_backend_state": iface._handle_get_backend_state,
                "is_dirty": iface._handle_is_dirty,
                "save_board": iface._handle_save_board,
                "reload_board": iface._handle_reload_board,
                "close_project": iface._handle_close_project,
            }
        )

        state = iface.handle_command("get_backend_state", {})
        assert state["loadedBoard"] is True
        assert state["boardPath"] == iface._normalize_board_path(new_path)
        assert state["dirty"] is None
        assert "IPC-owned" in state["dirtyReason"]

        dirty = iface.handle_command("is_dirty", {})
        assert dirty["boardPath"] == iface._normalize_board_path(new_path)
        assert dirty["dirty"] is None

        saved = iface.handle_command("save_board", {})
        assert saved["success"] is True
        assert saved["_backend"] == "ipc"
        assert saved["boardPath"] == iface._normalize_board_path(new_path)

        reloaded = iface.handle_command("reload_board", {})
        assert reloaded["success"] is False
        assert "No board loaded" not in reloaded["message"]
        assert str(new_path.resolve()) in reloaded["message"]

        ipc_save_count = backend.save_calls
        closed = iface.handle_command("close_project", {"save": True})
        assert closed["success"] is True
        assert closed["closed"] is True
        assert closed["saved"] is True
        assert closed["_backend"] == "ipc"
        assert backend.save_calls == ipc_save_count + 1
        assert iface.session_backend is None
        assert iface.session_board_path is None

    def test_batch_move_refuses_instead_of_mutating_swig_for_ipc_session(
        self, tmp_path, monkeypatch
    ):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, _, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        iface.component_commands = MagicMock()
        iface.command_routes["batch_move_components"] = iface._handle_batch_move_components

        result = iface.handle_command("batch_move_components", {"moves": {"R1": {"x": 1, "y": 2}}})

        assert result["success"] is False
        assert "move_component" in result["errorDetails"]
        iface.component_commands.batch_move_components.assert_not_called()

    def test_batch_move_downgrades_and_uses_reloaded_swig_when_ipc_disconnected(
        self, tmp_path, monkeypatch
    ):
        board_path = tmp_path / "proj" / "proj.kicad_pcb"
        iface, backend, _, _, _ = _loaded_iface(
            tmp_path, gui_board_path=board_path, monkeypatch=monkeypatch
        )
        backend.connected = False
        reloaded_board = _FakeBoard(board_path)
        iface._safe_load_board = lambda path: reloaded_board
        iface.component_commands = MagicMock()
        iface.component_commands.batch_move_components.return_value = {"success": True}
        iface.command_routes["batch_move_components"] = iface._handle_batch_move_components

        result = iface.handle_command(
            "batch_move_components",
            {"moves": {"R1": {"x": 1, "y": 2}}, "save": False},
        )

        assert result["success"] is True
        assert iface.session_backend == "swig"
        assert iface.board is reloaded_board
        iface.component_commands.batch_move_components.assert_called_once()


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

    def test_authoritative_path_prefers_pinned_session_over_stale_swig_board(self, tmp_path):
        old_path = tmp_path / "old.kicad_pcb"
        new_path = tmp_path / "new.kicad_pcb"
        iface = _make_iface({}, _FakeIPCBackend(str(new_path)), board=_FakeBoard(old_path))
        iface.session_backend = "ipc"
        iface.session_board_path = iface._normalize_board_path(new_path)

        assert iface._authoritative_board_path() == iface._normalize_board_path(new_path)

    def test_swig_session_without_healthy_board_is_not_reported_as_loaded(self, tmp_path):
        board_path = tmp_path / "missing.kicad_pcb"
        iface = _make_iface({}, None, use_ipc=False)
        iface.session_backend = "swig"
        iface.session_board_path = iface._normalize_board_path(board_path)
        iface.board = None

        assert iface._authoritative_board_path() is None


@pytest.mark.unit
def test_save_as_refreshes_symbol_and_footprint_project_context(tmp_path, monkeypatch):
    project_path = tmp_path / "new-project"
    board_path = project_path / "board.kicad_pcb"
    iface = _make_iface({}, None, use_ipc=False)
    iface.symbol_library_commands = MagicMock()
    iface.component_commands = MagicMock()
    iface.library_commands = MagicMock()
    footprint_library = object()
    monkeypatch.setattr(
        kicad_interface,
        "FootprintLibraryManager",
        lambda project_path: footprint_library,
    )

    iface._refresh_project_context_for_board(str(board_path))

    assert iface._current_project_path == project_path
    iface.symbol_library_commands.use_project.assert_called_once_with(project_path)
    assert iface.footprint_library is footprint_library
    assert iface.component_commands.library_manager is footprint_library
    assert iface.library_commands.library_manager is footprint_library
