"""
Tests for the auto-save guard in kicad_interface._auto_save_board.

The guard is meant to prevent the MCP server from silently overwriting a
.kicad_pcb file that was modified externally between LoadBoard and
SaveBoard (e.g. by KiCad GUI's own save, a git checkout, or another
process). Behaviour exercised here:

  - First-load semantics: with no recorded signature, auto-save proceeds.
  - Detect external change: when the on-disk file has been altered since
    the recorded signature, auto-save is refused and the in-memory
    mutation is NOT written to disk.
  - Backup creation: a successful save copies the prior file contents to
    `.mcp-backups/<name>.<timestamp>` before overwriting.
  - Backup pruning: only the most recent N backups are retained.
  - Signature update: after a successful save, the recorded signature is
    refreshed so subsequent saves are not falsely flagged.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_iface() -> Any:
    """Construct a KiCADInterface bypassing __init__ (avoids pcbnew / IPC)."""
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    iface.board = None
    iface._board_disk_signature = None
    iface._auto_save_backup_keep = 5
    return iface


@pytest.fixture()
def iface():
    return _make_iface()


@pytest.fixture()
def board_file(tmp_path: Path) -> Path:
    """A temp .kicad_pcb file with placeholder contents."""
    f = tmp_path / "test.kicad_pcb"
    f.write_text("(kicad_pcb (version 1) (generator test))\n")
    return f


def _fake_board(path: str) -> MagicMock:
    """A MagicMock that quacks like a pcbnew BOARD for our helpers."""
    b = MagicMock()
    b.GetFileName.return_value = path
    return b


# ---------------------------------------------------------------------------
# _disk_signature: read-only, no side effects
# ---------------------------------------------------------------------------


def test_disk_signature_returns_mtime_and_hash(iface, board_file):
    sig = iface._disk_signature(str(board_file))
    assert sig is not None
    mtime_ns, sha = sig
    assert isinstance(mtime_ns, int) and mtime_ns > 0
    assert isinstance(sha, str) and len(sha) == 64  # sha256 hex


def test_disk_signature_returns_none_for_missing_file(iface, tmp_path: Path):
    assert iface._disk_signature(str(tmp_path / "does-not-exist.kicad_pcb")) is None


def test_disk_signature_changes_when_file_changes(iface, board_file):
    s1 = iface._disk_signature(str(board_file))
    # ensure mtime tick (filesystems vary; nanoseconds usually suffice but
    # add a small sleep for resolutions that don't)
    time.sleep(0.01)
    board_file.write_text(board_file.read_text() + "; modified\n")
    s2 = iface._disk_signature(str(board_file))
    assert s1 != s2
    assert s1[1] != s2[1]  # hash differs


# ---------------------------------------------------------------------------
# _auto_save_board: skip cases (no board / no path)
# ---------------------------------------------------------------------------


def test_auto_save_skips_when_no_board(iface):
    iface.board = None
    result = iface._auto_save_board()
    assert result == {"saved": False, "skipped": "no board loaded"}


def test_auto_save_skips_when_no_path(iface):
    iface.board = MagicMock()
    iface.board.GetFileName.return_value = ""
    result = iface._auto_save_board()
    assert result["saved"] is False
    assert "skipped" in result


# ---------------------------------------------------------------------------
# _auto_save_board: happy-path save with signature tracking + backup
# ---------------------------------------------------------------------------


def test_auto_save_with_matching_signature_proceeds(iface, board_file):
    iface.board = _fake_board(str(board_file))
    iface._record_board_signature()
    pre_sig = iface._board_disk_signature
    assert pre_sig is not None

    save_calls = []

    def fake_save(path, board):
        save_calls.append((path, board))
        # Simulate pcbnew rewriting the file
        Path(path).write_text("(kicad_pcb (version 1) (generator test) ; saved)\n")

    with patch("kicad_interface.pcbnew") as mock_pcb:
        mock_pcb.SaveBoard.side_effect = fake_save
        result = iface._auto_save_board()

    assert result["saved"] is True
    assert result["boardPath"] == str(board_file)
    assert len(save_calls) == 1
    # Signature should have been refreshed
    assert iface._board_disk_signature is not None
    assert iface._board_disk_signature != pre_sig


def test_auto_save_creates_backup_before_writing(iface, board_file):
    iface.board = _fake_board(str(board_file))
    iface._record_board_signature()

    original_contents = board_file.read_text()

    def fake_save(path, board):
        Path(path).write_text("(kicad_pcb ; overwritten)\n")

    with patch("kicad_interface.pcbnew") as mock_pcb:
        mock_pcb.SaveBoard.side_effect = fake_save
        result = iface._auto_save_board()

    assert result["saved"] is True
    backup_dir = board_file.parent / ".mcp-backups"
    assert backup_dir.is_dir()
    backups = list(backup_dir.glob(f"{board_file.name}.*"))
    assert len(backups) == 1
    # Backup must contain the PRE-save contents (snapshot before overwrite)
    assert backups[0].read_text() == original_contents
    # Returned path matches the file we created
    assert result["backup"] == str(backups[0])


# ---------------------------------------------------------------------------
# _auto_save_board: refuses when disk diverged from recorded signature
# ---------------------------------------------------------------------------


def test_auto_save_refuses_when_disk_changed_externally(iface, board_file):
    iface.board = _fake_board(str(board_file))
    iface._record_board_signature()

    # Simulate an external actor (KiCad GUI, git, another process)
    # writing the file after we loaded it.
    time.sleep(0.01)
    board_file.write_text("(kicad_pcb ; changed by someone else)\n")

    with patch("kicad_interface.pcbnew") as mock_pcb:
        result = iface._auto_save_board()
        assert mock_pcb.SaveBoard.call_count == 0  # MUST NOT save

    assert result["saved"] is False
    assert result["diskChangedExternally"] is True
    assert result["memChangesUnsaved"] is True
    assert "warning" in result
    # File on disk must still hold the external content, untouched
    assert "changed by someone else" in board_file.read_text()


def test_auto_save_first_save_with_no_recorded_signature_proceeds(iface, board_file):
    """If we never loaded the file (e.g. first save_project after create),
    treat it as a normal first save rather than refusing."""
    iface.board = _fake_board(str(board_file))
    iface._board_disk_signature = None  # explicit: nothing recorded yet

    with patch("kicad_interface.pcbnew") as mock_pcb:
        mock_pcb.SaveBoard.side_effect = lambda p, b: Path(p).write_text("first\n")
        result = iface._auto_save_board()

    assert result["saved"] is True
    assert iface._board_disk_signature is not None  # now recorded


# ---------------------------------------------------------------------------
# Backup rotation: keep only N most-recent
# ---------------------------------------------------------------------------


def test_backup_pruning_keeps_only_n_most_recent(iface, board_file):
    iface.board = _fake_board(str(board_file))
    iface._auto_save_backup_keep = 3

    def fake_save(path, board):
        Path(path).write_text(f"(kicad_pcb ; save at {time.time_ns()})\n")

    with patch("kicad_interface.pcbnew") as mock_pcb:
        mock_pcb.SaveBoard.side_effect = fake_save
        for _ in range(7):
            iface._record_board_signature()
            iface._auto_save_board()
            time.sleep(0.005)  # ensure unique timestamps

    backup_dir = board_file.parent / ".mcp-backups"
    backups = sorted(backup_dir.glob(f"{board_file.name}.*"))
    assert len(backups) == 3
