"""Regression tests for #248 — one FootprintLoad per distinct footprint.

Reporter's instrumented data on a 40-component board showed repeated
FootprintLoad into the *same* library costing the same as the first
(Resistor_SMD: first 18 ms, rest-mean 20 ms) — nothing downstream memoized
it, so 13 identical resistors paid for 13 identical disk reads.

_add_missing_footprints_from_schematic now loads each distinct
(library, footprint) once and clones per component.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from utils.board_items import clone_footprint  # noqa: E402


class TestCloneFootprint:
    def test_kicad10_signature_is_tried_first(self):
        fp = MagicMock()
        fp.Duplicate.return_value = MagicMock()  # has SetReference via MagicMock
        clone_footprint(fp)
        fp.Duplicate.assert_called_once_with(False)

    def test_falls_back_to_kicad8_9_signature(self):
        """KiCad 8/9 Duplicate() takes no argument."""
        fp = MagicMock()
        result = MagicMock()

        calls = []

        def duplicate(*args):
            calls.append(args)
            if args:
                raise TypeError("Duplicate() takes 1 positional argument but 2 were given")
            return result

        fp.Duplicate = duplicate
        assert clone_footprint(fp) is result
        assert calls == [(False,), ()]

    def test_casts_when_duplicate_returns_a_bare_board_item(self, monkeypatch):
        """SWIG does not down-cast: Duplicate returns BOARD_ITEM, which has no
        SetReference until passed through Cast_to_FOOTPRINT."""
        import pcbnew

        class BareBoardItem:
            __slots__ = ()

        bare = BareBoardItem()
        casted = MagicMock()
        monkeypatch.setattr(pcbnew, "Cast_to_FOOTPRINT", lambda item: casted, raising=False)

        fp = MagicMock()
        fp.Duplicate.return_value = bare
        assert clone_footprint(fp) is casted

    def test_no_cast_available_returns_duplicate_unchanged(self, monkeypatch):
        import pcbnew

        class BareBoardItem:
            __slots__ = ()

        bare = BareBoardItem()
        monkeypatch.delattr(pcbnew, "Cast_to_FOOTPRINT", raising=False)
        fp = MagicMock()
        fp.Duplicate.return_value = bare
        assert clone_footprint(fp) is bare


class TestLoadIsMemoized:
    """The behaviour #248 is actually about."""

    def _run(self, monkeypatch, footprints):
        """Drive the real loop with N schematic components, return load count."""
        import pcbnew
        from commands.schematic_handlers import SchematicHandlersMixin

        load_calls = []

        def fake_load(library_path, fp_name):
            load_calls.append((library_path, fp_name))
            proto = MagicMock(name=f"proto:{fp_name}")
            # A fresh object per call -- a shared return_value would make the
            # independence assertion below test the mock, not the code.
            proto.Duplicate.side_effect = lambda *_a: MagicMock(name=f"clone:{fp_name}")
            return proto

        monkeypatch.setattr(pcbnew, "FootprintLoad", fake_load)

        handler = SchematicHandlersMixin.__new__(SchematicHandlersMixin)
        components = [{"reference": ref, "footprint": fp, "value": "x"} for ref, fp in footprints]
        monkeypatch.setattr(
            handler, "_extract_components_from_schematic", lambda _p: components, raising=False
        )
        lib_mgr = MagicMock()
        lib_mgr.libraries = {
            "Resistor_SMD": "/libs/Resistor_SMD.pretty",
            "Capacitor_SMD": "/libs/Capacitor_SMD.pretty",
        }
        monkeypatch.setattr(
            handler, "_get_project_library_manager", lambda _d: lib_mgr, raising=False
        )

        board = MagicMock()
        board.GetFootprints.return_value = []
        added, skipped = handler._add_missing_footprints_from_schematic(
            board, str(Path("x") / "t.kicad_sch")
        )
        return load_calls, added, skipped, board

    def test_identical_footprints_load_once(self, monkeypatch):
        """13 identical resistors -> 1 disk read, not 13."""
        fps = [(f"R{i}", "Resistor_SMD:R_0603_1608Metric") for i in range(1, 14)]
        load_calls, added, skipped, board = self._run(monkeypatch, fps)

        assert len(load_calls) == 1, f"expected 1 FootprintLoad, got {len(load_calls)}"
        assert len(added) == 13, "all 13 components must still be added"
        assert board.Add.call_count == 13

    def test_each_distinct_footprint_loads_once(self, monkeypatch):
        fps = [
            ("R1", "Resistor_SMD:R_0603_1608Metric"),
            ("R2", "Resistor_SMD:R_0603_1608Metric"),
            ("R3", "Resistor_SMD:R_0805_2012Metric"),
            ("C1", "Capacitor_SMD:C_0603_1608Metric"),
            ("C2", "Capacitor_SMD:C_0603_1608Metric"),
        ]
        load_calls, added, _, board = self._run(monkeypatch, fps)

        assert len(load_calls) == 3, f"expected 3 distinct loads, got {load_calls}"
        assert len(added) == 5
        assert board.Add.call_count == 5

    def test_every_component_gets_its_own_object(self, monkeypatch):
        """A shared object would mean the last SetReference wins and the board
        ends up with N references to one footprint."""
        fps = [(f"R{i}", "Resistor_SMD:R_0603_1608Metric") for i in range(1, 5)]
        _, _, _, board = self._run(monkeypatch, fps)

        added_objects = [c.args[0] for c in board.Add.call_args_list]
        assert len(set(id(o) for o in added_objects)) == 4, "the same object was added twice"

    def test_prototype_is_never_added_to_the_board(self, monkeypatch):
        """Handing the cached prototype to board.Add() would leave the cache
        holding a board-owned object."""
        fps = [("R1", "Resistor_SMD:R_0603_1608Metric")]
        _, _, _, board = self._run(monkeypatch, fps)

        added = board.Add.call_args_list[0].args[0]
        assert "clone:" in added._mock_name, "the prototype itself was added, not a clone"
