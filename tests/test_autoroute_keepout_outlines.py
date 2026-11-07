"""A rule area with several outlines reaches Freerouting whole.

KiCad's Specctra export writes only the first outline of a rule area; on a real board a
keepout built from many voltage halos exported as one polygon, and Freerouting put logic
vias 0.4 mm from 400 V pads that the dropped outlines covered.
"""

import os
import re

import pytest


def _require_pcbnew():
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1")
    return pytest.importorskip("pcbnew")


def _board_with_two_outline_keepout(pcbnew, tracks=True, vias=True):
    b = pcbnew.BOARD()
    mm = pcbnew.FromMM
    # board outline so the export has a boundary
    for (x1, y1), (x2, y2) in (((0, 0), (40, 0)), ((40, 0), (40, 30)), ((40, 30), (0, 30)), ((0, 30), (0, 0))):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        s.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
        s.SetLayer(pcbnew.Edge_Cuts)
        b.Add(s)
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(vias)
    z.SetLayer(pcbnew.F_Cu)
    o = z.Outline()
    for x0 in (5, 25):
        o.NewOutline()
        for x, y in ((x0, 5), (x0 + 8, 5), (x0 + 8, 12), (x0, 12)):
            o.Append(mm(x), mm(y))
    b.Add(z)
    return b


def _keepouts(text):
    return re.findall(r"\((keepout|wire_keepout|via_keepout) \"\" \(polygon F\.Cu 0 ([^)]*)\)", text)


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_every_outline_of_a_rule_area_is_exported(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import _append_missing_keepouts

    b = _board_with_two_outline_keepout(pcbnew)
    dsn = tmp_path / "b.dsn"
    assert pcbnew.ExportSpecctraDSN(b, str(dsn)) in (True, 0, None) or dsn.exists()
    before = _keepouts(dsn.read_text())
    assert len(before) == 1  # KiCad's own export: the second outline is missing

    assert _append_missing_keepouts(b, str(dsn)) == 1
    after = _keepouts(dsn.read_text())
    assert len(after) == 2
    xs = sorted(float(pts.split()[0]) for _, pts in after)
    # second rectangle starts at x = 25 mm (or 33 mm, depending on the first vertex)
    assert any(24999 <= x <= 33001 for x in xs[1:])
    # y is negated, as KiCad writes it
    assert all(float(pts.split()[1]) < 0 for _, pts in after)


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_keepout_kind_follows_the_rule_area_flags(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import _append_missing_keepouts

    b = _board_with_two_outline_keepout(pcbnew, tracks=False, vias=True)
    dsn = tmp_path / "b.dsn"
    pcbnew.ExportSpecctraDSN(b, str(dsn))
    _append_missing_keepouts(b, str(dsn))
    kinds = [k for k, _ in _keepouts(dsn.read_text())]
    assert kinds.count("via_keepout") == len(kinds) == 2


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_single_outline_areas_are_left_alone(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import _append_missing_keepouts

    b = pcbnew.BOARD()
    dsn = tmp_path / "b.dsn"
    dsn.write_text("(pcb x\n  (structure\n  )\n  (placement\n  )\n)\n")
    assert _append_missing_keepouts(b, str(dsn)) == 0
