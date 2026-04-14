"""
Tests for run_erc handler.

Covers:
  - Non-zero exit code acceptance (kicad-cli returns non-zero when violations exist)
  - KiCad 9 sheets[].violations JSON structure parsing
  - KiCad 8 top-level violations[] JSON structure (backward compat)
  - Missing/empty output file handling
"""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Shared fixture: KiCADInterface instance (no __init__, avoids pcbnew/IPC)
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    return iface


@pytest.fixture()
def iface():
    return _make_iface()


# ---------------------------------------------------------------------------
# Sample ERC JSON outputs
# ---------------------------------------------------------------------------

# KiCad 8 style: violations at top level
_ERC_KICAD8_JSON = {
    "violations": [
        {
            "type": "pin_not_connected",
            "severity": "error",
            "description": "Pin not connected",
            "items": [{"pos": {"x": 100.0, "y": 50.0}}],
        },
        {
            "type": "wire_dangling",
            "severity": "warning",
            "description": "Wire end not connected",
            "items": [{"pos": {"x": 200.0, "y": 75.0}}],
        },
    ]
}

# KiCad 9 style: violations nested under sheets[]
_ERC_KICAD9_JSON = {
    "violations": [],
    "sheets": [
        {
            "path": "/",
            "violations": [
                {
                    "type": "pin_not_connected",
                    "severity": "error",
                    "description": "Pin not connected",
                    "items": [{"pos": {"x": 10.0, "y": 20.0}}],
                },
            ],
        },
        {
            "path": "/sub-sheet-1",
            "violations": [
                {
                    "type": "label_dangling",
                    "severity": "error",
                    "description": "Label not connected to anything",
                    "items": [{"pos": {"x": 30.0, "y": 40.0}}],
                },
                {
                    "type": "wire_dangling",
                    "severity": "warning",
                    "description": "Wire end not connected",
                    "items": [{"pos": {"x": 50.0, "y": 60.0}}],
                },
            ],
        },
    ],
}

# KiCad 9 with violations in both top-level and sheets (edge case)
_ERC_MIXED_JSON = {
    "violations": [
        {
            "type": "power_pin_not_driven",
            "severity": "error",
            "description": "Power pin not driven",
            "items": [{"pos": {"x": 1.0, "y": 2.0}}],
        },
    ],
    "sheets": [
        {
            "path": "/sub",
            "violations": [
                {
                    "type": "pin_not_connected",
                    "severity": "error",
                    "description": "Pin not connected",
                    "items": [{"pos": {"x": 3.0, "y": 4.0}}],
                },
            ],
        },
    ],
}


def _mock_erc_run(erc_json: dict, returncode: int = 1):
    """Create a mock subprocess.run that writes ERC JSON to the output file."""

    def _side_effect(cmd, **kwargs):
        # Find the output path from the command args (--output <path>)
        output_idx = cmd.index("--output") + 1
        output_path = cmd[output_idx]
        with open(output_path, "w") as f:
            json.dump(erc_json, f)
        result = MagicMock()
        result.returncode = returncode
        result.stderr = ""
        return result

    return _side_effect


def _mock_erc_no_output(returncode: int = 2):
    """Create a mock subprocess.run that produces no output file."""

    def _side_effect(cmd, **kwargs):
        result = MagicMock()
        result.returncode = returncode
        result.stderr = "kicad-cli: error: schematic not found"
        return result

    return _side_effect


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.unit
class TestERCNonZeroExitCode:
    """kicad-cli returns non-zero when violations exist — this is not an error."""

    def test_nonzero_returncode_with_valid_json_succeeds(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        iface.design_rule_commands = MagicMock()
        iface.design_rule_commands._find_kicad_cli.return_value = "/usr/bin/kicad-cli"

        with patch("subprocess.run", side_effect=_mock_erc_run(_ERC_KICAD8_JSON, returncode=1)):
            result = iface._handle_run_erc({"schematicPath": str(sch)})

        assert result["success"] is True
        assert "2 violation" in result["message"]

    def test_zero_returncode_no_violations(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        iface.design_rule_commands = MagicMock()
        iface.design_rule_commands._find_kicad_cli.return_value = "/usr/bin/kicad-cli"

        with patch("subprocess.run", side_effect=_mock_erc_run({"violations": []}, returncode=0)):
            result = iface._handle_run_erc({"schematicPath": str(sch)})

        assert result["success"] is True
        assert "0 violation" in result["message"]

    def test_no_output_file_fails(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        iface.design_rule_commands = MagicMock()
        iface.design_rule_commands._find_kicad_cli.return_value = "/usr/bin/kicad-cli"

        with patch("subprocess.run", side_effect=_mock_erc_no_output()):
            result = iface._handle_run_erc({"schematicPath": str(sch)})

        assert result["success"] is False
        assert "no output" in result["message"].lower()


@pytest.mark.unit
class TestERCKicad9SheetsViolations:
    """KiCad 9 nests violations under sheets[].violations."""

    def test_kicad9_sheets_violations_collected(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        iface.design_rule_commands = MagicMock()
        iface.design_rule_commands._find_kicad_cli.return_value = "/usr/bin/kicad-cli"

        with patch("subprocess.run", side_effect=_mock_erc_run(_ERC_KICAD9_JSON)):
            result = iface._handle_run_erc({"schematicPath": str(sch)})

        assert result["success"] is True
        assert "3 violation" in result["message"]
        assert result["summary"]["by_severity"]["error"] == 2
        assert result["summary"]["by_severity"]["warning"] == 1

    def test_kicad8_top_level_violations_still_work(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        iface.design_rule_commands = MagicMock()
        iface.design_rule_commands._find_kicad_cli.return_value = "/usr/bin/kicad-cli"

        with patch("subprocess.run", side_effect=_mock_erc_run(_ERC_KICAD8_JSON)):
            result = iface._handle_run_erc({"schematicPath": str(sch)})

        assert result["success"] is True
        assert "2 violation" in result["message"]
        assert result["summary"]["by_severity"]["error"] == 1
        assert result["summary"]["by_severity"]["warning"] == 1

    def test_mixed_top_level_and_sheets_violations(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        iface.design_rule_commands = MagicMock()
        iface.design_rule_commands._find_kicad_cli.return_value = "/usr/bin/kicad-cli"

        with patch("subprocess.run", side_effect=_mock_erc_run(_ERC_MIXED_JSON)):
            result = iface._handle_run_erc({"schematicPath": str(sch)})

        assert result["success"] is True
        # 1 top-level + 1 from sheets = 2 total
        assert "2 violation" in result["message"]
        assert result["summary"]["by_severity"]["error"] == 2
