"""Guards on sync_schematic_to_board's replaceFootprints / deleteUnusedFootprints.

- A footprint is matched to its schematic symbol by symbol path (UUID) before
  reference, as KiCad does. After a re-annotation (R203 -> R299, same symbol)
  the footprint is renamed in place; deleteUnusedFootprints must never delete a
  footprint whose symbol UUID matches a netlist component.
- Both options are refused while the session is pinned to IPC (the board is
  open in KiCad), except under dryRun.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

BOARD_ONLY = 1 << 3


class _Footprint:
    def __init__(self, ref, path="", attrs=0, locked=False):
        self.ref, self.path, self.attrs, self.locked = ref, path, attrs, locked

    def GetReference(self):
        return self.ref

    def SetReference(self, ref):
        self.ref = ref

    def GetPath(self):
        return SimpleNamespace(AsString=lambda: self.path)

    def GetAttributes(self):
        return self.attrs

    def IsLocked(self):
        return self.locked


class _Board:
    def __init__(self, fps):
        self.fps = list(fps)
        self.deleted = []

    def GetFootprints(self):
        return self.fps

    def Delete(self, fp):
        self.fps.remove(fp)
        self.deleted.append(fp.ref)


def _handlers():
    from commands.schematic_handlers import SchematicHandlersMixin

    return SchematicHandlersMixin


COMPONENTS = [
    {"reference": "R299", "path": "/sheet-a/sym-r203"},  # R203 re-annotated to R299
    {"reference": "R1", "path": "/sheet-a/sym-r1"},
    {"reference": "U2", "path": "/sheet-b/sym-u"},  # a reused sheet: same symbol UUID,
    {"reference": "U3", "path": "/sheet-c/sym-u"},  # two instances, two footprints
]


@pytest.mark.unit
def test_rename_follows_the_symbol_path_not_the_reference():
    fps = [
        _Footprint("R203", "/sheet-a/sym-r203"),
        _Footprint("R1", "/sheet-a/sym-r1"),
        _Footprint("U3", "/sheet-b/sym-u"),  # swapped instances of a reused sheet
        _Footprint("U2", "/sheet-c/sym-u"),
        _Footprint("MH1"),  # hand-placed, no symbol link
    ]
    renamed = _handlers()._rename_footprints_by_symbol_path(_Board(fps), COMPONENTS)
    assert renamed == ["R203 -> R299", "U2 -> U3", "U3 -> U2"]
    assert [fp.ref for fp in fps] == ["R299", "R1", "U2", "U3", "MH1"]


@pytest.mark.unit
def test_delete_never_removes_a_footprint_whose_symbol_uuid_is_in_the_netlist():
    """The re-annotation case with the rename step skipped: R203's reference is
    not in the netlist, but its symbol UUID is R299's, so it stays."""
    fps = [
        _Footprint("R203", "/sheet-a/sym-r203"),
        _Footprint("R1", "/sheet-a/sym-r1"),
        _Footprint("R9", "/sheet-a/sym-gone"),  # symbol deleted from the schematic
        _Footprint("R10"),  # hand-placed, no symbol: unused
        _Footprint("MH1", attrs=BOARD_ONLY),
        _Footprint("R11", locked=True),
    ]
    board = _Board(fps)
    with patch("commands.schematic_handlers.pcbnew", SimpleNamespace(FP_BOARD_ONLY=BOARD_ONLY)):
        deleted, kept = _handlers()._delete_footprints_without_symbols(board, COMPONENTS)
    assert deleted == ["R10", "R9"]
    assert board.deleted == ["R9", "R10"]
    assert {k["reference"]: k["reason"] for k in kept} == {
        "R203": "its symbol path is schematic symbol R299's; not deleted",
        "R11": "locked; not deleted",
    }
    assert [fp.ref for fp in board.fps] == ["R203", "R1", "MH1", "R11"]


@pytest.mark.unit
def test_delete_removes_a_deleted_reused_sheet_instance():
    """A reused sheet: U2 (/sheet-b) and U3 (/sheet-c) share symbol UUID sym-u.
    Sheet instance C is deleted from the schematic. U3's footprint must go:
    the only component with its UUID is U2, and U2 has its own footprint at
    /sheet-b/sym-u. (Keyed on the UUID alone, U3 was kept as "U2's part".)"""
    components = [c for c in COMPONENTS if c["reference"] != "U3"]
    fps = [_Footprint("U2", "/sheet-b/sym-u"), _Footprint("U3", "/sheet-c/sym-u")]
    board = _Board(fps)
    with patch("commands.schematic_handlers.pcbnew", SimpleNamespace(FP_BOARD_ONLY=BOARD_ONLY)):
        deleted, kept = _handlers()._delete_footprints_without_symbols(board, components)
    assert deleted == ["U3"]
    assert kept == []
    assert [fp.ref for fp in board.fps] == ["U2"]


@pytest.mark.unit
def test_delete_keeps_a_stale_path_footprint_whose_symbol_is_unplaced():
    """The case the UUID guard is for: the footprint's path is stale (sheet
    instance re-created, /sheet-old), its reference is not in the netlist,
    and the component with its symbol UUID (U5 at /sheet-new) has no
    footprint on the board. It stays, and the reason names that component."""
    components = [{"reference": "U5", "path": "/sheet-new/sym-v"}]
    fps = [_Footprint("U4", "/sheet-old/sym-v")]
    board = _Board(fps)
    with patch("commands.schematic_handlers.pcbnew", SimpleNamespace(FP_BOARD_ONLY=BOARD_ONLY)):
        deleted, kept = _handlers()._delete_footprints_without_symbols(board, components)
    assert deleted == []
    assert kept == [
        {
            "reference": "U4",
            "reason": "its symbol UUID matches schematic symbol U5 (/sheet-new/sym-v), "
            "which has no footprint at that path; not deleted",
        }
    ]


def _make_iface(session_backend: str) -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    iface.board = None
    iface.session_backend = session_backend
    iface._board_disk_signature = None
    return iface


@pytest.mark.unit
@pytest.mark.parametrize(
    "params",
    [
        {"replaceFootprints": True},
        {"deleteUnusedFootprints": True},
        {"replaceFootprints": True, "deleteUnusedFootprints": True},
    ],
)
def test_replace_and_delete_are_refused_while_pinned_to_ipc(tmp_path, params):
    iface = _make_iface("ipc")
    iface.board = MagicMock(name="board")
    iface._safe_load_board = lambda p: pytest.fail("must not touch the board")
    result = iface._handle_sync_schematic_to_board(
        {"schematicPath": str(tmp_path / "p.kicad_sch"), "boardPath": str(tmp_path / "p.kicad_pcb")}
        | params
    )
    assert result["success"] is False
    assert "pinned to IPC" in result["message"]
    for name in params:
        assert name in result["message"]


@pytest.mark.unit
def test_dry_run_with_the_options_is_allowed_while_pinned_to_ipc(tmp_path):
    """Nothing is written in a preview, so the GUI cannot lose anything."""
    iface = _make_iface("ipc")
    iface.board = MagicMock(name="board")
    iface._safe_load_board = lambda p: None  # gets past the refusal, then fails to load
    result = iface._handle_sync_schematic_to_board(
        {
            "schematicPath": str(tmp_path / "p.kicad_sch"),
            "boardPath": str(tmp_path / "p.kicad_pcb"),
            "dryRun": True,
            "replaceFootprints": True,
            "deleteUnusedFootprints": True,
        }
    )
    assert "pinned to IPC" not in result["message"]
    assert result["message"].startswith("Could not load board")


@pytest.mark.unit
def test_options_run_on_a_swig_session(tmp_path):
    iface = _make_iface("swig")
    iface.board = MagicMock(name="board")
    iface._safe_load_board = lambda p: None
    result = iface._handle_sync_schematic_to_board(
        {
            "schematicPath": str(tmp_path / "p.kicad_sch"),
            "boardPath": str(tmp_path / "p.kicad_pcb"),
            "deleteUnusedFootprints": True,
        }
    )
    assert "pinned to IPC" not in result["message"]
