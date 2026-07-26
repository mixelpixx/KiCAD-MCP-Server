import os
import sys
from unittest.mock import MagicMock

import pytest
from commands.project import ProjectCommands, normalize_fs_path


class _Board:
    def __init__(self, filename):
        self.filename = str(filename)

    def GetFileName(self):
        return self.filename

    def SetFileName(self, filename):
        self.filename = str(filename)


@pytest.mark.unit
def test_swig_save_as_refuses_existing_destination_without_overwrite(tmp_path):
    current = tmp_path / "current.kicad_pcb"
    destination = tmp_path / "existing.kicad_pcb"
    current.write_text("(current)")
    destination.write_text("(existing)")
    board = _Board(current)
    commands = ProjectCommands(board)

    result = commands.save_project({"filename": str(destination)})

    assert result["success"] is False
    assert "Destination already exists" in result["message"]
    assert board.GetFileName() == str(current)
    assert destination.read_text() == "(existing)"


@pytest.mark.unit
def test_force_external_changes_does_not_allow_destination_overwrite(tmp_path):
    current = tmp_path / "current.kicad_pcb"
    destination = tmp_path / "existing.kicad_pcb"
    current.write_text("(current)")
    destination.write_text("(existing)")
    board = _Board(current)
    commands = ProjectCommands(board)

    result = commands.save_project({"filename": str(destination), "forceExternalChanges": True})

    assert result["success"] is False
    assert board.GetFileName() == str(current)
    assert destination.read_text() == "(existing)"


@pytest.mark.unit
def test_swig_save_as_overwrites_existing_destination_when_explicit(tmp_path, monkeypatch):
    import commands.project as project_module

    current = tmp_path / "current.kicad_pcb"
    destination = tmp_path / "existing.kicad_pcb"
    current.write_text("(current)")
    destination.write_text("(existing)")
    board = _Board(current)
    save_board = MagicMock()
    monkeypatch.setattr(project_module.pcbnew, "SaveBoard", save_board)
    commands = ProjectCommands(board)

    result = commands.save_project({"filename": str(destination), "overwrite": True})

    assert result["success"] is True
    assert board.GetFileName() == str(destination)
    save_board.assert_called_once_with(str(destination), board)


@pytest.mark.unit
def test_swig_save_project_accepts_path_alias_for_new_destination(tmp_path, monkeypatch):
    import commands.project as project_module

    current = tmp_path / "current.kicad_pcb"
    destination = tmp_path / "new.kicad_pcb"
    current.write_text("(current)")
    board = _Board(current)
    save_board = MagicMock()
    monkeypatch.setattr(project_module.pcbnew, "SaveBoard", save_board)
    commands = ProjectCommands(board)

    result = commands.save_project({"path": str(destination)})

    assert result["success"] is True
    assert board.GetFileName() == str(destination)
    save_board.assert_called_once_with(str(destination), board)


@pytest.mark.unit
def test_swig_save_to_current_path_is_a_plain_save(tmp_path, monkeypatch):
    """Echoing the loaded path back must not trip the "already exists" guard."""
    import commands.project as project_module

    current = tmp_path / "current.kicad_pcb"
    current.write_text("(current)")
    board = _Board(current)
    save_board = MagicMock()
    monkeypatch.setattr(project_module.pcbnew, "SaveBoard", save_board)
    commands = ProjectCommands(board)

    result = commands.save_project({"filename": str(current)})

    assert result["success"] is True
    assert board.GetFileName() == str(current)
    save_board.assert_called_once_with(str(current), board)


@pytest.mark.unit
def test_swig_save_to_current_path_ignores_windows_case_folding(tmp_path, monkeypatch):
    """Windows regression: C:\\Project\\Board.kicad_pcb == c:\\project\\board.kicad_pcb.

    A raw string compare called the second spelling a Save As, then refused it
    because the destination existed and overwrite defaulted to False. Linux CI
    cannot reproduce this with real paths (case *is* significant on POSIX), so
    the platform's case-folding rule is simulated by patching ``normcase`` — the
    same hook the production code relies on.
    """
    import commands.project as project_module

    current = tmp_path / "Current.kicad_pcb"
    current.write_text("(current)")
    board = _Board(current)
    save_board = MagicMock()
    monkeypatch.setattr(project_module.pcbnew, "SaveBoard", save_board)
    monkeypatch.setattr(project_module.os.path, "normcase", lambda p: str(p).lower())
    commands = ProjectCommands(board)

    result = commands.save_project({"filename": str(current).upper()})

    assert result["success"] is True, result.get("message")
    # Identity is untouched: this was a save, not a Save As to a new file.
    assert board.GetFileName() == str(current)
    # The board's own path is written, not the caller's alternate spelling.
    save_board.assert_called_once_with(str(current), board)


@pytest.mark.unit
def test_swig_save_through_symlinked_spelling_is_a_plain_save(tmp_path, monkeypatch):
    """A symlink pointing at the loaded board is the same file, not a Save As."""
    import commands.project as project_module

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    current = real_dir / "board.kicad_pcb"
    current.write_text("(current)")
    link_dir = tmp_path / "link"
    try:
        link_dir.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - unprivileged Windows
        pytest.skip("symlink creation not permitted on this platform")

    board = _Board(current)
    save_board = MagicMock()
    monkeypatch.setattr(project_module.pcbnew, "SaveBoard", save_board)
    commands = ProjectCommands(board)

    result = commands.save_project({"filename": str(link_dir / "board.kicad_pcb")})

    assert result["success"] is True, result.get("message")
    assert board.GetFileName() == str(current)
    save_board.assert_called_once_with(str(current), board)


@pytest.mark.unit
def test_normalize_fs_path_canonicalizes_for_same_file_comparison(tmp_path, monkeypatch):
    assert normalize_fs_path(None) is None
    assert normalize_fs_path("") is None

    lower = str(tmp_path / "board.kicad_pcb")
    # Redundant segments collapse on every platform.
    detoured = str(tmp_path / "sub" / ".." / "board.kicad_pcb")
    assert normalize_fs_path(detoured) == normalize_fs_path(lower)
    # Relative input is anchored to cwd, not left relative.
    monkeypatch.chdir(tmp_path)
    assert normalize_fs_path("board.kicad_pcb") == normalize_fs_path(lower)

    upper = lower.upper()
    if sys.platform == "win32":
        assert normalize_fs_path(lower) == normalize_fs_path(upper)
    else:
        assert normalize_fs_path(lower) != normalize_fs_path(upper)
    # Case folding follows the platform rule via normcase.
    monkeypatch.setattr(os.path, "normcase", lambda p: str(p).lower())
    assert normalize_fs_path(lower) == normalize_fs_path(upper)


@pytest.mark.unit
def test_failed_swig_save_as_does_not_change_board_identity(tmp_path, monkeypatch):
    import commands.project as project_module

    current = tmp_path / "current.kicad_pcb"
    destination = tmp_path / "new.kicad_pcb"
    current.write_text("(current)")
    board = _Board(current)
    monkeypatch.setattr(project_module.pcbnew, "SaveBoard", lambda path, board: False)
    commands = ProjectCommands(board)

    result = commands.save_project({"filename": str(destination)})

    assert result["success"] is False
    assert board.GetFileName() == str(current)
