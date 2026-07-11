#!/usr/bin/env python3
"""Transition shim for the TypeScript host.

The implementation moved to the installable ``kicad_mcp`` package under
``src/``. The TypeScript server still spawns this exact path, so it stays as
a thin launcher for the legacy stdio JSON-RPC loop. It disappears together
with the TypeScript layer.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kicad_mcp.legacy_stdio import main  # noqa: E402

if __name__ == "__main__":
    main()
