"""Tests for vendor PCB import (commands/pcb_import.py — kicad-cli pcb import wrapper)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.pcb_import import PcbImportCommands  # noqa: E402
from utils.kicad_cli import resolve_kicad_cli  # noqa: E402

# Gate cli-dependent tests on the same resolver the importer uses, so they run
# on any discoverable install, not only a hardcoded path.
_KICAD_CLI = resolve_kicad_cli()

_ALLEGRO_BRD = Path(
    "/home/cycix/Desktop/fai-tuner/golden-box/pfdsc_carrier/references/"
    "PolarFire_SoC_Discovery_Kit_Rev2_23_0954_PCB_091923.brd"
)


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_commands(tmp_path: Path, cli: str = "/usr/bin/kicad-cli") -> PcbImportCommands:
    """Build a PcbImportCommands with a fixed fake CLI path (bypasses resolver)."""
    pic = PcbImportCommands.__new__(PcbImportCommands)
    pic._kicad_cli = cli
    return pic


def test_missing_input_file_is_required() -> None:
    pic = _make_commands(Path("."))
    result = pic.import_pcb({})
    assert result["success"] is False
    assert "inputFile is required" in result["error"]


def test_input_file_not_found(tmp_path: Path) -> None:
    pic = _make_commands(tmp_path)
    missing = tmp_path / "does_not_exist.brd"
    result = pic.import_pcb({"inputFile": str(missing)})
    assert result["success"] is False
    assert "not found" in result["error"]


def test_invalid_format_rejected_client_side(tmp_path: Path) -> None:
    input_file = tmp_path / "board.brd"
    input_file.write_bytes(b"fake")
    pic = _make_commands(tmp_path)
    result = pic.import_pcb({"inputFile": str(input_file), "format": "allegro"})
    assert result["success"] is False
    assert "Invalid format" in result["error"]


def test_invalid_report_format_rejected_client_side(tmp_path: Path) -> None:
    input_file = tmp_path / "board.brd"
    input_file.write_bytes(b"fake")
    pic = _make_commands(tmp_path)
    result = pic.import_pcb({"inputFile": str(input_file), "reportFormat": "xml"})
    assert result["success"] is False
    assert "Invalid reportFormat" in result["error"]


def test_default_format_is_auto_and_output_path_derived(tmp_path: Path) -> None:
    input_file = tmp_path / "board.brd"
    input_file.write_bytes(b"fake")
    expected_out = tmp_path / "board.kicad_pcb"
    pic = _make_commands(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        # Simulate kicad-cli producing the output file.
        Path(cmd[cmd.index("-o") + 1]).write_text("(kicad_pcb)")
        return _FakeCompletedProcess(
            returncode=0,
            stdout=f"Importing '{input_file}' using Allegro format...\nSuccessfully saved imported board.",
        )

    with patch("commands.pcb_import.subprocess.run", side_effect=fake_run) as mock_run:
        result = pic.import_pcb({"inputFile": str(input_file)})

    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "/usr/bin/kicad-cli"
    assert cmd[1:3] == ["pcb", "import"]
    assert "--format" in cmd
    assert cmd[cmd.index("--format") + 1] == "auto"
    assert cmd[-1] == str(input_file)
    assert cmd[cmd.index("-o") + 1] == str(expected_out)

    assert result["success"] is True
    assert result["outputFile"] == str(expected_out)
    # Detected format is parsed from the "using X format" stdout phrase.
    assert result["format"] == "Allegro"


def test_explicit_format_passed_through(tmp_path: Path) -> None:
    input_file = tmp_path / "board.pcb"
    input_file.write_bytes(b"fake")
    pic = _make_commands(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        Path(cmd[cmd.index("-o") + 1]).write_text("(kicad_pcb)")
        return _FakeCompletedProcess(returncode=0, stdout="Importing using PADS format...")

    with patch("commands.pcb_import.subprocess.run", side_effect=fake_run) as mock_run:
        result = pic.import_pcb({"inputFile": str(input_file), "format": "pads"})

    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index("--format") + 1] == "pads"
    assert result["success"] is True


def test_explicit_output_file_used(tmp_path: Path) -> None:
    input_file = tmp_path / "board.brd"
    input_file.write_bytes(b"fake")
    custom_out = tmp_path / "nested" / "custom.kicad_pcb"
    pic = _make_commands(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        out = Path(cmd[cmd.index("-o") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("(kicad_pcb)")
        return _FakeCompletedProcess(returncode=0, stdout="using Allegro format")

    with patch("commands.pcb_import.subprocess.run", side_effect=fake_run):
        result = pic.import_pcb({"inputFile": str(input_file), "outputFile": str(custom_out)})

    assert result["outputFile"] == str(custom_out)


def test_report_format_requests_report_and_captures_contents(tmp_path: Path) -> None:
    input_file = tmp_path / "board.brd"
    input_file.write_bytes(b"fake")
    pic = _make_commands(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        Path(cmd[cmd.index("-o") + 1]).write_text("(kicad_pcb)")
        report_file = Path(cmd[cmd.index("--report-file") + 1])
        report_file.write_text('{"errors": []}')
        return _FakeCompletedProcess(returncode=0, stdout="using Allegro format")

    with patch("commands.pcb_import.subprocess.run", side_effect=fake_run) as mock_run:
        result = pic.import_pcb({"inputFile": str(input_file), "reportFormat": "json"})

    cmd = mock_run.call_args.args[0]
    assert "--report-format" in cmd
    assert cmd[cmd.index("--report-format") + 1] == "json"
    assert "--report-file" in cmd
    assert result["success"] is True
    assert result["report"] == '{"errors": []}'
    # The temp report file is cleaned up after being read.
    report_file = Path(cmd[cmd.index("--report-file") + 1])
    assert not report_file.exists()


def test_kicad_cli_stderr_surfaced_on_failure(tmp_path: Path) -> None:
    input_file = tmp_path / "board.brd"
    input_file.write_bytes(b"fake")
    pic = _make_commands(tmp_path)

    def fake_run(cmd, capture_output, text, timeout):
        return _FakeCompletedProcess(returncode=1, stderr="Invalid format: allegro")

    with patch("commands.pcb_import.subprocess.run", side_effect=fake_run):
        result = pic.import_pcb({"inputFile": str(input_file)})

    assert result["success"] is False
    assert "Invalid format: allegro" in result["error"]


def test_kicad_cli_not_found() -> None:
    pic = _make_commands(Path("."), cli=None)  # type: ignore[arg-type]
    input_file_holder = Path(__file__)  # any existing file works for the exists() check
    result = pic.import_pcb({"inputFile": str(input_file_holder)})
    assert result["success"] is False
    assert "kicad-cli" in result["error"].lower()


# ── Real-file integration test ──────────────────────────────────────────────
# Runs the actual `kicad-cli pcb import` against a real binary Cadence Allegro
# .brd reference board when both preconditions hold: the fixture file exists
# on disk and kicad-cli is resolvable. Skips cleanly otherwise so this suite
# is portable across machines that don't have the (large, non-repo) fixture.
@pytest.mark.skipif(_KICAD_CLI is None, reason="KiCad CLI not installed")
@pytest.mark.skipif(not _ALLEGRO_BRD.exists(), reason="Allegro reference .brd fixture not present")
@pytest.mark.integration
def test_real_allegro_brd_import(tmp_path: Path) -> None:
    pic = PcbImportCommands()
    out_file = tmp_path / "discovery_kit.kicad_pcb"

    result = pic.import_pcb({"inputFile": str(_ALLEGRO_BRD), "format": "auto", "outputFile": str(out_file)})

    assert result["success"] is True, result
    assert result["format"].lower() == "allegro"
    assert out_file.exists()
    # A trivial/empty import would be a handful of bytes; a real 581-footprint
    # board is megabytes of S-expression data.
    assert out_file.stat().st_size > 100_000
    text = out_file.read_text(encoding="utf-8", errors="replace")
    assert "(footprint" in text
    assert "(net " in text
