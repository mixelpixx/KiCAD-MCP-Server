"""
Tests for set_board_origin / get_board_origin (python/commands/board/origin.py).

Stub-mode tests validate parameters (conftest installs a MagicMock pcbnew).
Real-mode tests (KICAD_USE_REAL_PCBNEW=1) round-trip the origins through a
real board file and check the drill-origin offset via kicad-cli.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.board.origin import BoardOriginCommands  # noqa: E402


@pytest.fixture()
def commands():
    return BoardOriginCommands()


@pytest.fixture()
def board_file(tmp_path):
    p = tmp_path / "t.kicad_pcb"
    p.write_text('(kicad_pcb (version 20240108) (generator "pcbnew"))')
    return str(p)


# ---------------------------------------------------------------------------
# Stub-mode validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidation:
    def test_missing_board_path(self, commands):
        r = commands.set_board_origin({"x": 1, "y": 2})
        assert r["success"] is False
        assert "boardPath" in r["message"]
        r = commands.get_board_origin({})
        assert r["success"] is False
        assert "boardPath" in r["message"]

    def test_nonexistent_file(self, commands, tmp_path):
        r = commands.set_board_origin(
            {"boardPath": str(tmp_path / "nope.kicad_pcb"), "x": 1, "y": 2}
        )
        assert r["success"] is False
        assert "not found" in r["message"]

    def test_invalid_type(self, commands, board_file):
        r = commands.set_board_origin(
            {"boardPath": board_file, "type": "bogus", "x": 1, "y": 2}
        )
        assert r["success"] is False
        assert "type must be one of" in r["message"]

    def test_missing_coordinates(self, commands, board_file):
        r = commands.set_board_origin({"boardPath": board_file})
        assert r["success"] is False
        assert "x and y" in r["message"]
        r = commands.set_board_origin({"boardPath": board_file, "x": 1})
        assert r["success"] is False

    def test_non_numeric_coordinates(self, commands, board_file):
        r = commands.set_board_origin(
            {"boardPath": board_file, "x": "abc", "y": 2}
        )
        assert r["success"] is False
        assert "numeric" in r["message"]

    def test_invalid_unit(self, commands, board_file):
        r = commands.set_board_origin(
            {"boardPath": board_file, "x": 1, "y": 2, "unit": "furlong"}
        )
        assert r["success"] is False
        assert "unit must be one of" in r["message"]


# ---------------------------------------------------------------------------
# Real pcbnew round trip (gated)
# ---------------------------------------------------------------------------


@pytest.mark.real_pcbnew
class TestRealPcbnew:
    @pytest.fixture(autouse=True)
    def _require_real_pcbnew(self):
        if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
            pytest.skip("set KICAD_USE_REAL_PCBNEW=1 to run against real pcbnew")

    def _make_board(self, tmp_path):
        import pcbnew

        board_path = str(tmp_path / "t.kicad_pcb")
        board = pcbnew.BOARD()
        pcbnew.SaveBoard(board_path, board)
        return board_path

    def test_aux_round_trip(self, commands, tmp_path):
        board_path = self._make_board(tmp_path)
        r = commands.set_board_origin(
            {"boardPath": board_path, "type": "aux", "x": 10, "y": 20}
        )
        assert r["success"], r
        # Nonzero origins are serialized as an aux_axis_origin token
        text = Path(board_path).read_text(encoding="utf-8")
        assert "aux_axis_origin" in text

        g = commands.get_board_origin({"boardPath": board_path})
        assert g["success"], g
        assert g["aux"] == {"x": 10.0, "y": 20.0}

    def test_grid_and_both(self, commands, tmp_path):
        board_path = self._make_board(tmp_path)
        r = commands.set_board_origin(
            {"boardPath": board_path, "type": "grid", "x": 5, "y": 6}
        )
        assert r["success"], r
        g = commands.get_board_origin({"boardPath": board_path})
        assert g["grid"] == {"x": 5.0, "y": 6.0}
        assert g["aux"] == {"x": 0.0, "y": 0.0}

        r = commands.set_board_origin(
            {"boardPath": board_path, "type": "both", "x": 7, "y": 8}
        )
        assert r["success"], r
        g = commands.get_board_origin({"boardPath": board_path})
        assert g["aux"] == {"x": 7.0, "y": 8.0}
        assert g["grid"] == {"x": 7.0, "y": 8.0}

    def test_unit_conversion_inch(self, commands, tmp_path):
        import pcbnew

        board_path = self._make_board(tmp_path)
        r = commands.set_board_origin(
            {"boardPath": board_path, "x": 1, "y": 0.5, "unit": "inch"}
        )
        assert r["success"], r
        board = pcbnew.LoadBoard(board_path)
        aux = board.GetDesignSettings().GetAuxOrigin()
        assert aux.x == 25400000
        assert aux.y == 12700000

    def test_drill_origin_offset(self, commands, tmp_path):
        """Setting the aux origin must shift kicad-cli's plot-origin drill
        coordinates by exactly the origin vector."""
        import pcbnew

        if shutil.which("kicad-cli") is None:
            pytest.skip("kicad-cli not available")

        fp_lib = "/usr/share/kicad/footprints/Connector_PinHeader_2.54mm.pretty"
        if not os.path.isdir(fp_lib):
            pytest.skip("KiCad standard footprint library not installed")

        board_path = str(tmp_path / "t.kicad_pcb")
        board = pcbnew.BOARD()
        fp = pcbnew.FootprintLoad(fp_lib, "PinHeader_1x01_P2.54mm_Vertical")
        assert fp is not None
        fp.SetPosition(pcbnew.VECTOR2I(30000000, 30000000))  # (30, 30) mm
        board.Add(fp)
        pcbnew.SaveBoard(board_path, board)

        def _drill_coords(out_dir):
            out_dir.mkdir()
            subprocess.run(
                [
                    "kicad-cli",
                    "pcb",
                    "export",
                    "drill",
                    "--drill-origin",
                    "plot",
                    "--excellon-units",
                    "mm",
                    "-o",
                    str(out_dir) + "/",
                    board_path,
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            coords = []
            for drl in sorted(out_dir.glob("*.drl")):
                for line in drl.read_text().splitlines():
                    if line.startswith("X"):
                        x_part, y_part = line[1:].split("Y")
                        coords.append((float(x_part), float(y_part)))
            return coords

        before = _drill_coords(tmp_path / "before")
        r = commands.set_board_origin(
            {"boardPath": board_path, "type": "aux", "x": 30, "y": 30}
        )
        assert r["success"], r
        after = _drill_coords(tmp_path / "after")

        assert before and after
        # Compare deltas rather than absolute strings (Excellon Y sign and
        # zero formats vary between KiCad versions).
        (bx, by), (ax, ay) = before[0], after[0]
        assert abs(abs(bx - ax) - 30.0) < 0.01
        assert abs(abs(by - ay) - 30.0) < 0.01
