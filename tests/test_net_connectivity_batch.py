"""Batched net connectivity (#394): same answers as one net at a time, and no
state that outlives a request.

The fixture is a two-sheet hierarchy with a two-unit part (whose units must not
leak pins into each other's nets, #293), local labels, a hierarchical label and
power-port symbols. Expected pins come from the geometry, worked out by hand:

    root: U1 unit 1 pin 3 at (107.62, 100) --wire-- R1 pin 1 at (116.19, 100)
          U1 unit 2 pin 7 at (107.62, 150) --wire-- R2 pin 1 at (116.19, 150)
          label OUT_A at U1.3, label OUT_B at U1.7
          GND power ports on R1 pin 2 (123.81, 100) and R2 pin 2 (123.81, 150)
    child: hierarchical label OUT_A at (60, 50) --wire-- R3 pin 1 at (66.19, 50)
           GND power port on R3 pin 2 (73.81, 50)

(Device:R pins sit at library (0, +/-3.81); rotated 90 degrees a pin (px, py)
lands at (x - py, y - px).)
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import commands.wire_connectivity as wc  # noqa: E402
from commands.pin_locator import PinLocator  # noqa: E402
from commands.schematic import SchematicManager  # noqa: E402

pytestmark = pytest.mark.unit

_U = "00000000-0000-0000-0000-0000000{:05x}"

_LIB_R = """
    (symbol "Device:R" (pin_numbers (hide yes)) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (symbol "R_0_1")
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))
        (pin passive line (at 0 -3.81 90) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27)))))))"""

_LIB_GND = """
    (symbol "power:GND" (power) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "#PWR" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Value" "GND" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (symbol "GND_0_1")
      (symbol "GND_1_1"
        (pin power_in line (at 0 0 270) (length 0)
          (name "GND" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27)))))))"""

_LIB_AMP = """
    (symbol "TEST:DualAmp" (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Value" "DualAmp" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (symbol "DualAmp_1_1"
        (pin output line (at 7.62 0 180) (length 2.54)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "3" (effects (font (size 1.27 1.27))))))
      (symbol "DualAmp_2_1"
        (pin output line (at 7.62 0 180) (length 2.54)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "7" (effects (font (size 1.27 1.27)))))))"""


def _sym(n: int, lib_id: str, ref: str, value: str, x: float, y: float, rot: int, unit=1) -> str:
    return (
        f'  (symbol (lib_id "{lib_id}") (at {x} {y} {rot}) (unit {unit})\n'
        f'    (in_bom yes) (on_board yes) (dnp no) (uuid "{_U.format(n)}")\n'
        f'    (property "Reference" "{ref}" (at {x} {y} 0) (effects (font (size 1.27 1.27))))\n'
        f'    (property "Value" "{value}" (at {x} {y} 0) (effects (font (size 1.27 1.27)))))\n'
    )


def _wire(n: int, x1: float, y1: float, x2: float, y2: float) -> str:
    return (
        f"  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n"
        f'    (stroke (width 0) (type default)) (uuid "{_U.format(n)}"))\n'
    )


def _label(n: int, kind: str, name: str, x: float, y: float) -> str:
    shape = " (shape input)" if kind == "hierarchical_label" else ""
    return (
        f'  ({kind} "{name}"{shape} (at {x} {y} 0)\n'
        f'    (effects (font (size 1.27 1.27))) (uuid "{_U.format(n)}"))\n'
    )


def _root() -> str:
    return (
        '(kicad_sch (version 20250114) (generator "test")\n'
        f'  (uuid "{_U.format(1)}")\n  (paper "A4")\n'
        f"  (lib_symbols{_LIB_AMP}{_LIB_R}{_LIB_GND})\n"
        + _sym(10, "TEST:DualAmp", "U1", "DualAmp", 100, 100, 0, unit=1)
        + _sym(11, "TEST:DualAmp", "U1", "DualAmp", 100, 150, 0, unit=2)
        + _sym(12, "Device:R", "R1", "1k", 120, 100, 90)
        + _sym(13, "Device:R", "R2", "1k", 120, 150, 90)
        + _sym(14, "power:GND", "#PWR01", "GND", 123.81, 100, 0)
        + _sym(15, "power:GND", "#PWR02", "GND", 123.81, 150, 0)
        + _wire(20, 107.62, 100, 116.19, 100)
        + _wire(21, 107.62, 150, 116.19, 150)
        + _label(30, "label", "OUT_A", 107.62, 100)
        + _label(31, "label", "OUT_B", 107.62, 150)
        + "  (sheet (at 150 80) (size 20 20)\n"
        + f'    (uuid "{_U.format(40)}")\n'
        + '    (property "Sheetname" "Child" (at 150 79 0) (effects (font (size 1.27 1.27))))\n'
        + '    (property "Sheetfile" "child.kicad_sch" (at 150 101 0)'
        + " (effects (font (size 1.27 1.27)))))\n"
        + '  (sheet_instances (path "/" (page "1")))\n)\n'
    )


def _child(label_name: str = "OUT_A") -> str:
    return (
        '(kicad_sch (version 20250114) (generator "test")\n'
        f'  (uuid "{_U.format(2)}")\n  (paper "A4")\n'
        f"  (lib_symbols{_LIB_R}{_LIB_GND})\n"
        + _sym(50, "Device:R", "R3", "10k", 70, 50, 90)
        + _sym(51, "power:GND", "#PWR03", "GND", 73.81, 50, 0)
        + _wire(60, 60, 50, 66.19, 50)
        + _label(70, "hierarchical_label", label_name, 60, 50)
        + ")\n"
    )


EXPECTED = {
    "OUT_A": {("U1", "3"), ("R1", "1"), ("R3", "1")},
    "OUT_B": {("U1", "7"), ("R2", "1")},
    "GND": {("R1", "2"), ("R2", "2"), ("R3", "2")},
}


@pytest.fixture()
def design(tmp_path: Path) -> Path:
    (tmp_path / "root.kicad_sch").write_text(_root(), encoding="utf-8")
    (tmp_path / "child.kicad_sch").write_text(_child(), encoding="utf-8")
    return tmp_path / "root.kicad_sch"


def _pins(connections) -> set:
    return {(c["component"], c["pin"]) for c in connections}


def _batched(root: Path) -> dict:
    sch = SchematicManager.load_schematic(str(root))
    result = wc.get_connections_for_nets(sch, str(root), sorted(EXPECTED))
    return {net: _pins(conns) for net, conns in result.items()}


def test_batched_resolution_matches_the_geometry(design: Path) -> None:
    assert _batched(design) == EXPECTED


def test_each_net_alone_equals_the_batched_answer(design: Path) -> None:
    # get_connections_for_net resolves one net per call; anything a batch
    # shares between nets (sheet parse, wire graph, pin index) must not leak
    # one net's pins into another's.
    batched = _batched(design)
    for net in EXPECTED:
        sch = SchematicManager.load_schematic(str(design))
        alone = _pins(wc.get_connections_for_net(sch, str(design), net))
        assert alone == batched[net], net


def test_an_edit_between_calls_is_seen_even_with_the_same_size_and_mtime(design: Path) -> None:
    # The parse cache lives for one call only. A process-wide cache keyed on
    # (mtime_ns, size), as first proposed, would miss this edit: same length,
    # and the mtime is put back.
    assert ("R3", "1") in _batched(design)["OUT_A"]
    child = design.parent / "child.kicad_sch"
    st = os.stat(child)
    child.write_text(_child(label_name="OUT_Z"), encoding="utf-8")
    os.utime(child, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert os.stat(child).st_size == st.st_size

    after = _batched(design)
    assert ("R3", "1") not in after["OUT_A"]
    assert after["OUT_A"] == {("U1", "3"), ("R1", "1")}


def test_no_parse_cache_survives_a_call() -> None:
    assert not hasattr(wc, "_SEXP_CACHE")


def test_pin_memo_is_off_unless_asked_for(design: Path) -> None:
    shared = PinLocator()  # the kind ConnectionManager keeps for the worker's life
    shared.get_all_symbol_pins(design, "R1")
    assert shared._all_pins_cache == {}

    per_request = PinLocator(memoize_pins=True)
    first = per_request.get_all_symbol_pins(design, "R1")
    assert per_request.get_all_symbol_pins(design, "R1") is first
