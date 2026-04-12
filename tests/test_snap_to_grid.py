"""
Tests for the snap_to_grid schematic tool.

Unit tests cover the snapping math and per-element-type logic using synthetic
S-expressions.  Integration tests run against real .kicad_sch files created
from the empty template.
"""

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
import sexpdata
from sexpdata import Symbol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_snap import _is_on_grid, _snap_mm, snap_to_grid

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "python" / "templates" / "empty.kicad_sch"


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


def _wire_sexp(x1: float, y1: float, x2: float, y2: float) -> str:
    u = str(uuid.uuid4())
    return (
        f"(wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n"
        f"  (stroke (width 0) (type default))\n"
        f'  (uuid "{u}"))'
    )


def _junction_sexp(x: float, y: float) -> str:
    u = str(uuid.uuid4())
    return f'(junction (at {x} {y}) (diameter 0) (color 0 0 0 0) (uuid "{u}"))'


def _label_sexp(name: str, x: float, y: float, angle: float = 0) -> str:
    u = str(uuid.uuid4())
    return (
        f'(label "{name}" (at {x} {y} {angle})\n'
        f"  (effects (font (size 1.27 1.27)) (justify left bottom))\n"
        f'  (uuid "{u}"))'
    )


# ---------------------------------------------------------------------------
# Unit tests — pure math, no file I/O
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSnapMath:
    def test_snap_mm_already_on_grid(self):
        assert _snap_mm(2.54, 2.54) == pytest.approx(2.54)

    def test_snap_mm_rounds_up(self):
        # 2.55 is closer to 5.08 than to 2.54 (distance 2.53 vs 0.01)
        # Actually 2.55 / 2.54 = 1.0039..., rounds to 1 → 2.54
        assert _snap_mm(2.55, 2.54) == pytest.approx(2.54)

    def test_snap_mm_rounds_to_next(self):
        # 3.81 / 2.54 = 1.5 → rounds to 2 → 5.08
        assert _snap_mm(3.81, 2.54) == pytest.approx(5.08)

    def test_snap_mm_negative(self):
        assert _snap_mm(-2.51, 2.54) == pytest.approx(-2.54)

    def test_snap_mm_zero(self):
        assert _snap_mm(0.0, 2.54) == pytest.approx(0.0)

    def test_snap_mm_small_grid(self):
        assert _snap_mm(1.28, 1.27) == pytest.approx(1.27)

    def test_is_on_grid_true(self):
        assert _is_on_grid(2.54, 2.54)
        assert _is_on_grid(0.0, 2.54)
        assert _is_on_grid(5.08, 2.54)

    def test_is_on_grid_false(self):
        assert not _is_on_grid(2.55, 2.54)
        assert not _is_on_grid(1.0, 2.54)

    def test_snap_invalid_grid_raises(self):
        with pytest.raises(ValueError, match="grid_size must be positive"):
            snap_to_grid(Path("/nonexistent"), grid_size=-1.0)

    def test_snap_unknown_element_raises(self):
        with pytest.raises(ValueError, match="Unknown element type"):
            snap_to_grid(Path("/nonexistent"), elements=["bogus"])


# ---------------------------------------------------------------------------
# Integration tests — real .kicad_sch files
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSnapWires:
    def test_off_grid_wire_is_snapped(self):
        path = _make_temp_schematic(_wire_sexp(2.51, 5.03, 7.56, 5.03))
        result = snap_to_grid(path, grid_size=2.54, elements=["wires"])
        assert result["snapped"] >= 1

        # Verify coordinates in the written file
        data = sexpdata.loads(path.read_text(encoding="utf-8"))
        wire = next(
            item for item in data if isinstance(item, list) and item and item[0] == Symbol("wire")
        )
        pts = next(sub for sub in wire[1:] if isinstance(sub, list) and sub[0] == Symbol("pts"))
        xy_pairs = [sub for sub in pts[1:] if isinstance(sub, list) and sub[0] == Symbol("xy")]
        for pt in xy_pairs:
            assert _is_on_grid(float(pt[1]), 2.54), f"x={pt[1]} not on grid"
            assert _is_on_grid(float(pt[2]), 2.54), f"y={pt[2]} not on grid"

    def test_on_grid_wire_counts_as_already_on_grid(self):
        path = _make_temp_schematic(_wire_sexp(2.54, 5.08, 7.62, 5.08))
        result = snap_to_grid(path, grid_size=2.54, elements=["wires"])
        assert result["snapped"] == 0
        assert result["already_on_grid"] >= 1

    def test_wires_not_snapped_when_excluded(self):
        path = _make_temp_schematic(_wire_sexp(2.51, 5.03, 7.56, 5.03))
        result = snap_to_grid(path, grid_size=2.54, elements=["junctions"])
        assert result["snapped"] == 0


@pytest.mark.integration
class TestSnapJunctions:
    def test_off_grid_junction_is_snapped(self):
        path = _make_temp_schematic(_junction_sexp(2.51, 2.51))
        result = snap_to_grid(path, grid_size=2.54, elements=["junctions"])
        assert result["snapped"] >= 1

        data = sexpdata.loads(path.read_text(encoding="utf-8"))
        junc = next(
            item
            for item in data
            if isinstance(item, list) and item and item[0] == Symbol("junction")
        )
        at = next(sub for sub in junc[1:] if isinstance(sub, list) and sub[0] == Symbol("at"))
        assert _is_on_grid(float(at[1]), 2.54)
        assert _is_on_grid(float(at[2]), 2.54)

    def test_on_grid_junction_unchanged(self):
        path = _make_temp_schematic(_junction_sexp(2.54, 2.54))
        result = snap_to_grid(path, grid_size=2.54, elements=["junctions"])
        assert result["snapped"] == 0
        assert result["already_on_grid"] >= 1


@pytest.mark.integration
class TestSnapLabels:
    def test_off_grid_label_snapped_preserves_angle(self):
        path = _make_temp_schematic(_label_sexp("NET_A", 2.51, 5.03, angle=90))
        result = snap_to_grid(path, grid_size=2.54, elements=["labels"])
        assert result["snapped"] >= 1

        data = sexpdata.loads(path.read_text(encoding="utf-8"))
        lbl = next(
            item for item in data if isinstance(item, list) and item and item[0] == Symbol("label")
        )
        at = next(sub for sub in lbl[1:] if isinstance(sub, list) and sub[0] == Symbol("at"))
        assert _is_on_grid(float(at[1]), 2.54), f"x={at[1]} not on grid"
        assert _is_on_grid(float(at[2]), 2.54), f"y={at[2]} not on grid"
        # angle must be preserved
        assert float(at[3]) == pytest.approx(90.0)

    def test_on_grid_label_unchanged(self):
        path = _make_temp_schematic(_label_sexp("NET_B", 2.54, 5.08))
        result = snap_to_grid(path, grid_size=2.54, elements=["labels"])
        assert result["snapped"] == 0


@pytest.mark.integration
class TestSnapDefaults:
    def test_default_elements_snaps_wires_and_junctions_and_labels(self):
        extra = "\n".join(
            [
                _wire_sexp(2.51, 5.03, 7.56, 5.03),
                _junction_sexp(2.51, 2.51),
                _label_sexp("VCC", 2.51, 2.51),
            ]
        )
        path = _make_temp_schematic(extra)
        result = snap_to_grid(path)  # defaults: grid=2.54, elements=None
        assert result["snapped"] >= 3
        assert result["grid_size"] == pytest.approx(1.27)

    def test_idempotent(self):
        path = _make_temp_schematic(_wire_sexp(2.51, 5.03, 7.56, 5.03))
        snap_to_grid(path, grid_size=2.54)
        content_after_first = path.read_text(encoding="utf-8")
        snap_to_grid(path, grid_size=2.54)
        content_after_second = path.read_text(encoding="utf-8")
        assert content_after_first == content_after_second

    def test_default_grid_is_1_27mm(self):
        # Regression: default was 2.54 mm, which displaces valid KiCAD pin
        # coordinates that fall on the 50-mil (1.27 mm) grid but not on the
        # 100-mil (2.54 mm) grid — e.g. 26.67 mm = 21 × 1.27 mm.
        # With the correct 1.27 mm default those coordinates must be left
        # untouched (snapped == 0, already_on_grid >= 1).
        # 26.67 / 2.54 == 10.5 → would snap to 25.40 mm (off by 1.27 mm).
        # 26.67 / 1.27 == 21.0 → already on grid, no move.
        path = _make_temp_schematic(_wire_sexp(335.28, 26.67, 350.52, 26.67))
        result = snap_to_grid(path)  # default grid
        assert result["grid_size"] == pytest.approx(1.27)
        assert result["snapped"] == 0, (
            "Wire at valid 50-mil pin coordinates was displaced by default snap — "
            "default grid must be 1.27 mm, not 2.54 mm"
        )
        assert result["already_on_grid"] >= 1

    def test_custom_grid(self):
        # 1.27 mm grid — wire at 1.25 should snap to 1.27
        path = _make_temp_schematic(_wire_sexp(1.25, 1.25, 2.51, 2.51))
        result = snap_to_grid(path, grid_size=1.27)
        assert result["snapped"] >= 1
        data = sexpdata.loads(path.read_text(encoding="utf-8"))
        wire = next(
            item for item in data if isinstance(item, list) and item and item[0] == Symbol("wire")
        )
        pts = next(sub for sub in wire[1:] if isinstance(sub, list) and sub[0] == Symbol("pts"))
        xy_pairs = [sub for sub in pts[1:] if isinstance(sub, list) and sub[0] == Symbol("xy")]
        for pt in xy_pairs:
            assert _is_on_grid(float(pt[1]), 1.27), f"x={pt[1]} not on 1.27 grid"
            assert _is_on_grid(float(pt[2]), 1.27), f"y={pt[2]} not on 1.27 grid"
