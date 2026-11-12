"""A boardPath given to autoroute (export_dsn, import_ses) is the board the command runs on.

Before, the path was accepted and then ignored: with nothing loaded, autoroute refused with
"No board is loaded"; with a different board loaded it routed that board and saved it over
boardPath. The interface now loads the named board first, the way open_project does, so
every command handler holds it (not only the Freerouting one), and a path that differs
only in spelling (case, `..` segments) does not reload from disk.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

HANDLERS = (
    "project_commands",
    "board_commands",
    "component_commands",
    "net_copper_commands",
    "routing_commands",
    "stackup_commands",
    "via_summary_commands",
    "design_rule_commands",
    "export_commands",
    "freerouting_commands",
)


def _fake_board(path: Path) -> MagicMock:
    board = MagicMock(name=f"board:{path.name}")
    board.GetFileName.return_value = str(path)
    board.GetFootprints.return_value = []
    return board


def _make_iface(loaded: Any = None) -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    iface.board = loaded
    iface.use_ipc = False
    iface.session_backend = "swig" if loaded is not None else None
    iface.session_board_path = None
    iface._board_disk_signature = None
    iface._last_auto_save_status = None
    for name in HANDLERS:
        setattr(iface, name, MagicMock(name=name))
        getattr(iface, name).board = loaded
    iface.calls: List[Dict[str, Any]] = []

    def _autoroute(params):
        iface.calls.append({"params": params, "board": iface.freerouting_commands.board})
        return {"success": True}

    iface.freerouting_commands.autoroute.side_effect = _autoroute
    iface.command_routes = {"autoroute": iface.freerouting_commands.autoroute}
    iface._refuse_if_schematic_open = lambda command, params: None
    iface._result_backend_for_command = lambda command, result: "swig"
    iface.loaded_paths: List[str] = []
    iface.pinned: List[str] = []

    def _load(path):
        iface.loaded_paths.append(path)
        return _fake_board(Path(path))

    iface._safe_load_board = _load
    iface._pin_session_backend = lambda p: iface.pinned.append(str(p))
    iface.refreshed: List[Any] = []
    iface._refresh_symbol_library_for_project = lambda p: iface.refreshed.append(p)
    return iface


@pytest.fixture()
def boards(tmp_path: Path):
    a = tmp_path / "a.kicad_pcb"
    b = tmp_path / "b.kicad_pcb"
    a.write_text("(kicad_pcb ; a)\n")
    b.write_text("(kicad_pcb ; b)\n")
    return a, b


@pytest.mark.unit
def test_nothing_loaded_boardpath_is_loaded_for_every_handler(boards) -> None:
    a, _ = boards
    iface = _make_iface()
    out = iface.handle_command("autoroute", {"boardPath": str(a)})
    assert out["success"], out
    assert iface.loaded_paths == [str(a)]
    assert iface.board.GetFileName() == str(a)
    for name in HANDLERS:  # _update_command_handlers ran: not only the Freerouting one
        assert getattr(iface, name).board is iface.board, name
    assert iface.calls[0]["board"] is iface.board  # the handler saw the new board
    assert iface.pinned == [str(a)]
    assert iface._board_disk_signature == iface._disk_signature(str(a))


@pytest.mark.unit
def test_another_board_loaded_switches_to_boardpath(boards) -> None:
    a, b = boards
    iface = _make_iface(loaded=_fake_board(a))
    out = iface.handle_command("autoroute", {"boardPath": str(b)})
    assert out["success"], out
    assert iface.loaded_paths == [str(b)]
    assert iface.calls[0]["board"].GetFileName() == str(b)
    assert iface.routing_commands.board.GetFileName() == str(b)


@pytest.mark.unit
def test_same_board_spelled_differently_is_not_reloaded(boards, monkeypatch) -> None:
    a, _ = boards
    loaded = _fake_board(a)
    iface = _make_iface(loaded=loaded)
    # `..` segments resolve to the same file
    spelled = a.parent / "sub" / ".." / a.name
    out = iface.handle_command("autoroute", {"boardPath": str(spelled)})
    assert out["success"] and iface.loaded_paths == [] and iface.board is loaded
    # a path that differs only in case, on a case-insensitive file system
    monkeypatch.setattr("kicad_interface.os.path.normcase", lambda p: str(p).lower())
    upper = a.parent / a.name.upper()
    upper.write_text(a.read_text())  # so isfile holds on Linux too
    out = iface.handle_command("autoroute", {"boardPath": str(upper)})
    assert out["success"] and iface.loaded_paths == [] and iface.board is loaded
    # the same path exactly
    out = iface.handle_command("autoroute", {"boardPath": str(a)})
    assert out["success"] and iface.loaded_paths == [] and len(iface.calls) == 3


@pytest.mark.unit
def test_missing_file_is_refused_before_the_handler_runs(tmp_path) -> None:
    iface = _make_iface()
    out = iface.handle_command("autoroute", {"boardPath": str(tmp_path / "none.kicad_pcb")})
    assert out["success"] is False and "not found" in out["message"]
    assert iface.calls == [] and iface.loaded_paths == [] and iface.board is None


@pytest.mark.unit
def test_unloadable_board_is_a_failure_not_a_route_of_the_old_board(boards) -> None:
    a, b = boards
    iface = _make_iface(loaded=_fake_board(a))
    iface._safe_load_board = lambda p: None
    out = iface.handle_command("autoroute", {"boardPath": str(b)})
    assert out["success"] is False and "Failed to load" in out["message"]
    assert iface.calls == [] and iface.board.GetFileName() == str(a)


@pytest.mark.unit
def test_ipc_session_refuses_a_different_board(boards) -> None:
    a, b = boards
    iface = _make_iface(loaded=_fake_board(a))
    iface.session_backend = "ipc"
    iface.session_board_path = str(a)
    out = iface.handle_command("autoroute", {"boardPath": str(b)})
    assert out["success"] is False and "open_project" in out["errorDetails"]
    assert iface.calls == [] and iface.loaded_paths == []
    # the board KiCad has open is fine
    out = iface.handle_command("autoroute", {"boardPath": str(a)})
    assert out["success"] and len(iface.calls) == 1


@pytest.mark.unit
def test_without_boardpath_and_for_other_commands_nothing_changes(boards) -> None:
    a, b = boards
    loaded = _fake_board(a)
    iface = _make_iface(loaded=loaded)
    out = iface.handle_command("autoroute", {})
    assert out["success"] and iface.loaded_paths == [] and iface.board is loaded
    other = MagicMock(return_value={"success": True})
    iface.command_routes["get_board_info"] = other
    out = iface.handle_command("get_board_info", {"boardPath": str(b)})
    assert out["success"] and iface.loaded_paths == [] and iface.board is loaded
    other.assert_called_once()


@pytest.mark.unit
def test_unsaved_changes_are_not_dropped_by_a_switch(boards) -> None:
    """Auto-save refused after a mutation: the edits exist only in memory. Switching would
    drop them and is_dirty would then report clean; the switch is refused instead."""
    a, b = boards
    loaded = _fake_board(a)
    iface = _make_iface(loaded=loaded)
    iface._last_auto_save_status = {"memChangesUnsaved": True, "diskChangedExternally": True}
    out = iface.handle_command("autoroute", {"boardPath": str(b)})
    assert out["success"] is False, out
    assert "save_project" in out["errorDetails"] and "reload_board" in out["errorDetails"]
    assert iface.calls == [] and iface.loaded_paths == [] and iface.board is loaded
    assert iface._last_auto_save_status["memChangesUnsaved"] is True  # still reported dirty


@pytest.mark.unit
def test_ipc_session_with_no_swig_board_accepts_its_own_board(boards) -> None:
    """In an IPC-pinned session the SWIG board can be missing; the session's identity is
    session_board_path, so naming that board is not 'another board'."""
    a, b = boards
    iface = _make_iface()
    iface.session_backend = "ipc"
    iface.session_board_path = str(a)
    out = iface.handle_command("autoroute", {"boardPath": str(a)})
    assert out["success"], out
    assert iface.loaded_paths == [] and len(iface.calls) == 1
    out = iface.handle_command("autoroute", {"boardPath": str(b)})
    assert out["success"] is False and "open_project" in out["errorDetails"]


@pytest.mark.unit
def test_switch_moves_the_project_and_says_so(boards) -> None:
    """The switch runs open_board's steps, symbol libraries included, and the reply names
    the board the session now holds."""
    a, b = boards
    iface = _make_iface(loaded=_fake_board(a))
    out = iface.handle_command("autoroute", {"boardPath": str(b)})
    assert out["success"], out
    assert len(iface.refreshed) == 1 and str(iface.refreshed[0]).startswith(str(b.parent))
    assert out["sessionBoardPath"] == str(b)
    assert str(a) in out["boardSwitchWarning"] and str(b) in out["boardSwitchWarning"]
    # the same board again: no switch, no note
    out = iface.handle_command("autoroute", {"boardPath": str(b)})
    assert out["success"] and "boardSwitchWarning" not in out
