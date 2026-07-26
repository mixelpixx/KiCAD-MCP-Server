from unittest.mock import MagicMock

import pytest

from commands.project import ProjectCommands


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
