"""
Regression tests for sync_schematic_to_board's footprint-add path.

Before the fix, _handle_sync_schematic_to_board only mutated nets and pad
assignments — it iterated board.GetFootprints() and never added new ones.
A schematic symbol whose Reference was not yet on the PCB was therefore
silently dropped on the floor: no footprint added, no rats nest reaching
the missing component.

These tests cover _add_missing_footprints_from_schematic and its kicad-cli
helper _extract_components_from_schematic.
"""

import sys
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_existing_fp(reference: str) -> MagicMock:
    fp = MagicMock(name=f"existing_fp_{reference}")
    fp.GetReference.return_value = reference
    return fp


def _interface() -> Any:
    from kicad_interface import KiCADInterface

    return KiCADInterface()


# ---------------------------------------------------------------------------
# _add_missing_footprints_from_schematic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddMissingFootprintsFromSchematic:
    """The fix path: walk netlist, add footprints for refs not yet on the board."""

    def _patch_extract(self, components: List[dict]) -> Any:
        return patch.object(
            _interface().__class__,
            "_extract_components_from_schematic",
            return_value=components,
        )

    def test_adds_footprint_for_missing_reference(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        board = MagicMock(name="board")
        board.GetFootprints.return_value = []  # nothing on the board yet

        loaded_module = MagicMock(name="loaded_R0603")
        with (
            patch.object(
                _interface().__class__,
                "_extract_components_from_schematic",
                return_value=[
                    {
                        "reference": "R99",
                        "value": "10k",
                        "footprint": "Resistor_SMD:R_0603_1608Metric",
                    }
                ],
            ),
            patch("commands.schematic_handlers.pcbnew") as mock_pcbnew,
            patch("commands.library.LibraryManager") as mock_lm_cls,
        ):
            mock_pcbnew.FootprintLoad.return_value = loaded_module
            lm = MagicMock()
            lm.libraries = {"Resistor_SMD": "/fake/Resistor_SMD.pretty"}
            mock_lm_cls.return_value = lm

            iface = _interface()
            added, skipped = iface._add_missing_footprints_from_schematic(board, str(sch))

        assert len(added) == 1
        assert added[0]["reference"] == "R99"
        assert added[0]["footprint"] == "Resistor_SMD:R_0603_1608Metric"
        assert skipped == []
        # Footprint was added to the board. Since #248 the loaded footprint is
        # a cached prototype and a CLONE is what gets added — the prototype
        # must never be handed to board.Add(), or the cache would end up
        # holding a board-owned object.
        board.Add.assert_called_once()
        added_object = board.Add.call_args.args[0]
        assert added_object is not loaded_module, "prototype was added instead of a clone"
        assert added_object is loaded_module.Duplicate.return_value
        added_object.SetReference.assert_called_with("R99")
        added_object.SetValue.assert_called_with("10k")

    def test_skips_reference_already_on_board(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        board = MagicMock(name="board")
        board.GetFootprints.return_value = [_make_existing_fp("R1")]

        with (
            patch.object(
                _interface().__class__,
                "_extract_components_from_schematic",
                return_value=[
                    {
                        "reference": "R1",
                        "value": "10k",
                        "footprint": "Resistor_SMD:R_0603_1608Metric",
                    }
                ],
            ),
            patch("commands.schematic_handlers.pcbnew"),
            patch("commands.library.LibraryManager") as mock_lm_cls,
        ):
            lm = MagicMock()
            lm.libraries = {"Resistor_SMD": "/fake/Resistor_SMD.pretty"}
            mock_lm_cls.return_value = lm

            iface = _interface()
            added, skipped = iface._add_missing_footprints_from_schematic(board, str(sch))

        assert added == []
        assert skipped == []
        board.Add.assert_not_called()

    def test_skips_power_symbols(self, tmp_path: Any) -> None:
        """References starting with # (e.g. #PWR, #FLG) have no PCB footprint."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        board = MagicMock(name="board")
        board.GetFootprints.return_value = []

        with (
            patch.object(
                _interface().__class__,
                "_extract_components_from_schematic",
                return_value=[
                    {"reference": "#PWR0001", "value": "GND", "footprint": ""},
                    {"reference": "#FLG0001", "value": "PWR_FLAG", "footprint": ""},
                ],
            ),
            patch("commands.schematic_handlers.pcbnew"),
            patch("commands.library.LibraryManager") as mock_lm_cls,
        ):
            mock_lm_cls.return_value = MagicMock(libraries={})

            iface = _interface()
            added, skipped = iface._add_missing_footprints_from_schematic(board, str(sch))

        assert added == []
        # Power refs are excluded entirely — they don't show up in the skipped
        # diagnostic list either, since "no PCB footprint" is the right answer.
        assert skipped == []
        board.Add.assert_not_called()

    def test_records_skip_reason_for_missing_footprint_property(self, tmp_path: Any) -> None:
        """A schematic symbol with no Footprint property is reported as skipped."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        board = MagicMock(name="board")
        board.GetFootprints.return_value = []

        with (
            patch.object(
                _interface().__class__,
                "_extract_components_from_schematic",
                return_value=[{"reference": "R1", "value": "10k", "footprint": ""}],
            ),
            patch("commands.schematic_handlers.pcbnew"),
            patch("commands.library.LibraryManager") as mock_lm_cls,
        ):
            mock_lm_cls.return_value = MagicMock(libraries={})

            iface = _interface()
            added, skipped = iface._add_missing_footprints_from_schematic(board, str(sch))

        assert added == []
        assert len(skipped) == 1
        assert skipped[0]["reference"] == "R1"
        assert "no Library:Name" in skipped[0]["reason"]

    def test_records_skip_reason_for_unknown_library(self, tmp_path: Any) -> None:
        """If the footprint's library nickname isn't in fp-lib-table, skip with reason."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        board = MagicMock(name="board")
        board.GetFootprints.return_value = []

        with (
            patch.object(
                _interface().__class__,
                "_extract_components_from_schematic",
                return_value=[
                    {
                        "reference": "U1",
                        "value": "MyChip",
                        "footprint": "MyVendor:MyChip_QFN24",
                    }
                ],
            ),
            patch("commands.schematic_handlers.pcbnew"),
            patch("commands.library.LibraryManager") as mock_lm_cls,
        ):
            mock_lm_cls.return_value = MagicMock(libraries={})  # MyVendor not present

            iface = _interface()
            added, skipped = iface._add_missing_footprints_from_schematic(board, str(sch))

        assert added == []
        assert len(skipped) == 1
        assert skipped[0]["reference"] == "U1"
        assert "MyVendor" in skipped[0]["reason"]

    def test_no_op_when_kicad_cli_returns_empty(self, tmp_path: Any) -> None:
        """If the netlist extractor returns nothing, the helper is a no-op."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        board = MagicMock(name="board")
        board.GetFootprints.return_value = []

        with patch.object(
            _interface().__class__,
            "_extract_components_from_schematic",
            return_value=[],
        ):
            iface = _interface()
            added, skipped = iface._add_missing_footprints_from_schematic(board, str(sch))

        assert added == []
        assert skipped == []
        board.Add.assert_not_called()


# ---------------------------------------------------------------------------
# _extract_components_from_schematic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractComponentsFromSchematic:
    """The kicad-cli helper that produces (reference, value, footprint) records."""

    def test_parses_kicad_xml_netlist(self, tmp_path: Any) -> None:
        netlist_xml = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <design />
  <components>
    <comp ref="R1">
      <value>10k</value>
      <footprint>Resistor_SMD:R_0603_1608Metric</footprint>
    </comp>
    <comp ref="C1">
      <value>0.1uF</value>
      <footprint>Capacitor_SMD:C_0603_1608Metric</footprint>
    </comp>
    <comp ref="U1">
      <value>MyChip</value>
      <footprint />
    </comp>
  </components>
  <nets />
</export>
"""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        def fake_run(cmd: Any, **kwargs: Any) -> Any:
            output_idx = cmd.index("--output") + 1
            Path(cmd[output_idx]).write_text(netlist_xml)
            return MagicMock(returncode=0, stderr="", stdout="")

        with (
            patch.object(
                _interface().__class__, "_find_kicad_cli_static", return_value="/fake/kicad-cli"
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            iface = _interface()
            comps = iface._extract_components_from_schematic(str(sch))

        assert len(comps) == 3
        refs = [c["reference"] for c in comps]
        assert refs == ["R1", "C1", "U1"]
        # Empty <footprint /> resolves to ""
        u1 = next(c for c in comps if c["reference"] == "U1")
        assert u1["footprint"] == ""

    def test_returns_empty_when_kicad_cli_missing(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        with patch.object(_interface().__class__, "_find_kicad_cli_static", return_value=None):
            iface = _interface()
            comps = iface._extract_components_from_schematic(str(sch))

        assert comps == []

    def test_returns_empty_when_kicad_cli_fails(self, tmp_path: Any) -> None:
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)\n")

        with (
            patch.object(
                _interface().__class__, "_find_kicad_cli_static", return_value="/fake/kicad-cli"
            ),
            patch(
                "subprocess.run",
                return_value=MagicMock(returncode=1, stderr="boom", stdout=""),
            ),
        ):
            iface = _interface()
            comps = iface._extract_components_from_schematic(str(sch))

        assert comps == []


@pytest.mark.unit
class TestRefdesMismatchDoesNotDuplicate:
    """#250: a re-annotated schematic must not duplicate the whole board.

    sync matched purely on reference strings, so when schematic and PCB
    reference designators diverged (re-annotation after layout), every
    component looked "missing" and was added again at the origin. The board
    footprint's path (its schematic symbol UUID) identifies the symbol
    regardless of its current name.
    """

    @staticmethod
    def _fp_with_path(reference, symbol_uuid):
        fp = MagicMock(name=f"fp_{reference}")
        fp.GetReference.return_value = reference
        path = MagicMock()
        path.AsString.return_value = f"/{symbol_uuid}"
        fp.GetPath.return_value = path
        return fp

    def _run(self, board, components, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        sch.write_text("(kicad_sch)\n")
        with (
            patch.object(
                _interface().__class__,
                "_extract_components_from_schematic",
                return_value=components,
            ),
            patch("commands.schematic_handlers.pcbnew") as mock_pcbnew,
            patch("commands.library.LibraryManager") as mock_lm_cls,
        ):
            mock_pcbnew.FootprintLoad.return_value = MagicMock(name="proto")
            lm = MagicMock()
            lm.libraries = {"Resistor_SMD": "/fake/Resistor_SMD.pretty"}
            mock_lm_cls.return_value = lm
            iface = _interface()
            return iface._add_missing_footprints_from_schematic(board, str(sch))

    def test_same_symbol_uuid_is_not_added_again(self, tmp_path):
        # Board has R1 bound to symbol uuid AAA; schematic renamed it to R5.
        board = MagicMock(name="board")
        board.GetFootprints.return_value = [self._fp_with_path("R1", "aaa-uuid")]
        added, skipped = self._run(
            board,
            [
                {
                    "reference": "R5",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0603_1608Metric",
                    "uuid": "aaa-uuid",
                }
            ],
            tmp_path,
        )
        assert added == [], "re-annotated symbol must not be re-added"
        assert len(skipped) == 1
        assert "already on board as 'R1'" in skipped[0]["reason"]

    def test_genuinely_new_symbol_is_still_added(self, tmp_path):
        board = MagicMock(name="board")
        board.GetFootprints.return_value = [self._fp_with_path("R1", "aaa-uuid")]
        added, skipped = self._run(
            board,
            [
                {
                    "reference": "R9",
                    "value": "1k",
                    "footprint": "Resistor_SMD:R_0603_1608Metric",
                    "uuid": "bbb-uuid",
                }
            ],
            tmp_path,
        )
        assert len(added) == 1 and added[0]["reference"] == "R9"

    def test_reused_sheet_instances_claim_one_footprint_each(self, tmp_path):
        # Two sheet instances share the symbol uuid; two comps, two boards fps.
        board = MagicMock(name="board")
        board.GetFootprints.return_value = [
            self._fp_with_path("Q101", "shared-uuid"),
            self._fp_with_path("Q201", "shared-uuid"),
        ]
        comps = [
            {"reference": "Q5", "value": "", "footprint": "X:Y", "uuid": "shared-uuid"},
            {"reference": "Q6", "value": "", "footprint": "X:Y", "uuid": "shared-uuid"},
        ]
        added, skipped = self._run(board, comps, tmp_path)
        assert added == []
        assert len(skipped) == 2
        claimed = {s["reason"].split("'")[1] for s in skipped}
        assert claimed == {"Q101", "Q201"}, "each comp claims a distinct footprint"

    def test_reference_match_takes_priority_over_uuid(self, tmp_path):
        # Same ref on both sides: today's behavior (silent skip) is preserved.
        board = MagicMock(name="board")
        board.GetFootprints.return_value = [self._fp_with_path("R1", "aaa-uuid")]
        added, skipped = self._run(
            board,
            [{"reference": "R1", "value": "", "footprint": "X:Y", "uuid": "aaa-uuid"}],
            tmp_path,
        )
        assert added == [] and skipped == []
