"""Regression tests for #247 — SWIG ownership on board-item deletion.

Background: ``BOARD.Remove()`` transfers C++ ownership of the item to the
Python wrapper (``item.thisown = 1``). Command handlers that removed an item
and then dropped the reference made the interpreter free an object KiCad
still referenced, corrupting SWIG state process-wide — or segfaulting.

Verified against a real KiCad 10.0 install before this fix landed: one
``delete_component`` poisoned the whole process, so the second one raised
``'SwigPyObject' object has no attribute 'thisown'`` and even a pure read
raised ``... has no attribute 'GetPosition'`` — matching the trace in #247.

These tests pin the contract: deletion goes through ``BOARD.Delete()`` (which
leaves ownership in C++), never bare ``Remove()``.
"""

import ast
from pathlib import Path

import pytest
from utils.board_items import delete_board_item

PYTHON_ROOT = Path(__file__).resolve().parents[1] / "python"


class _FakeBoard:
    """Board exposing both APIs, recording which one the caller reached for."""

    def __init__(self, has_delete=True):
        self.deleted = []
        self.removed = []
        if not has_delete:
            # Emulate a build with no Delete() at all.
            del self.__class__.Delete

    def Delete(self, item):
        self.deleted.append(item)

    def Remove(self, item):
        self.removed.append(item)


class _FakeItem:
    def __init__(self):
        self.thisown = True


class TestDeleteBoardItem:
    def test_prefers_delete_so_ownership_stays_in_cpp(self):
        board = _FakeBoard()
        item = _FakeItem()

        delete_board_item(board, item)

        assert board.deleted == [item]
        assert board.removed == [], "Remove() would hand ownership to Python (#247)"

    def test_falls_back_to_remove_plus_disown(self):
        """On a build with no Delete(), ownership must still be disclaimed."""

        class NoDelete:
            def __init__(self):
                self.removed = []

            def Remove(self, item):
                self.removed.append(item)

        board = NoDelete()
        item = _FakeItem()

        delete_board_item(board, item)

        assert board.removed == [item]
        assert item.thisown is False, "Python must not be left owning the C++ item"

    def test_missing_thisown_is_not_an_error(self):
        """A proxy without thisown must not fail the user's delete."""

        class NoDelete:
            def Remove(self, item):
                pass

        class Bare:
            __slots__ = ()

        delete_board_item(NoDelete(), Bare())  # must not raise


class TestNoBareRemoveRemains:
    """The whole bug class, enforced statically.

    delete_component was only one of six call sites — delete_trace and the
    board-outline handlers had the identical defect. A grep-style guard is
    what stops the next one from being reintroduced.
    """

    def _board_remove_calls(self, path: Path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "Remove":
                continue
            # self.board.Remove(...) / board.Remove(...)
            target = func.value
            name = None
            if isinstance(target, ast.Attribute):
                name = target.attr
            elif isinstance(target, ast.Name):
                name = target.id
            if name in {"board", "pcb_board"}:
                hits.append(f"{path.name}:{node.lineno}")
        return hits

    def test_no_command_module_calls_board_remove(self):
        offenders = []
        for path in PYTHON_ROOT.rglob("*.py"):
            if path.name == "board_items.py":
                continue  # the sanctioned fallback lives here
            offenders.extend(self._board_remove_calls(path))

        assert not offenders, (
            "board.Remove() transfers C++ ownership to Python and corrupts SWIG "
            "state when the reference is dropped (#247). Use "
            "utils.board_items.delete_board_item() instead. Offenders: " + ", ".join(offenders)
        )


class TestBoardHealthProbeSeesDeadChildren:
    """The probe blind spot that let #247 go undetected.

    _is_board_healthy() checked BOARD methods only. In the real failure the
    BOARD kept working and only the items it returned were dead, so the probe
    passed and the existing auto-recovery never fired.
    """

    @pytest.fixture
    def interface(self):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)  # no __init__: no pcbnew needed
        iface.board = None
        return iface

    def _board(self, footprints):
        class B:
            def GetDesignSettings(self):
                pass

            def GetBoardEdgesBoundingBox(self):
                pass

            def GetFileName(self):
                return "x.kicad_pcb"

            def GetFootprints(self):
                return footprints

        return B()

    def test_healthy_board_with_live_children(self, interface):
        class LiveFp:
            def GetPosition(self):
                return (0, 0)

        assert interface._is_board_healthy(self._board([LiveFp()])) is True

    def test_healthy_board_with_dead_children_is_unhealthy(self, interface):
        class DeadFp:
            """What a dehydrated proxy looks like: no methods at all."""

            __slots__ = ()

        assert interface._is_board_healthy(self._board([DeadFp()])) is False

    def test_empty_board_is_healthy(self, interface):
        assert interface._is_board_healthy(self._board([])) is True

    def test_board_without_getfootprints_is_not_penalised(self, interface):
        class B:
            def GetDesignSettings(self):
                pass

            def GetBoardEdgesBoundingBox(self):
                pass

            def GetFileName(self):
                return "x.kicad_pcb"

        assert interface._is_board_healthy(B()) is True

    def test_iteration_blowing_up_is_unhealthy(self, interface):
        class B:
            def GetDesignSettings(self):
                pass

            def GetBoardEdgesBoundingBox(self):
                pass

            def GetFileName(self):
                return "x.kicad_pcb"

            def GetFootprints(self):
                raise AttributeError("'SwigPyObject' object has no attribute 'GetFootprints'")

        assert interface._is_board_healthy(B()) is False
