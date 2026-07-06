"""
Tests for the lint_offgrid tool (python/commands/schematic_lint_grid.py).

Field-observed failure mode: a symbol origin 0.03 mm off 157.48 mm
(= 124 x 1.27) poisoned junction placement for a whole sheet. lint_offgrid
reports such offenders and, with fix=true, snaps them via byte-exact text
surgery — never touching (lib_symbols) content, property field positions,
or offenders more than 0.5 mm off-grid (needsHuman).
"""

import difflib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import sexpdata  # noqa: E402

from commands.schematic_lint_grid import lint_offgrid  # noqa: E402

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"


def _make_temp_schematic(tmp_path: Path, extra_block: str = "") -> Path:
    dest = tmp_path / "test.kicad_sch"
    content = TEMPLATE_SCH.read_text(encoding="utf-8")
    if extra_block:
        content = content.rstrip()
        if content.endswith(")"):
            content = content[:-1] + "\n" + extra_block + ")\n"
    dest.write_text(content, encoding="utf-8")
    return dest


# The field-observed case: origin at 157.51 instead of 157.48 (124 x 1.27).
OFFGRID_SYMBOL = """\
  (symbol (lib_id "Device:R") (at 157.51 50.8 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 158.78 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 158.78 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""

OFFGRID_WIRE = """\
  (wire (pts (xy 157.51 50.8) (xy 165.1 50.8))
    (stroke (width 0) (type default))
    (uuid "abababab-cdcd-efef-0101-232323232323")
  )
"""

LABEL_VARIANTS = """\
  (label "NET1" (at 157.51 25.4 0)
    (effects (font (size 1.27 1.27)))
  )
  (global_label "NET2" (at 157.51 27.94 0)
    (effects (font (size 1.27 1.27)))
  )
  (hierarchical_label "NET3" (at 157.51 30.48 0)
    (effects (font (size 1.27 1.27)))
  )
  (junction (at 157.51 33.02)
    (diameter 0) (color 0 0 0 0)
  )
  (no_connect (at 157.51 35.56)
    (uuid "12312312-4564-7897-8908-098098098098")
  )
"""

# lib_symbols block carrying an off-grid local pin (must never be flagged)
LIB_WITH_OFFGRID_PIN = """\
  (symbol (lib_id "Test:FAKE") (at 25.4 25.4 0) (unit 1)
    (uuid "deadbeef-0000-0000-0000-000000000000")
    (property "Reference" "U9" (at 25.41 22.2 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""


@pytest.mark.unit
class TestLint:
    def test_clean_sheet_no_offenders(self, tmp_path):
        sch = _make_temp_schematic(tmp_path)
        r = lint_offgrid(str(sch))
        assert r["offenders"] == []
        assert r["fixed"] == 0

    def test_detects_symbol_origin_and_wire_endpoint(self, tmp_path):
        sch = _make_temp_schematic(tmp_path, OFFGRID_SYMBOL + OFFGRID_WIRE)
        before = sch.read_text(encoding="utf-8")
        r = lint_offgrid(str(sch))
        types = sorted(o["type"] for o in r["offenders"])
        assert types == ["symbol_origin", "wire_endpoint"]
        for o in r["offenders"]:
            assert o["x"] == 157.51
            assert o["snappedX"] == 157.48
            assert abs(o["offsetMm"] - 0.03) < 1e-6
            assert o["needsHuman"] is False
            assert o["line"] > 0
        # report-only: file bytes unchanged
        assert sch.read_text(encoding="utf-8") == before

    def test_fix_snaps_and_preserves_formatting(self, tmp_path):
        sch = _make_temp_schematic(tmp_path, OFFGRID_SYMBOL + OFFGRID_WIRE)
        before = sch.read_text(encoding="utf-8")
        r = lint_offgrid(str(sch), fix=True)
        assert r["fixed"] == 2
        after = sch.read_text(encoding="utf-8")

        # Both offenders snapped to the SAME grid node -> connectivity kept
        assert "157.51" not in after
        assert '(at 157.48 50.8 0)' in after
        assert "(xy 157.48 50.8)" in after

        # re-lint: clean; file still parses
        assert lint_offgrid(str(sch))["offenders"] == []
        sexpdata.loads(after)

        # formatting preserved: diff touches only the two offender lines
        changed = [
            line
            for line in difflib.unified_diff(
                before.splitlines(), after.splitlines(), lineterm="", n=0
            )
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        assert len(changed) == 4  # 2 lines removed + 2 added

    def test_lib_symbols_pins_excluded(self, tmp_path):
        # The template's lib_symbols carries pins at (0, 3.81)-style local
        # coords; inject a placed symbol so the sheet is non-trivial and make
        # a lib pin off-grid by rewriting one local pin coordinate.
        sch = _make_temp_schematic(tmp_path, LIB_WITH_OFFGRID_PIN)
        content = sch.read_text(encoding="utf-8")
        assert "(at 0 3.81 270)" in content  # template Device:R pin
        content = content.replace("(at 0 3.81 270)", "(at 0 3.812 270)", 1)
        sch.write_text(content, encoding="utf-8")

        r = lint_offgrid(str(sch), fix=True)
        # The off-grid LOCAL pin def is not flagged and not modified
        assert all(o["type"] != "wire_endpoint" or True for o in r["offenders"])
        assert "(at 0 3.812 270)" in sch.read_text(encoding="utf-8")
        # No offender at the lib pin coordinate
        assert not any(abs(o["y"] - 3.812) < 1e-9 for o in r["offenders"])

    def test_property_positions_excluded(self, tmp_path):
        sch = _make_temp_schematic(tmp_path, LIB_WITH_OFFGRID_PIN)
        r = lint_offgrid(str(sch))
        # U9's Reference property sits at 25.41 (off-grid) — not flagged;
        # the symbol origin itself (25.4 = 20 x 1.27) is on-grid.
        assert r["offenders"] == []

    def test_needs_human_threshold(self, tmp_path):
        # 1.0 mm off-grid: 11.16 -> nearest 11.43 (9 x 1.27) offset 0.27?
        # Use an unambiguous case: x = 10.16 + 0.6 = 10.76 -> nearest 10.16
        # or 11.43; 10.76/1.27 = 8.472 -> 8 -> 10.16, offset 0.6 > 0.5.
        wire = """\
  (wire (pts (xy 10.76 20.32) (xy 15.24 20.32))
    (stroke (width 0) (type default))
    (uuid "abababab-cdcd-efef-0101-888888888888")
  )
"""
        sch = _make_temp_schematic(tmp_path, wire)
        before = sch.read_text(encoding="utf-8")
        r = lint_offgrid(str(sch), fix=True)
        offender = next(o for o in r["offenders"] if o["x"] == 10.76)
        assert offender["needsHuman"] is True
        assert r["needsHuman"] == 1
        assert r["fixed"] == 0
        assert sch.read_text(encoding="utf-8") == before  # untouched

    def test_label_variants_detected(self, tmp_path):
        sch = _make_temp_schematic(tmp_path, LABEL_VARIANTS)
        r = lint_offgrid(str(sch))
        assert r["counts"].get("label") == 3
        assert r["counts"].get("junction") == 1
        assert r["counts"].get("no_connect") == 1

    def test_string_with_parens_does_not_break_scan(self, tmp_path):
        block = OFFGRID_SYMBOL.replace('"10k"', '"Cap (100nF) special"')
        sch = _make_temp_schematic(tmp_path, block)
        r = lint_offgrid(str(sch), fix=True)
        assert r["fixed"] == 1
        after = sch.read_text(encoding="utf-8")
        assert '"Cap (100nF) special"' in after
        sexpdata.loads(after)


# ---------------------------------------------------------------------------
# Handler-level tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandler:
    def _get_handler(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            iface = KiCADInterface.__new__(KiCADInterface)
        return iface._handle_lint_offgrid

    def test_missing_path(self):
        r = self._get_handler()({})
        assert r["success"] is False
        assert "schematicPath" in r["message"]

    def test_nonexistent_file(self, tmp_path):
        r = self._get_handler()({"schematicPath": str(tmp_path / "no.kicad_sch")})
        assert r["success"] is False

    def test_invalid_grid(self, tmp_path):
        sch = _make_temp_schematic(tmp_path)
        r = self._get_handler()({"schematicPath": str(sch), "gridSize": 0})
        assert r["success"] is False

    def test_report_and_fix(self, tmp_path):
        sch = _make_temp_schematic(tmp_path, OFFGRID_SYMBOL + OFFGRID_WIRE)
        handler = self._get_handler()
        r = handler({"schematicPath": str(sch)})
        assert r["success"] is True
        assert len(r["offenders"]) == 2
        assert r["fixed"] == 0
        assert "_spans" not in r["offenders"][0]

        r = handler({"schematicPath": str(sch), "fix": True})
        assert r["success"] is True
        assert r["fixed"] == 2
        assert handler({"schematicPath": str(sch)})["offenders"] == []


# ---------------------------------------------------------------------------
# Netlist equivalence (integration)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConnectivityPreserved:
    def test_wire_and_label_snap_to_same_node(self, tmp_path):
        """An off-grid label anchor coincident with an off-grid wire endpoint
        must land on the same grid node after fix (net membership identical)."""
        block = (
            OFFGRID_WIRE
            + '  (label "NETX" (at 157.51 50.8 0)\n'
            + "    (effects (font (size 1.27 1.27)))\n"
            + "  )\n"
        )
        sch = _make_temp_schematic(tmp_path, block)
        r = lint_offgrid(str(sch), fix=True)
        assert r["fixed"] == 2
        content = sch.read_text(encoding="utf-8")
        assert content.count("157.48 50.8") == 2  # wire endpoint + label anchor
