"""autoroute routeNets / excludeNets: route one set of nets, leave the rest as obstacles.

An isolated high-voltage board is routed one domain at a time (the pack-side
nets inside their region, then the logic nets), and high-current nets are
poured by hand rather than routed. Freerouting routes every net in the DSN, so
the selection is applied to the DSN copy: excluded nets lose their (net ...)
block, while their pads and copper stay on the board as obstacles. The
(class ...) lists are left alone: Freerouting skips a class member it does not
know, and KiCad's auto-generated names such as "Net-(C5-Pad1)" contain the
parenthesis that a rewrite used to trip over.
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


def test_filter_keeps_only_selected_nets_and_leaves_the_classes_alone():
    text, removed = filter_dsn_nets(DSN, net_selector(["/HV PWR/*"], []))
    assert sorted(removed) == ["/CSOUT", "/MODULE CONTROLLER/SD CLK"]
    assert '(net "/HV PWR/CAN H"' in text
    assert "(net /CSOUT" not in text and '(net "/MODULE CONTROLLER/SD CLK"' not in text
    # The class lists are untouched, rules included.
    classes = text[text.index("(class kicad_default") :]
    assert classes == DSN[DSN.index("(class kicad_default") :]
    # Balanced, and the rest of the file is untouched.
    assert text.count("(") == text.count(")")
    assert text.startswith("(pcb x.dsn\n  (structure") and text.rstrip().endswith("(wiring)\n)")


# KiCad's own names for unlabelled nets carry a parenthesis.
AUTO_NAMED = """(pcb x.dsn
  (structure (layer F.Cu (type signal)))
  (network
    (net VCC
      (pins C5-2 U1-1)
    )
    (net "Net-(C5-Pad1)"
      (pins C5-1 R1-2)
    )
    (net "Net-(R1-Pad1)"
      (pins R1-1 U1-3)
    )
    (class kicad_default "" VCC "Net-(C5-Pad1)" "Net-(R1-Pad1)"
      (circuit (use_via Via[0-1]_600:300_um))
      (rule (width 250) (clearance 200))
    )
  )
  (wiring)
)
"""


def test_auto_generated_net_names_with_parentheses():
    # routeNets: ["VCC"] used to produce '(class kicad_default \n (C5-Pad1)" ...' and
    # unbalance the quotes for the rest of the file.
    text, removed = filter_dsn_nets(AUTO_NAMED, net_selector(["VCC"], []))
    assert removed == ["Net-(C5-Pad1)", "Net-(R1-Pad1)"]
    assert "(net VCC" in text and '(net "Net-(C5-Pad1)"' not in text
    assert text.count('"') % 2 == 0 and text.count("(") == text.count(")")
    assert text[text.index("(class") :] == AUTO_NAMED[AUTO_NAMED.index("(class") :]
    # and the other way round: excluding one such net removes exactly it
    text, removed = filter_dsn_nets(AUTO_NAMED, net_selector([], ["Net-(C5-Pad1)"]))
    assert removed == ["Net-(C5-Pad1)"]
    assert '(net "Net-(R1-Pad1)"' in text and "(net VCC" in text


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
    if not (fp_dir / "Resistor_SMD.pretty").is_dir():
        pytest.skip(f"no footprint library at {fp_dir}")
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

    cmd = FreeroutingCommands(pcbnew.LoadBoard(str(path)))
    r = cmd.autoroute({"freeroutingJar": _jar(), "routeNets": ["A"], "timeout": 120})
    assert r["success"], r
    assert r["netsLeftOut"] == ["B"]
    routed = {t.GetNetname() for t in pcbnew.LoadBoard(str(path)).GetTracks()}
    assert routed == {"A"}


WIRED = """(pcb x.dsn
  (structure
    (layer F.Cu (type signal))
    (layer "Bottom side" (type signal))
  )
  (library
    (padstack "Via[0-1]_600:300_um"
      (shape (circle F.Cu 600))
      (shape (circle "Bottom side" 600))
    )
  )
  (network
    (net "/HV PWR/CAN H"
      (pins J5-4 U8-7)
    )
    (net "/MODULE CONTROLLER/SD CLK"
      (pins U2-53 J4-5)
    )
  )
  (wiring
    (wire (path F.Cu 250  1000 -2000  5000 -2000)(net "/HV PWR/CAN H")(type route))
    (via "Via[0-1]_600:300_um" 5000 -2000 (net "/HV PWR/CAN H")(type route))
    (wire (path "Bottom side" 250  5000 -2000  5000 -6000)(net "/HV PWR/CAN H")(type route))
    (wire (path "Bottom side" 200  100 -100  900 -100)(net "/MODULE CONTROLLER/SD CLK")(type route))
  )
)
"""


def test_left_out_nets_copper_becomes_keepouts():
    # Found routing in passes: a wire whose net is no longer in (network) is dropped by
    # Freerouting, so a logic pass routed through the pack nets' tracks (79 shorts).
    out, removed = filter_dsn_nets(WIRED, net_selector(["/MODULE*"], []))
    assert removed == ["/HV PWR/CAN H"]
    wiring = out[out.index("(wiring") :]
    assert "CAN H" not in wiring  # gone from the wiring
    assert "SD CLK" in wiring  # the routed net's own wire stays
    structure = out[out.index("(structure") : out.index("(library")]
    assert '(keepout "" (path F.Cu 250 1000 -2000  5000 -2000))' in structure
    # a wire on a layer KiCad quotes keeps the quoted name
    assert '(keepout "" (path "Bottom side" 250 5000 -2000  5000 -6000))' in structure
    # the via blocks every copper layer, at its padstack's diameter, names quoted as KiCad does
    assert '(keepout "" (circle F.Cu 600 5000 -2000))' in structure
    assert '(keepout "" (circle "Bottom side" 600 5000 -2000))' in structure
    assert "(circle Bottom side" not in structure
    assert out.count("(") == out.count(")")


def test_no_left_out_wiring_leaves_the_structure_alone():
    out, removed = filter_dsn_nets(WIRED, net_selector([], []))
    assert removed == [] and out == WIRED
