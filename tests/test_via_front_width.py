"""Tests for _via_front_width(), the KiCad 8/9/10 via width accessor shim.

KiCad 9 moved vias onto per-layer padstacks. ``PCB_VIA`` gained
``GetWidth( PCB_LAYER_ID )`` plus the ``GetFrontWidth()`` wrapper, and the
inherited no-argument ``GetWidth()`` became a trap: it still returns the
ALL_LAYERS size, but trips ``wxCHECK_MSG`` (``pcbnew/pcb_track.cpp`` 9.0:381,
10.0:387). On a stable Windows build that is a modal debug alert, once per via,
which is what users actually reported.

KiCad 8 has neither new accessor -- its ``PCB_VIA`` only inherits
``PCB_TRACK::GetWidth()`` (``pcbnew/pcb_track.h`` 8.0:107) -- and this server
supports 8.0 in CI, so the shim cannot simply call the new API.

These fakes are deliberately plain classes rather than MagicMock. A MagicMock
auto-creates ``GetFrontWidth`` even when simulating KiCad 8, and ``int()`` of
the returned mock is 1, so the "KiCad 8" case would silently pass while
returning a 1 nm width. Controlling attribute presence exactly is the entire
point of this suite.
"""

import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

# Need pcbnew imported (real or stubbed) before the routing module.
import pcbnew  # noqa: F401, E402
from commands.routing import _via_front_width  # noqa: E402


class _Kicad8Via:
    """KiCad 8: one width for all layers, and no per-layer accessor at all."""

    def __init__(self, width):
        self._width = width

    def GetWidth(self):
        return self._width


class _Kicad9Via:
    """KiCad 9/10: GetFrontWidth() is correct; no-arg GetWidth() asserts.

    GetWidth() raises here to model the wxCHECK_MSG as if it were fatal. The
    real build only warns and returns a usable value, so a shim that called it
    would still produce correct numbers and the defect would show up solely as
    a dialog -- invisible to a test. Making it raise is what lets this suite
    prove the shim never takes that path.
    """

    def __init__(self, front_width):
        self._front_width = front_width

    def GetWidth(self, *args):
        raise AssertionError("PCB_VIA::GetWidth called without a layer argument")

    def GetFrontWidth(self):
        return self._front_width


def test_uses_front_width_on_kicad_9_and_10():
    assert _via_front_width(_Kicad9Via(800000)) == 800000


def test_never_calls_the_asserting_accessor_on_kicad_9_and_10():
    # _Kicad9Via.GetWidth raises, so returning at all proves it was not called.
    via = _Kicad9Via(600000)
    assert _via_front_width(via) == 600000


def test_falls_back_to_plain_getwidth_on_kicad_8():
    # No GetFrontWidth attribute exists, which is exactly the KiCad 8 shape.
    via = _Kicad8Via(450000)
    assert not hasattr(via, "GetFrontWidth")
    assert _via_front_width(via) == 450000


def test_returns_int_not_float():
    # Callers divide by a scale to produce mm, and some feed the value to
    # integer floor division (obstacle radii). A float here would change
    # results silently rather than fail loudly.
    assert isinstance(_via_front_width(_Kicad9Via(800000)), int)
    assert isinstance(_via_front_width(_Kicad8Via(800000)), int)
