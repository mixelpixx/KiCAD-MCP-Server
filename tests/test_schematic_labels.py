"""
Tests for schematic label filters on list_schematic_labels.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "python" / "templates" / "empty.kicad_sch"


def _make_temp_schematic(extra_sexp: str = "") -> Path:
    """Copy empty.kicad_sch to a temp file and optionally append S-expression content."""
    tmp = Path(tempfile.mkdtemp()) / "test.kicad_sch"
    shutil.copy(TEMPLATE_PATH, tmp)
    if extra_sexp:
        content = tmp.read_text(encoding="utf-8")
        idx = content.rfind(")")
        content = content[:idx] + "\n" + extra_sexp + "\n)"
        tmp.write_text(content, encoding="utf-8")
    return tmp


def _label_sexp(name: str, x: float, y: float) -> str:
    return f'(label "{name}" (at {x} {y} 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "l-{name}-{x}-{y}"))'


def _global_label_sexp(name: str, x: float, y: float) -> str:
    return f'(global_label "{name}" (at {x} {y} 0) (shape input) (effects (font (size 1.27 1.27))) (uuid "g-{name}-{x}-{y}"))'


# ===========================================================================
# TestListSchematicLabelsSchema (unit)
# ===========================================================================


@pytest.mark.unit
class TestListSchematicLabelsSchema:
    """Validate parameter acceptance and rejection for list_schematic_labels."""

    def test_list_schematic_labels_accepts_net_name_param(self) -> None:
        from kicad_interface import KiCADInterface

        ki = KiCADInterface()
        tmp = _make_temp_schematic()
        result = ki._handle_list_schematic_labels({"schematicPath": str(tmp), "netName": "VCC"})
        assert result["success"] is True

    def test_list_schematic_labels_accepts_label_type_param(self) -> None:
        from kicad_interface import KiCADInterface

        ki = KiCADInterface()
        tmp = _make_temp_schematic()
        result = ki._handle_list_schematic_labels({"schematicPath": str(tmp), "labelType": "net"})
        assert result["success"] is True

    def test_invalid_label_type_rejected(self) -> None:
        from kicad_interface import KiCADInterface

        ki = KiCADInterface()
        tmp = _make_temp_schematic()
        result = ki._handle_list_schematic_labels({"schematicPath": str(tmp), "labelType": "label"})
        assert result["success"] is False
        msg = result["message"]
        assert "net" in msg
        assert "global" in msg
        assert "power" in msg


# ===========================================================================
# TestListSchematicLabelsFilters (unit)
# ===========================================================================


@pytest.mark.unit
class TestListSchematicLabelsFilters:
    """Verify filter behaviour of _handle_list_schematic_labels."""

    def _ki(self):
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_no_filters_returns_all_labels(self) -> None:
        extra = _label_sexp("VCC", 10, 10) + "\n" + _global_label_sexp("GND", 20, 20)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels({"schematicPath": str(tmp)})
        assert result["success"] is True
        names = {lbl["name"] for lbl in result["labels"]}
        assert "VCC" in names
        assert "GND" in names
        assert result["count"] == len(result["labels"])

    def test_net_name_filter_returns_only_matching(self) -> None:
        extra = _label_sexp("VCC", 10, 10) + "\n" + _label_sexp("GND", 20, 20)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels(
            {"schematicPath": str(tmp), "netName": "VCC"}
        )
        assert result["success"] is True
        assert all(lbl["name"] == "VCC" for lbl in result["labels"])
        assert result["count"] == len(result["labels"])

    def test_net_name_filter_case_sensitive(self) -> None:
        extra = _label_sexp("VCC", 10, 10)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels(
            {"schematicPath": str(tmp), "netName": "vcc"}
        )
        assert result["success"] is True
        assert result["count"] == 0

    def test_net_name_filter_no_match_returns_empty(self) -> None:
        extra = _label_sexp("VCC", 10, 10)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels(
            {"schematicPath": str(tmp), "netName": "NONEXISTENT"}
        )
        assert result["success"] is True
        assert result["labels"] == []
        assert result["count"] == 0

    def test_label_type_filter_net_only(self) -> None:
        extra = _label_sexp("SIG", 10, 10) + "\n" + _global_label_sexp("SIG", 20, 20)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels(
            {"schematicPath": str(tmp), "labelType": "net"}
        )
        assert result["success"] is True
        assert all(lbl["type"] == "net" for lbl in result["labels"])

    def test_label_type_filter_global_only(self) -> None:
        extra = _label_sexp("SIG", 10, 10) + "\n" + _global_label_sexp("SIG", 20, 20)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels(
            {"schematicPath": str(tmp), "labelType": "global"}
        )
        assert result["success"] is True
        assert all(lbl["type"] == "global" for lbl in result["labels"])

    def test_label_type_filter_power_only(self) -> None:
        extra = _label_sexp("VCC", 10, 10)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels(
            {"schematicPath": str(tmp), "labelType": "power"}
        )
        assert result["success"] is True
        assert all(lbl["type"] == "power" for lbl in result["labels"])

    def test_combined_filters_and_semantics(self) -> None:
        extra = (
            _label_sexp("VCC", 10, 10)
            + "\n"
            + _label_sexp("GND", 20, 20)
            + "\n"
            + _global_label_sexp("VCC", 30, 30)
        )
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels(
            {"schematicPath": str(tmp), "netName": "VCC", "labelType": "net"}
        )
        assert result["success"] is True
        assert all(lbl["name"] == "VCC" and lbl["type"] == "net" for lbl in result["labels"])

    def test_absent_filters_backward_compatible(self) -> None:
        extra = _label_sexp("NET1", 5, 5)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_list_schematic_labels({"schematicPath": str(tmp)})
        assert result["success"] is True
        assert "labels" in result
        assert "count" in result
