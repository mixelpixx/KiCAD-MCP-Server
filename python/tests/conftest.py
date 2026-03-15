"""
Shared fixtures and stubs for python/tests/.

Stubs out modules that require a full KiCAD installation (pcbnew, skip)
so that unit tests can run in any CI environment.
"""

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub: pcbnew  (KiCAD SWIG bindings — not available outside KiCAD python)
# ---------------------------------------------------------------------------
if "pcbnew" not in sys.modules:
    sys.modules["pcbnew"] = MagicMock()

# ---------------------------------------------------------------------------
# Stub: skip  (kicad-skip — use real module if available, stub otherwise)
# ---------------------------------------------------------------------------
try:
    import skip as _skip_test  # noqa: F401 — try importing real skip
except ImportError:
    skip_mod = types.ModuleType("skip")

    class _FakeSchematic:
        """Minimal stand-in for skip.Schematic used in PinLocator cache."""

        def __init__(self, path: str):
            self.path = path
            self.symbol = []

    skip_mod.Schematic = _FakeSchematic  # type: ignore[attr-defined]
    sys.modules["skip"] = skip_mod
