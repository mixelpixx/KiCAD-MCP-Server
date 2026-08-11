"""Regression tests for #222 — add_layer could not add inner copper layers.

The report said the layers "do not persist". That was true — add_layer was
missing from _BOARD_MUTATING_COMMANDS so no auto-save fired — but it was the
least damaging of four defects:

1. never saved (the reported symptom)
2. ``In1_Cu + (number - 1)`` resolved to a NON-COPPER layer, because copper
   layer IDs step by 2 (F.Cu=0, B.Cu=2, In1.Cu=4, In2.Cu=6). The reporter's
   ``number: 4`` produced layer 7.
3. ``needed_count = 2 + number`` turned two inner layers into six, then eight
4. tool_schemas.py described a completely different tool (layerName/layerType)

So even with the save fixed, the old code wrote layer names onto IDs that are
not copper layers. These tests pin the arithmetic and the round-trip.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# Real KiCad layer IDs — the whole point of #222 is that these are not
# contiguous. Hard-coded rather than read from pcbnew so the expectation is
# visible in the test rather than derived from the thing under test.
F_CU, B_CU, IN1_CU, IN2_CU, IN3_CU = 0, 2, 4, 6, 8


@pytest.fixture(autouse=True)
def _real_layer_constants(monkeypatch):
    """conftest stubs pcbnew with a MagicMock, so pcbnew.In1_Cu would be a mock
    and the arithmetic under test would be meaningless. Pin the real KiCad 10
    values — the non-contiguity is exactly what #222 is about."""
    import pcbnew

    for attr, value in (
        ("F_Cu", F_CU),
        ("B_Cu", B_CU),
        ("In1_Cu", IN1_CU),
        ("LT_SIGNAL", 0),
        ("LT_POWER", 1),
        ("LT_MIXED", 2),
        ("LT_JUMPER", 3),
    ):
        monkeypatch.setattr(pcbnew, attr, value, raising=False)


def _commands(copper_count=2):
    """BoardLayerCommands with a mock board that tracks the copper count."""
    from commands.board.layers import BoardLayerCommands

    board = MagicMock()
    state = {"count": copper_count}
    board.GetCopperLayerCount.side_effect = lambda: state["count"]
    board.SetCopperLayerCount.side_effect = lambda n: state.update(count=n)

    def _canonical(lid):
        if lid == F_CU:
            return "F.Cu"
        if lid == B_CU:
            return "B.Cu"
        return f"In{(lid - IN1_CU) // 2 + 1}.Cu"

    board.GetStandardLayerName.side_effect = _canonical

    cmd = BoardLayerCommands(board=board)
    return cmd, board, state


class TestInnerLayerResolution:
    """The step-by-2 bug."""

    @pytest.mark.parametrize(
        "ordinal,expected_id,expected_name",
        [(1, IN1_CU, "In1.Cu"), (2, IN2_CU, "In2.Cu"), (3, IN3_CU, "In3.Cu")],
    )
    def test_ordinal_maps_to_the_right_copper_layer(self, ordinal, expected_id, expected_name):
        cmd, board, _ = _commands()
        r = cmd.add_layer(
            {"name": expected_name, "type": "copper", "position": "inner", "number": ordinal}
        )
        assert r["success"] is True
        assert r["layer"]["id"] == expected_id
        assert r["layer"]["canonicalName"] == expected_name

    def test_resolved_layer_is_always_a_copper_id(self):
        """The old formula produced odd IDs; copper layers are all even."""
        for ordinal in range(1, 31):
            cmd, _, _ = _commands()
            r = cmd.add_layer(
                {"name": "X", "type": "copper", "position": "inner", "number": ordinal}
            )
            assert r["success"] is True
            assert (
                r["layer"]["id"] % 2 == 0
            ), f"ordinal {ordinal} resolved to an odd (non-copper) id"

    def test_the_exact_reported_call_no_longer_hits_layer_seven(self):
        """#222 used number: 4 and the old code computed layer 7."""
        cmd, _, _ = _commands()
        r = cmd.add_layer({"name": "In1.Cu", "type": "copper", "position": "inner", "number": 4})
        assert r["success"] is True
        assert r["layer"]["id"] != 7
        assert r["layer"]["id"] == 10  # In4.Cu — ordinal 4, per the documented meaning

    def test_top_and_bottom(self):
        cmd, _, _ = _commands()
        assert (
            cmd.add_layer({"name": "F.Cu", "type": "copper", "position": "top"})["layer"]["id"]
            == F_CU
        )
        assert (
            cmd.add_layer({"name": "B.Cu", "type": "copper", "position": "bottom"})["layer"]["id"]
            == B_CU
        )


class TestCopperLayerCount:
    def test_two_inner_layers_gives_four_copper_layers(self):
        """Old code: 2 + number, so number=4 asked for six copper layers."""
        cmd, board, state = _commands()
        cmd.add_layer({"name": "In1.Cu", "type": "copper", "position": "inner", "number": 1})
        cmd.add_layer({"name": "In2.Cu", "type": "copper", "position": "inner", "number": 2})
        assert state["count"] == 4

    def test_count_is_never_reduced(self):
        cmd, board, state = _commands(copper_count=8)
        cmd.add_layer({"name": "In1.Cu", "type": "copper", "position": "inner", "number": 1})
        assert state["count"] == 8

    def test_top_layer_does_not_touch_the_count(self):
        cmd, board, state = _commands()
        cmd.add_layer({"name": "F.Cu", "type": "copper", "position": "top"})
        board.SetCopperLayerCount.assert_not_called()


class TestNaming:
    def test_custom_name_is_set(self):
        cmd, board, _ = _commands()
        cmd.add_layer({"name": "PWR", "type": "copper", "position": "inner", "number": 1})
        board.SetLayerName.assert_called_once_with(IN1_CU, "PWR")

    def test_canonical_name_is_not_rewritten(self):
        """Naming a layer what KiCad already calls it must leave the file alone."""
        cmd, board, _ = _commands()
        cmd.add_layer({"name": "In1.Cu", "type": "copper", "position": "inner", "number": 1})
        board.SetLayerName.assert_not_called()


class TestValidation:
    @pytest.mark.parametrize("bad_type", ["technical", "user", "silkscreen"])
    def test_non_copper_types_are_rejected(self, bad_type):
        """These used to silently retype F.Cu."""
        cmd, board, _ = _commands()
        r = cmd.add_layer({"name": "X", "type": bad_type, "position": "top"})
        assert r["success"] is False
        assert "copper" in r["errorDetails"].lower()
        board.SetLayerType.assert_not_called()

    @pytest.mark.parametrize("bad", [0, -1, 31, 99])
    def test_out_of_range_ordinal_rejected(self, bad):
        cmd, _, _ = _commands()
        r = cmd.add_layer({"name": "X", "type": "copper", "position": "inner", "number": bad})
        assert r["success"] is False
        assert "ordinal" in r["errorDetails"]

    def test_non_integer_ordinal_rejected(self):
        cmd, _, _ = _commands()
        r = cmd.add_layer({"name": "X", "type": "copper", "position": "inner", "number": "abc"})
        assert r["success"] is False

    def test_inner_without_number_rejected(self):
        cmd, _, _ = _commands()
        r = cmd.add_layer({"name": "X", "type": "copper", "position": "inner"})
        assert r["success"] is False
        assert "number is required" in r["errorDetails"]

    def test_bad_position_rejected(self):
        cmd, _, _ = _commands()
        r = cmd.add_layer({"name": "X", "type": "copper", "position": "sideways"})
        assert r["success"] is False


class TestAutoSaveRegistration:
    def test_add_layer_is_a_board_mutating_command(self):
        """Without this, add_layer reports success and writes nothing (#222)."""
        from kicad_interface import KiCADInterface

        assert "add_layer" in KiCADInterface._BOARD_MUTATING_COMMANDS


class TestSchemaMatchesTheRealTool:
    def test_schema_declares_the_parameters_the_handler_reads(self):
        """tool_schemas.py described layerName/layerType; the tool takes
        name/type/position/number (#222)."""
        from schemas.tool_schemas import TOOL_SCHEMAS

        entry = TOOL_SCHEMAS["add_layer"]
        props = entry["inputSchema"]["properties"]
        assert set(props) == {"name", "type", "position", "number"}
        assert entry["inputSchema"]["required"] == ["name", "type", "position"]


# --------------------------------------------------------------------------
# Real KiCad round-trip — the check that would have caught the original report
# --------------------------------------------------------------------------

_KICAD_PY = Path(r"C:\KiCad\10.0\bin\python.exe")

_ROUNDTRIP = r"""
import os, re, sys, tempfile
import pcbnew
sys.path.insert(0, sys.argv[1])
from commands.board.layers import BoardLayerCommands

d = tempfile.mkdtemp(); p = os.path.join(d, "t.kicad_pcb")
board = pcbnew.BOARD()
cmd = BoardLayerCommands(board=board)
r1 = cmd.add_layer({"name": "PWR",  "type": "copper", "position": "inner", "number": 1})
r2 = cmd.add_layer({"name": "In2.Cu", "type": "copper", "position": "inner", "number": 2})
assert r1["success"] and r2["success"], (r1, r2)
pcbnew.SaveBoard(p, board)

txt = open(p, encoding="utf-8").read()
block = re.search(r"\(layers(.*?)\n\s*\)\n", txt, re.S).group(1)
print("BLOCK_START")
print(block.strip()[:400])
print("BLOCK_END")
print("IDS:", r1["layer"]["id"], r2["layer"]["id"])
print("COUNT:", pcbnew.LoadBoard(p).GetCopperLayerCount())
"""


@pytest.mark.skipif(not _KICAD_PY.exists(), reason="real KiCad 10 not installed")
def test_inner_layers_actually_reach_the_file():
    """#222's core complaint: the (layers) table on disk lacked the inner layers."""
    python_root = str(Path(__file__).parent.parent / "python")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(_ROUNDTRIP)
        script = fh.name
    try:
        proc = subprocess.run(
            [str(_KICAD_PY), script, python_root],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        os.unlink(script)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    block = out.split("BLOCK_START")[1].split("BLOCK_END")[0]

    # Both inner layers present, on the correct (even) copper IDs, with the
    # custom name stored alongside the canonical one.
    assert '(4 "In1.Cu" signal "PWR")' in block, block
    assert '(6 "In2.Cu" signal)' in block, block
    assert "IDS: 4 6" in out, out
    assert "COUNT: 4" in out, out
