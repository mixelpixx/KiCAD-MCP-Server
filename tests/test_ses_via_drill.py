"""An SES import keeps each via's drill as its padstack names it.

KiCad's ImportSpecctraSES keeps the padstack's drill, except when it equals the Default netclass's
via drill: makeVIA stores that one as undefined, and it then resolves through the via's net's own
class. A 0.5/0.3 via ("Via[0-5]_500:300_um") on a board whose Default drill is 0.3, on a net whose
class asks for 0.8/0.4 vias, comes back 0.5 mm with a 0.4 mm drill: a 0.05 mm annular ring, under
any fab's minimum (KiCad 10.0.8; 22 such vias on every Freerouting pass of a real 6-layer board).
_restore_via_drills puts the padstack's drill back on the vias the import created; vias KiCad kept
right are left as they are.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.freerouting import _restore_via_drills, _ses_via_drills, _via_ids  # noqa: E402

SES_LIBRARY = """
    (library_out
      (padstack "Via[0-5]_500:300_um"
        (shape (circle F.Cu 5000 0 0))
        (attach off)
      )
      (padstack "Via[0-5]_800:400_um"
        (shape (circle F.Cu 8000 0 0))
        (attach off)
      )
    )
"""


@pytest.mark.unit
def test_padstack_names_give_diameter_and_drill():
    assert _ses_via_drills(SES_LIBRARY) == {500_000: 300_000, 800_000: 400_000}


@pytest.mark.unit
def test_a_diameter_with_two_drills_is_ambiguous():
    text = SES_LIBRARY + '(padstack "Via[0-1]_500:250_um" (shape (circle F.Cu 5000 0 0)))'
    assert _ses_via_drills(text)[500_000] is None


@pytest.mark.unit
def test_names_not_in_kicads_form_are_ignored():
    assert _ses_via_drills('(padstack "MyVia" (shape (circle F.Cu 5000 0 0)))') == {}
    assert _ses_via_drills("") == {}


class _Uuid:
    def __init__(self, s):
        self.s = s

    def AsString(self):
        return self.s


class _Via:
    def __init__(self, uid, dia, drill):
        self.m_Uuid = _Uuid(uid)
        self.dia, self.drill = dia, drill

    def GetClass(self):
        return "PCB_VIA"

    def GetWidth(self, *layer):
        return self.dia

    def GetDrillValue(self):
        return self.drill

    def SetDrill(self, v):
        self.drill = v


class _Track:
    def GetClass(self):
        return "PCB_TRACK"


class _Board:
    def __init__(self, items):
        self.items = items

    def GetTracks(self):
        return self.items


class _Pcbnew:
    F_Cu = 0


@pytest.mark.unit
def test_imported_via_gets_its_padstack_drill_back():
    kept = _Via("kept", 500_000, 400_000)  # was on the board before: left alone
    imported = _Via("new", 500_000, 400_000)  # the import gave it the netclass drill
    right = _Via("new2", 800_000, 400_000)  # already right
    board = _Board([kept, imported, right, _Track()])
    report = _restore_via_drills(board, SES_LIBRARY, {"kept"}, _Pcbnew)
    assert imported.drill == 300_000
    assert kept.drill == 400_000 and right.drill == 400_000
    assert report == {"count": 1, "changes": {"0.5/0.4 -> 0.5/0.3 mm": 1}}


@pytest.mark.unit
def test_nothing_changes_without_the_before_list():
    via = _Via("new", 500_000, 400_000)
    report = _restore_via_drills(_Board([via]), SES_LIBRARY, None, _Pcbnew)
    assert via.drill == 400_000 and report["count"] == 0


@pytest.mark.unit
def test_ambiguous_or_unknown_diameters_are_left_alone():
    text = SES_LIBRARY + '(padstack "Via[0-1]_500:250_um" (shape (circle F.Cu 5000 0 0)))'
    a = _Via("a", 500_000, 400_000)
    b = _Via("b", 600_000, 400_000)
    _restore_via_drills(_Board([a, b]), text, set(), _Pcbnew)
    assert a.drill == 400_000 and b.drill == 400_000


@pytest.mark.unit
def test_via_ids_that_cannot_be_read_skip_the_restore():
    class NoUuid:
        def GetClass(self):
            return "PCB_VIA"

    assert _via_ids(_Board([NoUuid()])) is None


SES = """(session t.ses
  (base_design t.dsn)
  (placement (resolution um 10))
  (was_is)
  (routes
    (resolution um 10)
    (parser (host_cad "KiCad's Pcbnew") (host_version "10"))
    (library_out
      (padstack "Via[0-1]_500:300_um"
        (shape (circle F.Cu 5000 0 0))
        (shape (circle B.Cu 5000 0 0))
        (attach off)
      )
    )
    (network_out
      (net "VDRILL_BIG"
        (via "Via[0-1]_500:300_um" 100000 -100000)
      )
    )
  )
)
"""


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_real_import_loses_a_drill_equal_to_the_default_class_and_the_restore_fixes_it(tmp_path):
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1 under KiCad's Python")
    import pcbnew

    board = pcbnew.BOARD()
    settings = board.GetDesignSettings().m_NetSettings
    if not hasattr(settings, "SetNetclassPatternAssignment"):
        pytest.skip("netclass patterns need KiCad 9+")
    nc = pcbnew.NETCLASS("VDRILL_BIG")
    nc.SetViaDiameter(800_000)
    nc.SetViaDrill(400_000)
    settings.SetNetclass("VDRILL_BIG", nc)
    settings.SetNetclassPatternAssignment("VDRILL_BIG", "VDRILL_BIG")
    board.Add(pcbnew.NETINFO_ITEM(board, "VDRILL_BIG"))
    if hasattr(settings, "ClearAllCaches"):
        settings.ClearAllCaches()
    # A loaded board has its nets bound to their classes; a fresh BOARD() needs the sync, or the
    # net stays in Default and the import takes Default's drill instead (which hides the fault).
    board.SynchronizeNetsAndNetClasses(False)
    assert board.FindNet("VDRILL_BIG").GetNetClassName() == "VDRILL_BIG"
    ses = tmp_path / "t.ses"
    ses.write_text(SES)

    before = _via_ids(board)
    assert pcbnew.ImportSpecctraSES(board, str(ses))
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    assert len(vias) == 1
    via = vias[0]
    assert via.GetWidth(pcbnew.F_Cu) == 500_000
    # KiCad 10.0.8: the padstack's 0.3 drill equals the Default class's (a fresh board's Default via
    # drill is 0.3), so makeVIA stores it as undefined and it resolves through the net's class (0.4).
    # If a later KiCad compares against the net's own class instead, this fails, and the restore is
    # no longer needed.
    assert via.GetDrillValue() == 400_000

    report = _restore_via_drills(board, SES, before, pcbnew)
    assert via.GetDrillValue() == 300_000
    assert report["count"] == 1


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_real_import_keeps_a_drill_that_is_not_the_default_class_one(tmp_path):
    """The narrow trigger, from the other side: a 0.5/0.25 padstack (0.25 is not the Default class's
    0.3) comes through the import with its own drill, on the same big-class net, and the restore
    changes nothing."""
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1 under KiCad's Python")
    import pcbnew

    board = pcbnew.BOARD()
    settings = board.GetDesignSettings().m_NetSettings
    if not hasattr(settings, "SetNetclassPatternAssignment"):
        pytest.skip("netclass patterns need KiCad 9+")
    nc = pcbnew.NETCLASS("VDRILL_BIG")
    nc.SetViaDiameter(800_000)
    nc.SetViaDrill(400_000)
    settings.SetNetclass("VDRILL_BIG", nc)
    settings.SetNetclassPatternAssignment("VDRILL_BIG", "VDRILL_BIG")
    board.Add(pcbnew.NETINFO_ITEM(board, "VDRILL_BIG"))
    if hasattr(settings, "ClearAllCaches"):
        settings.ClearAllCaches()
    board.SynchronizeNetsAndNetClasses(False)
    assert board.FindNet("VDRILL_BIG").GetNetClassName() == "VDRILL_BIG"
    ses_text = SES.replace("500:300_um", "500:250_um")
    assert ses_text != SES
    ses = tmp_path / "t.ses"
    ses.write_text(ses_text)

    before = _via_ids(board)
    assert pcbnew.ImportSpecctraSES(board, str(ses))
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    assert len(vias) == 1
    assert vias[0].GetDrillValue() == 250_000  # kept: not the Default class's drill

    report = _restore_via_drills(board, ses_text, before, pcbnew)
    assert vias[0].GetDrillValue() == 250_000
    assert report["count"] == 0
