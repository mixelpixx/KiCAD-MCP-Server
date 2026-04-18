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


# ===========================================================================
# TestMoveSchematicNetLabelSchema (unit)
# ===========================================================================


@pytest.mark.unit
class TestMoveSchematicNetLabelSchema:
    """Validate parameter acceptance and rejection for move_schematic_net_label."""

    def _ki(self):
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def test_missing_schematic_path_rejected(self) -> None:
        result = self._ki()._handle_move_schematic_net_label(
            {"netName": "VCC", "newPosition": {"x": 10, "y": 10}}
        )
        assert result["success"] is False
        assert "schematicPath" in result["message"]

    def test_missing_net_name_rejected(self) -> None:
        result = self._ki()._handle_move_schematic_net_label(
            {"schematicPath": "/tmp/fake.kicad_sch", "newPosition": {"x": 10, "y": 10}}
        )
        assert result["success"] is False
        assert "netName" in result["message"]

    def test_missing_new_position_rejected(self) -> None:
        tmp = _make_temp_schematic()
        result = self._ki()._handle_move_schematic_net_label(
            {"schematicPath": str(tmp), "netName": "VCC", "newPosition": {}}
        )
        assert result["success"] is False
        assert "newPosition" in result["message"]

    def test_invalid_label_type_rejected(self) -> None:
        tmp = _make_temp_schematic()
        result = self._ki()._handle_move_schematic_net_label(
            {
                "schematicPath": str(tmp),
                "netName": "VCC",
                "newPosition": {"x": 10, "y": 10},
                "labelType": "net",
            }
        )
        assert result["success"] is False
        assert "labelType" in result["message"]


# ===========================================================================
# TestMoveSchematicNetLabel (integration)
# ===========================================================================


@pytest.mark.integration
class TestMoveSchematicNetLabel:
    """Integration tests for _handle_move_schematic_net_label."""

    def _ki(self):
        from kicad_interface import KiCADInterface

        return KiCADInterface()

    def _read_label_positions(self, path: Path, name: str) -> list:
        """Return list of (x, y) tuples for all labels matching name."""
        import sexpdata
        from sexpdata import Symbol

        _SYM_AT = Symbol("at")
        _LABEL_SYMS = {Symbol("label"), Symbol("global_label"), Symbol("hierarchical_label")}
        sch_data = sexpdata.loads(path.read_text(encoding="utf-8"))
        positions = []
        for item in sch_data:
            if not (isinstance(item, list) and len(item) >= 2 and item[0] in _LABEL_SYMS):
                continue
            if item[1] != name:
                continue
            at_entry = next(
                (p for p in item if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT),
                None,
            )
            if at_entry is not None:
                positions.append((float(at_entry[1]), float(at_entry[2])))
        return positions

    def test_move_net_label_updates_position(self) -> None:
        tmp = _make_temp_schematic(_label_sexp("VCC", 10.0, 20.0))
        result = self._ki()._handle_move_schematic_net_label(
            {
                "schematicPath": str(tmp),
                "netName": "VCC",
                "newPosition": {"x": 30.0, "y": 40.0},
            }
        )
        assert result["success"] is True
        assert result["oldPosition"] == {"x": 10.0, "y": 20.0}
        assert result["newPosition"] == {"x": 30.0, "y": 40.0}
        positions = self._read_label_positions(tmp, "VCC")
        assert len(positions) == 1
        assert positions[0] == (30.0, 40.0)

    def test_move_global_label(self) -> None:
        tmp = _make_temp_schematic(_global_label_sexp("GND", 5.0, 5.0))
        result = self._ki()._handle_move_schematic_net_label(
            {
                "schematicPath": str(tmp),
                "netName": "GND",
                "newPosition": {"x": 15.0, "y": 25.0},
            }
        )
        assert result["success"] is True
        positions = self._read_label_positions(tmp, "GND")
        assert positions[0] == (15.0, 25.0)

    def test_disambiguate_by_current_position(self) -> None:
        extra = _label_sexp("SIG", 10.0, 10.0) + "\n" + _label_sexp("SIG", 20.0, 20.0)
        tmp = _make_temp_schematic(extra)
        result = self._ki()._handle_move_schematic_net_label(
            {
                "schematicPath": str(tmp),
                "netName": "SIG",
                "newPosition": {"x": 50.0, "y": 50.0},
                "currentPosition": {"x": 10.0, "y": 10.0},
            }
        )
        assert result["success"] is True
        positions = sorted(self._read_label_positions(tmp, "SIG"))
        assert (20.0, 20.0) in positions
        assert (50.0, 50.0) in positions

    def test_label_not_found_returns_failure(self) -> None:
        tmp = _make_temp_schematic()
        result = self._ki()._handle_move_schematic_net_label(
            {
                "schematicPath": str(tmp),
                "netName": "NONEXISTENT",
                "newPosition": {"x": 10.0, "y": 10.0},
            }
        )
        assert result["success"] is False
        assert "NONEXISTENT" in result["message"]

    def test_label_type_filter_skips_wrong_type(self) -> None:
        # Only a global_label exists; requesting labelType="label" should not find it
        tmp = _make_temp_schematic(_global_label_sexp("PWR", 10.0, 10.0))
        result = self._ki()._handle_move_schematic_net_label(
            {
                "schematicPath": str(tmp),
                "netName": "PWR",
                "newPosition": {"x": 30.0, "y": 30.0},
                "labelType": "label",
            }
        )
        assert result["success"] is False

    def test_current_position_no_match_returns_failure(self) -> None:
        tmp = _make_temp_schematic(_label_sexp("NET", 10.0, 10.0))
        result = self._ki()._handle_move_schematic_net_label(
            {
                "schematicPath": str(tmp),
                "netName": "NET",
                "newPosition": {"x": 30.0, "y": 30.0},
                "currentPosition": {"x": 99.0, "y": 99.0},
            }
        )
        assert result["success"] is False
