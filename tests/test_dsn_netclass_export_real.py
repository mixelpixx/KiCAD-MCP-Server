"""Real-pcbnew end-to-end regression test for #302.

Requires KICAD_USE_REAL_PCBNEW=1 (run under KiCad's bundled Python, e.g.
``C:\\KiCad\\10.0\\bin\\python.exe -m pytest``). Builds a small board plus a
``.kicad_pro`` defining a 2.0 mm "Power" class over PWR/PWR2, then asserts
the production ``export_dsn`` emits the class with its rules and via
padstack — the exact scenario from the issue, where every net previously
exported under ``kicad_default`` at 0.2 mm.
"""

import json
import os
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_pcbnew,
]


@pytest.fixture(autouse=True)
def require_real_pcbnew() -> None:
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("real pcbnew DSN test requires KICAD_USE_REAL_PCBNEW=1")


def _build_board(pcbnew, pcb_path: Path):
    def mm(v):
        return pcbnew.FromMM(v)

    board = pcbnew.BOARD()
    nets = {}
    for name in ["PWR", "PWR2", "SIG", "GND"]:
        item = pcbnew.NETINFO_ITEM(board, name)
        board.Add(item)
        nets[name] = item

    for x1, y1, x2, y2 in [(0, 0, 50, 0), (50, 0, 50, 50), (50, 50, 0, 50), (0, 50, 0, 0)]:
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        seg.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)

    for ref, y, net_a, net_b in [("R1", 10, "PWR", "GND"), ("R2", 30, "PWR2", "SIG")]:
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(pcbnew.VECTOR2I(mm(10), mm(y)))
        for i, net in enumerate([net_a, net_b], start=1):
            pad = pcbnew.PAD(fp)
            pad.SetNumber(str(i))
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
            pad.SetSize(pcbnew.VECTOR2I(mm(1.6), mm(1.6)))
            pad.SetDrillSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
            pad.SetLayerSet(pad.PTHMask())
            pad.SetPosition(pcbnew.VECTOR2I(mm(10 + (i - 1) * 5), mm(y)))
            pad.SetNet(nets[net])
            fp.Add(pad)
        board.Add(fp)

    pcbnew.SaveBoard(str(pcb_path), board)


def _write_project(pro_path: Path) -> None:
    from kicad_mcp.utils.kicad_project import new_project_settings

    data = new_project_settings(pro_path.stem)
    classes = data["net_settings"]["classes"]
    power = dict(classes[0])
    power.update(name="Power", track_width=2.0, clearance=0.35, via_diameter=1.2, via_drill=0.6)
    classes.append(power)
    data["net_settings"]["netclass_patterns"] = [
        {"netclass": "Power", "pattern": "PWR"},
        {"netclass": "Power", "pattern": "PWR2"},
    ]
    pro_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_export_dsn_emits_project_net_classes(tmp_path: Path) -> None:
    import pcbnew

    from kicad_mcp.commands.freerouting import FreeroutingCommands

    pcb_path = tmp_path / "t302.kicad_pcb"
    _build_board(pcbnew, pcb_path)
    _write_project(tmp_path / "t302.kicad_pro")

    board = pcbnew.LoadBoard(str(pcb_path))
    result = FreeroutingCommands(board).export_dsn({"outputPath": str(tmp_path / "t302.dsn")})

    assert result["success"] is True, result
    assert result["netClasses"]["applied"] == ["Power"]
    assert "warning" not in result["netClasses"]

    dsn = (tmp_path / "t302.dsn").read_text(encoding="utf-8")
    assert "(class Power PWR PWR2" in dsn
    assert "(width 2000)" in dsn
    assert "(clearance 350)" in dsn
    assert '"Via[0-1]_1200:600_um"' in dsn
    # The claimed nets must leave the default class.
    assert "(class kicad_default GND SIG" in dsn
