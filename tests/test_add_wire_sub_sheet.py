"""
Regression tests for WireManager.add_wire / add_polyline_wire on hierarchical
sub-sheets.

Sub-sheets do not carry a (sheet_instances ...) block — that block is only
emitted on the root .kicad_sch in a hierarchical design. Before the fix, both
methods bailed out with "No sheet_instances section found in schematic" and
returned False, so users saw "Failed to add wire" on every call into a child
sheet.
"""

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# Minimal sub-sheet content: same outer (kicad_sch ...) form as a root sheet
# but WITHOUT (sheet_instances ...).
SUB_SHEET_NO_SHEET_INSTANCES = """(kicad_sch
\t(version 20260306)
\t(generator "eeschema")
\t(generator_version "10.0")
\t(uuid "bbbb2222-2222-2222-2222-bbbbbbbbbbbb")
\t(paper "A4")
\t(lib_symbols)
)
"""


def _write_sub_sheet(tmp_path: Path) -> Path:
    sch = tmp_path / "child.kicad_sch"
    sch.write_text(SUB_SHEET_NO_SHEET_INSTANCES, encoding="utf-8")
    return sch


@pytest.mark.unit
class TestAddWireSubSheet:
    """WireManager.add_wire must succeed on hierarchical sub-sheets."""

    def setup_method(self) -> None:
        from commands.wire_manager import WireManager

        self.WireManager = WireManager

    def test_add_wire_succeeds_on_sub_sheet(self, tmp_path: Any) -> None:
        sch = _write_sub_sheet(tmp_path)

        ok = self.WireManager.add_wire(sch, [40.0, 40.0], [40.0, 50.0])

        assert ok is True
        content = sch.read_text(encoding="utf-8")
        # The sexpdata writer emits the wire form somewhere in the file.
        assert "wire" in content
        assert "40.0" in content or "40 " in content

    def test_add_wire_keeps_outer_form_balanced_on_sub_sheet(self, tmp_path: Any) -> None:
        sch = _write_sub_sheet(tmp_path)

        self.WireManager.add_wire(sch, [10.0, 10.0], [10.0, 20.0])

        content = sch.read_text(encoding="utf-8")
        assert content.count("(") == content.count(
            ")"
        ), "Inserting into a sub-sheet must keep parens balanced"

        import sexpdata

        parsed = sexpdata.loads(content)
        assert parsed[0] == sexpdata.Symbol("kicad_sch")

    def test_add_wire_writes_endpoints_on_sub_sheet(self, tmp_path: Any) -> None:
        """The new wire must round-trip through sexpdata with the requested endpoints."""
        import sexpdata

        sch = _write_sub_sheet(tmp_path)

        self.WireManager.add_wire(sch, [12.5, 22.5], [42.5, 22.5])

        parsed = sexpdata.loads(sch.read_text(encoding="utf-8"))
        wires = [
            item
            for item in parsed[1:]
            if isinstance(item, list) and len(item) > 0 and item[0] == sexpdata.Symbol("wire")
        ]
        assert wires, "expected at least one (wire ...) item at top level after insert"
        # Find xy points among the wire's children
        wire_text = sexpdata.dumps(wires[0])
        assert "12.5" in wire_text and "22.5" in wire_text and "42.5" in wire_text


@pytest.mark.unit
class TestAddPolylineWireSubSheet:
    """WireManager.add_polyline_wire must succeed on hierarchical sub-sheets."""

    def setup_method(self) -> None:
        from commands.wire_manager import WireManager

        self.WireManager = WireManager

    def test_add_polyline_wire_succeeds_on_sub_sheet(self, tmp_path: Any) -> None:
        sch = _write_sub_sheet(tmp_path)

        ok = self.WireManager.add_polyline_wire(sch, [[10.0, 10.0], [20.0, 10.0], [20.0, 30.0]])

        assert ok is True

    def test_add_polyline_wire_writes_n_minus_1_segments(self, tmp_path: Any) -> None:
        """A 4-point polyline must insert 3 (wire ...) segments into the file."""
        import sexpdata

        sch = _write_sub_sheet(tmp_path)

        self.WireManager.add_polyline_wire(
            sch, [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [20.0, 10.0]]
        )

        parsed = sexpdata.loads(sch.read_text(encoding="utf-8"))
        wires = [
            item
            for item in parsed[1:]
            if isinstance(item, list) and len(item) > 0 and item[0] == sexpdata.Symbol("wire")
        ]
        assert len(wires) == 3, f"expected 3 wire segments, got {len(wires)}"

    def test_add_polyline_wire_keeps_outer_form_balanced_on_sub_sheet(self, tmp_path: Any) -> None:
        sch = _write_sub_sheet(tmp_path)

        self.WireManager.add_polyline_wire(sch, [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])

        content = sch.read_text(encoding="utf-8")
        assert content.count("(") == content.count(")")
