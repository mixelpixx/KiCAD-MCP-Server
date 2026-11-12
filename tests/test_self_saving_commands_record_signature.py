"""
autoroute, import_ses and refill_zones write the board file themselves. Before
the fix none of them recorded that write, so the session's disk signature still
described the file as it was before the command. The next auto-save (after any
board-mutating command, or refill_zones' own) compared the file against that
stale signature and refused with "the on-disk PCB file's contents changed
externally", leaving the edit only in memory. Every later mutation was refused
the same way until the project was reopened.

The same mechanism must still refuse a genuine external edit, and must not
record a file the command did not write as the session's own board.
"""

import os
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.skipif(
    os.environ.get("KICAD_USE_REAL_PCBNEW") == "1",
    reason="drives KiCADInterface against the stubbed pcbnew",
)

pcbnew_mock = sys.modules["pcbnew"]

SES = """(session board
  (base_design board)
  (routes
    (resolution um 10)
    (network_out
      (net GND
        (wire (path F.Cu 5000 0 0 1000 0))
      )
    )
  )
)
"""


def _fake_board(path: Path, text: str = "(kicad_pcb ; routed)\n") -> MagicMock:
    board = MagicMock(name="board")
    board.GetFileName.return_value = str(path)
    board.GetFootprints.return_value = []
    board.GetTracks.return_value = []
    board.GetNetInfo.return_value.GetNetCount.return_value = 0
    board.GetAreaCount.return_value = 1
    # pcbnew's BOARD.Save writes the file.
    board.Save.side_effect = lambda p: Path(p).write_text(text)
    return board


@pytest.fixture()
def iface(tmp_path: Path) -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface()
    iface.use_ipc = False
    pcb = tmp_path / "p.kicad_pcb"
    pcb.write_text("(kicad_pcb ; as opened)\n")
    iface.board = _fake_board(pcb)
    iface._update_command_handlers()
    iface._record_board_signature()  # as open_project does
    iface._safe_load_board = lambda p: iface.board
    return iface


@pytest.fixture(autouse=True)
def _pcbnew_stub() -> Any:
    pcbnew_mock.ImportSpecctraSES.side_effect = None
    pcbnew_mock.ImportSpecctraSES.return_value = True
    old = pcbnew_mock.SaveBoard.side_effect
    pcbnew_mock.SaveBoard.side_effect = lambda p, b: Path(p).write_text("(kicad_pcb ; autosaved)\n")
    with (
        patch("commands.freerouting.preserve_project_settings", lambda p: nullcontext()),
        patch("kicad_interface.preserve_project_settings", lambda p: nullcontext()),
    ):
        yield
    pcbnew_mock.SaveBoard.side_effect = old


def _pcb(iface: Any) -> Path:
    return Path(iface.board.GetFileName())


def _ses(tmp_path: Path) -> str:
    ses = tmp_path / "p.ses"
    ses.write_text(SES)
    return str(ses)


@pytest.mark.unit
@pytest.mark.parametrize("pass_board_path", [True, False])
def test_import_ses_records_its_own_save(iface, tmp_path, pass_board_path) -> None:
    params = {"sesPath": _ses(tmp_path)}
    if pass_board_path:
        params["boardPath"] = str(_pcb(iface))
    result = iface.handle_command("import_ses", params)

    assert result["success"], result
    assert "routed" in _pcb(iface).read_text()
    assert iface._board_disk_signature == iface._disk_signature(str(_pcb(iface)))


@pytest.mark.unit
def test_mutation_after_import_ses_is_auto_saved(iface, tmp_path) -> None:
    assert iface.handle_command("import_ses", {"sesPath": _ses(tmp_path)})["success"]

    status = iface._auto_save_board()

    assert status["saved"] is True, status
    assert "diskChangedExternally" not in status
    assert "autosaved" in _pcb(iface).read_text()


@pytest.mark.unit
def test_external_edit_after_import_ses_is_still_refused(iface, tmp_path) -> None:
    assert iface.handle_command("import_ses", {"sesPath": _ses(tmp_path)})["success"]
    _pcb(iface).write_text("(kicad_pcb ; edited in KiCad)\n")

    status = iface._auto_save_board()

    assert status["saved"] is False
    assert status["diskChangedExternally"] is True
    assert "edited in KiCad" in _pcb(iface).read_text()


@pytest.mark.unit
def test_save_to_another_file_does_not_record_it_as_the_board(iface, tmp_path) -> None:
    """Saving the board to a different file leaves the session board's file
    untouched, so an external edit to that file must still be refused."""
    _pcb(iface).write_text("(kicad_pcb ; edited in KiCad)\n")
    other = tmp_path / "other.kicad_pcb"
    other.write_text("(kicad_pcb)\n")

    iface.freerouting_commands._save_board(str(other), "SES import")

    assert "routed" in other.read_text()
    status = iface._auto_save_board()
    assert status["saved"] is False
    assert status["diskChangedExternally"] is True


@pytest.mark.unit
def test_failed_save_records_nothing(iface) -> None:
    _pcb(iface).write_text("(kicad_pcb ; edited in KiCad)\n")
    iface.board.Save.side_effect = OSError("disk full")

    iface.freerouting_commands._save_board(str(_pcb(iface)), "autoroute")

    status = iface._auto_save_board()
    assert status["saved"] is False
    assert status["diskChangedExternally"] is True


@pytest.mark.unit
def test_refill_zones_auto_save_is_not_refused(iface) -> None:
    """refill_zones saves, lets a subprocess fill and save the file, reloads it,
    and is then auto-saved by handle_command like every board mutation."""

    def fake_run(cmd, **kw):
        _pcb(iface).write_text("(kicad_pcb ; zones filled)\n")
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        result = iface.handle_command("refill_zones", {})

    assert result["success"], result
    assert "autoSave" not in result, result.get("autoSave")
    assert "warnings" not in result, result.get("warnings")
