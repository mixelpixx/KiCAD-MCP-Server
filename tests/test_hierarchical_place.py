"""Tests for hierarchical_place (commands/hierarchical_place.py).

Parameter validation runs against the stubbed pcbnew from conftest. The real
placement round-trip needs the actual pcbnew module and is gated on
KICAD_USE_REAL_PCBNEW=1 (same convention as test_real_pcbnew_matrix.py).
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.hierarchical_place import HierarchicalPlaceCommands  # noqa: E402


def test_requires_board_path():
    r = HierarchicalPlaceCommands().hierarchical_place({})
    assert r["success"] is False
    assert "boardPath" in r["message"]


def test_missing_file():
    r = HierarchicalPlaceCommands().hierarchical_place(
        {"boardPath": "/no/such/board.kicad_pcb"}
    )
    assert r["success"] is False
    assert "not found" in r["message"]


class TestRealPcbnew:
    @pytest.fixture(autouse=True)
    def require_real_pcbnew(self):
        if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
            pytest.skip("requires real pcbnew (set KICAD_USE_REAL_PCBNEW=1)")

    def test_deoverlaps_real_board(self, tmp_path):
        import pcbnew

        fp_lib = "/usr/share/kicad/footprints/Resistor_SMD.pretty"
        if not Path(fp_lib).exists():
            pytest.skip("stock footprint library not installed")

        brd = pcbnew.BOARD()
        for ref in ["R1", "R2", "R3"]:
            fp = pcbnew.FootprintLoad(fp_lib, "R_0805_2012Metric")
            if fp is None:
                pytest.skip("could not load test footprint")
            fp.SetParent(brd)
            fp.SetReference(ref)
            fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(10)))  # all overlap
            brd.Add(fp)
        board_path = tmp_path / "b.kicad_pcb"
        pcbnew.SaveBoard(str(board_path), brd)

        r = HierarchicalPlaceCommands().hierarchical_place({"boardPath": str(board_path)})
        assert r["success"] is True, r
        assert r["footprint_count"] == 3
        assert r["placed_count"] == 3

        reloaded = pcbnew.LoadBoard(str(board_path))
        positions = {
            f.GetReference(): (f.GetPosition().x, f.GetPosition().y)
            for f in reloaded.GetFootprints()
        }
        assert len(positions) == 3
        # The three no longer share a single coordinate -> they were de-overlapped.
        assert len(set(positions.values())) > 1

    def test_empty_board(self, tmp_path):
        import pcbnew

        brd = pcbnew.BOARD()
        board_path = tmp_path / "empty.kicad_pcb"
        pcbnew.SaveBoard(str(board_path), brd)
        r = HierarchicalPlaceCommands().hierarchical_place({"boardPath": str(board_path)})
        assert r["success"] is True, r
        assert r["placed_count"] == 0
