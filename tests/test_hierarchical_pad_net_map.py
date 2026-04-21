"""
Tests for _build_hierarchical_pad_net_map in KiCADInterface.

The method walks every .kicad_sch file in a project, collects label positions
(local, global, hierarchical) and wire connectivity, then matches each component
pin to the propagated net name.  It is used by sync_schematic_to_board so that
hierarchical projects — where all components live in sub-sheets — are handled
correctly.

Coverage:
  - Empty schematic → empty maps (TestEmptySchematic)
  - Label placed directly at a pin endpoint → net assigned (TestLabelAtPin)
  - Label reachable through a wire segment → net propagated (TestLabelViaWire)
  - Power symbols (#PWR) excluded from component map (TestPowerSymbols)
  - Components across multiple sub-sheet files all collected (TestMultipleSubsheets)
  - Symbol with non-zero rotation has correct absolute pin positions (TestRotatedSymbol)
"""

import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# ---------------------------------------------------------------------------
# A minimal .kicad_sch snippet with lib_symbols for a 2-pin resistor.
# PinLocator reads lib_symbols via sexpdata (no skip needed for that step),
# so we embed the symbol definition in the real file on disk.
#
# TestLib:R pin layout (relative to symbol origin, rotation = 0):
#   pin "1"  at (-1.27,  0)   → wire connects on the left
#   pin "2"  at ( 1.27,  0)   → wire connects on the right
# ---------------------------------------------------------------------------

_SCH_WITH_TESTLIB_R = textwrap.dedent("""\
    (kicad_sch (version 20231120)
      (lib_symbols
        (symbol "TestLib:R"
          (symbol "TestLib:R_1_1"
            (pin passive line (at -1.27 0 0) (length 0)
              (name "~" (effects (font (size 1.27 1.27))))
              (number "1" (effects (font (size 1.27 1.27))))
            )
            (pin passive line (at 1.27 0 180) (length 0)
              (name "~" (effects (font (size 1.27 1.27))))
              (number "2" (effects (font (size 1.27 1.27))))
            )
          )
        )
      )
    )
""")

_SCH_EMPTY = "(kicad_sch (version 20231120))"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _sym_mock(ref: str, lib_id: str, x: float, y: float, rotation: float = 0) -> MagicMock:
    """Minimal mock of a skip symbol instance."""
    m = MagicMock()
    m.property.Reference.value = ref
    m.property.Value.value = "~"
    m.lib_id.value = lib_id
    m.at.value = [x, y, rotation]
    return m


def _lbl_mock(name: str, x: float, y: float) -> MagicMock:
    """Minimal mock of a skip label (any type)."""
    m = MagicMock()
    m.value = name
    m.at.value = [x, y, 0]
    return m


def _wire_mock(x1: float, y1: float, x2: float, y2: float) -> MagicMock:
    """Minimal mock of a skip wire with two endpoints."""
    m = MagicMock()
    p1 = MagicMock()
    p1.value = [x1, y1]
    p2 = MagicMock()
    p2.value = [x2, y2]
    m.pts.xy = [p1, p2]
    return m


def _sch_mock(
    symbols=(),
    labels=(),
    global_labels=(),
    hier_labels=(),
    wires=(),
) -> MagicMock:
    """Build a mock skip.Schematic with the given collections."""
    m = MagicMock()
    m.symbol = list(symbols)
    m.label = list(labels)
    m.global_label = list(global_labels)
    m.hierarchical_label = list(hier_labels)
    m.wire = list(wires)
    return m


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        return KiCADInterface.__new__(KiCADInterface)


@pytest.fixture()
def iface() -> Any:
    return _make_iface()


# ---------------------------------------------------------------------------
# Helper: call _build_hierarchical_pad_net_map with both skip.Schematic
# entry-points patched (walker import + PinLocator module-level import).
# ---------------------------------------------------------------------------


def _call(iface: Any, sch_file: Path, mock_sch: MagicMock):
    with (
        patch("skip.Schematic", return_value=mock_sch),
        patch("commands.pin_locator.Schematic", return_value=mock_sch),
    ):
        return iface._build_hierarchical_pad_net_map(str(sch_file))


# ===========================================================================
# TestEmptySchematic
# ===========================================================================


@pytest.mark.unit
class TestEmptySchematic:
    def test_empty_file_returns_empty_maps(self, iface, tmp_path):
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_EMPTY)
        pad_net_map, net_names = _call(iface, sch, _sch_mock())
        assert pad_net_map == {}
        assert net_names == set()

    def test_no_symbols_returns_empty_map(self, iface, tmp_path):
        """Labels without any symbols produce net_names but empty pad_net_map."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_EMPTY)
        mock_sch = _sch_mock(global_labels=[_lbl_mock("FLOATING", 0, 0)])
        pad_net_map, net_names = _call(iface, sch, mock_sch)
        assert pad_net_map == {}
        assert "FLOATING" in net_names


# ===========================================================================
# TestLabelAtPin
# ===========================================================================


@pytest.mark.unit
class TestLabelAtPin:
    """Label placed exactly at a pin endpoint is assigned to that pin."""

    def test_global_label_pin1(self, iface, tmp_path):
        """Global label at pin-1 position → (R1, 1) in map."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        # R1 at (10, 10); pin 1 abs = (10 − 1.27, 10) = (8.73, 10)
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("VCC", 8.73, 10.0)],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "VCC"
        assert "VCC" in net_names

    def test_global_label_pin2(self, iface, tmp_path):
        """Global label at pin-2 position → (R1, 2) in map."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        # pin 2 abs = (10 + 1.27, 10) = (11.27, 10)
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("GND", 11.27, 10.0)],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "2")) == "GND"
        assert "GND" in net_names

    def test_both_pins_mapped(self, iface, tmp_path):
        """Labels at both pin positions → both (ref, pin) keys present."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            global_labels=[
                _lbl_mock("NET_A", 8.73, 10.0),
                _lbl_mock("NET_B", 11.27, 10.0),
            ],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "NET_A"
        assert pad_net_map.get(("R1", "2")) == "NET_B"

    def test_local_label_also_works(self, iface, tmp_path):
        """Local (net) labels are treated identically to global labels."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            labels=[_lbl_mock("LOCAL_NET", 8.73, 10.0)],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "LOCAL_NET"

    def test_hierarchical_label_also_works(self, iface, tmp_path):
        """Hierarchical labels are treated identically to global labels."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            hier_labels=[_lbl_mock("HIER_NET", 8.73, 10.0)],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "HIER_NET"


# ===========================================================================
# TestLabelViaWire
# ===========================================================================


@pytest.mark.unit
class TestLabelViaWire:
    """Net name propagates through wire segments to reach pin endpoints."""

    def test_label_one_hop_away(self, iface, tmp_path):
        """Label at wire start, wire end at pin → net assigned."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        # pin 1 at (8.73, 10); label at (5.0, 10); wire (5.0,10)→(8.73,10)
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("WIRED_NET", 5.0, 10.0)],
            wires=[_wire_mock(5.0, 10.0, 8.73, 10.0)],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "WIRED_NET"

    def test_label_two_hops_away(self, iface, tmp_path):
        """Net propagates through two chained wire segments."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        # label at (3.0, 10); wire1: 3→6; wire2: 6→8.73 → pin 1
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("FAR_NET", 3.0, 10.0)],
            wires=[
                _wire_mock(3.0, 10.0, 6.0, 10.0),
                _wire_mock(6.0, 10.0, 8.73, 10.0),
            ],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "FAR_NET"

    def test_unconnected_pin_absent_from_map(self, iface, tmp_path):
        """A pin with no label and no wire to a label is absent from pad_net_map."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        # label only at pin 1; pin 2 has nothing
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("NET_A", 8.73, 10.0)],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert ("R1", "2") not in pad_net_map


# ===========================================================================
# TestPowerSymbols
# ===========================================================================


@pytest.mark.unit
class TestPowerSymbols:
    def test_power_ref_not_in_component_map(self, iface, tmp_path):
        """Symbols starting with '#' must not produce pad_net_map entries."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_EMPTY)
        pwr = _sym_mock("#PWR01", "power:GND", 0.0, 0.0)
        pwr.property.Value.value = "GND"
        mock_sch = _sch_mock(symbols=[pwr])
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert not any(ref.startswith("#") for ref, _ in pad_net_map)

    def test_flag_ref_not_in_component_map(self, iface, tmp_path):
        """Symbols starting with '#FLG' must not produce pad_net_map entries."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_EMPTY)
        flg = _sym_mock("#FLG00", "power:PWR_FLAG", 0.0, 0.0)
        flg.property.Value.value = "PWR_FLAG"
        mock_sch = _sch_mock(symbols=[flg])
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert not any(ref.startswith("#") for ref, _ in pad_net_map)


# ===========================================================================
# TestMultipleSubsheets
# ===========================================================================


@pytest.mark.unit
class TestMultipleSubsheets:
    def test_components_in_subsheet_collected(self, iface, tmp_path):
        """A component in a sub-sheet is included in the returned map."""
        top = tmp_path / "top.kicad_sch"
        top.write_text(_SCH_EMPTY)
        sub_dir = tmp_path / "sheets"
        sub_dir.mkdir()
        sub = sub_dir / "component_sheet.kicad_sch"
        sub.write_text(_SCH_WITH_TESTLIB_R)

        top_mock = _sch_mock()  # top sheet has no components
        sub_mock = _sch_mock(
            symbols=[_sym_mock("R2", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("SUB_VCC", 8.73, 10.0)],
        )

        def _factory(path: str) -> MagicMock:
            from pathlib import Path as _P
            return sub_mock if _P(path).name == "component_sheet.kicad_sch" else top_mock

        with (
            patch("skip.Schematic", side_effect=_factory),
            patch("commands.pin_locator.Schematic", side_effect=_factory),
        ):
            pad_net_map, net_names = iface._build_hierarchical_pad_net_map(str(top))

        assert pad_net_map.get(("R2", "1")) == "SUB_VCC"
        assert "SUB_VCC" in net_names

    def test_top_and_sub_components_merged(self, iface, tmp_path):
        """Components from both top-level and sub-sheet appear in the same map."""
        top = tmp_path / "top.kicad_sch"
        top.write_text(_SCH_WITH_TESTLIB_R)
        sub_dir = tmp_path / "sheets"
        sub_dir.mkdir()
        sub = sub_dir / "component_sheet.kicad_sch"
        sub.write_text(_SCH_WITH_TESTLIB_R)

        top_mock = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("TOP_NET", 8.73, 10.0)],
        )
        sub_mock = _sch_mock(
            symbols=[_sym_mock("R2", "TestLib:R", 10.0, 10.0)],
            global_labels=[_lbl_mock("SUB_NET", 8.73, 10.0)],
        )

        def _factory(path: str) -> MagicMock:
            from pathlib import Path as _P
            return sub_mock if _P(path).name == "component_sheet.kicad_sch" else top_mock

        with (
            patch("skip.Schematic", side_effect=_factory),
            patch("commands.pin_locator.Schematic", side_effect=_factory),
        ):
            pad_net_map, _ = iface._build_hierarchical_pad_net_map(str(top))

        assert pad_net_map.get(("R1", "1")) == "TOP_NET"
        assert pad_net_map.get(("R2", "1")) == "SUB_NET"


# ===========================================================================
# TestRotatedSymbol
# ===========================================================================


@pytest.mark.unit
class TestRotatedSymbol:
    def test_90_degree_rotation(self, iface, tmp_path):
        """A 90° CCW rotation maps pin (-1.27, 0) → (0, -1.27) in local coords."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_SCH_WITH_TESTLIB_R)
        # R1 at (10, 10), rotation=90°
        # pin 1 (-1.27, 0) rotated 90° CCW → (0, -1.27) → abs (10.0, 8.73)
        # pin 2 ( 1.27, 0) rotated 90° CCW → (0,  1.27) → abs (10.0, 11.27)
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0, rotation=90)],
            global_labels=[
                _lbl_mock("UP_NET", 10.0, 8.73),
                _lbl_mock("DN_NET", 10.0, 11.27),
            ],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "UP_NET"
        assert pad_net_map.get(("R1", "2")) == "DN_NET"
