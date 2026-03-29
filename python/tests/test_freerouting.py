"""
Tests for the Freerouting autoroute integration.

Covers:
  - FreeroutingCommands.check_freerouting (dependency detection)
  - FreeroutingCommands.export_dsn (DSN export via pcbnew)
  - FreeroutingCommands.import_ses (SES import via pcbnew)
  - FreeroutingCommands.autoroute (full pipeline, direct + docker)
  - Error handling: missing board, no runtime, missing JAR, timeouts
  - _find_java, _docker_available, _java_version_ok helpers
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from commands.freerouting import (
    FreeroutingCommands,
    _docker_available,
    _find_docker,
    _find_java,
    _java_version_ok,
)

# pcbnew mock from conftest
pcbnew_mock = sys.modules["pcbnew"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_pcbnew_mock():
    """Reset pcbnew mock before each test."""
    pcbnew_mock.reset_mock()
    pcbnew_mock.ExportSpecctraDSN.side_effect = None
    pcbnew_mock.ExportSpecctraDSN.return_value = MagicMock()
    pcbnew_mock.ImportSpecctraSES.side_effect = None
    pcbnew_mock.ImportSpecctraSES.return_value = MagicMock()
    yield


@pytest.fixture
def mock_board():
    board = MagicMock()
    board.GetFileName.return_value = "/tmp/test_project/test.kicad_pcb"
    board.GetTracks.return_value = []
    return board


@pytest.fixture
def cmds(mock_board):
    return FreeroutingCommands(board=mock_board)


@pytest.fixture
def cmds_no_board():
    return FreeroutingCommands(board=None)


def _patch_direct_java():
    """Patch to simulate Java 21+ available locally."""
    return patch.object(
        FreeroutingCommands,
        "_resolve_execution_mode",
        return_value={"mode": "direct", "use_docker": False},
    )


def _patch_docker_mode():
    """Patch to simulate Docker execution mode."""
    return patch.object(
        FreeroutingCommands,
        "_resolve_execution_mode",
        return_value={"mode": "docker", "use_docker": True},
    )


def _patch_no_runtime():
    """Patch to simulate no Java and no Docker."""
    return patch.object(
        FreeroutingCommands,
        "_resolve_execution_mode",
        return_value={
            "mode": "error",
            "error": "Neither Java 21+ nor Docker found.",
        },
    )


# ---------------------------------------------------------------------------
# check_freerouting
# ---------------------------------------------------------------------------


class TestCheckFreerouting:
    def test_no_java_no_docker(self, cmds):
        with (
            patch("commands.freerouting._find_java", return_value=None),
            patch(
                "commands.freerouting._docker_available",
                return_value=False,
            ),
        ):
            result = cmds.check_freerouting({"freeroutingJar": "/nonexistent.jar"})
        assert result["success"] is True
        assert result["java"]["found"] is False
        assert result["docker"]["available"] is False
        assert result["ready"] is False
        assert result["execution_mode"] == "none"

    def test_java_too_old_docker_available(self, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        with (
            patch(
                "commands.freerouting._find_java",
                return_value="/usr/bin/java",
            ),
            patch(
                "commands.freerouting._java_version_ok",
                return_value=False,
            ),
            patch(
                "commands.freerouting._docker_available",
                return_value=True,
            ),
            patch("commands.freerouting.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(stderr='openjdk version "17.0.1"', stdout="")
            result = cmds.check_freerouting({"freeroutingJar": str(jar)})
        assert result["ready"] is True
        assert result["execution_mode"] == "docker"

    def test_java_21_direct(self, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        with (
            patch(
                "commands.freerouting._find_java",
                return_value="/usr/bin/java",
            ),
            patch(
                "commands.freerouting._java_version_ok",
                return_value=True,
            ),
            patch(
                "commands.freerouting._docker_available",
                return_value=False,
            ),
            patch("commands.freerouting.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(stderr='openjdk version "21.0.1"', stdout="")
            result = cmds.check_freerouting({"freeroutingJar": str(jar)})
        assert result["ready"] is True
        assert result["execution_mode"] == "direct"


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
        Path(dsn_path).write_text("(pcb test)")

        result = cmds.export_dsn({})
        assert result["success"] is True
        assert result["path"] == dsn_path

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

    def test_no_runtime(self, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        with _patch_no_runtime():
            result = cmds.autoroute({"freeroutingJar": str(jar)})
        assert result["success"] is False
        assert "No suitable Java runtime" in result["message"]

    def test_no_jar(self, cmds):
        result = cmds.autoroute({"freeroutingJar": "/nonexistent/freerouting.jar"})
        assert result["success"] is False
        assert "JAR not found" in result["message"]

    @patch("commands.freerouting.subprocess.run")
    def test_dsn_export_fails(self, mock_run, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()

        pcbnew_mock.ExportSpecctraDSN.side_effect = Exception("export fail")

        with _patch_direct_java():
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
        pcbnew_mock.ExportSpecctraDSN.side_effect = lambda b, p: (
            dsn_file.write_text("(pcb)"),
            True,
        )[1]
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="", timeout=10)

        with _patch_direct_java():
            result = cmds.autoroute({"freeroutingJar": str(jar), "timeout": 10})
        assert result["success"] is False
        assert "timed out" in result["message"]

    @patch("commands.freerouting.subprocess.run")
    def test_full_success_direct(self, mock_run, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        board_dir = tmp_path / "project"
        board_dir.mkdir()
        board_file = board_dir / "test.kicad_pcb"
        board_file.touch()
        dsn_file = board_dir / "test.dsn"
        ses_file = board_dir / "test.ses"

        cmds.board.GetFileName.return_value = str(board_file)

        pcbnew_mock.ExportSpecctraDSN.side_effect = lambda b, p: (
            dsn_file.write_text("(pcb)"),
            True,
        )[1]
        mock_run.return_value = MagicMock(returncode=0, stdout="Routing completed", stderr="")
        ses_file.write_text("(session)")
        pcbnew_mock.ImportSpecctraSES.return_value = True

        track = MagicMock()
        track.GetClass.return_value = "PCB_TRACK"
        via = MagicMock()
        via.GetClass.return_value = "PCB_VIA"
        cmds.board.GetTracks.return_value = [track, track, via]

        with _patch_direct_java():
            result = cmds.autoroute({"freeroutingJar": str(jar)})

        assert result["success"] is True
        assert result["mode"] == "direct"
        assert result["board_stats"]["tracks"] == 2
        assert result["board_stats"]["vias"] == 1
        assert "elapsed_seconds" in result

    @patch("commands.freerouting.subprocess.run")
    def test_full_success_docker(self, mock_run, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        board_dir = tmp_path / "project"
        board_dir.mkdir()
        board_file = board_dir / "test.kicad_pcb"
        board_file.touch()
        dsn_file = board_dir / "test.dsn"
        ses_file = board_dir / "test.ses"

        cmds.board.GetFileName.return_value = str(board_file)

        pcbnew_mock.ExportSpecctraDSN.side_effect = lambda b, p: (
            dsn_file.write_text("(pcb)"),
            True,
        )[1]
        mock_run.return_value = MagicMock(returncode=0, stdout="Routing completed", stderr="")
        ses_file.write_text("(session)")
        pcbnew_mock.ImportSpecctraSES.return_value = True

        cmds.board.GetTracks.return_value = [MagicMock()]

        with (
            _patch_docker_mode(),
            patch(
                "commands.freerouting._find_docker",
                return_value="/usr/bin/docker",
            ),
        ):
            result = cmds.autoroute({"freeroutingJar": str(jar)})

        assert result["success"] is True
        assert result["mode"] == "docker"
        # Verify a container runtime was invoked
        call_args = mock_run.call_args[0][0]
        assert "run" in call_args
        assert "--rm" in call_args

    @patch("commands.freerouting.subprocess.run")
    def test_freerouting_nonzero_exit(self, mock_run, cmds, tmp_path):
        jar = tmp_path / "freerouting.jar"
        jar.touch()
        board_dir = tmp_path / "project"
        board_dir.mkdir()
        board_file = board_dir / "test.kicad_pcb"
        board_file.touch()
        dsn_file = board_dir / "test.dsn"

        cmds.board.GetFileName.return_value = str(board_file)
        pcbnew_mock.ExportSpecctraDSN.side_effect = lambda b, p: (
            dsn_file.write_text("(pcb)"),
            True,
        )[1]
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="OutOfMemoryError")

        with _patch_direct_java():
            result = cmds.autoroute({"freeroutingJar": str(jar)})

        assert result["success"] is False
        assert "exited with code 1" in result["message"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestFindJava:
    def test_finds_via_which(self):
        with patch(
            "commands.freerouting.shutil.which",
            return_value="/usr/bin/java",
        ):
            assert _find_java() == "/usr/bin/java"

    def test_none_when_not_found(self):
        with (
            patch(
                "commands.freerouting.shutil.which",
                return_value=None,
            ),
            patch("os.path.isfile", return_value=False),
        ):
            assert _find_java() is None


class TestFindDocker:
    def test_finds_docker(self):
        with patch(
            "commands.freerouting.shutil.which",
            side_effect=lambda x: "/usr/bin/docker" if x == "docker" else None,
        ):
            assert _find_docker() == "/usr/bin/docker"

    def test_finds_podman(self):
        with patch(
            "commands.freerouting.shutil.which",
            side_effect=lambda x: "/usr/bin/podman" if x == "podman" else None,
        ):
            assert _find_docker() == "/usr/bin/podman"

    def test_none_when_not_found(self):
        with patch(
            "commands.freerouting.shutil.which",
            return_value=None,
        ):
            assert _find_docker() is None


class TestDockerAvailable:
    def test_docker_found(self):
        with (
            patch(
                "commands.freerouting._find_docker",
                return_value="/usr/bin/docker",
            ),
            patch("commands.freerouting.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            assert _docker_available() is True

    def test_docker_not_installed(self):
        with patch(
            "commands.freerouting._find_docker",
            return_value=None,
        ):
            assert _docker_available() is False

    def test_docker_not_running(self):
        with (
            patch(
                "commands.freerouting._find_docker",
                return_value="/usr/bin/docker",
            ),
            patch("commands.freerouting.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1)
            assert _docker_available() is False


class TestJavaVersionOk:
    def test_java_21(self):
        with patch("commands.freerouting.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stderr='openjdk version "21.0.1"', stdout="")
            assert _java_version_ok("/usr/bin/java") is True

    def test_java_17(self):
        with patch("commands.freerouting.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stderr='openjdk version "17.0.18"', stdout="")
            assert _java_version_ok("/usr/bin/java") is False

    def test_java_error(self):
        with patch(
            "commands.freerouting.subprocess.run",
            side_effect=Exception("not found"),
        ):
            assert _java_version_ok("/usr/bin/java") is False
