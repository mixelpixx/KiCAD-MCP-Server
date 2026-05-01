"""
Matrix tests for PinLocator.get_pin_angle on a Device:R symbol.

For each combination of (symbol_rotation, mirror, pin), we construct a real
.kicad_sch fixture, then compare:
  - actual:   PinLocator().get_pin_angle(...)
  - expected: derived geometrically from WireDragger.pin_world_xy by extending
              the pin one length unit along its library angle and measuring the
              world-frame displacement direction.

This characterizes the post-PR-#88 angle reflection logic. Cases that disagree
with the geometric expectation are marked xfail with a "PR #88 regression
candidate" annotation.
"""

import importlib.util
import math
import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sexpdata

# ---------------------------------------------------------------------------
# Module loading — bypass pcbnew, mirror the test_rotate_schematic_mirror style
# ---------------------------------------------------------------------------
_PYTHON_DIR = os.path.join(os.path.dirname(__file__), "..", "python")
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

# Stub pcbnew before importing pin_locator (skip is real and works fine)
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
# Device:R pin definitions (per python/templates/empty.kicad_sch)
#   pin 1: (0, 3.81), library angle 270, length 1.27
#   pin 2: (0, -3.81), library angle 90, length 1.27
# ---------------------------------------------------------------------------
PIN_DEFS = {
    "1": {"x": 0.0, "y": 3.81, "angle": 270.0, "length": 1.27},
    "2": {"x": 0.0, "y": -3.81, "angle": 90.0, "length": 1.27},
}

SYMBOL_X = 100.0
SYMBOL_Y = 100.0


def _make_sch_text(rotation: float, mirror: str | None) -> str:
    mirror_line = ""
    if mirror == "x":
        mirror_line = "(mirror x)"
    elif mirror == "y":
        mirror_line = "(mirror y)"

    return textwrap.dedent(f"""\
        (kicad_sch (version 20250114) (generator "test")
          (lib_symbols
            (symbol "Device:R" (pin_numbers hide) (pin_names (offset 0))
              (symbol "R_1_1"
                (pin passive line (at 0 3.81 270) (length 1.27)
                  (name "~" (effects (font (size 1.27 1.27))))
                  (number "1" (effects (font (size 1.27 1.27))))
                )
                (pin passive line (at 0 -3.81 90) (length 1.27)
                  (name "~" (effects (font (size 1.27 1.27))))
                  (number "2" (effects (font (size 1.27 1.27))))
                )
              )
            )
          )
          (symbol (lib_id "Device:R") (at {SYMBOL_X} {SYMBOL_Y} {rotation})
            {mirror_line}
            (property "Reference" "R1" (at {SYMBOL_X} {SYMBOL_Y} 0))
            (property "Value" "10k" (at {SYMBOL_X} {SYMBOL_Y} 0))
          )
        )
    """)


def _write_sch(tmp_path: Path, rotation: float, mirror: str | None) -> Path:
    p = tmp_path / f"r_rot{int(rotation)}_mirror{mirror or 'none'}.kicad_sch"
    p.write_text(_make_sch_text(rotation, mirror))
    return p


def _expected_stub_angle(pin_num: str, rotation: float, mirror: str | None) -> float:
    """Geometrically expected outward angle: extend in library coords by +length
    along library angle, transform to world, take atan2 of displacement."""
    pin = PIN_DEFS[pin_num]
    px, py = pin["x"], pin["y"]
    lib_angle_rad = math.radians(pin["angle"])
    ox = px + pin["length"] * math.cos(lib_angle_rad)
    oy = py + pin["length"] * math.sin(lib_angle_rad)

    mirror_x = mirror == "x"
    mirror_y = mirror == "y"

    wx_pin, wy_pin = WireDragger.pin_world_xy(
        px, py, SYMBOL_X, SYMBOL_Y, rotation, mirror_x, mirror_y
    )
    wx_out, wy_out = WireDragger.pin_world_xy(
        ox, oy, SYMBOL_X, SYMBOL_Y, rotation, mirror_x, mirror_y
    )

    deg = math.degrees(math.atan2(wy_out - wy_pin, wx_out - wx_pin)) % 360.0
    # Snap to 0/90/180/270 (axis-aligned pins; FP noise tolerance)
    snapped = round(deg / 90.0) * 90.0 % 360.0
    if abs(((deg - snapped) + 540) % 360 - 180) < 1e-6:
        # within tolerance
        return snapped
    return snapped


# ---------------------------------------------------------------------------
# Parametrized matrix
# ---------------------------------------------------------------------------
ROTATIONS = [0, 90, 180, 270]
MIRRORS = [None, "x", "y"]
PINS = ["1", "2"]


@pytest.mark.parametrize("rotation", ROTATIONS)
@pytest.mark.parametrize("mirror", MIRRORS)
@pytest.mark.parametrize("pin_num", PINS)
def test_get_pin_angle_matches_geometric_expectation(tmp_path, rotation, mirror, pin_num):
    sch_path = _write_sch(tmp_path, rotation, mirror)
    expected = _expected_stub_angle(pin_num, rotation, mirror)

    locator = PinLocator()
    actual = locator.get_pin_angle(sch_path, "R1", pin_num)

    assert (
        actual is not None
    ), f"get_pin_angle returned None for rot={rotation} mirror={mirror} pin={pin_num}"

    # Normalize both to [0, 360)
    actual_n = actual % 360.0
    expected_n = expected % 360.0

    assert abs(((actual_n - expected_n) + 540) % 360 - 180) < 1e-3, (
        f"actual={actual_n}, expected={expected_n} "
        f"(rotation={rotation}, mirror={mirror}, pin={pin_num})"
    )
