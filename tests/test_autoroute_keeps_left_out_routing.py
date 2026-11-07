"""Routing in passes keeps the earlier passes.

ImportSpecctraSES clears every track before adding the session's wires. A session from a
DSN with nets left out (routeNets / excludeNets) has none of theirs, so a pack-only pass
erased the logic routing done by the pass before it (found on a real 4-layer board:
600 tracks down to 66). The tracks and vias of left-out nets are now recorded before the
import and re-created after it.
"""

import os

import pytest


def _pcbnew():
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1")
    return pytest.importorskip("pcbnew")


def _board(pcbnew):
    b = pcbnew.BOARD()
    for name in ("LOGIC", "PACK"):
        b.Add(pcbnew.NETINFO_ITEM(b, name))
    mm = pcbnew.FromMM
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(mm(1), mm(2)))
    t.SetEnd(pcbnew.VECTOR2I(mm(9), mm(2)))
    t.SetWidth(mm(0.2))
    t.SetLayer(pcbnew.B_Cu)
    t.SetNet(b.FindNet("LOGIC"))
    b.Add(t)
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(mm(9), mm(2)))
    v.SetWidth(mm(0.6))
    v.SetDrill(mm(0.3))
    v.SetNet(b.FindNet("LOGIC"))
    b.Add(v)
    return b


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_snapshot_and_restore_round_trip():
    pcbnew = _pcbnew()
    from commands.freerouting import _restore_tracks, _snapshot_tracks

    b = _board(pcbnew)
    snap = _snapshot_tracks(b, ["LOGIC"])
    assert len(snap) == 2
    assert _snapshot_tracks(b, ["PACK"]) == []
    # what an import does to them
    b2 = pcbnew.BOARD()
    for name in ("LOGIC", "PACK"):
        b2.Add(pcbnew.NETINFO_ITEM(b2, name))
    assert _restore_tracks(b2, snap) == 2
    items = list(b2.GetTracks())
    track = next(t for t in items if t.GetClass() == "PCB_TRACK")
    via = next(t for t in items if t.GetClass() == "PCB_VIA")
    assert track.GetNetname() == "LOGIC" and track.GetLayer() == pcbnew.B_Cu
    assert (track.GetStart().x, track.GetEnd().x) == (pcbnew.FromMM(1), pcbnew.FromMM(9))
    assert track.GetWidth() == pcbnew.FromMM(0.2)
    assert via.GetDrillValue() == pcbnew.FromMM(0.3) and via.GetWidth() == pcbnew.FromMM(0.6)


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_a_real_import_of_a_session_without_a_net_keeps_its_tracks(tmp_path):
    pcbnew = _pcbnew()
    from commands.freerouting import _restore_tracks, _snapshot_tracks

    b = _board(pcbnew)
    dsn = tmp_path / "b.dsn"
    pcbnew.ExportSpecctraDSN(b, str(dsn))
    # A session that routes nothing (as from a DSN that left LOGIC out).
    ses = tmp_path / "b.ses"
    ses.write_text('(session "b.ses" (base_design "b.dsn")\n'
                   '  (routes (resolution um 10) (parser (host_cad "KiCad") (host_version "x"))\n'
                   '    (library_out) (network_out)))\n')
    kept = _snapshot_tracks(b, ["LOGIC"])
    pcbnew.ImportSpecctraSES(b, str(ses))
    assert [t for t in b.GetTracks() if t.GetNetname() == "LOGIC"] == []  # what KiCad does
    _restore_tracks(b, kept)
    assert len([t for t in b.GetTracks() if t.GetNetname() == "LOGIC"]) == 2
