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
# pcbnew stub
# ---------------------------------------------------------------------------
_pcbnew = MagicMock(name="pcbnew")
_pcbnew.__file__ = "/fake/pcbnew.cpython-313-x86_64-linux-gnu.so"
_pcbnew.__name__ = "pcbnew"
_pcbnew.__spec__ = None
_pcbnew.GetBuildVersion.return_value = "9.0.0-stub"
sys.modules["pcbnew"] = _pcbnew

# ---------------------------------------------------------------------------
# Stub: skip  (kicad-skip — use real module if available, stub otherwise)
# ---------------------------------------------------------------------------
try:
    import skip as _skip_test  # noqa: F401
except ImportError:
    skip_mod = types.ModuleType("skip")

    class _FakeSchematic:
        def __init__(self, path: str):
            self.path = path
            self.symbol = []

    skip_mod.Schematic = _FakeSchematic  # type: ignore[attr-defined]
    sys.modules["skip"] = skip_mod
