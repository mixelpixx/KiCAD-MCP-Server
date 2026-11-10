"""sync_junctions and a wire that ends on the middle of another wire.

KiCad connects such a T only with a junction at the meeting point. KiCad's
editor splits the through-wire there, but a wire written by a tool usually
isn't split, and sync_junctions counted wire ends only: it added no junction
(so KiCad left the T open) and deleted one that was already there (so it cut a
working connection). Both run on every add_wire, delete_wire, move and rotate.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.wire_manager import WireManager  # noqa: E402

FONT = "(effects (font (size 1.27 1.27)))"
LIB = f"""  (lib_symbols
    (symbol "T:R" (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "R" (at 0 2.54 0) {FONT})
      (property "Value" "R" (at 0 -2.54 0) {FONT})
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "R_1_1"
        (pin passive line (at -1.27 0 0) (length 0) (name "~" {FONT}) (number "1" {FONT}))
        (pin passive line (at 1.27 0 180) (length 0) (name "~" {FONT}) (number "2" {FONT}))
      )
    )
  )
"""
ROOT = "11111111-1111-1111-1111-111111111111"


def _sym(ref, uuid, x, y):
    return f"""  (symbol (lib_id "T:R") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid "{uuid}")
    (property "Reference" "{ref}" (at {x} {y - 3} 0) {FONT})
    (property "Value" "10k" (at {x} {y + 3} 0) {FONT})
    (property "Footprint" "R:R" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "{uuid[:-4]}0001"))
    (pin "2" (uuid "{uuid[:-4]}0002"))
    (instances (project "p" (path "/{ROOT}" (reference "{ref}") (unit 1))))
  )
"""


def _wire(n, x1, y1, x2, y2):
    return (
        f"  (wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default))"
        f' (uuid "55555555-5555-5555-5555-5555555555{n:02d}"))\n'
    )


def _junction(x, y):
    return f'  (junction (at {x} {y}) (diameter 0) (color 0 0 0 0) (uuid "55555555-5555-5555-5555-555555555599"))\n'


def _sch(body: str, symbols: str = "") -> str:
    return (
        f'(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n'
        f'  (uuid "{ROOT}")\n  (paper "A4")\n'
        + LIB
        + body
        + symbols
        + '  (sheet_instances (path "/" (page "1")))\n)\n'
    )


# R1 pin 2 at (101.27, 100); W1 runs right to x=120. W2 drops from (110, 100),
# the middle of W1, to (110, 130); W3 runs to R2 pin 2 at (101.27, 130).
TEE = (
    _wire(1, 101.27, 100, 120, 100) + _wire(2, 110, 100, 110, 130) + _wire(3, 110, 130, 101.27, 130)
)
SYMBOLS = _sym("R1", "33333333-3333-3333-3333-333333330000", 100, 100) + _sym(
    "R2", "44444444-4444-4444-4444-444444440000", 100, 130
)


def _junctions(data):
    return [
        tuple(float(v) for v in next(p for p in item[1:] if p[0] == sexpdata.Symbol("at"))[1:3])
        for item in data
        if isinstance(item, list) and item and item[0] == sexpdata.Symbol("junction")
    ]


def test_wire_ending_mid_wire_gets_a_junction():
    data = sexpdata.loads(_sch(TEE, SYMBOLS))
    added, removed = WireManager.sync_junctions(data)
    assert (added, removed) == (1, 0)
    assert _junctions(data) == [(110.0, 100.0)]


def test_existing_mid_wire_junction_is_kept():
    data = sexpdata.loads(_sch(TEE + _junction(110, 100), SYMBOLS))
    assert WireManager.sync_junctions(data) == (0, 0)
    assert _junctions(data) == [(110.0, 100.0)]


def test_a_plain_crossing_is_not_dotted():
    # Two wires crossing with no end at the crossing are not connected in KiCad.
    data = sexpdata.loads(_sch(_wire(1, 100, 100, 120, 100) + _wire(2, 110, 90, 110, 110)))
    assert WireManager.sync_junctions(data) == (0, 0)


def test_a_stale_junction_at_a_crossing_is_still_removed():
    data = sexpdata.loads(
        _sch(_wire(1, 100, 100, 120, 100) + _wire(2, 110, 90, 110, 110) + _junction(110, 100))
    )
    assert WireManager.sync_junctions(data) == (0, 1)


def test_a_pin_sitting_mid_wire_is_not_dotted():
    # KiCad treats a pin on the middle of a wire as unconnected; dotting it
    # would change the netlist. R1 pin 2 sits on the interior of this wire.
    data = sexpdata.loads(_sch(_wire(1, 95, 100, 110, 100), SYMBOLS))
    assert WireManager.sync_junctions(data) == (0, 0)


def test_diagonal_tee():
    data = sexpdata.loads(_sch(_wire(1, 100, 100, 120, 120) + _wire(2, 110, 110, 130, 100)))
    assert WireManager.sync_junctions(data) == (1, 0)
    assert _junctions(data) == [(110.0, 110.0)]


def _kicad_joins_r1_r2(sch: Path) -> bool:
    """True when KiCad's netlist puts R1 pin 2 and R2 pin 2 on one net."""
    out = sch.with_suffix(".net")
    subprocess.run(
        [
            "kicad-cli",
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadsexpr",
            "-o",
            str(out),
            str(sch),
        ],
        capture_output=True,
        check=True,
    )
    root = sexpdata.loads(out.read_text())
    nets = next(x for x in root[1:] if isinstance(x, list) and x[0] == sexpdata.Symbol("nets"))
    for net in nets[1:]:
        pins = set()
        for node in net[1:]:
            if isinstance(node, list) and node[0] == sexpdata.Symbol("node"):
                fields = {str(f[0]): str(f[1]) for f in node[1:] if isinstance(f, list)}
                pins.add((fields.get("ref"), fields.get("pin")))
        if {("R1", "2"), ("R2", "2")} <= pins:
            return True
    return False


@pytest.mark.integration
def test_kicad_connects_the_tee_after_sync(tmp_path):
    if not shutil.which("kicad-cli"):
        pytest.skip("needs kicad-cli")
    sch = tmp_path / "p.kicad_sch"
    sch.write_text(_sch(TEE, SYMBOLS))
    assert not _kicad_joins_r1_r2(sch)  # KiCad leaves the T open without a junction

    data = sexpdata.loads(sch.read_text())
    WireManager.sync_junctions(data)
    sch.write_text(sexpdata.dumps(data))
    assert _kicad_joins_r1_r2(sch)
