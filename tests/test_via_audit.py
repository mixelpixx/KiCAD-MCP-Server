"""audit_via_nets: compare every via's net with a reference board.

The unit tests pair synthetic vias. The real-pcbnew tests save a board, change
a via's net the way KiCad did on save, and check the audit names it, against
both a reference file and a git revision.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from utils.via_audit import Via, compare_vias  # noqa: E402

MM = 1_000_000


def _via(uuid, x, y, net, top="F.Cu", bottom="B.Cu"):
    return Via(uuid=uuid, x=x * MM, y=y * MM, top=top, bottom=bottom, net=net, drill=300_000)


def test_net_change_matched_by_uuid():
    ref = [_via("a", 1, 1, "GND"), _via("b", 2, 2, "VBAT")]
    cur = [_via("a", 1, 1, "ISENSE_ADC"), _via("b", 2, 2, "VBAT")]
    r = compare_vias(ref, cur)
    assert r["net_changed_count"] == 1
    c = r["net_changed"][0]
    assert (c["uuid"], c["reference_net"], c["board_net"], c["matched_by"]) == (
        "a",
        "GND",
        "ISENSE_ADC",
        "uuid",
    )
    assert c["position_mm"] == [1.0, 1.0]
    assert r["net_transitions"] == {"GND -> ISENSE_ADC": 1}
    assert r["vias_compared"] == 2 and r["added_count"] == r["removed_count"] == 0


def test_new_uuids_fall_back_to_position_and_layers():
    # An autorouter import can give every via a new UUID.
    ref = [_via("a", 1, 1, "VBAT"), _via("b", 5, 5, "VBAT")]
    cur = [_via("x", 1, 1, "GND"), _via("y", 5, 5, "VBAT")]
    r = compare_vias(ref, cur)
    assert r["vias_compared"] == 2
    assert r["net_transitions"] == {"VBAT -> GND": 1}
    assert r["net_changed"][0]["matched_by"] == "position"


def test_layer_pair_must_match_for_a_position_match():
    ref = [_via("a", 1, 1, "GND", "F.Cu", "In1.Cu")]
    cur = [_via("x", 1, 1, "GND", "F.Cu", "B.Cu")]
    r = compare_vias(ref, cur)
    assert r["vias_compared"] == 0
    assert r["added_count"] == 1 and r["removed_count"] == 1


def test_added_removed_moved_and_unnetted():
    ref = [_via("a", 1, 1, "GND"), _via("gone", 9, 9, "VBAT"), _via("m", 3, 3, "")]
    cur = [_via("a", 1, 1, "GND"), _via("new", 7, 7, "VBAT"), _via("m", 4, 3, "")]
    r = compare_vias(ref, cur)
    assert r["net_changed_count"] == 0
    assert [v["uuid"] for v in r["added"]] == ["new"]
    assert [v["uuid"] for v in r["removed"]] == ["gone"]
    assert r["moved"][0]["moved_from_mm"] == [3.0, 3.0]


def test_stacked_vias_at_one_point_pair_one_to_one():
    ref = [_via("a", 1, 1, "GND"), _via("b", 1, 1, "GND")]
    cur = [_via("x", 1, 1, "GND"), _via("y", 1, 1, "VBAT")]
    r = compare_vias(ref, cur)
    assert r["vias_compared"] == 2 and r["added_count"] == r["removed_count"] == 0
    assert r["net_transitions"] == {"GND -> VBAT": 1}


# --- real pcbnew ---------------------------------------------------------------


def _require_pcbnew():
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1")


def _board(path: Path):
    """Save a board with three vias: two GND, one VBAT. Returns the via UUIDs."""
    import pcbnew

    board = pcbnew.BOARD()
    nets = {}
    for name in ("GND", "VBAT", "ISENSE_ADC"):
        nets[name] = pcbnew.NETINFO_ITEM(board, name)
        board.Add(nets[name])
    uuids = []
    for i, name in enumerate(("GND", "GND", "VBAT")):
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10 + 5 * i), pcbnew.FromMM(10)))
        via.SetWidth(pcbnew.FromMM(0.6))
        via.SetDrill(pcbnew.FromMM(0.3))
        via.SetNet(nets[name])
        board.Add(via)
        uuids.append(via.m_Uuid.AsString())
    pcbnew.SaveBoard(str(path), board)
    return uuids


def _change_net(path: Path, uuid: str, net: str):
    import pcbnew

    board = pcbnew.LoadBoard(str(path))
    target = board.FindNet(net)
    if target is None:  # KiCad 10 does not save a net no item uses
        target = pcbnew.NETINFO_ITEM(board, net)
        board.Add(target)
    for item in board.GetTracks():
        if item.m_Uuid.AsString() == uuid:
            item.SetNet(target)
    pcbnew.SaveBoard(str(path), board)


def _audit(params):
    from commands.design_rules import DesignRuleCommands

    return DesignRuleCommands(None).audit_via_nets(params)


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_audit_against_a_reference_file(tmp_path):
    _require_pcbnew()
    ref = tmp_path / "ref.kicad_pcb"
    uuids = _board(ref)
    cur = tmp_path / "board.kicad_pcb"
    shutil.copy(ref, cur)
    _change_net(cur, uuids[0], "ISENSE_ADC")

    r = _audit({"boardPath": str(cur), "reference": str(ref)})
    assert r["success"], r
    assert r["vias_compared"] == 3
    assert r["net_transitions"] == {"GND -> ISENSE_ADC": 1}
    assert r["net_changed"][0]["uuid"] == uuids[0]
    assert r["message"].startswith("1 via(s) changed net")


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_audit_against_a_git_revision(tmp_path):
    _require_pcbnew()
    if not shutil.which("git"):
        pytest.skip("needs git")
    repo = tmp_path / "repo"
    (repo / "hw").mkdir(parents=True)
    board = repo / "hw" / "board.kicad_pcb"
    uuids = _board(board)
    for args in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "good"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    _change_net(board, uuids[2], "GND")

    r = _audit({"boardPath": str(board), "reference": "HEAD"})
    assert r["success"], r
    assert r["reference"] == "git HEAD:hw/board.kicad_pcb"
    assert r["net_transitions"] == {"VBAT -> GND": 1}

    clean = _audit({"boardPath": str(board), "reference": str(board)})
    assert clean["net_changed_count"] == 0
    assert clean["message"].startswith("0 via(s) changed net")


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_unreadable_reference_fails_with_the_reason(tmp_path):
    _require_pcbnew()
    board = tmp_path / "board.kicad_pcb"
    _board(board)
    r = _audit({"boardPath": str(board), "reference": "HEAD"})
    assert not r["success"]
    assert r["message"].startswith("Failed")
    assert "not in a git repository" in r["message"] or "git could not read" in r["message"]

    assert not _audit({"boardPath": str(board)})["success"]  # reference is required
