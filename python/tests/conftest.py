"""
Test configuration for python/tests.

Sets up sys.modules stubs for heavy KiCAD modules (pcbnew, skip) before any
test module can trigger their import, preventing crashes on systems where the
real KiCAD environment is not fully initialised for testing.
"""

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# pcbnew stub — kicad_interface.py accesses pcbnew.__file__ and
# pcbnew.GetBuildVersion() at module level.  Use MagicMock so that any
# attribute access (pcbnew.BOARD, pcbnew.PCB_TRACK, …) returns a mock
# rather than raising AttributeError.
# ---------------------------------------------------------------------------
_pcbnew = MagicMock(name="pcbnew")
_pcbnew.__file__ = "/fake/pcbnew.cpython-313-x86_64-linux-gnu.so"
_pcbnew.__name__ = "pcbnew"
_pcbnew.__spec__ = None
_pcbnew.GetBuildVersion.return_value = "9.0.0-stub"
sys.modules["pcbnew"] = _pcbnew

# ---------------------------------------------------------------------------
# skip stub — used by PinLocator / _handle_add_schematic_wire at runtime.
# ---------------------------------------------------------------------------
_skip = types.ModuleType("skip")


class _FakeSchematic:
    def __init__(self, path):
        self._path = path

    @property
    def symbol(self):
        return []


_skip.Schematic = _FakeSchematic
sys.modules["skip"] = _skip
