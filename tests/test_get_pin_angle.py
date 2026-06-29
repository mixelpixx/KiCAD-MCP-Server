"""Matrix tests for PinLocator.get_pin_angle across rotation x mirror.

get_pin_angle returns the *outward* bearing of a pin endpoint — the direction a
wire stub leaves the pin, away from the symbol body — in the convention the sole
consumer (connection_schematic.connect_to_net) uses:

    stub_end = pin + L * (cos θ, −sin θ)        # screen Y is down

so 0=right, 90=up, 180=left, 270=down.

Two symbols are exercised:
  * Device:R — vertical pins (library angles 90/270)
  * Device:D — horizontal pins (library angles 0/180)

Horizontal pins are the regression guard: the previous implementation negated
the library angle (a Y-flip), which only yields the outward direction for
vertical pins (270↔90).  Horizontal pins (0→0, 180→180) came out pointing *into*
the body — 180° wrong — and the old test, which used only Device:R, never saw
it.

Oracles, strongest first:
  * test_wire_stub_extends_outward — behavioural and implementation-independent:
    the 2.54 mm stub the consumer would place must land farther from the symbol
    origin than the pin itself.  The old code fails this for every Device:D case.
  * test_get_pin_angle_known_values — hand-computed bearings for canonical
    placements, including the real-world D10 freewheel diode (rot 90 + mirror x).
  * test_get_pin_angle_matches_pin_world_xy — exhaustive agreement with the
    netlist-verified WireDragger.pin_world_xy transform.
"""

import importlib.util
import math
import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module loading — bypass pcbnew, mirror the test_rotate_schematic_mirror style
# ---------------------------------------------------------------------------
_PYTHON_DIR = os.path.join(os.path.dirname(__file__), "..", "python")
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

sys.modules.setdefault("pcbnew", MagicMock())

_pl_spec = importlib.util.spec_from_file_location(
    "pin_locator_under_test",
    os.path.join(_PYTHON_DIR, "commands", "pin_locator.py"),
)
_pl_mod = importlib.util.module_from_spec(_pl_spec)
_pl_spec.loader.exec_module(_pl_mod)
PinLocator = _pl_mod.PinLocator

_wd_spec = importlib.util.spec_from_file_location(
    "wire_dragger_under_test",
    os.path.join(_PYTHON_DIR, "commands", "wire_dragger.py"),
)
_wd_mod = importlib.util.module_from_spec(_wd_spec)
_wd_spec.loader.exec_module(_wd_mod)
WireDragger = _wd_mod.WireDragger


# ---------------------------------------------------------------------------
# Fixtures: a vertical-pin (Device:R) and a horizontal-pin (Device:D) symbol
# ---------------------------------------------------------------------------
SYMBOL_X = 100.0
SYMBOL_Y = 100.0
STUB_LEN = 2.54  # matches connection_schematic.connect_to_net

SYMS = {
    "R": {  # vertical pins
        "lib_id": "Device:R",
        # pin: (x, y, library angle)
        "pins": {"1": (0.0, 3.81, 270.0), "2": (0.0, -3.81, 90.0)},
        "body": textwrap.dedent("""\
            (symbol "R_1_1"
                (pin passive line (at 0 3.81 270) (length 1.27)
                  (name "~" (effects (font (size 1.27 1.27))))
                  (number "1" (effects (font (size 1.27 1.27)))))
                (pin passive line (at 0 -3.81 90) (length 1.27)
                  (name "~" (effects (font (size 1.27 1.27))))
                  (number "2" (effects (font (size 1.27 1.27)))))
              )"""),
    },
    "D": {  # horizontal pins
        "lib_id": "Device:D",
        "pins": {"1": (-3.81, 0.0, 0.0), "2": (3.81, 0.0, 180.0)},
        "body": textwrap.dedent("""\
            (symbol "D_1_1"
                (pin passive line (at -3.81 0 0) (length 2.54)
                  (name "K" (effects (font (size 1.27 1.27))))
                  (number "1" (effects (font (size 1.27 1.27)))))
                (pin passive line (at 3.81 0 180) (length 2.54)
                  (name "A" (effects (font (size 1.27 1.27))))
                  (number "2" (effects (font (size 1.27 1.27)))))
              )"""),
    },
}

ROTATIONS = [0, 90, 180, 270]
MIRRORS = [None, "x", "y"]
PINS = ["1", "2"]


def _make_sch_text(sym: str, rotation: float, mirror) -> str:
    spec = SYMS[sym]
    mirror_line = {"x": "(mirror x)", "y": "(mirror y)"}.get(mirror, "")
    return textwrap.dedent(f"""\
        (kicad_sch (version 20250114) (generator "test")
          (lib_symbols
            (symbol "{spec['lib_id']}" (pin_numbers hide) (pin_names (offset 0))
              {spec['body']}
            )
          )
          (symbol (lib_id "{spec['lib_id']}") (at {SYMBOL_X} {SYMBOL_Y} {rotation})
            {mirror_line}
            (property "Reference" "U1" (at {SYMBOL_X} {SYMBOL_Y} 0))
            (property "Value" "v" (at {SYMBOL_X} {SYMBOL_Y} 0))
          )
        )
    """)


def _write_sch(tmp_path: Path, sym: str, rotation: float, mirror) -> Path:
    p = tmp_path / f"{sym}_rot{int(rotation)}_mir{mirror or 'none'}.kicad_sch"
    p.write_text(_make_sch_text(sym, rotation, mirror))
    return p


def _pin_world(sym, pin_num, rotation, mirror):
    px, py, _ = SYMS[sym]["pins"][pin_num]
    return WireDragger.pin_world_xy(
        px, py, SYMBOL_X, SYMBOL_Y, rotation, mirror == "x", mirror == "y"
    )


def _outward_from_pin_world_xy(sym, pin_num, rotation, mirror):
    """Ground-truth outward bearing derived from the netlist-verified position
    transform: the library pin angle points *into* the body, so endpoint minus a
    bodyward point is the outward vector (screen Y down → negate the Y term)."""
    px, py, lib_angle = SYMS[sym]["pins"][pin_num]
    a = math.radians(lib_angle)
    ex, ey = _pin_world(sym, pin_num, rotation, mirror)
    bx, by = WireDragger.pin_world_xy(
        px + math.cos(a),
        py + math.sin(a),
        SYMBOL_X,
        SYMBOL_Y,
        rotation,
        mirror == "x",
        mirror == "y",
    )
    deg = math.degrees(math.atan2(-(ey - by), ex - bx)) % 360.0
    return round(deg / 90.0) * 90.0 % 360.0


# ---------------------------------------------------------------------------
# 1. Behavioural oracle (implementation-independent): the stub goes OUTWARD
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sym", ["R", "D"])
@pytest.mark.parametrize("rotation", ROTATIONS)
@pytest.mark.parametrize("mirror", MIRRORS)
@pytest.mark.parametrize("pin_num", PINS)
def test_wire_stub_extends_outward(tmp_path, sym, rotation, mirror, pin_num):
    """Replays what connect_to_net does and asserts the stub lands away from the
    symbol body.  For R/D the pins are radial, so 'outward' == 'farther from the
    placement origin'.  This is the assertion the old code violated for every
    horizontal-pin (Device:D) case."""
    sch = _write_sch(tmp_path, sym, rotation, mirror)
    angle = PinLocator().get_pin_angle(sch, "U1", pin_num)
    assert angle is not None

    pin_x, pin_y = _pin_world(sym, pin_num, rotation, mirror)
    rad = math.radians(angle)
    stub_x = pin_x + STUB_LEN * math.cos(rad)
    stub_y = pin_y - STUB_LEN * math.sin(rad)  # connect_to_net's Y-down convention

    def d2(x, y):
        return (x - SYMBOL_X) ** 2 + (y - SYMBOL_Y) ** 2

    assert d2(stub_x, stub_y) > d2(pin_x, pin_y) + 1e-6, (
        f"{sym} pin{pin_num} rot={rotation} mir={mirror}: stub heads INTO the body "
        f"(pin=({pin_x:.2f},{pin_y:.2f}) stub=({stub_x:.2f},{stub_y:.2f}) angle={angle})"
    )


# ---------------------------------------------------------------------------
# 2. Hand-computed canonical bearings (non-circular spot checks)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sym, pin_num, rotation, mirror, expected",
    [
        ("R", "1", 0, None, 90.0),  # top pin, points up
        ("R", "2", 0, None, 270.0),  # bottom pin, points down
        ("D", "1", 0, None, 180.0),  # left pin (cathode), points left
        ("D", "2", 0, None, 0.0),  # right pin (anode), points right
        ("D", "1", 90, "x", 90.0),  # real-world: D10 freewheel diode → HS_HOT (up)
    ],
)
def test_get_pin_angle_known_values(tmp_path, sym, pin_num, rotation, mirror, expected):
    sch = _write_sch(tmp_path, sym, rotation, mirror)
    angle = PinLocator().get_pin_angle(sch, "U1", pin_num)
    assert angle is not None
    assert (
        abs(((angle - expected) + 540) % 360 - 180) < 1e-3
    ), f"{sym} pin{pin_num} rot={rotation} mir={mirror}: got {angle}, expected {expected}"


# ---------------------------------------------------------------------------
# 3. Exhaustive agreement with the netlist-verified pin_world_xy transform
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sym", ["R", "D"])
@pytest.mark.parametrize("rotation", ROTATIONS)
@pytest.mark.parametrize("mirror", MIRRORS)
@pytest.mark.parametrize("pin_num", PINS)
def test_get_pin_angle_matches_pin_world_xy(tmp_path, sym, rotation, mirror, pin_num):
    sch = _write_sch(tmp_path, sym, rotation, mirror)
    actual = PinLocator().get_pin_angle(sch, "U1", pin_num)
    assert actual is not None

    expected = _outward_from_pin_world_xy(sym, pin_num, rotation, mirror)
    assert abs(((actual - expected) + 540) % 360 - 180) < 1e-3, (
        f"{sym} pin{pin_num} rot={rotation} mir={mirror}: "
        f"actual={actual % 360.0}, expected={expected}"
    )
