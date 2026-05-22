"""
Tests for SWIG board-dehydration detection and recovery in KiCADInterface.

Reproduces the failure mode users hit on KiCAD nightly builds: after sequences
like delete_trace + add_via, pcbnew.LoadBoard returns a "dehydrated" BOARD —
a SWIG proxy whose method dispatch table is missing, so every method access
raises AttributeError. Without recovery, every subsequent call fails and
open_project keeps reporting fake success because LoadBoard didn't raise.

Also covers the check_kicad_ui consistency fix where running and processes
could disagree.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Fixtures: stand-ins for SWIG BOARD proxies
# ---------------------------------------------------------------------------


def _make_dehydrated_board() -> Any:
    """A bare object simulating the post-dehydration SwigPyObject — no methods."""

    class _Dehydrated:
        # Intentionally empty: hasattr(...) for the health-check methods
        # returns False, matching the symptom users hit.
        pass

    return _Dehydrated()


def _make_healthy_board() -> Any:
    """A MagicMock that satisfies _is_board_healthy."""
    board = MagicMock(name="HealthyBoard")
    board.GetDesignSettings = MagicMock(return_value=MagicMock())
    board.GetBoardEdgesBoundingBox = MagicMock(return_value=MagicMock())
    board.GetFileName = MagicMock(return_value="/tmp/test.kicad_pcb")
    return board


def _make_iface() -> Any:
    """Build a KiCADInterface skipping __init__ — same pattern as test_erc_handler.

    handle_command reads `use_ipc` and `ipc_board_api` early; set them so a
    test exercising the routing layer doesn't crash on the IPC short-circuit.
    """
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
        iface.use_ipc = False
        iface.ipc_board_api = None
        return iface


# ---------------------------------------------------------------------------
# _is_board_healthy
# ---------------------------------------------------------------------------


def test_is_board_healthy_returns_false_for_none():
    iface = _make_iface()
    iface.board = None
    assert iface._is_board_healthy() is False


def test_is_board_healthy_returns_false_for_dehydrated_proxy():
    iface = _make_iface()
    iface.board = _make_dehydrated_board()
    assert iface._is_board_healthy() is False


def test_is_board_healthy_returns_true_for_real_board():
    iface = _make_iface()
    iface.board = _make_healthy_board()
    assert iface._is_board_healthy() is True


def test_is_board_healthy_accepts_explicit_target():
    iface = _make_iface()
    iface.board = None  # self.board is broken
    healthy = _make_healthy_board()
    # Explicit argument bypasses self.board
    assert iface._is_board_healthy(healthy) is True
    assert iface._is_board_healthy(_make_dehydrated_board()) is False


# ---------------------------------------------------------------------------
# _safe_load_board
# ---------------------------------------------------------------------------


def test_safe_load_board_returns_loaded_board_when_healthy():
    iface = _make_iface()
    healthy = _make_healthy_board()
    with patch("kicad_interface.pcbnew") as mock_pcbnew:
        mock_pcbnew.LoadBoard = MagicMock(return_value=healthy)
        result = iface._safe_load_board("/tmp/x.kicad_pcb")
    assert result is healthy


def test_safe_load_board_retries_after_pcbnew_reload_when_dehydrated():
    iface = _make_iface()
    dehydrated = _make_dehydrated_board()
    healthy = _make_healthy_board()

    # First LoadBoard returns dehydrated → reload pcbnew → second LoadBoard returns healthy
    with patch("kicad_interface.pcbnew") as mock_pcbnew, patch("importlib.reload") as mock_reload:
        mock_pcbnew.LoadBoard = MagicMock(side_effect=[dehydrated, healthy])
        mock_reload.return_value = mock_pcbnew  # reload returns the (mock) module
        result = iface._safe_load_board("/tmp/x.kicad_pcb")

    assert result is healthy
    assert mock_pcbnew.LoadBoard.call_count == 2
    mock_reload.assert_called_once()


def test_safe_load_board_returns_none_when_recovery_fails():
    iface = _make_iface()
    dehydrated = _make_dehydrated_board()

    with patch("kicad_interface.pcbnew") as mock_pcbnew, patch("importlib.reload") as mock_reload:
        mock_pcbnew.LoadBoard = MagicMock(return_value=dehydrated)  # always dehydrated
        mock_reload.return_value = mock_pcbnew
        result = iface._safe_load_board("/tmp/x.kicad_pcb")

    assert result is None


def test_safe_load_board_returns_none_when_loadboard_raises():
    iface = _make_iface()
    with patch("kicad_interface.pcbnew") as mock_pcbnew:
        mock_pcbnew.LoadBoard = MagicMock(side_effect=RuntimeError("io error"))
        result = iface._safe_load_board("/tmp/missing.kicad_pcb")
    assert result is None


# ---------------------------------------------------------------------------
# handle_command("open_project") — surfacing dehydration vs. recovery
# ---------------------------------------------------------------------------


def _wire_open_project(iface: Any, board_to_assign: Any, board_path: str) -> None:
    """Make iface.project_commands.open_project return success and assign a board."""
    iface.project_commands = MagicMock()

    def _fake(params):
        iface.project_commands.board = board_to_assign
        return {
            "success": True,
            "message": f"Opened project: {Path(board_path).name}",
            "project": {
                "name": Path(board_path).stem,
                "path": board_path,
                "boardPath": board_path,
            },
        }

    iface.project_commands.open_project = _fake
    # Stub the rest of _update_command_handlers' targets
    for attr in (
        "board_commands",
        "component_commands",
        "routing_commands",
        "design_rule_commands",
        "export_commands",
        "freerouting_commands",
    ):
        setattr(iface, attr, MagicMock())
    # Provide minimal command_routes so handle_command can route
    iface.command_routes = {"open_project": iface.project_commands.open_project}


def test_handle_open_project_surfaces_dehydration_when_recovery_fails():
    """If LoadBoard returns a dehydrated proxy and recovery fails, the MCP must
    return success=False — never claim "Opened project" while the board is
    unusable. This is the fix for the silent-success bug users hit."""
    iface = _make_iface()
    dehydrated = _make_dehydrated_board()
    _wire_open_project(iface, dehydrated, "/tmp/test.kicad_pcb")
    iface._safe_load_board = MagicMock(return_value=None)  # recovery impossible

    result = iface.handle_command("open_project", {"filename": "/tmp/test.kicad_pro"})

    assert result["success"] is False, f"Expected failure, got: {result}"
    combined = (result.get("errorDetails", "") + result.get("message", "")).lower()
    assert "dehydrated" in combined or "swigpyobject" in combined


def test_handle_open_project_recovers_via_safe_load_board():
    """When _safe_load_board succeeds, open_project should report success
    with a warning and the recovered board should be installed."""
    iface = _make_iface()
    dehydrated = _make_dehydrated_board()
    healthy = _make_healthy_board()
    _wire_open_project(iface, dehydrated, "/tmp/test.kicad_pcb")
    iface._safe_load_board = MagicMock(return_value=healthy)

    result = iface.handle_command("open_project", {"filename": "/tmp/test.kicad_pro"})

    assert result["success"] is True, f"Expected recovery success, got: {result}"
    assert iface.board is healthy
    iface._safe_load_board.assert_called_once_with("/tmp/test.kicad_pcb")
    warnings = result.get("warnings", [])
    assert any("dehydrated" in w.lower() for w in warnings)


def test_handle_open_project_passes_through_when_already_healthy():
    """The fast path: LoadBoard returned a healthy board, no recovery needed."""
    iface = _make_iface()
    healthy = _make_healthy_board()
    _wire_open_project(iface, healthy, "/tmp/test.kicad_pcb")
    iface._safe_load_board = MagicMock(
        side_effect=AssertionError("should not be called when board is healthy")
    )

    result = iface.handle_command("open_project", {"filename": "/tmp/test.kicad_pro"})

    assert result["success"] is True
    assert iface.board is healthy
    assert "warnings" not in result  # no recovery happened


# ---------------------------------------------------------------------------
# _auto_save_board — recover if save dehydrates the board in-memory
# ---------------------------------------------------------------------------


def test_auto_save_recovers_when_save_leaves_board_dehydrated():
    """If pcbnew.SaveBoard somehow corrupts the in-memory BOARD (observed on
    nightlies after delete_trace + auto-save), _auto_save_board reloads from
    disk so the next command sees a usable proxy."""
    iface = _make_iface()

    # Start with a healthy board that becomes dehydrated after SaveBoard runs
    healthy = _make_healthy_board()
    healthy.GetFileName = MagicMock(return_value="/tmp/test.kicad_pcb")
    iface.board = healthy

    recovered = _make_healthy_board()
    iface._safe_load_board = MagicMock(return_value=recovered)
    # Stub _update_command_handlers' downstream targets
    for attr in (
        "project_commands",
        "board_commands",
        "component_commands",
        "routing_commands",
        "design_rule_commands",
        "export_commands",
        "freerouting_commands",
    ):
        setattr(iface, attr, MagicMock())

    def _save_then_dehydrate(path, board):
        # SaveBoard succeeds but leaves iface.board unusable
        iface.board = _make_dehydrated_board()
        iface.board.GetFileName = MagicMock(return_value="/tmp/test.kicad_pcb")

    with patch("kicad_interface.pcbnew") as mock_pcbnew:
        mock_pcbnew.SaveBoard = MagicMock(side_effect=_save_then_dehydrate)
        iface._auto_save_board()

    assert iface.board is recovered
    iface._safe_load_board.assert_called_once_with("/tmp/test.kicad_pcb")


# ---------------------------------------------------------------------------
# check_kicad_ui consistency fix
# ---------------------------------------------------------------------------


def test_check_kicad_ui_running_false_when_no_processes():
    iface = _make_iface()
    with patch("kicad_interface.KiCADProcessManager") as MockMgr:
        MockMgr.return_value.get_process_info.return_value = []
        result = iface._handle_check_kicad_ui({})
    assert result["success"] is True
    assert result["running"] is False
    assert result["processes"] == []


def test_check_kicad_ui_running_true_when_processes_present():
    iface = _make_iface()
    with patch("kicad_interface.KiCADProcessManager") as MockMgr:
        MockMgr.return_value.get_process_info.return_value = [
            {"pid": "1234", "name": "kicad", "command": "/Applications/KiCad/.../kicad"}
        ]
        result = iface._handle_check_kicad_ui({})
    assert result["success"] is True
    assert result["running"] is True
    assert len(result["processes"]) == 1


def test_check_kicad_ui_running_and_processes_never_disagree():
    """Regression test for the old race where running=True coexisted with
    processes=[] because is_running() and get_process_info() used different
    detection methods."""
    iface = _make_iface()
    with patch("kicad_interface.KiCADProcessManager") as MockMgr:
        # Even if some hypothetical separate is_running() returned True,
        # only get_process_info matters now.
        MockMgr.return_value.is_running.return_value = True
        MockMgr.return_value.get_process_info.return_value = []
        result = iface._handle_check_kicad_ui({})
    assert result["running"] is False
    assert result["processes"] == []


# ---------------------------------------------------------------------------
# run_drc — caller-overridable timeout
# ---------------------------------------------------------------------------


def test_run_drc_honors_timeout_sec_param():
    """timeoutSec param must be passed to the subprocess.run timeout argument."""
    import subprocess as _sp

    from commands.design_rules import DesignRuleCommands

    cmds = DesignRuleCommands(board=_make_healthy_board())
    cmds.board.GetFileName = MagicMock(return_value="/tmp/exists.kicad_pcb")

    captured: dict = {}

    def _fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        # Raise TimeoutExpired so we don't need to fake JSON output
        raise _sp.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    with (
        patch("os.path.exists", return_value=True),
        patch("subprocess.run", side_effect=_fake_run),
        patch.object(cmds, "_find_kicad_cli", return_value="/usr/bin/kicad-cli"),
    ):
        result = cmds.run_drc({"timeoutSec": 45})

    assert captured["timeout"] == 45
    assert result["success"] is False
    assert "45" in result["errorDetails"]


def test_run_drc_clamps_extreme_timeout_values():
    """Bad timeoutSec values must be clamped, not crash."""
    import subprocess as _sp

    from commands.design_rules import DesignRuleCommands

    cmds = DesignRuleCommands(board=_make_healthy_board())
    cmds.board.GetFileName = MagicMock(return_value="/tmp/exists.kicad_pcb")

    captured: dict = {}

    def _fake_run(cmd, **kwargs):
        captured.setdefault("timeouts", []).append(kwargs.get("timeout"))
        raise _sp.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    with (
        patch("os.path.exists", return_value=True),
        patch("subprocess.run", side_effect=_fake_run),
        patch.object(cmds, "_find_kicad_cli", return_value="/usr/bin/kicad-cli"),
    ):
        cmds.run_drc({"timeoutSec": -100})  # below clamp
        cmds.run_drc({"timeoutSec": 99999})  # above clamp
        cmds.run_drc({"timeoutSec": "garbage"})  # unparseable → default 600

    assert captured["timeouts"][0] == 10  # clamped to min
    assert captured["timeouts"][1] == 1800  # clamped to max
    assert captured["timeouts"][2] == 600  # fallback default
