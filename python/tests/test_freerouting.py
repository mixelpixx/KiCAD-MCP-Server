"""
Tests for the Freerouting autoroute integration.

Covers:
  - FreeroutingCommands.check_freerouting (dependency detection)
  - FreeroutingCommands.export_dsn (DSN export via pcbnew)
  - FreeroutingCommands.import_ses (SES import via pcbnew)
  - FreeroutingCommands.autoroute (full pipeline)
  - Error handling: missing board, missing java, missing JAR, timeouts
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from commands.freerouting import FreeroutingCommands, _find_java

# Ensure the pcbnew mock from conftest is available at module level
# so methods that do `import pcbnew` get the mock.
pcbnew_mock = sys.modules["pcbnew"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_pcbnew_mock():
    """Reset pcbnew mock before each test."""
    pcbnew_mock.reset_mock()
    # Clear side_effects that persist through reset_mock
    pcbnew_mock.ExportSpecctraDSN.side_effect = None
    pcbnew_mock.ExportSpecctraDSN.return_value = MagicMock()
    pcbnew_mock.ImportSpecctraSES.side_effect = None
    pcbnew_mock.ImportSpecctraSES.return_value = MagicMock()
    yield


@pytest.fixture
def mock_board():
    """Create a mock pcbnew.BOARD with minimal interface."""
    board = MagicMock()
    board.GetFileName.return_value = "/tmp/test_project/test.kicad_pcb"
    board.GetTracks.return_value = []
    return board


@pytest.fixture
def cmds(mock_board):
    """FreeroutingCommands with a mock board."""
    return FreeroutingCommands(board=mock_board)


@pytest.fixture
def cmds_no_board():
    """FreeroutingCommands without a board."""
    return FreeroutingCommands(board=None)


# ---------------------------------------------------------------------------
# check_freerouting
# ---------------------------------------------------------------------------


class TestCheckFreerouting:
    def test_java_not_found(self, cmds):
        with patch(
            "commands.freerouting._find_java", return_value=None
        ):
            result = cmds.check_freerouting(
                {"freeroutingJar": "/nonexistent.jar"}
            )
        assert result["success"] is True
        assert result["java"]["found"] is False
        assert result["freerouting"]["jar_found"] is False
        assert result["ready"] is False

    def test_java_found_no_jar(self, cmds):
        with patch(
            "commands.freerouting._find_java", return_value="/usr/bin/java"
        ), patch(
            "commands.freerouting.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(
                stderr='openjdk version "17.0.1"', stdout=""
            )
            result = cmds.check_freerouting(
                {"freeroutingJar": "/nonexistent.jar"}
            )
        assert result["java"]["found"] is True
        assert result["java"]["path"] == "/usr/bin/java"
        assert result["freerouting"]["jar_found"] is False
        assert result["ready"] is False

    def test_all_ready(self, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        with patch(
            "commands.freerouting._find_java", return_value="/usr/bin/java"
        ), patch(
            "commands.freerouting.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(
                stderr='openjdk version "17.0.1"', stdout=""
            )
            result = cmds.check_freerouting(
                {"freeroutingJar": str(jar)}
            )
        assert result["ready"] is True


# ---------------------------------------------------------------------------
# export_dsn
# ---------------------------------------------------------------------------


class TestExportDsn:
    def test_no_board(self, cmds_no_board):
        result = cmds_no_board.export_dsn({})
        assert result["success"] is False
        assert "No board" in result["message"]

    def test_export_success(self, cmds, tmp_path):
        board_path = str(tmp_path / "test.kicad_pcb")
        dsn_path = str(tmp_path / "test.dsn")
        cmds.board.GetFileName.return_value = board_path

        pcbnew_mock.ExportSpecctraDSN.return_value = True
        # Simulate DSN file creation
        Path(dsn_path).write_text("(pcb test)")

        result = cmds.export_dsn({})
        assert result["success"] is True
        assert result["path"] == dsn_path
        pcbnew_mock.ExportSpecctraDSN.assert_called_once_with(
            cmds.board, dsn_path
        )

    def test_export_custom_path(self, cmds, tmp_path):
        output = str(tmp_path / "custom.dsn")
        pcbnew_mock.ExportSpecctraDSN.return_value = True
        Path(output).write_text("(pcb test)")

        result = cmds.export_dsn({"outputPath": output})
        assert result["success"] is True
        assert result["path"] == output

    def test_export_failure(self, cmds):
        pcbnew_mock.ExportSpecctraDSN.side_effect = Exception("DSN error")
        result = cmds.export_dsn({})
        assert result["success"] is False
        assert "DSN error" in result["errorDetails"]


# ---------------------------------------------------------------------------
# import_ses
# ---------------------------------------------------------------------------


class TestImportSes:
    def test_no_board(self, cmds_no_board):
        result = cmds_no_board.import_ses({"sesPath": "/tmp/test.ses"})
        assert result["success"] is False
        assert "No board" in result["message"]

    def test_missing_ses_path(self, cmds):
        result = cmds.import_ses({})
        assert result["success"] is False
        assert "Missing sesPath" in result["message"]

    def test_ses_file_not_found(self, cmds):
        result = cmds.import_ses({"sesPath": "/nonexistent/test.ses"})
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_import_success(self, cmds, tmp_path):
        ses_file = tmp_path / "test.ses"
        ses_file.write_text("(session test)")

        pcbnew_mock.ImportSpecctraSES.return_value = True
        cmds.board.GetTracks.return_value = []

        result = cmds.import_ses({"sesPath": str(ses_file)})
        assert result["success"] is True
        pcbnew_mock.ImportSpecctraSES.assert_called_once_with(
            cmds.board, str(ses_file)
        )

    def test_import_failure(self, cmds, tmp_path):
        ses_file = tmp_path / "test.ses"
        ses_file.write_text("(session test)")

        pcbnew_mock.ImportSpecctraSES.side_effect = Exception("SES error")
        result = cmds.import_ses({"sesPath": str(ses_file)})
        assert result["success"] is False
        assert "SES error" in result["errorDetails"]


# ---------------------------------------------------------------------------
# autoroute (full pipeline)
# ---------------------------------------------------------------------------


class TestAutoroute:
    def test_no_board(self, cmds_no_board):
        result = cmds_no_board.autoroute({})
        assert result["success"] is False
        assert "No board" in result["message"]

    def test_no_java(self, cmds):
        with patch(
            "commands.freerouting._find_java", return_value=None
        ):
            result = cmds.autoroute({})
        assert result["success"] is False
        assert "Java not found" in result["message"]

    def test_no_jar(self, cmds):
        with patch(
            "commands.freerouting._find_java", return_value="/usr/bin/java"
        ):
            result = cmds.autoroute(
                {"freeroutingJar": "/nonexistent/freerouting.jar"}
            )
        assert result["success"] is False
        assert "JAR not found" in result["message"]

    @patch("commands.freerouting.subprocess.run")
    def test_dsn_export_fails(self, mock_run, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()

        pcbnew_mock.ExportSpecctraDSN.side_effect = Exception(
            "export fail"
        )

        with patch(
            "commands.freerouting._find_java", return_value="/usr/bin/java"
        ):
            result = cmds.autoroute({"freeroutingJar": str(jar)})
        assert result["success"] is False
        assert "DSN export failed" in result["message"]

    @patch("commands.freerouting.subprocess.run")
    def test_freerouting_timeout(self, mock_run, cmds, tmp_path):
        import subprocess

        jar = tmp_path / "freerouting.jar"
        jar.touch()
        board_dir = tmp_path / "project"
        board_dir.mkdir()
        board_file = board_dir / "test.kicad_pcb"
        board_file.touch()
        dsn_file = board_dir / "test.dsn"

        cmds.board.GetFileName.return_value = str(board_file)
        pcbnew_mock.ExportSpecctraDSN.side_effect = (
            lambda b, p: (dsn_file.write_text("(pcb)"), True)[1]
        )
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="", timeout=10
        )

        with patch(
            "commands.freerouting._find_java", return_value="/usr/bin/java"
        ):
            result = cmds.autoroute(
                {"freeroutingJar": str(jar), "timeout": 10}
            )
        assert result["success"] is False
        assert "timed out" in result["message"]

    @patch("commands.freerouting.subprocess.run")
    def test_full_success(self, mock_run, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        board_dir = tmp_path / "project"
        board_dir.mkdir()
        board_file = board_dir / "test.kicad_pcb"
        board_file.touch()
        dsn_file = board_dir / "test.dsn"
        ses_file = board_dir / "test.ses"

        cmds.board.GetFileName.return_value = str(board_file)

        # DSN export creates file
        pcbnew_mock.ExportSpecctraDSN.side_effect = (
            lambda b, p: (dsn_file.write_text("(pcb)"), True)[1]
        )
        # Freerouting creates SES file
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Routing completed", stderr=""
        )
        ses_file.write_text("(session)")

        # SES import succeeds
        pcbnew_mock.ImportSpecctraSES.return_value = True

        # Board tracks after import
        track = MagicMock()
        track.GetClass.return_value = "PCB_TRACK"
        via = MagicMock()
        via.GetClass.return_value = "PCB_VIA"
        cmds.board.GetTracks.return_value = [track, track, via]

        with patch(
            "commands.freerouting._find_java", return_value="/usr/bin/java"
        ):
            result = cmds.autoroute({"freeroutingJar": str(jar)})

        assert result["success"] is True
        assert result["board_stats"]["tracks"] == 2
        assert result["board_stats"]["vias"] == 1
        assert "elapsed_seconds" in result
        pcbnew_mock.ExportSpecctraDSN.assert_called_once()
        pcbnew_mock.ImportSpecctraSES.assert_called_once()

    @patch("commands.freerouting.subprocess.run")
    def test_freerouting_nonzero_exit(
        self, mock_run, cmds, tmp_path
    ):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        board_dir = tmp_path / "project"
        board_dir.mkdir()
        board_file = board_dir / "test.kicad_pcb"
        board_file.touch()
        dsn_file = board_dir / "test.dsn"

        cmds.board.GetFileName.return_value = str(board_file)
        pcbnew_mock.ExportSpecctraDSN.side_effect = (
            lambda b, p: (dsn_file.write_text("(pcb)"), True)[1]
        )
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="OutOfMemoryError"
        )

        with patch(
            "commands.freerouting._find_java", return_value="/usr/bin/java"
        ):
            result = cmds.autoroute({"freeroutingJar": str(jar)})

        assert result["success"] is False
        assert "exited with code 1" in result["message"]


# ---------------------------------------------------------------------------
# _find_java helper
# ---------------------------------------------------------------------------


class TestFindJava:
    def test_finds_via_which(self):
        with patch(
            "commands.freerouting.shutil.which",
            return_value="/usr/bin/java",
        ):
            assert _find_java() == "/usr/bin/java"

    def test_none_when_not_found(self):
        with patch(
            "commands.freerouting.shutil.which", return_value=None
        ), patch("os.path.isfile", return_value=False):
            assert _find_java() is None
