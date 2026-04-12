"""
Tests for case-sensitivity warnings in add_schematic_net_label.

When a label is placed whose name differs from an existing net only in case
(e.g. adding "outp" when "OUTP" already exists), the tool should succeed but
include a `case_warnings` list in the response.

Covers:
  - Unit: case_warnings populated when names differ only in case
  - Unit: no case_warnings when name is an exact match or no similar name exists
  - Integration: place "outp" in a schematic that already has "OUTP" -> warning
  - Integration: place "VCC" in a schematic that already has "VCC" -> no warning
"""

import shutil
import sys
import tempfile
import types
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "python" / "templates" / "empty.kicad_sch"


# ---------------------------------------------------------------------------
# Helpers shared between unit and integration tests
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    """Return a KiCADInterface instance with __init__ stubbed out."""
    for mod in ["pcbnew", "skip"]:
        sys.modules.setdefault(mod, types.ModuleType(mod))
    from kicad_interface import KiCADInterface

    with patch.object(KiCADInterface, "__init__", lambda self, *a, **kw: None):
        return KiCADInterface.__new__(KiCADInterface)


def _label_sexp(name: str, x: float, y: float, angle: float = 0) -> str:
    u = str(uuid.uuid4())
    return (
        f'(label "{name}" (at {x} {y} {angle})\n'
        f"  (effects (font (size 1.27 1.27)) (justify left bottom))\n"
        f'  (uuid "{u}"))'
    )


def _make_temp_schematic(extra_sexp: str = "") -> Path:
    """Copy empty.kicad_sch to a temp dir, optionally injecting extra S-expressions."""
    tmp = Path(tempfile.mkdtemp()) / "test.kicad_sch"
    shutil.copy(TEMPLATE_PATH, tmp)
    if extra_sexp:
        content = tmp.read_text(encoding="utf-8")
        idx = content.rfind(")")
        content = content[:idx] + "\n" + extra_sexp + "\n)"
        tmp.write_text(content, encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# Unit tests — mock file I/O completely
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCaseWarningPopulated:
    """case_warnings should be present when new label differs from existing by case only."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.iface = _make_iface()

    def _make_mock_label(self, value: str) -> MagicMock:
        lbl = MagicMock()
        lbl.value = value
        return lbl

    def _make_mock_schematic(self, label_names: list) -> MagicMock:
        sch = MagicMock(spec=["label", "global_label"])
        sch.label = [self._make_mock_label(n) for n in label_names]
        sch.global_label = []
        return sch

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_case_warning_when_uppercase_exists(self, mock_load: Any, mock_add_label: Any) -> None:
        """Adding 'outp' when 'OUTP' already exists produces a case_warning."""
        mock_load.return_value = self._make_mock_schematic(["OUTP"])

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "outp",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" in result
        assert len(result["case_warnings"]) == 1
        assert "OUTP" in result["case_warnings"][0]
        assert "outp" in result["case_warnings"][0]

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_case_warning_when_lowercase_exists(self, mock_load: Any, mock_add_label: Any) -> None:
        """Adding 'OUTP' when 'outp' already exists produces a case_warning."""
        mock_load.return_value = self._make_mock_schematic(["outp"])

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "OUTP",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" in result
        assert len(result["case_warnings"]) == 1

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_multiple_case_collisions_all_reported(
        self, mock_load: Any, mock_add_label: Any
    ) -> None:
        """Multiple existing labels that differ only in case all produce warnings."""
        mock_load.return_value = self._make_mock_schematic(["OUTP", "Outp", "oUtP"])

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "outp",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" in result
        assert len(result["case_warnings"]) == 3

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_global_label_case_collision_reported(
        self, mock_load: Any, mock_add_label: Any
    ) -> None:
        """Case collision against a global_label also produces a warning."""
        sch = MagicMock(spec=["label", "global_label"])
        sch.label = []
        sch.global_label = [self._make_mock_label("VDD")]

        mock_load.return_value = sch

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "vdd",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" in result
        assert len(result["case_warnings"]) == 1
        assert "VDD" in result["case_warnings"][0]


@pytest.mark.unit
class TestCaseWarningAbsent:
    """case_warnings should be absent (or empty) when there is no case collision."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.iface = _make_iface()

    def _make_mock_schematic(self, label_names: list) -> MagicMock:
        sch = MagicMock(spec=["label", "global_label"])
        sch.label = []
        for name in label_names:
            lbl = MagicMock()
            lbl.value = name
            sch.label.append(lbl)
        sch.global_label = []
        return sch

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_exact_match_no_warning(self, mock_load: Any, mock_add_label: Any) -> None:
        """Adding 'VCC' when 'VCC' already exists is not a case mismatch."""
        mock_load.return_value = self._make_mock_schematic(["VCC"])

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "VCC",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" not in result or result.get("case_warnings") == []

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_unrelated_nets_no_warning(self, mock_load: Any, mock_add_label: Any) -> None:
        """Adding a label whose name has no case-insensitive match produces no warning."""
        mock_load.return_value = self._make_mock_schematic(["GND", "VCC", "CLK"])

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "MOSI",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" not in result or result.get("case_warnings") == []

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_empty_schematic_no_warning(self, mock_load: Any, mock_add_label: Any) -> None:
        """Adding a label to an empty schematic produces no warning."""
        mock_load.return_value = self._make_mock_schematic([])

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "SIG",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" not in result or result.get("case_warnings") == []

    @patch("commands.wire_manager.WireManager.add_label", return_value=True)
    @patch("commands.schematic.SchematicManager.load_schematic")
    def test_load_failure_no_warning_but_still_succeeds(
        self, mock_load: Any, mock_add_label: Any
    ) -> None:
        """If loading the schematic for net-name inspection fails, succeed without warning."""
        mock_load.side_effect = RuntimeError("I/O error")

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": "/fake/sch.kicad_sch",
                "netName": "SIG",
                "position": [10.0, 20.0],
            }
        )

        assert result["success"] is True
        assert "case_warnings" not in result or result.get("case_warnings") == []


# ---------------------------------------------------------------------------
# Integration tests — real .kicad_sch file I/O
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCaseWarningIntegration:
    """End-to-end: use the handler against a real .kicad_sch file."""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.iface = _make_iface()

    def test_case_collision_produces_warning(self) -> None:
        """Placing 'outp' when 'OUTP' already exists in the file produces a warning."""
        path = _make_temp_schematic(_label_sexp("OUTP", 10.0, 10.0))

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": str(path),
                "netName": "outp",
                "position": [20.0, 20.0],
            }
        )

        assert result["success"] is True, f"Unexpected failure: {result.get('message')}"
        assert "case_warnings" in result, "Expected case_warnings in response"
        assert len(result["case_warnings"]) >= 1
        # Warning message should name both parties
        warning_text = " ".join(result["case_warnings"])
        assert "OUTP" in warning_text
        assert "outp" in warning_text

    def test_exact_match_no_warning(self) -> None:
        """Placing 'VCC' when 'VCC' already exists should NOT produce a case warning."""
        path = _make_temp_schematic(_label_sexp("VCC", 10.0, 10.0))

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": str(path),
                "netName": "VCC",
                "position": [20.0, 20.0],
            }
        )

        assert result["success"] is True, f"Unexpected failure: {result.get('message')}"
        case_warnings = result.get("case_warnings", [])
        assert case_warnings == [], f"Unexpected case_warnings: {case_warnings}"

    def test_no_similar_nets_no_warning(self) -> None:
        """Placing a label whose name has no case-insensitive match gives no warning."""
        path = _make_temp_schematic(_label_sexp("GND", 10.0, 10.0))

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": str(path),
                "netName": "MOSI",
                "position": [20.0, 20.0],
            }
        )

        assert result["success"] is True, f"Unexpected failure: {result.get('message')}"
        case_warnings = result.get("case_warnings", [])
        assert case_warnings == [], f"Unexpected case_warnings: {case_warnings}"

    def test_mixed_case_collision_multiple_existing(self) -> None:
        """Multiple existing labels with same letters in different case all warn."""
        extra = "\n".join(
            [
                _label_sexp("OUTP", 10.0, 10.0),
                _label_sexp("Outp", 15.0, 10.0),
            ]
        )
        path = _make_temp_schematic(extra)

        result = self.iface._handle_add_schematic_net_label(
            {
                "schematicPath": str(path),
                "netName": "outp",
                "position": [20.0, 20.0],
            }
        )

        assert result["success"] is True, f"Unexpected failure: {result.get('message')}"
        assert "case_warnings" in result
        assert len(result["case_warnings"]) == 2
