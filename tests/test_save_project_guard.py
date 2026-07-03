"""save_project divergence guard (issue #244).

The explicit save_project tool used to write pcbnew.SaveBoard unconditionally:
a direct edit to the .kicad_pcb made after the MCP loaded the board (e.g. a
manual net-name patch after a Freerouting import) was silently overwritten,
and the dispatcher then re-recorded the disk signature, blessing the clobber.

_handle_save_project now applies the same content-hash check the auto-save
path has used since the disk signature was introduced:
  * contents diverged + saving to the loaded file -> refused (success:false,
    diskChangedExternally:true) and the delegate save never runs;
  * force=true -> proceeds;
  * saving to a *different* filename -> never blocked (explicit destination);
  * no divergence -> proceeds unchanged.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_interface import KiCADInterface  # noqa: E402

pytestmark = pytest.mark.unit


class _FakeBoard:
    def __init__(self, filename):
        self._filename = str(filename)

    def GetFileName(self):
        return self._filename


class _FakeProjectCommands:
    """Records delegate calls; the real one would pcbnew.SaveBoard."""

    def __init__(self):
        self.save_calls = []

    def save_project(self, params):
        self.save_calls.append(params)
        return {"success": True, "message": "saved", "project": {"path": "x"}}


def _make_iface(tmp_path, diverged: bool):
    board_file = tmp_path / "board.kicad_pcb"
    board_file.write_text("(kicad_pcb original)", encoding="utf-8")

    iface = KiCADInterface.__new__(KiCADInterface)
    iface.board = _FakeBoard(board_file)
    iface.project_commands = _FakeProjectCommands()
    iface._last_auto_save_status = None
    iface._is_board_healthy = lambda *a, **k: True
    # Record the signature of the original content, then optionally simulate
    # an external edit so the recorded and current signatures diverge.
    iface._board_disk_signature = iface._disk_signature(str(board_file))
    if diverged:
        board_file.write_text("(kicad_pcb externally patched)", encoding="utf-8")
    return iface, board_file


class TestDivergenceRefusal:
    def test_refuses_when_disk_changed_externally(self, tmp_path):
        iface, _ = _make_iface(tmp_path, diverged=True)

        result = iface._handle_save_project({})

        assert result["success"] is False
        assert result["diskChangedExternally"] is True
        assert "force=true" in result["message"]
        assert iface.project_commands.save_calls == [], "delegate save must not run"

    def test_external_edit_survives_a_refused_save(self, tmp_path):
        iface, board_file = _make_iface(tmp_path, diverged=True)

        iface._handle_save_project({})

        assert board_file.read_text(encoding="utf-8") == "(kicad_pcb externally patched)"


class TestOverrides:
    def test_force_true_proceeds(self, tmp_path):
        iface, _ = _make_iface(tmp_path, diverged=True)

        result = iface._handle_save_project({"force": True})

        assert result["success"] is True
        assert len(iface.project_commands.save_calls) == 1

    def test_saving_to_a_different_filename_is_never_blocked(self, tmp_path):
        iface, _ = _make_iface(tmp_path, diverged=True)
        other = tmp_path / "elsewhere.kicad_pcb"

        result = iface._handle_save_project({"filename": str(other)})

        assert result["success"] is True
        assert iface.project_commands.save_calls == [{"filename": str(other)}]


class TestNoDivergence:
    def test_clean_save_proceeds_unchanged(self, tmp_path):
        iface, _ = _make_iface(tmp_path, diverged=False)

        result = iface._handle_save_project({})

        assert result["success"] is True
        assert len(iface.project_commands.save_calls) == 1

    def test_no_board_loaded_delegates(self, tmp_path):
        iface, _ = _make_iface(tmp_path, diverged=True)
        iface.board = None  # nothing loaded -> guard is moot, delegate decides

        result = iface._handle_save_project({})

        # The fake delegate reports success; the real one returns its own
        # "No board is loaded" failure. Either way the guard must not block.
        assert len(iface.project_commands.save_calls) == 1
        assert result["success"] is True
