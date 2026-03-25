"""
Pytest configuration for python/tests.

Sets up sys.path so that the python/ package root is importable without
installing the project, and provides shared fixtures.
"""
import sys
from pathlib import Path

# Make the python/ package root importable
PYTHON_ROOT = Path(__file__).parent.parent
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

# Stub out heavy KiCAD C-extension modules so tests can run without a real
# KiCAD installation.  Extend this list whenever a new import fails.
import types
from unittest.mock import MagicMock

# Use MagicMock so any attribute access (e.g. pcbnew.BOARD, pcbnew.LoadBoard)
# returns another MagicMock rather than raising AttributeError.
for _stub_name in ("pcbnew", "skip"):
    if _stub_name not in sys.modules:
        _m = MagicMock(spec_set=None)
        _m.__name__ = _stub_name
        sys.modules[_stub_name] = _m
