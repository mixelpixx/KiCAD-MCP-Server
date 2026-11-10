"""Routing in passes keeps the earlier passes.

ImportSpecctraSES removes the board's unlocked tracks and adds the session's wires. A
session from a DSN with nets left out (routeNets / excludeNets) has none of theirs, so a
pack-only pass erased the logic routing done by the pass before it (found on a real 4-layer
board: 600 tracks down to 66). KiCad keeps locked tracks through the import, so the tracks,
arcs and vias of left-out nets are locked for the import and their lock flags put back
afterwards: the same objects survive, with their UUIDs, arcs and group membership, and
nothing is duplicated (re-creating them after the import, the first version of this fix,
gave 3 tracks where there were 2 and lost arcs and UUIDs).
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
    a = pcbnew.PCB_ARC(b)
    a.SetStart(pcbnew.VECTOR2I(mm(9), mm(2)))
    a.SetMid(pcbnew.VECTOR2I(mm(11), mm(4)))
    a.SetEnd(pcbnew.VECTOR2I(mm(13), mm(2)))
    a.SetWidth(mm(0.2))
    a.SetLayer(pcbnew.F_Cu)
    a.SetNet(b.FindNet("LOGIC"))
    a.SetLocked(True)  # a lock the user set: must come back as it was
    b.Add(a)
    p = pcbnew.PCB_TRACK(b)
    p.SetStart(pcbnew.VECTOR2I(mm(1), mm(8)))
    p.SetEnd(pcbnew.VECTOR2I(mm(9), mm(8)))
    p.SetWidth(mm(0.3))
    p.SetLayer(pcbnew.F_Cu)
    p.SetNet(b.FindNet("PACK"))
    b.Add(p)
    return b


def _ids(b, net):
    return {str(t.m_Uuid.AsString()) for t in b.GetTracks() if t.GetNetname() == net}


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_lock_and_restore_round_trip():
    pcbnew = _pcbnew()
    from commands.freerouting import _lock_tracks_of_nets, _restore_lock_states

    b = _board(pcbnew)
    kept = _lock_tracks_of_nets(b, ["LOGIC"])
    assert len(kept) == 3 and sorted(was for _, was in kept) == [False, False, True]
    assert all(t.IsLocked() for t in b.GetTracks() if t.GetNetname() == "LOGIC")
    assert not next(t for t in b.GetTracks() if t.GetNetname() == "PACK").IsLocked()
    assert _lock_tracks_of_nets(b, ["NONE"]) == []
    assert _restore_lock_states(kept) == 3
    states = {t.GetClass(): t.IsLocked() for t in b.GetTracks() if t.GetNetname() == "LOGIC"}
    assert states == {"PCB_TRACK": False, "PCB_VIA": False, "PCB_ARC": True}


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_a_real_import_of_a_session_without_a_net_keeps_its_tracks(tmp_path):
    pcbnew = _pcbnew()
    from commands.freerouting import _lock_tracks_of_nets, _restore_lock_states

    b = _board(pcbnew)
    dsn = tmp_path / "b.dsn"
    pcbnew.ExportSpecctraDSN(b, str(dsn))
    # A session that routes nothing (as from a DSN that left LOGIC out).
    ses = tmp_path / "b.ses"
    ses.write_text(
        '(session "b.ses" (base_design "b.dsn")\n'
        '  (routes (resolution um 10) (parser (host_cad "KiCad") (host_version "x"))\n'
        "    (library_out) (network_out)))\n"
    )
    before = _ids(b, "LOGIC")
    assert len(before) == 3
    # what KiCad does without the lock: the unlocked LOGIC track and via are gone
    probe = _board(pcbnew)
    pcbnew.ImportSpecctraSES(probe, str(ses))
    assert {t.GetClass() for t in probe.GetTracks() if t.GetNetname() == "LOGIC"} == {"PCB_ARC"}

    kept = _lock_tracks_of_nets(b, ["LOGIC"])
    assert pcbnew.ImportSpecctraSES(b, str(ses))
    _restore_lock_states(kept)
    assert _ids(b, "LOGIC") == before  # the same objects, no duplicates
    assert _ids(b, "PACK") == set()  # the net in the session was cleared, as before
    states = {t.GetClass(): t.IsLocked() for t in b.GetTracks() if t.GetNetname() == "LOGIC"}
    assert states == {"PCB_TRACK": False, "PCB_VIA": False, "PCB_ARC": True}
    arc = next(t for t in b.GetTracks() if t.GetClass() == "PCB_ARC")
    assert arc.GetMid() == pcbnew.VECTOR2I(pcbnew.FromMM(11), pcbnew.FromMM(4))
