"""
Shared pytest fixtures and KiCAD module stubs for python/tests/.

KiCAD's `pcbnew` and `skip` C-extension modules are not available in the
test environment, so we stub them out here before any test module imports
code that would transitively pull them in.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub out KiCAD C-extension modules that are unavailable in CI
# ---------------------------------------------------------------------------
for _mod in ("pcbnew", "skip"):
    if _mod not in sys.modules:
        _mock = MagicMock()
        _mock.__file__ = f"/fake/{_mod}.so"
        sys.modules[_mod] = _mock
