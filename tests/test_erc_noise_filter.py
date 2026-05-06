"""
Tests for ERC noise segregation in _handle_run_erc.

Key behaviour under test:
  - Schema registers `includeNoise` as an optional boolean
  - endpoint_off_grid / lib_symbol_issues / lib_symbol_mismatch go to
    noise_violations[] by default (includeNoise omitted or False)
  - Those same types appear in violations[] when includeNoise=True
  - Real errors (pin_not_connected) always stay in violations[]
  - Coordinate scaling: x_mm = raw_x * 100, y_mm = raw_y * 100
  - summary.noise_suppressed count matches len(noise_violations)
  - Mixed batches: correct counts for both buckets
"""

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"


# ---------------------------------------------------------------------------
# Helper: construct mock subprocess.run that writes JSON to the ERC output file
# ---------------------------------------------------------------------------


def _mock_erc_run(erc_json: dict, returncode: int = 1):
    """Return a side_effect callable that writes erc_json to the --output path."""

    def _side_effect(cmd, **kwargs):
        output_idx = cmd.index("--output") + 1
        output_path = cmd[output_idx]
        with open(output_path, "w") as fh:
            json.dump(erc_json, fh)
        result = MagicMock()
        result.returncode = returncode
        result.stderr = ""
        return result

    return _side_effect


# ---------------------------------------------------------------------------
# Helper: build a minimal violation dict
# ---------------------------------------------------------------------------


def _violation(
    vtype: str, severity: str = "error", description: str = "", x: float = 1.0, y: float = 2.0
) -> dict:
    return {
        "type": vtype,
        "severity": severity,
        "description": description or vtype,
        "items": [{"pos": {"x": x, "y": y}}],
    }


# ---------------------------------------------------------------------------
# Fixture: KiCADInterface + DesignRuleCommands (no real __init__)
# ---------------------------------------------------------------------------


def _make_iface():
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

    iface = KiCADInterface.__new__(KiCADInterface)
    iface.design_rule_commands = MagicMock()
    iface.design_rule_commands._find_kicad_cli.return_value = "/usr/bin/kicad-cli"
    return iface


@pytest.fixture()
def iface():
    return _make_iface()


@pytest.fixture()
def sch_path(tmp_path):
    dest = tmp_path / "test.kicad_sch"
    shutil.copy(TEMPLATE_SCH, dest)
    return dest


# ===========================================================================
# Schema tests
# ===========================================================================


@pytest.mark.unit
class TestERCNoiseFilterSchema:
    def test_run_erc_in_tool_schemas(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        assert "run_erc" in TOOL_SCHEMAS

    def test_include_noise_is_optional_boolean(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        schema = TOOL_SCHEMAS["run_erc"]
        props = schema["inputSchema"]["properties"]
        assert "includeNoise" in props
        assert props["includeNoise"]["type"] == "boolean"
        required = schema["inputSchema"].get("required", [])
        assert "includeNoise" not in required


# ===========================================================================
# Noise filtering logic
# ===========================================================================


@pytest.mark.unit
class TestERCNoiseFiltering:
    def _run(self, iface, sch_path, erc_data, extra_params=None):
        params = {"schematicPath": str(sch_path)}
        if extra_params:
            params.update(extra_params)
        with patch("subprocess.run", side_effect=_mock_erc_run(erc_data)):
            return iface._handle_run_erc(params)

    def test_endpoint_off_grid_goes_to_noise_by_default(self, iface, sch_path):
        data = {"violations": [_violation("endpoint_off_grid", severity="warning")]}
        result = self._run(iface, sch_path, data)
        assert result["success"] is True
        assert len(result["violations"]) == 0
        assert len(result["noise_violations"]) == 1
        assert result["noise_violations"][0]["type"] == "endpoint_off_grid"

    def test_lib_symbol_issues_goes_to_noise_by_default(self, iface, sch_path):
        data = {"violations": [_violation("lib_symbol_issues", severity="warning")]}
        result = self._run(iface, sch_path, data)
        assert len(result["violations"]) == 0
        assert len(result["noise_violations"]) == 1

    def test_lib_symbol_mismatch_goes_to_noise_by_default(self, iface, sch_path):
        data = {"violations": [_violation("lib_symbol_mismatch", severity="warning")]}
        result = self._run(iface, sch_path, data)
        assert len(result["violations"]) == 0
        assert len(result["noise_violations"]) == 1

    def test_endpoint_off_grid_in_violations_when_include_noise_true(self, iface, sch_path):
        data = {"violations": [_violation("endpoint_off_grid", severity="warning")]}
        result = self._run(iface, sch_path, data, extra_params={"includeNoise": True})
        assert result["success"] is True
        assert len(result["violations"]) == 1
        assert result["violations"][0]["type"] == "endpoint_off_grid"
        assert len(result["noise_violations"]) == 0

    def test_lib_symbol_mismatch_in_violations_when_include_noise_true(self, iface, sch_path):
        data = {"violations": [_violation("lib_symbol_mismatch")]}
        result = self._run(iface, sch_path, data, extra_params={"includeNoise": True})
        assert len(result["violations"]) == 1
        assert len(result["noise_violations"]) == 0

    def test_pin_not_connected_always_in_violations(self, iface, sch_path):
        data = {"violations": [_violation("pin_not_connected", severity="error")]}
        result = self._run(iface, sch_path, data)
        assert len(result["violations"]) == 1
        assert result["violations"][0]["type"] == "pin_not_connected"
        assert len(result["noise_violations"]) == 0

    def test_real_error_stays_in_violations_even_with_include_noise_false(self, iface, sch_path):
        data = {"violations": [_violation("wire_dangling", severity="warning")]}
        result = self._run(iface, sch_path, data, extra_params={"includeNoise": False})
        assert len(result["violations"]) == 1
        assert len(result["noise_violations"]) == 0


# ===========================================================================
# Coordinate scaling
# ===========================================================================


@pytest.mark.unit
class TestERCCoordinateScaling:
    def test_coordinate_scaling_x_and_y(self, iface, sch_path):
        # raw x=1.0, y=2.0 → x_mm=100.0, y_mm=200.0
        data = {"violations": [_violation("pin_not_connected", x=1.0, y=2.0)]}
        with patch("subprocess.run", side_effect=_mock_erc_run(data)):
            result = iface._handle_run_erc({"schematicPath": str(sch_path)})
        assert result["success"] is True
        loc = result["violations"][0]["location"]
        assert loc["x_mm"] == pytest.approx(100.0)
        assert loc["y_mm"] == pytest.approx(200.0)

    def test_coordinate_scaling_with_fractional_values(self, iface, sch_path):
        data = {"violations": [_violation("pin_not_connected", x=0.5, y=0.25)]}
        with patch("subprocess.run", side_effect=_mock_erc_run(data)):
            result = iface._handle_run_erc({"schematicPath": str(sch_path)})
        loc = result["violations"][0]["location"]
        assert loc["x_mm"] == pytest.approx(50.0)
        assert loc["y_mm"] == pytest.approx(25.0)

    def test_noise_violation_also_has_coordinates(self, iface, sch_path):
        data = {"violations": [_violation("endpoint_off_grid", x=3.0, y=4.0)]}
        with patch("subprocess.run", side_effect=_mock_erc_run(data)):
            result = iface._handle_run_erc({"schematicPath": str(sch_path)})
        loc = result["noise_violations"][0]["location"]
        assert loc["x_mm"] == pytest.approx(300.0)
        assert loc["y_mm"] == pytest.approx(400.0)


# ===========================================================================
# Summary counts
# ===========================================================================


@pytest.mark.unit
class TestERCSummaryCounts:
    def _run(self, iface, sch_path, erc_data, extra_params=None):
        params = {"schematicPath": str(sch_path)}
        if extra_params:
            params.update(extra_params)
        with patch("subprocess.run", side_effect=_mock_erc_run(erc_data)):
            return iface._handle_run_erc(params)

    def test_noise_suppressed_matches_noise_violations_length(self, iface, sch_path):
        data = {
            "violations": [
                _violation("endpoint_off_grid"),
                _violation("endpoint_off_grid"),
                _violation("lib_symbol_mismatch"),
            ]
        }
        result = self._run(iface, sch_path, data)
        assert result["summary"]["noise_suppressed"] == len(result["noise_violations"])
        assert result["summary"]["noise_suppressed"] == 3

    def test_mixed_noise_and_real_correct_counts(self, iface, sch_path):
        data = {
            "violations": [
                _violation("pin_not_connected", severity="error"),
                _violation("wire_dangling", severity="warning"),
                _violation("endpoint_off_grid", severity="warning"),
                _violation("lib_symbol_issues", severity="warning"),
            ]
        }
        result = self._run(iface, sch_path, data)
        assert len(result["violations"]) == 2
        assert len(result["noise_violations"]) == 2
        assert result["summary"]["total"] == 2
        assert result["summary"]["noise_suppressed"] == 2
        assert result["summary"]["by_severity"]["error"] == 1
        assert result["summary"]["by_severity"]["warning"] == 1

    def test_all_noise_total_is_zero(self, iface, sch_path):
        data = {
            "violations": [
                _violation("endpoint_off_grid"),
                _violation("lib_symbol_mismatch"),
            ]
        }
        result = self._run(iface, sch_path, data)
        assert result["summary"]["total"] == 0
        assert result["summary"]["noise_suppressed"] == 2

    def test_no_violations_all_zeros(self, iface, sch_path):
        data = {"violations": []}
        result = self._run(iface, sch_path, data, extra_params={})
        assert result["success"] is True
        assert result["summary"]["total"] == 0
        assert result["summary"]["noise_suppressed"] == 0
        assert len(result["violations"]) == 0
        assert len(result["noise_violations"]) == 0

    def test_message_reflects_main_violations_count(self, iface, sch_path):
        data = {
            "violations": [
                _violation("pin_not_connected", severity="error"),
                _violation("endpoint_off_grid", severity="warning"),
            ]
        }
        result = self._run(iface, sch_path, data)
        assert "1 violation" in result["message"]

    def test_kicad9_sheets_violations_also_filtered(self, iface, sch_path):
        data = {
            "violations": [],
            "sheets": [
                {
                    "path": "/",
                    "violations": [
                        _violation("endpoint_off_grid", severity="warning"),
                        _violation("pin_not_connected", severity="error"),
                    ],
                }
            ],
        }
        result = self._run(iface, sch_path, data)
        assert len(result["violations"]) == 1
        assert len(result["noise_violations"]) == 1
