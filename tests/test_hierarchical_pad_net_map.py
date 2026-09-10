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

_LIB_SYMBOLS_BLOCK = textwrap.dedent("""\
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
        (symbol "TestLib:PWR"
          (symbol "TestLib:PWR_1_1"
            (pin power_in line (at 0 0 90) (length 0)
              (name "~" (effects (font (size 1.27 1.27))))
              (number "1" (effects (font (size 1.27 1.27))))
            )
          )
        )
        (symbol "TestLib:D"
          (symbol "TestLib:D_1_1"
            (pin passive line (at -1.27 0 0) (length 0)
              (name "K" (effects (font (size 1.27 1.27))))
              (number "1" (effects (font (size 1.27 1.27))))
            )
            (pin passive line (at 1.27 0 180) (length 0)
              (name "A" (effects (font (size 1.27 1.27))))
              (number "2" (effects (font (size 1.27 1.27))))
            )
          )
        )
      )
""")

_SCH_WITH_TESTLIB_R = "(kicad_sch (version 20231120)\n" + _LIB_SYMBOLS_BLOCK + ")\n"

_SCH_EMPTY = "(kicad_sch (version 20231120))"


def _build_sch_with_instances(
    instances: "list[tuple[str, str, float, float, float]] | None" = None,
) -> str:
    """Build a .kicad_sch text with TestLib:R lib_symbols + the given symbol instances.

    Each instance tuple: (reference, lib_id, x, y, rotation).

    Required because PinLocator._get_symbol_transform reads the symbol position,
    rotation, and lib_id directly from disk via sexpdata (it does not consult
    the kicad-skip cache that the tests mock for labels/wires).
    """
    parts = ["(kicad_sch (version 20231120)", _LIB_SYMBOLS_BLOCK]
    for i, (ref, lib_id, x, y, rot) in enumerate(instances or [], start=1):
        uuid = f"00000000-0000-0000-0000-{i:012d}"
        parts.append(
            f'  (symbol (lib_id "{lib_id}") (at {x} {y} {rot}) (unit 1)\n'
            f"    (uuid {uuid})\n"
            f'    (property "Reference" "{ref}" (at {x} {y - 2.54} 0))\n'
            f'    (property "Value" "~" (at {x} {y + 2.54} 0))\n'
            f'    (pin "1" (uuid {uuid[:-1]}a))\n'
            f'    (pin "2" (uuid {uuid[:-1]}b))\n'
            f"  )\n"
        )
    parts.append(")\n")
    return "".join(parts)


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


def _pwr_mock(ref: str, value: str, lib_id: str, x: float, y: float) -> MagicMock:
    """Mock of a power-ish symbol (#PWR / #FLG) whose Value carries the net name.

    Distinct from _sym_mock only in that Value is meaningful rather than "~".
    """
    m = MagicMock()
    m.property.Reference.value = ref
    m.property.Value.value = value
    m.lib_id.value = lib_id
    m.at.value = [x, y, 0]
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
# Helper: call _build_hierarchical_pad_net_map with every skip.Schematic
# entry-point patched (walker import, PinLocator module-level import, and
# the guarded SchematicManager loader in commands.schematic).
# ---------------------------------------------------------------------------


def _call(iface: Any, sch_file: Path, mock_sch: MagicMock):
    with (
        patch("skip.Schematic", return_value=mock_sch),
        patch("commands.pin_locator.Schematic", return_value=mock_sch),
        patch("commands.schematic.Schematic", return_value=mock_sch),
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
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
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
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
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
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
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
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            labels=[_lbl_mock("LOCAL_NET", 8.73, 10.0)],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "LOCAL_NET"

    def test_hierarchical_label_also_works(self, iface, tmp_path):
        """Hierarchical labels are treated identically to global labels."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
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
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
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
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
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
        top.write_text(_with_sheet_ref(_SCH_EMPTY, "sheets/component_sheet.kicad_sch"))
        sub_dir = tmp_path / "sheets"
        sub_dir.mkdir()
        sub = sub_dir / "component_sheet.kicad_sch"
        sub.write_text(_build_sch_with_instances([("R2", "TestLib:R", 10.0, 10.0, 0)]))

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
            patch("commands.schematic.Schematic", side_effect=_factory),
        ):
            pad_net_map, net_names = iface._build_hierarchical_pad_net_map(str(top))

        assert pad_net_map.get(("R2", "1")) == "SUB_VCC"
        assert "SUB_VCC" in net_names

    def test_top_and_sub_components_merged(self, iface, tmp_path):
        """Components from both top-level and sub-sheet appear in the same map."""
        top = tmp_path / "top.kicad_sch"
        top.write_text(
            _with_sheet_ref(
                _build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]),
                "sheets/component_sheet.kicad_sch",
            )
        )
        sub_dir = tmp_path / "sheets"
        sub_dir.mkdir()
        sub = sub_dir / "component_sheet.kicad_sch"
        sub.write_text(_build_sch_with_instances([("R2", "TestLib:R", 10.0, 10.0, 0)]))

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
            patch("commands.schematic.Schematic", side_effect=_factory),
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
        """eeschema rot=90 is CCW in screen Y-down: TRANSFORM(0,1,-1,0).
        Pin 1 lib (-1.27, 0) → internal (-1.27, 0) → (0,1,-1,0) applied = (0, 1.27)
            → world (10.0, 11.27).
        Pin 2 lib ( 1.27, 0) → internal ( 1.27, 0) → (0,1,-1,0) applied = (0, -1.27)
            → world (10.0, 8.73).
        Verified vs kicad-cli netlist on a Device:D rotated 90."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 90)]))
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0, rotation=90)],
            global_labels=[
                _lbl_mock("UP_NET", 10.0, 11.27),
                _lbl_mock("DN_NET", 10.0, 8.73),
            ],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)
        assert pad_net_map.get(("R1", "1")) == "UP_NET"
        assert pad_net_map.get(("R1", "2")) == "DN_NET"


# ===========================================================================
# TestPowerFlagIsNotANet
# ===========================================================================


@pytest.mark.unit
class TestPowerFlagIsNotANet:
    """A PWR_FLAG (#FLG) must never contribute a net name.

    Its Value property is the literal string "PWR_FLAG" — an ERC marker, not a
    net. Treating it as one invented a bogus "PWR_FLAG" net and could propagate
    that name over the real net the flag is wired to.
    """

    def test_pwr_flag_value_does_not_become_a_net(self, iface, tmp_path):
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(
            _build_sch_with_instances(
                [
                    ("R1", "TestLib:R", 10.0, 10.0, 0),
                    ("#PWR01", "TestLib:PWR", 8.73, 10.0, 0),
                    ("#FLG01", "TestLib:PWR", 5.0, 10.0, 0),
                ]
            )
        )
        # #PWR01 pin sits exactly on R1 pin 1; the flag hangs off a wire to it.
        mock_sch = _sch_mock(
            symbols=[
                _sym_mock("R1", "TestLib:R", 10.0, 10.0),
                _pwr_mock("#PWR01", "VCC", "TestLib:PWR", 8.73, 10.0),
                _pwr_mock("#FLG01", "PWR_FLAG", "TestLib:PWR", 5.0, 10.0),
            ],
            wires=[_wire_mock(5.0, 10.0, 8.73, 10.0)],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)

        assert "PWR_FLAG" not in net_names
        # The real rail still resolves, and the flag did not overwrite it.
        assert pad_net_map.get(("R1", "1")) == "VCC"

    def test_pwr_flag_does_not_overwrite_net_across_wire(self, iface, tmp_path):
        """The flag's name must not win the BFS over the rail it is attached to."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(
            _build_sch_with_instances(
                [
                    ("R1", "TestLib:R", 10.0, 10.0, 0),
                    ("#FLG01", "TestLib:PWR", 5.0, 10.0, 0),
                ]
            )
        )
        mock_sch = _sch_mock(
            symbols=[
                _sym_mock("R1", "TestLib:R", 10.0, 10.0),
                _pwr_mock("#FLG01", "PWR_FLAG", "TestLib:PWR", 5.0, 10.0),
            ],
            global_labels=[_lbl_mock("VBUS", 8.73, 10.0)],
            wires=[_wire_mock(5.0, 10.0, 8.73, 10.0)],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)

        assert "PWR_FLAG" not in net_names
        assert pad_net_map.get(("R1", "1")) == "VBUS"


# ===========================================================================
# TestUnlabelledNetGetsAutoName
# ===========================================================================


@pytest.mark.unit
class TestUnlabelledNetGetsAutoName:
    """A wire joining two component pins with no label is still a net.

    KiCad synthesises a name for it during F8 ("Net-(R1-Pad2)"). Without that these
    pads reached the board with no net at all, so the connection was silently
    dropped from the layout and the pads were left unroutable.
    """

    def test_bare_wire_between_two_pins_is_named_and_shared(self, iface, tmp_path):
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(
            _build_sch_with_instances(
                [
                    ("R1", "TestLib:R", 10.0, 10.0, 0),
                    ("R2", "TestLib:R", 20.0, 10.0, 0),
                ]
            )
        )
        # R1 pin2 (11.27, 10) --- wire --- R2 pin1 (18.73, 10). No labels at all.
        mock_sch = _sch_mock(
            symbols=[
                _sym_mock("R1", "TestLib:R", 10.0, 10.0),
                _sym_mock("R2", "TestLib:R", 20.0, 10.0),
            ],
            wires=[_wire_mock(11.27, 10.0, 18.73, 10.0)],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)

        r1_2 = pad_net_map.get(("R1", "2"))
        r2_1 = pad_net_map.get(("R2", "1"))
        assert r1_2 is not None, "unlabelled net was dropped entirely"
        assert r1_2 == r2_1, "the two pads must land on the SAME net"
        assert r1_2.startswith("Net-("), f"expected a KiCad-style auto name, got {r1_2!r}"
        assert r1_2 in net_names

    def test_auto_name_uses_the_pad_number_not_the_pin_name(self, iface, tmp_path):
        """KiCad builds the name from the pad NUMBER even when the pin has a name.

        Checked with kicad-cli 10.0.0: a symbol whose pin 1 is named IN still
        yields Net-(C1-Pad1). D1 pin 2 is named "A" here and must still be Pad2.
        """
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(
            _build_sch_with_instances(
                [
                    ("D1", "TestLib:D", 10.0, 10.0, 0),
                    ("R1", "TestLib:R", 20.0, 10.0, 0),
                ]
            )
        )
        mock_sch = _sch_mock(
            symbols=[
                _sym_mock("D1", "TestLib:D", 10.0, 10.0),
                _sym_mock("R1", "TestLib:R", 20.0, 10.0),
            ],
            wires=[_wire_mock(11.27, 10.0, 18.73, 10.0)],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)

        # "Net-(D1-Pad2)" sorts before "Net-(R1-Pad1)".
        assert pad_net_map.get(("D1", "2")) == "Net-(D1-Pad2)"
        assert pad_net_map.get(("R1", "1")) == "Net-(D1-Pad2)"

    def test_lowest_candidate_name_wins_as_a_plain_string(self, iface, tmp_path):
        """KiCad compares the candidate names as plain strings: R10 beats R2.

        Checked with kicad-cli 10.0.0 (R2 wired to R10 gives Net-(R10-Pad1)).
        """
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(
            _build_sch_with_instances(
                [
                    ("R2", "TestLib:R", 10.0, 10.0, 0),
                    ("R10", "TestLib:R", 20.0, 10.0, 0),
                ]
            )
        )
        mock_sch = _sch_mock(
            symbols=[
                _sym_mock("R2", "TestLib:R", 10.0, 10.0),
                _sym_mock("R10", "TestLib:R", 20.0, 10.0),
            ],
            wires=[_wire_mock(11.27, 10.0, 18.73, 10.0)],
        )
        pad_net_map, _ = _call(iface, sch, mock_sch)

        assert pad_net_map.get(("R2", "2")) == "Net-(R10-Pad1)"
        assert pad_net_map.get(("R10", "1")) == "Net-(R10-Pad1)"

    def test_explicit_label_still_wins_over_auto_name(self, iface, tmp_path):
        """Auto-naming must only fill genuine gaps, never override a real label."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(
            _build_sch_with_instances(
                [
                    ("R1", "TestLib:R", 10.0, 10.0, 0),
                    ("R2", "TestLib:R", 20.0, 10.0, 0),
                ]
            )
        )
        mock_sch = _sch_mock(
            symbols=[
                _sym_mock("R1", "TestLib:R", 10.0, 10.0),
                _sym_mock("R2", "TestLib:R", 20.0, 10.0),
            ],
            global_labels=[_lbl_mock("SIGNAL", 11.27, 10.0)],
            wires=[_wire_mock(11.27, 10.0, 18.73, 10.0)],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)

        assert pad_net_map.get(("R1", "2")) == "SIGNAL"
        assert pad_net_map.get(("R2", "1")) == "SIGNAL"
        assert not any(n.startswith("Net-(") for n in net_names)

    def test_single_pin_stub_is_not_named(self, iface, tmp_path):
        """A wire reaching only one pin is not a connection worth inventing a net for."""
        sch = tmp_path / "top.kicad_sch"
        sch.write_text(_build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)]))
        mock_sch = _sch_mock(
            symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
            wires=[_wire_mock(11.27, 10.0, 15.0, 10.0)],
        )
        pad_net_map, net_names = _call(iface, sch, mock_sch)

        assert pad_net_map == {}
        assert net_names == set()


# ===========================================================================
# TestOnlyTheSheetTreeIsRead
# ===========================================================================

_SHEET_REF = """  (sheet (at 50 50) (size 20 20) (uuid "00000000-0000-0000-0000-00000000aaaa")
    (property "Sheetname" "sub")
    (property "Sheetfile" "sub.kicad_sch")
  )
"""


def _with_sheet_ref(sch_text: str, file_name: str = "sub.kicad_sch") -> str:
    """Append a (sheet ...) reference to *file_name* before the closing paren.

    Since #400 only sheets reachable from the root are read, so a test that
    wants a sub-sheet scanned has to reference it the way KiCad would.
    """
    cut = sch_text.rstrip().rfind(")")
    block = _SHEET_REF.replace('"sub.kicad_sch"', f'"{file_name}"')
    return sch_text[:cut] + block + ")\n"


@pytest.mark.unit
class TestOnlyTheSheetTreeIsRead:
    """Only sheets reachable from the root are part of the design (#400).

    A recursive glob also read KiCad's .history/ snapshots, this server's own
    .mcp-backups/ copies, hand-made backup folders and any stray sheet in the
    directory as live sheets. Whichever sorted last overwrote the live nets,
    and every one of them could inject parts and nets the design no longer
    has. One real board got 25 wrong pad nets that way.
    """

    def test_backups_and_strays_neither_overwrite_nor_inject(self, iface, tmp_path):
        live_r1 = _build_sch_with_instances([("R1", "TestLib:R", 10.0, 10.0, 0)])
        live_r2 = _build_sch_with_instances([("R2", "TestLib:R", 10.0, 10.0, 0)])
        (tmp_path / "top.kicad_sch").write_text(_with_sheet_ref(live_r1))
        (tmp_path / "sub.kicad_sch").write_text(live_r2)
        # Decoys: same file names as the live sheets, plus an unreferenced stray.
        for directory in ("_backup", ".mcp-backups", ".history"):
            (tmp_path / directory).mkdir()
            (tmp_path / directory / "top.kicad_sch").write_text(_with_sheet_ref(live_r1))
            (tmp_path / directory / "sub.kicad_sch").write_text(live_r2)
        (tmp_path / "zz_stray.kicad_sch").write_text(
            _build_sch_with_instances([("R9", "TestLib:R", 10.0, 10.0, 0)])
        )

        def _mock_for(path: str) -> MagicMock:
            from pathlib import Path as _P

            p = _P(path)
            if p.parent == tmp_path and p.name == "top.kicad_sch":
                return _sch_mock(
                    symbols=[_sym_mock("R1", "TestLib:R", 10.0, 10.0)],
                    global_labels=[_lbl_mock("LIVE_A", 8.73, 10.0)],
                )
            if p.parent == tmp_path and p.name == "sub.kicad_sch":
                return _sch_mock(
                    symbols=[_sym_mock("R2", "TestLib:R", 10.0, 10.0)],
                    global_labels=[_lbl_mock("LIVE_B", 8.73, 10.0)],
                )
            if p.name == "zz_stray.kicad_sch":
                return _sch_mock(
                    symbols=[_sym_mock("R9", "TestLib:R", 10.0, 10.0)],
                    global_labels=[_lbl_mock("PHANTOM", 8.73, 10.0)],
                )
            # A backup copy: the same R1/R2 with the nets they had before the edit.
            ref = "R1" if p.name == "top.kicad_sch" else "R2"
            return _sch_mock(
                symbols=[_sym_mock(ref, "TestLib:R", 10.0, 10.0)],
                global_labels=[_lbl_mock("STALE", 8.73, 10.0)],
            )

        opened: list = []

        def _factory(path: str) -> MagicMock:
            opened.append(str(path))
            return _mock_for(str(path))

        sheets: list = []
        with (
            patch("skip.Schematic", side_effect=_factory),
            patch("commands.pin_locator.Schematic", side_effect=_factory),
            patch("commands.schematic.Schematic", side_effect=_factory),
        ):
            pad_net_map, net_names = iface._build_hierarchical_pad_net_map(
                str(tmp_path / "top.kicad_sch"), sheets_out=sheets
            )

        assert [Path(s).name for s in sheets] == ["top.kicad_sch", "sub.kicad_sch"]
        assert all(Path(s).parent == tmp_path for s in sheets)
        decoy_dirs = ("_backup", ".mcp-backups", ".history")
        assert not any(Path(o).parent.name in decoy_dirs for o in opened)
        assert not any(Path(o).name == "zz_stray.kicad_sch" for o in opened)
        assert pad_net_map.get(("R1", "1")) == "LIVE_A"
        assert pad_net_map.get(("R2", "1")) == "LIVE_B"
        assert ("R9", "1") not in pad_net_map
        assert net_names == {"LIVE_A", "LIVE_B"}
