"""autoroute routeNets / excludeNets: route one set of nets, leave the rest as obstacles.

An isolated high-voltage board is routed one domain at a time (the pack-side
nets inside their region, then the logic nets), and high-current nets are
poured by hand rather than routed. Freerouting routes every net in the DSN, so
the selection is applied to the DSN copy: excluded nets lose their (net ...)
block and their place in the (class ...) lists, while their pads and copper
stay on the board as obstacles.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.freerouting import filter_dsn_nets, net_selector  # noqa: E402

DSN = """(pcb x.dsn
  (structure (layer F.Cu (type signal)))
  (network
    (net "/HV PWR/CAN H"
      (pins J5-4 U8-7)
    )
    (net /CSOUT
      (pins U1-5 Q2-12)
    )
    (net "/MODULE CONTROLLER/SD CLK"
      (pins U2-53 J4-5)
    )
    (class kicad_default /CSOUT "/MODULE CONTROLLER/SD CLK"
      (circuit (use_via Via[0-3]_600:300_um))
      (rule (width 200) (clearance 200))
    )
    (class PACK "/HV PWR/CAN H"
      (circuit (use_via Via[0-3]_600:300_um))
      (rule (width 300) (clearance 200))
    )
  )
  (wiring)
)
"""


def test_selector_include_and_exclude_globs():
    keep = net_selector(["/HV PWR/*"], [])
    assert keep("/HV PWR/CAN H") and not keep("/CSOUT")
    keep = net_selector([], ["/CSOUT", "/MODULE CONTROLLER/SD*"])
    assert keep("/HV PWR/CAN H") and not keep("/CSOUT") and not keep("/MODULE CONTROLLER/SD CLK")
    assert net_selector([], [])("anything")


def test_filter_keeps_only_selected_nets_and_classes_stay_valid():
    text, removed = filter_dsn_nets(DSN, net_selector(["/HV PWR/*"], []))
    assert sorted(removed) == ["/CSOUT", "/MODULE CONTROLLER/SD CLK"]
    assert '(net "/HV PWR/CAN H"' in text
    assert "(net /CSOUT" not in text and '"/MODULE CONTROLLER/SD CLK"\n' not in text
    # The class lists no longer name the removed nets, and keep their rules.
    assert "(class kicad_default \n" in text or "(class kicad_default" in text
    default = text[text.index("(class kicad_default") :]
    default = default[: default.index("(class PACK")]
    assert "/CSOUT" not in default and "SD CLK" not in default and "(rule (width 200)" in default
    assert '(class PACK "/HV PWR/CAN H"' in text
    # Balanced, and the rest of the file is untouched.
    assert text.count("(") == text.count(")")
    assert text.startswith("(pcb x.dsn\n  (structure") and text.rstrip().endswith("(wiring)\n)")


def test_no_selection_changes_nothing():
    text, removed = filter_dsn_nets(DSN, net_selector([], []))
    assert text == DSN and removed == []


def _jar():
    jar = os.environ.get("FREEROUTING_JAR")
    return jar if jar and os.path.isfile(jar) else None


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_autoroute_routes_only_the_selected_net(tmp_path):
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1" or not _jar() or not shutil.which("java"):
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1, FREEROUTING_JAR and java")
    import pcbnew

    from commands.freerouting import FreeroutingCommands

    fp_dir = next(
        (
            Path(os.environ[v])
            for v in ("KICAD10_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR")
            if v in os.environ
        ),
        Path("/usr/share/kicad/footprints"),
    )
    board = pcbnew.BOARD()
    for n in ("A", "B"):
        board.Add(pcbnew.NETINFO_ITEM(board, n))
    for ref, x, y, net in (
        ("R1", 5, 5, "A"),
        ("R2", 20, 5, "A"),
        ("R3", 5, 15, "B"),
        ("R4", 20, 15, "B"),
    ):
        fp = pcbnew.FootprintLoad(str(fp_dir / "Resistor_SMD.pretty"), "R_0603_1608Metric")
        fp.SetReference(ref)
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        for p in fp.Pads():
            p.SetNet(board.FindNet(net))
    for x1, y1, x2, y2 in ((0, 0, 25, 0), (25, 0, 25, 20), (25, 20, 0, 20), (0, 20, 0, 0)):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
        s.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
        board.Add(s)
    path = tmp_path / "r.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)
    (tmp_path / "r.kicad_pro").write_text("{}\n")

    cmd = FreeroutingCommands(None)  # nothing loaded: boardPath alone must be enough
    r = cmd.autoroute(
        {"boardPath": str(path), "freeroutingJar": _jar(), "routeNets": ["A"], "timeout": 120}
    )
    assert r["success"], r
    assert r["netsLeftOut"] == ["B"]
    routed = {t.GetNetname() for t in pcbnew.LoadBoard(str(path)).GetTracks()}
    assert routed == {"A"}
